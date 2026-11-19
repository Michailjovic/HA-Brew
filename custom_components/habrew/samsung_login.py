"""Samsung account sign-in relay.

Samsung only redirects the sign-in to ``http://localhost:4794/signin/callback`` on the computer
that runs the browser. The certificate flow shows a one-line command; it downloads a tiny helper
from Home Assistant, which opens the sign-in page, catches that one POST and forwards it here.
Everything else (keys, CSRs, Samsung API calls, storage) happens in Home Assistant.

All URLs carry a random one-time token and stop working once the sign-in arrived or after
``LOGIN_TIMEOUT``.
"""

from __future__ import annotations

import asyncio
import secrets
import time
from dataclasses import dataclass, field
from http import HTTPStatus

from aiohttp import web
from homeassistant.components.http import HomeAssistantView
from homeassistant.core import HomeAssistant
from homeassistant.helpers.network import NoURLAvailableError, get_url

from .const import DOMAIN
from .drivers.tizen.samsung_cert import CALLBACK_PORT, LOGIN_URL, SamsungCertError, SamsungSession, parse_callback

LOGIN_TIMEOUT = 15 * 60
BASE_PATH = "/api/habrew/samsung_login"
_DATA_KEY = "samsung_logins"

_TEXT = {
    "en": {
        "open": "Opening the Samsung account sign-in in your browser...",
        "busy": "Port 4794 is in use (is Tizen Studio or another certificate tool running?). Close it and try again.",
        "wait": "Waiting for the sign-in. Keep this window open.",
        "done": "Done. Go back to Home Assistant.",
        "ok": "Signed in. You can close this tab and go back to Home Assistant.",
        "fail": "Signed in, but Home Assistant could not be reached. Run the command again.",
    },
    "cs": {
        "open": "Otevírám přihlášení k účtu Samsung v prohlížeči...",
        "busy": "Port 4794 je obsazený (neběží Tizen Studio nebo jiný nástroj na certifikáty?). Zavři ho a zkus to znovu.",
        "wait": "Čekám na přihlášení. Nech toto okno otevřené.",
        "done": "Hotovo. Vrať se do Home Assistantu.",
        "ok": "Přihlášeno. Tuto záložku můžeš zavřít a vrátit se do Home Assistantu.",
        "fail": "Přihlášení proběhlo, ale Home Assistant není dostupný. Spusť příkaz znovu.",
    },
}

_PS1 = r"""$ErrorActionPreference = 'Stop'
$cb = '__CALLBACK__'
$login = '__LOGIN__'
$okHtml = '<html><meta charset="utf-8"><body style="font-family:sans-serif;margin:3em"><h2>HA-Brew</h2><p>__OK__</p></body></html>'
$failHtml = '<html><meta charset="utf-8"><body style="font-family:sans-serif;margin:3em"><h2>HA-Brew</h2><p>__FAIL__</p></body></html>'
$l = New-Object System.Net.HttpListener
$l.Prefixes.Add('http://localhost:__PORT__/')
try { $l.Start() } catch { Write-Host '__BUSY__' -ForegroundColor Red; Read-Host '[Enter]'; return }
Write-Host '__OPEN__'
Start-Process $login
Write-Host '__WAIT__'
try {
  while ($true) {
    $c = $l.GetContext()
    if ($c.Request.HttpMethod -ne 'POST') { $c.Response.StatusCode = 404; $c.Response.Close(); continue }
    $body = (New-Object System.IO.StreamReader($c.Request.InputStream, [System.Text.Encoding]::UTF8)).ReadToEnd()
    $html = $okHtml
    try { Invoke-RestMethod -Method Post -Uri $cb -Body $body -ContentType 'application/x-www-form-urlencoded' | Out-Null }
    catch { $html = $failHtml }
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($html)
    $c.Response.ContentType = 'text/html; charset=utf-8'
    $c.Response.OutputStream.Write($bytes, 0, $bytes.Length)
    $c.Response.Close()
    break
  }
} finally { $l.Stop() }
Write-Host '__DONE__' -ForegroundColor Green
Start-Sleep -Seconds 4
"""

_PY = r"""import http.server, socket, urllib.request, webbrowser
CB = '__CALLBACK__'
LOGIN = '__LOGIN__'
PAGE = '<html><meta charset="utf-8"><body style="font-family:sans-serif;margin:3em"><h2>HA-Brew</h2><p>%s</p></body></html>'


class Handler(http.server.BaseHTTPRequestHandler):
    done = False

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get('Content-Length') or 0))
        msg = '__OK__'
        try:
            req = urllib.request.Request(CB, data=body, headers={'Content-Type': 'application/x-www-form-urlencoded'})
            urllib.request.urlopen(req, timeout=60).read()
        except Exception:
            msg = '__FAIL__'
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.end_headers()
        self.wfile.write((PAGE % msg).encode('utf-8'))
        Handler.done = True

    def do_GET(self):
        self.send_response(404)
        self.end_headers()

    def log_message(self, *args):
        pass


class Server(http.server.HTTPServer):
    address_family = socket.AF_INET6

    def server_bind(self):
        try:
            self.socket.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
        except OSError:
            pass
        super().server_bind()


try:
    try:
        server = Server(('::', __PORT__), Handler)
    except OSError:
        server = http.server.HTTPServer(('127.0.0.1', __PORT__), Handler)
except OSError:
    raise SystemExit('__BUSY__')
print('__OPEN__')
webbrowser.open(LOGIN)
print('__WAIT__')
while not Handler.done:
    server.handle_request()
print('__DONE__')
"""


@dataclass
class PendingLogin:
    """One sign-in waited for by a config flow."""

    future: asyncio.Future[SamsungSession]
    created: float = field(default_factory=time.monotonic)

    @property
    def expired(self) -> bool:
        return time.monotonic() - self.created > LOGIN_TIMEOUT


def async_register(hass: HomeAssistant) -> None:
    hass.http.register_view(HelperView())
    hass.http.register_view(CallbackView())


def start_login(hass: HomeAssistant) -> tuple[str, PendingLogin]:
    """Create a one-time token; the caller awaits ``pending.future``."""
    logins: dict[str, PendingLogin] = hass.data.setdefault(DOMAIN, {}).setdefault(_DATA_KEY, {})
    for token in [t for t, p in logins.items() if p.expired or p.future.done()]:
        logins.pop(token)
    token = secrets.token_urlsafe(24)
    logins[token] = PendingLogin(future=hass.loop.create_future())
    return token, logins[token]


def finish_login(hass: HomeAssistant, token: str) -> None:
    pending = hass.data.get(DOMAIN, {}).get(_DATA_KEY, {}).pop(token, None)
    if pending and not pending.future.done():
        pending.future.cancel()


def base_url(hass: HomeAssistant) -> str:
    """Address a computer in the home network can reach Home Assistant at."""
    try:
        return get_url(hass, allow_cloud=False, prefer_external=False)
    except NoURLAvailableError:
        return get_url(hass, allow_cloud=False, allow_internal=False)


def commands(hass: HomeAssistant, token: str) -> dict[str, str]:
    """The one-line commands for the flow's description."""
    url = f"{base_url(hass)}{BASE_PATH}/{token}"
    return {
        "windows": f"powershell -NoProfile -ExecutionPolicy Bypass -Command \"irm '{url}/helper.ps1' | iex\"",
        "unix": f"curl -fsSL '{url}/helper.py' | python3",
        "login_url": LOGIN_URL,
    }


def _pending(hass: HomeAssistant, token: str) -> PendingLogin | None:
    pending = hass.data.get(DOMAIN, {}).get(_DATA_KEY, {}).get(token)
    if pending is None or pending.expired or pending.future.done():
        return None
    return pending


def render_helper(hass: HomeAssistant, token: str, kind: str) -> str:
    texts = _TEXT["cs" if (hass.config.language or "").startswith("cs") else "en"]
    script = _PS1 if kind == "ps1" else _PY
    values = {
        "__CALLBACK__": f"{base_url(hass)}{BASE_PATH}/{token}",
        "__LOGIN__": LOGIN_URL,
        "__PORT__": str(CALLBACK_PORT),
        **{f"__{k.upper()}__": v.replace("'", "") for k, v in texts.items()},
    }
    for key, value in values.items():
        script = script.replace(key, value)
    return script


class HelperView(HomeAssistantView):
    """Serves the helper script (no login: the one-time token is the credential)."""

    url = BASE_PATH + "/{token}/helper.{kind}"
    name = "api:habrew:samsung_login:helper"
    requires_auth = False

    async def get(self, request: web.Request, token: str, kind: str) -> web.Response:
        hass: HomeAssistant = request.app["hass"]
        if kind not in ("ps1", "py") or _pending(hass, token) is None:
            return web.Response(status=HTTPStatus.NOT_FOUND)
        return web.Response(text=render_helper(hass, token, kind), content_type="text/plain", charset="utf-8")


class CallbackView(HomeAssistantView):
    """Receives the sign-in form forwarded by the helper."""

    url = BASE_PATH + "/{token}"
    name = "api:habrew:samsung_login:callback"
    requires_auth = False

    async def post(self, request: web.Request, token: str) -> web.Response:
        hass: HomeAssistant = request.app["hass"]
        pending = _pending(hass, token)
        if pending is None:
            return web.Response(status=HTTPStatus.NOT_FOUND)
        body = await request.content.read(64 * 1024)
        try:
            session = parse_callback(body)
        except SamsungCertError as err:
            return web.Response(status=HTTPStatus.BAD_REQUEST, text=str(err))
        pending.future.set_result(session)
        return web.Response(text="ok")
