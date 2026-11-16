/*
 * HA-Brew sidebar panel.
 * Plain web component (no build step). Talks to the integration over the WebSocket API
 * (habrew/*) and reads live install progress from the update entities.
 */

const STRINGS = {
  en: {
    tvs: "TVs",
    catalog: "Catalog",
    certificates: "Certificates",
    refresh: "Check now",
    online: "Online",
    offline: "Offline",
    not_loaded: "Not loaded",
    managed: "Managed by HA-Brew",
    app: "App",
    on_tv: "On TV",
    available: "Available",
    source: "Source",
    action: "",
    install: "Install",
    update: "Update",
    reinstall: "Reinstall",
    up_to_date: "Up to date",
    remove: "Remove",
    confirm_remove: "Really remove?",
    other_apps: "Other apps on the TV",
    manage: "Manage",
    not_in_catalog: "not in catalog",
    add_github: "Add from GitHub",
    name: "Name",
    repo: "Repository (owner/name)",
    pattern: "Release file (regex)",
    prereleases: "Pre-releases",
    certificate: "Certificate",
    tv: "TV",
    save: "Add",
    cancel: "Cancel",
    no_tvs: "No TV added yet.",
    add_tv: "Add a TV",
    no_certs: "Add a signing certificate to this TV first.",
    add_cert: "Add certificate",
    search: "Search apps…",
    all_categories: "All categories",
    show_adult: "Show 18+",
    add_to_tv: "Add to TV",
    install_now: "Install right away",
    added: "Added",
    installed_on: "Installed",
    requires: "Tizen ≥ {v}",
    partner: "Partner certificate",
    flag_root: "root",
    "flag_closed-source": "closed source",
    "flag_self-updating": "self-updating",
    catalog_credit: "Catalog: Apps2Samsung community packages",
    catalog_error: "The catalog could not be loaded.",
    expires: "Expires",
    days_left: "{d} days",
    expired: "expired",
    cert_type_tizenbrew: "TizenBrew Installer",
    cert_type_p12: "author.p12 + distributor.p12",
    author: "Author",
    installing: "Installing… {p} %",
    done_install: "{app} installed.",
    done_add: "{app} added.",
    error: "Error",
    github: "GitHub",
    catalog_src: "Catalog",
    loading: "Loading…",
    no_apps: "No apps managed yet. Add one from the catalog, from GitHub, or manage an app below.",
    tv_offline_hint: "The TV is off or not reachable. Versions shown are the last known.",
    count: "{n} apps",
  },
  cs: {
    tvs: "Televize",
    catalog: "Katalog",
    certificates: "Certifikáty",
    refresh: "Zkontrolovat",
    online: "Online",
    offline: "Offline",
    not_loaded: "Nenačteno",
    managed: "Spravováno HA-Brew",
    app: "Aplikace",
    on_tv: "V TV",
    available: "Dostupná",
    source: "Zdroj",
    action: "",
    install: "Nainstalovat",
    update: "Aktualizovat",
    reinstall: "Přeinstalovat",
    up_to_date: "Aktuální",
    remove: "Odebrat",
    confirm_remove: "Opravdu odebrat?",
    other_apps: "Další aplikace v televizi",
    manage: "Spravovat",
    not_in_catalog: "není v katalogu",
    add_github: "Přidat z GitHubu",
    name: "Název",
    repo: "Repozitář (vlastník/název)",
    pattern: "Soubor z release (regex)",
    prereleases: "Předběžné verze",
    certificate: "Certifikát",
    tv: "Televize",
    save: "Přidat",
    cancel: "Zrušit",
    no_tvs: "Zatím není přidaná žádná televize.",
    add_tv: "Přidat televizi",
    no_certs: "Nejdřív k této televizi přidej podpisový certifikát.",
    add_cert: "Přidat certifikát",
    search: "Hledat aplikace…",
    all_categories: "Všechny kategorie",
    show_adult: "Zobrazit 18+",
    add_to_tv: "Přidat do TV",
    install_now: "Rovnou nainstalovat",
    added: "Přidáno",
    installed_on: "Nainstalováno",
    requires: "Tizen ≥ {v}",
    partner: "Partner certifikát",
    flag_root: "root",
    "flag_closed-source": "uzavřený kód",
    "flag_self-updating": "aktualizuje se sama",
    catalog_credit: "Katalog: Apps2Samsung community packages",
    catalog_error: "Katalog se nepodařilo načíst.",
    expires: "Platnost do",
    days_left: "{d} dní",
    expired: "vypršel",
    cert_type_tizenbrew: "TizenBrew Installer",
    cert_type_p12: "author.p12 + distributor.p12",
    author: "Autor",
    installing: "Instaluji… {p} %",
    done_install: "{app} nainstalováno.",
    done_add: "{app} přidáno.",
    error: "Chyba",
    github: "GitHub",
    catalog_src: "Katalog",
    loading: "Načítám…",
    no_apps: "Zatím žádné spravované aplikace. Přidej je z katalogu, z GitHubu nebo převezmi aplikaci níže.",
    tv_offline_hint: "Televize je vypnutá nebo nedostupná. Zobrazené verze jsou poslední známé.",
    count: "{n} aplikací",
  },
};

const esc = (v) =>
  String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

class HaBrewPanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._tab = "tvs";
    this._overview = null;
    this._catalog = null;
    this._catalogError = null;
    this._busy = {};
    this._form = null; // {kind, entry, ...}
    this._confirm = null;
    this._filter = { q: "", cat: "", adult: false };
    this.shadowRoot.addEventListener("click", (ev) => this._onClick(ev));
    this.shadowRoot.addEventListener("input", (ev) => this._onInput(ev));
    this.shadowRoot.addEventListener("change", (ev) => this._onInput(ev));
  }

  // ------------------------------------------------------------------ HA properties
  set hass(hass) {
    const first = !this._hass;
    this._hass = hass;
    if (first) {
      this._load();
      this._timer = setInterval(() => this._load(), 60000);
      return;
    }
    this._watchStates();
  }

  get hass() {
    return this._hass;
  }

  set narrow(value) {
    this._narrow = value;
    this._render();
  }

  set panel(_value) {}

  disconnectedCallback() {
    clearInterval(this._timer);
  }

  // ------------------------------------------------------------------ helpers
  t(key, vars = {}) {
    const lang = (this._hass?.language || "en").startsWith("cs") ? "cs" : "en";
    let s = STRINGS[lang][key] ?? STRINGS.en[key] ?? key;
    for (const [k, v] of Object.entries(vars)) s = s.replace(`{${k}}`, v);
    return s;
  }

  _ws(type, data = {}) {
    return this._hass.callWS({ type: `habrew/${type}`, ...data });
  }

  _toast(message) {
    this.dispatchEvent(new CustomEvent("hass-notification", { detail: { message }, bubbles: true, composed: true }));
  }

  _navigate(path) {
    history.pushState(null, "", path);
    window.dispatchEvent(new CustomEvent("location-changed", { detail: { replace: false } }));
  }

  _entityProgress(app) {
    const st = app.entity_id && this._hass?.states[app.entity_id];
    if (st && st.attributes.in_progress) return st.attributes.update_percentage ?? 0;
    return app.progress ?? null;
  }

  _watchStates() {
    if (!this._overview) return;
    const ids = this._overview.tvs.flatMap((tv) => tv.apps.map((a) => a.entity_id)).filter(Boolean);
    const versions = [];
    const progress = [];
    for (const id of ids) {
      const s = this._hass.states[id];
      if (!s) continue;
      const a = s.attributes;
      versions.push(`${s.state}|${a.installed_version}|${a.latest_version}|${a.tv_reachable}`);
      progress.push(`${a.in_progress}|${a.update_percentage}`);
    }
    const vSig = versions.join(";");
    const pSig = progress.join(";");
    if (vSig !== this._vSig) {
      const initial = this._vSig === undefined;
      this._vSig = vSig;
      this._pSig = pSig;
      if (!initial) this._load();
      return;
    }
    if (pSig !== this._pSig) {
      this._pSig = pSig;
      this._render();
    }
  }

  async _load() {
    try {
      this._overview = await this._ws("overview");
    } catch (err) {
      this._toast(`${this.t("error")}: ${err.message || err}`);
    }
    if (this._tab === "catalog" && !this._catalog) await this._loadCatalog();
    this._render();
  }

  async _loadCatalog(refresh = false) {
    try {
      this._catalog = await this._ws("catalog", { refresh });
      this._catalogError = null;
    } catch (err) {
      this._catalogError = err.message || String(err);
    }
  }

  // ------------------------------------------------------------------ events
  async _onClick(ev) {
    const el = ev.target.closest("[data-action]");
    if (!el) return;
    const { action, entry, sub, key, pkg, tab } = el.dataset;
    switch (action) {
      case "menu":
        this.dispatchEvent(new CustomEvent("hass-toggle-menu", { bubbles: true, composed: true }));
        break;
      case "tab":
        this._tab = tab;
        this._form = null;
        if (tab === "catalog" && !this._catalog) {
          this._render();
          await this._loadCatalog();
        }
        this._render();
        break;
      case "refresh":
        await this._run(`refresh:${entry}`, () => this._ws("refresh", { entry_id: entry }));
        break;
      case "refresh-catalog":
        await this._run("catalog", () => this._loadCatalog(true));
        break;
      case "install":
        await this._install(entry, sub);
        break;
      case "remove":
        if (this._confirm !== sub) {
          this._confirm = sub;
          this._render();
          setTimeout(() => {
            if (this._confirm === sub) {
              this._confirm = null;
              this._render();
            }
          }, 4000);
          return;
        }
        this._confirm = null;
        await this._run(`remove:${sub}`, () => this._ws("app/remove", { entry_id: entry, subentry_id: sub }));
        break;
      case "form-manage":
        this._form = { kind: "manage", entry, pkg };
        this._render();
        break;
      case "form-github":
        this._form = { kind: "github", entry };
        this._render();
        break;
      case "form-catalog":
        this._form = { kind: "catalog", key };
        this._render();
        break;
      case "form-cancel":
        this._form = null;
        this._render();
        break;
      case "form-submit":
        await this._submitForm(el.closest("form"));
        break;
      case "open-config":
        this._navigate(`/config/integrations/integration/habrew`);
        break;
      case "add-tv":
        this._navigate(`/config/integrations/dashboard/add?domain=habrew`);
        break;
      default:
        break;
    }
  }

  _onInput(ev) {
    const el = ev.target;
    if (!el.dataset.filter) return;
    if (el.dataset.filter === "adult") this._filter.adult = el.checked;
    else this._filter[el.dataset.filter] = el.value;
    const list = this.shadowRoot.getElementById("catalog-list");
    if (list) list.innerHTML = this._catalogItems();
  }

  async _run(busyKey, fn, okMessage) {
    this._busy[busyKey] = true;
    this._render();
    try {
      const result = await fn();
      if (okMessage) this._toast(okMessage);
      return result;
    } catch (err) {
      this._toast(`${this.t("error")}: ${err.message || err}`);
      return undefined;
    } finally {
      delete this._busy[busyKey];
      await this._load();
    }
  }

  async _install(entry, sub) {
    const app = this._findApp(entry, sub);
    await this._run(`install:${sub}`, () => this._ws("app/install", { entry_id: entry, subentry_id: sub }), this.t("done_install", { app: app?.title || "" }));
  }

  _findApp(entry, sub) {
    return this._overview?.tvs.find((t) => t.entry_id === entry)?.apps.find((a) => a.subentry_id === sub);
  }

  async _submitForm(form) {
    if (!form) return;
    const fd = Object.fromEntries(new FormData(form).entries());
    const entry = fd.entry_id;
    let payload;
    if (this._form.kind === "github") {
      payload = {
        entry_id: entry,
        source: "github",
        certificate: fd.certificate,
        name: fd.name || undefined,
        repo: fd.repo,
        asset_pattern: fd.asset_pattern || "\\.wgt$",
        include_prereleases: fd.include_prereleases === "on",
      };
    } else {
      payload = { entry_id: entry, source: "catalog", certificate: fd.certificate, catalog_key: fd.catalog_key };
    }
    const installNow = fd.install_now === "on";
    const result = await this._run("form", () => this._ws("app/add", payload));
    if (!result) return;
    this._form = null;
    this._toast(this.t("done_add", { app: fd.name || fd.catalog_label || payload.repo || "" }));
    if (installNow) {
      // the TV entry reloads after a subentry is added; wait until the new app has a release
      for (let i = 0; i < 30; i++) {
        await new Promise((r) => setTimeout(r, 1000));
        await this._load();
        const app = this._findApp(entry, result.subentry_id);
        if (app && app.latest_version) {
          await this._install(entry, result.subentry_id);
          return;
        }
      }
    }
  }

  // ------------------------------------------------------------------ rendering
  _render() {
    if (!this._hass) return;
    const focused = this.shadowRoot.activeElement;
    const keep = focused && focused.dataset?.filter ? { f: focused.dataset.filter, pos: focused.selectionStart } : null;
    // keep what the user typed into an open form across re-renders
    const formValues = {};
    let focusName = null;
    for (const el of this.shadowRoot.querySelectorAll(".inline-form [name]")) {
      if (el.type === "hidden") continue;
      formValues[el.name] = el.type === "checkbox" ? el.checked : el.value;
      if (el === focused) focusName = el.name;
    }
    this.shadowRoot.innerHTML = `<style>${STYLE}</style>
      <div class="toolbar">
        ${this._narrow ? `<button class="icon-btn" data-action="menu"><ha-icon icon="mdi:menu"></ha-icon></button>` : ""}
        <div class="title">HA-Brew</div>
      </div>
      <div class="tabs">
        ${["tvs", "catalog", "certificates"]
          .map((t) => `<button class="tab ${this._tab === t ? "active" : ""}" data-action="tab" data-tab="${t}">${this.t(t)}</button>`)
          .join("")}
      </div>
      <div class="content">${this._content()}</div>`;
    for (const el of this.shadowRoot.querySelectorAll(".inline-form [name]")) {
      if (!(el.name in formValues)) continue;
      if (el.type === "checkbox") el.checked = formValues[el.name];
      else el.value = formValues[el.name];
      if (el.name === focusName) el.focus();
    }
    if (keep) {
      const el = this.shadowRoot.querySelector(`[data-filter="${keep.f}"]`);
      if (el) {
        el.focus();
        if (keep.pos != null && el.setSelectionRange) el.setSelectionRange(keep.pos, keep.pos);
      }
    }
  }

  _content() {
    if (!this._overview) return `<div class="empty">${this.t("loading")}</div>`;
    if (!this._overview.tvs.length) {
      return `<div class="card empty">${this.t("no_tvs")}<br><br><button class="btn primary" data-action="add-tv">${this.t("add_tv")}</button></div>`;
    }
    if (this._tab === "catalog") return this._catalogView();
    if (this._tab === "certificates") return this._certView();
    return this._overview.tvs.map((tv) => this._tvCard(tv)).join("");
  }

  _status(tv) {
    if (!tv.loaded) return `<span class="chip warn">${this.t("not_loaded")}</span>`;
    return tv.reachable ? `<span class="chip ok">${this.t("online")}</span>` : `<span class="chip off">${this.t("offline")}</span>`;
  }

  _tvCard(tv) {
    const busy = this._busy[`refresh:${tv.entry_id}`];
    const sub = [tv.model, tv.platform_version ? `Tizen ${tv.platform_version}` : "", tv.host].filter(Boolean).join(" · ");
    const managed = tv.apps.length
      ? `<div class="table">
          <div class="row head"><div>${this.t("app")}</div><div>${this.t("on_tv")}</div><div>${this.t("available")}</div><div></div></div>
          ${tv.apps.map((a) => this._appRow(tv, a)).join("")}
        </div>`
      : `<div class="hint">${this.t("no_apps")}</div>`;
    const others = tv.tv_apps.filter((a) => !a.managed_by);
    return `<div class="card">
      <div class="card-head">
        <div><div class="h1">${esc(tv.title)} ${this._status(tv)}</div><div class="muted">${esc(sub)}</div></div>
        <div class="actions">
          <button class="btn" data-action="refresh" data-entry="${tv.entry_id}" ${busy ? "disabled" : ""}>
            <ha-icon icon="mdi:refresh"></ha-icon>${this.t("refresh")}</button>
        </div>
      </div>
      ${tv.loaded && !tv.reachable ? `<div class="hint warn">${this.t("tv_offline_hint")}</div>` : ""}
      <div class="section-title">${this.t("managed")}</div>
      ${managed}
      ${this._form?.kind === "github" && this._form.entry === tv.entry_id ? this._githubForm(tv) : `<div class="add-row"><button class="btn" data-action="form-github" data-entry="${tv.entry_id}"><ha-icon icon="mdi:github"></ha-icon>${this.t("add_github")}</button></div>`}
      ${others.length ? `<div class="section-title">${this.t("other_apps")} <span class="muted">(${this.t("count", { n: others.length })})</span></div>
        <div class="table">${others.map((a) => this._otherRow(tv, a)).join("")}</div>` : ""}
    </div>`;
  }

  _appRow(tv, a) {
    const progress = this._entityProgress(a);
    const busy = this._busy[`install:${a.subentry_id}`] || progress != null;
    const icon = a.icon ? `<img class="app-icon" src="${esc(a.icon)}" alt="">` : `<div class="app-icon ph"><ha-icon icon="mdi:application"></ha-icon></div>`;
    const src = a.source === "catalog" ? this.t("catalog_src") : a.repo ? esc(a.repo) : this.t("github");
    let action;
    if (busy) {
      const p = progress ?? 0;
      action = `<div class="progress"><div class="bar" style="width:${p}%"></div><span>${this.t("installing", { p })}</span></div>`;
    } else if (!a.latest_version) {
      action = `<span class="muted">—</span>`;
    } else if (!a.installed_version) {
      action = `<button class="btn primary" data-action="install" data-entry="${tv.entry_id}" data-sub="${a.subentry_id}">${this.t("install")}</button>`;
    } else if (a.update_available) {
      action = `<button class="btn primary" data-action="install" data-entry="${tv.entry_id}" data-sub="${a.subentry_id}">${this.t("update")}</button>`;
    } else {
      action = `<span class="chip ok">${this.t("up_to_date")}</span>
        <button class="icon-btn" title="${this.t("reinstall")}" data-action="install" data-entry="${tv.entry_id}" data-sub="${a.subentry_id}"><ha-icon icon="mdi:reload"></ha-icon></button>`;
    }
    const removeBtn =
      this._confirm === a.subentry_id
        ? `<button class="btn danger small" data-action="remove" data-entry="${tv.entry_id}" data-sub="${a.subentry_id}">${this.t("confirm_remove")}</button>`
        : `<button class="icon-btn" title="${this.t("remove")}" data-action="remove" data-entry="${tv.entry_id}" data-sub="${a.subentry_id}" ${busy ? "disabled" : ""}><ha-icon icon="mdi:delete-outline"></ha-icon></button>`;
    return `<div class="row">
      <div class="app">${icon}<div><div class="app-name">${esc(a.title)}</div>
        <div class="muted small">${src} · ${esc(a.certificate || "?")}</div>
        ${a.error ? `<div class="err small">${esc(a.error)}</div>` : ""}</div></div>
      <div><span class="ver">${esc(a.installed_version || "—")}</span></div>
      <div><span class="ver ${a.update_available ? "new" : ""}">${esc(a.latest_version || "—")}</span></div>
      <div class="actions">${action}${removeBtn}</div>
    </div>`;
  }

  _otherRow(tv, a) {
    let action;
    if (this._form?.kind === "manage" && this._form.entry === tv.entry_id && this._form.pkg === a.package_id) {
      return `<div class="row form-row">${this._manageForm(tv, a)}</div>`;
    }
    if (a.catalog.length) {
      action = `<button class="btn" data-action="form-manage" data-entry="${tv.entry_id}" data-pkg="${esc(a.package_id)}">${this.t("manage")}</button>`;
    } else {
      action = `<span class="muted small">${this.t("not_in_catalog")}</span>`;
    }
    const newer = a.catalog.find((c) => c.version && c.version !== a.version);
    return `<div class="row">
      <div class="app"><div class="app-icon ph"><ha-icon icon="mdi:television-play"></ha-icon></div>
        <div><div class="app-name">${esc(a.title || a.app_id)}</div><div class="muted small">${esc(a.app_id)}</div></div></div>
      <div><span class="ver">${esc(a.version || "—")}</span></div>
      <div><span class="ver">${newer ? esc(newer.version) : a.catalog[0] ? esc(a.catalog[0].version) : "—"}</span></div>
      <div class="actions">${action}</div>
    </div>`;
  }

  _certSelect(tv) {
    if (!tv.certificates.length) return null;
    return `<label>${this.t("certificate")}<select name="certificate">${tv.certificates
      .map((c) => `<option value="${c.id}">${esc(c.title)}${c.author_cn ? ` (${esc(c.author_cn)})` : ""}</option>`)
      .join("")}</select></label>`;
  }

  _noCert(tv) {
    return `<div class="hint warn">${this.t("no_certs")} <button class="btn small" data-action="open-config">${this.t("add_cert")}</button></div>`;
  }

  _formButtons(withInstall = true) {
    const busy = this._busy.form;
    return `<div class="form-actions">
      ${withInstall ? `<label class="check"><input type="checkbox" name="install_now"> ${this.t("install_now")}</label>` : ""}
      <button type="button" class="btn" data-action="form-cancel">${this.t("cancel")}</button>
      <button type="button" class="btn primary" data-action="form-submit" ${busy ? "disabled" : ""}>${this.t("save")}</button>
    </div>`;
  }

  _manageForm(tv, a) {
    const certs = this._certSelect(tv);
    if (!certs) return this._noCert(tv);
    return `<form class="inline-form">
      <input type="hidden" name="entry_id" value="${tv.entry_id}">
      <input type="hidden" name="catalog_label" value="${esc(a.title)}">
      <div class="form-title">${esc(a.title)}</div>
      <label>${this.t("catalog")}<select name="catalog_key">${a.catalog
        .map((c) => `<option value="${esc(c.key)}">${esc(c.name)}${c.variant ? ` – ${esc(c.variant)}` : ""} (${esc(c.version)})</option>`)
        .join("")}</select></label>
      ${certs}
      ${this._formButtons(true)}
    </form>`;
  }

  _githubForm(tv) {
    const certs = this._certSelect(tv);
    if (!certs) return this._noCert(tv);
    return `<form class="inline-form">
      <input type="hidden" name="entry_id" value="${tv.entry_id}">
      <div class="form-title"><ha-icon icon="mdi:github"></ha-icon> ${this.t("add_github")}</div>
      <label>${this.t("name")}<input name="name" placeholder="Nuvio TV"></label>
      <label>${this.t("repo")}<input name="repo" placeholder="NuvioMedia/NuvioTVSmart" required></label>
      <label>${this.t("pattern")}<input name="asset_pattern" value="\\.wgt$"></label>
      ${certs}
      <label class="check"><input type="checkbox" name="include_prereleases"> ${this.t("prereleases")}</label>
      ${this._formButtons(true)}
    </form>`;
  }

  // ------------------------------------------------------------------ catalog
  _catalogView() {
    if (!this._catalog && !this._catalogError) return `<div class="empty">${this.t("loading")}</div>`;
    if (this._catalogError) {
      return `<div class="card empty">${this.t("catalog_error")}<br><span class="muted small">${esc(this._catalogError)}</span><br><br>
        <button class="btn" data-action="refresh-catalog">${this.t("refresh")}</button></div>`;
    }
    const cats = this._catalog.categories || {};
    return `<div class="filters">
        <input class="search" data-filter="q" placeholder="${this.t("search")}" value="${esc(this._filter.q)}">
        <select data-filter="cat"><option value="">${this.t("all_categories")}</option>
          ${Object.entries(cats).map(([k, v]) => `<option value="${esc(k)}" ${this._filter.cat === k ? "selected" : ""}>${esc(v)}</option>`).join("")}
        </select>
        <label class="check"><input type="checkbox" data-filter="adult" ${this._filter.adult ? "checked" : ""}> ${this.t("show_adult")}</label>
        <button class="icon-btn" title="${this.t("refresh")}" data-action="refresh-catalog" ${this._busy.catalog ? "disabled" : ""}><ha-icon icon="mdi:refresh"></ha-icon></button>
      </div>
      <div class="grid" id="catalog-list">${this._catalogItems()}</div>
      <div class="credit"><a href="https://github.com/Apps2Samsung/tizen-community-packages" target="_blank" rel="noreferrer">${this.t("catalog_credit")}</a></div>`;
  }

  _catalogItems() {
    if (!this._catalog) return "";
    const q = this._filter.q.trim().toLowerCase();
    const items = this._catalog.entries
      .filter((e) => (this._filter.adult || !e.adult) && (!this._filter.cat || e.category === this._filter.cat))
      .filter((e) => !q || `${e.name} ${e.variant} ${e.description} ${e.repo}`.toLowerCase().includes(q))
      .sort((a, b) => a.name.localeCompare(b.name) || a.variant.localeCompare(b.variant));
    const tvs = this._overview?.tvs || [];
    return items
      .map((e) => {
        const status = tvs
          .map((tv) => {
            const managed = tv.apps.find((a) => a.catalog_key === e.key);
            const installed = tv.tv_apps.find((a) => a.package_id && a.package_id === e.package_id);
            if (managed) return `<span class="chip ok">${esc(tv.title)}: ${this.t("added")}</span>`;
            if (installed) return `<span class="chip">${esc(tv.title)}: ${this.t("installed_on")} ${esc(installed.version)}</span>`;
            return "";
          })
          .join("");
        const flags = (e.flags || []).map((f) => `<span class="chip warn">${esc(this.t(`flag_${f}`))}</span>`).join("");
        const form = this._form?.kind === "catalog" && this._form.key === e.key ? this._catalogForm(e) : "";
        return `<div class="card item">
          <div class="item-head">
            ${e.icon ? `<img class="app-icon big" src="${esc(e.icon)}" alt="" loading="lazy">` : `<div class="app-icon big ph"><ha-icon icon="mdi:application"></ha-icon></div>`}
            <div><div class="app-name">${esc(e.name)}</div>${e.variant && e.variant !== e.name ? `<div class="muted small">${esc(e.variant)}</div>` : ""}</div>
          </div>
          <div class="desc">${esc(e.description)}</div>
          <div class="meta"><span class="ver">${esc(e.version || "?")}</span>
            ${e.required_version ? `<span class="chip">${this.t("requires", { v: esc(e.required_version) })}</span>` : ""}
            ${e.cert_level === "partner" ? `<span class="chip warn">${this.t("partner")}</span>` : ""}${flags}</div>
          ${status ? `<div class="meta">${status}</div>` : ""}
          <div class="item-foot">
            ${e.repo ? `<a class="muted small" href="https://github.com/${esc(e.repo)}" target="_blank" rel="noreferrer">${esc(e.repo)}</a>` : "<span></span>"}
            ${form ? "" : `<button class="btn primary small" data-action="form-catalog" data-key="${esc(e.key)}">${this.t("add_to_tv")}</button>`}
          </div>
          ${form}
        </div>`;
      })
      .join("");
  }

  _catalogForm(e) {
    const tvs = (this._overview?.tvs || []).filter((tv) => tv.loaded);
    if (!tvs.length) return "";
    const withCerts = tvs.filter((tv) => tv.certificates.length);
    if (!withCerts.length) return this._noCert(tvs[0]);
    const tv = withCerts[0];
    return `<form class="inline-form">
      <input type="hidden" name="catalog_key" value="${esc(e.key)}">
      <input type="hidden" name="catalog_label" value="${esc(e.name)}">
      <label>${this.t("tv")}<select name="entry_id">${withCerts.map((t) => `<option value="${t.entry_id}">${esc(t.title)}</option>`).join("")}</select></label>
      ${this._certSelect(tv)}
      ${this._formButtons(true)}
    </form>`;
  }

  // ------------------------------------------------------------------ certificates
  _certView() {
    return this._overview.tvs
      .map(
        (tv) => `<div class="card">
        <div class="card-head"><div class="h1">${esc(tv.title)}</div>
          <div class="actions"><button class="btn" data-action="open-config"><ha-icon icon="mdi:plus"></ha-icon>${this.t("add_cert")}</button></div></div>
        ${
          tv.certificates.length
            ? `<div class="table">${tv.certificates
                .map((c) => {
                  const exp = c.expires ? new Date(c.expires) : null;
                  const days = exp ? Math.floor((exp - Date.now()) / 86400000) : null;
                  const cls = days == null ? "" : days < 0 ? "err" : days < 30 ? "err" : days < 90 ? "warn-text" : "";
                  const used = tv.apps.filter((a) => a.certificate_id === c.id).map((a) => esc(a.title)).join(", ");
                  return `<div class="row cert">
                    <div><div class="app-name">${esc(c.title)}</div><div class="muted small">${this.t(`cert_type_${c.cert_type}`)}</div></div>
                    <div class="small">${this.t("author")}: ${esc(c.author_cn || "?")}</div>
                    <div class="small ${cls}">${this.t("expires")}: ${exp ? exp.toLocaleDateString() : "?"}${days != null ? ` (${days < 0 ? this.t("expired") : this.t("days_left", { d: days })})` : ""}</div>
                    <div class="muted small">${used}</div>
                  </div>`;
                })
                .join("")}</div>`
            : `<div class="hint">${this.t("no_certs")}</div>`
        }
      </div>`,
      )
      .join("");
  }
}

const STYLE = `
:host { display:block; min-height:100vh; background: var(--primary-background-color); color: var(--primary-text-color);
  font-family: var(--paper-font-body1_-_font-family, Roboto, sans-serif); }
.toolbar { display:flex; align-items:center; gap:8px; height:56px; padding:0 16px; background: var(--app-header-background-color, var(--primary-color));
  color: var(--app-header-text-color, var(--text-primary-color)); font-size:20px; }
.title { font-weight:400; }
.tabs { display:flex; gap:4px; padding:0 16px; background: var(--app-header-background-color, var(--primary-color)); overflow-x:auto; }
.tab { background:none; border:none; color: var(--app-header-text-color, var(--text-primary-color)); opacity:.75; padding:12px 16px; font-size:14px;
  cursor:pointer; border-bottom:2px solid transparent; text-transform:uppercase; letter-spacing:.05em; }
.tab.active { opacity:1; border-bottom-color: currentColor; }
.content { max-width:1100px; margin:0 auto; padding:16px; box-sizing:border-box; }
.card { background: var(--ha-card-background, var(--card-background-color)); border-radius: var(--ha-card-border-radius, 12px);
  box-shadow: var(--ha-card-box-shadow, none); border: 1px solid var(--divider-color); padding:16px; margin-bottom:16px; }
.card-head { display:flex; justify-content:space-between; align-items:flex-start; gap:12px; flex-wrap:wrap; }
.h1 { font-size:20px; display:flex; align-items:center; gap:8px; flex-wrap:wrap; }
.muted { color: var(--secondary-text-color); }
.small { font-size:12px; }
.err { color: var(--error-color); }
.warn-text { color: var(--warning-color); }
.section-title { margin:18px 0 6px; font-weight:500; font-size:14px; text-transform:uppercase; letter-spacing:.04em; color: var(--secondary-text-color); }
.table { display:flex; flex-direction:column; }
.row { display:grid; grid-template-columns: minmax(0,3fr) 1fr 1fr minmax(0,2fr); gap:12px; align-items:center; padding:10px 0; border-top:1px solid var(--divider-color); }
.row.head { font-size:12px; color: var(--secondary-text-color); border-top:none; padding-bottom:4px; }
.row.cert { grid-template-columns: minmax(0,2fr) 1fr 1.4fr 1fr; }
.row.form-row { display:block; }
.app { display:flex; align-items:center; gap:12px; min-width:0; }
.app > div { min-width:0; }
.app-name { font-weight:500; overflow:hidden; text-overflow:ellipsis; }
.app-icon { width:36px; height:36px; border-radius:8px; object-fit:cover; flex:none; background: var(--secondary-background-color); }
.app-icon.big { width:48px; height:48px; }
.app-icon.ph { display:flex; align-items:center; justify-content:center; color: var(--secondary-text-color); }
.ver { font-family: var(--code-font-family, monospace); font-size:13px; }
.ver.new { color: var(--warning-color); font-weight:600; }
.actions { display:flex; align-items:center; justify-content:flex-end; gap:6px; flex-wrap:wrap; }
.btn { display:inline-flex; align-items:center; gap:6px; border-radius:18px; padding:6px 14px; font-size:14px; cursor:pointer;
  border:1px solid var(--divider-color); background:transparent; color: var(--primary-color); font-family:inherit; }
.btn ha-icon { --mdc-icon-size:18px; }
.btn.primary { background: var(--primary-color); border-color: var(--primary-color); color: var(--text-primary-color, #fff); }
.btn.danger { background: var(--error-color); border-color: var(--error-color); color:#fff; }
.btn.small { padding:3px 10px; font-size:12px; }
.btn[disabled], .icon-btn[disabled] { opacity:.5; cursor:default; }
.icon-btn { background:none; border:none; color: inherit; cursor:pointer; padding:6px; border-radius:50%; display:inline-flex; }
.icon-btn:hover { background: var(--secondary-background-color); }
.chip { display:inline-block; padding:2px 8px; border-radius:10px; font-size:11px; background: var(--secondary-background-color); color: var(--secondary-text-color); }
.chip.ok { background: rgba(76,175,80,.15); color: var(--success-color, #4caf50); }
.chip.off { background: rgba(158,158,158,.2); }
.chip.warn { background: rgba(255,152,0,.15); color: var(--warning-color, #ff9800); }
.hint { padding:10px 12px; border-radius:8px; background: var(--secondary-background-color); color: var(--secondary-text-color); font-size:13px; margin-top:8px; }
.hint.warn { background: rgba(255,152,0,.12); color: var(--primary-text-color); }
.add-row { margin-top:10px; }
.progress { position:relative; min-width:150px; height:24px; border-radius:12px; background: var(--secondary-background-color); overflow:hidden; font-size:12px; }
.progress .bar { position:absolute; inset:0 auto 0 0; background: var(--primary-color); opacity:.35; transition: width .4s; }
.progress span { position:relative; display:block; text-align:center; line-height:24px; }
.inline-form { display:grid; grid-template-columns: repeat(auto-fit, minmax(200px,1fr)); gap:10px 14px; padding:12px; margin-top:10px;
  border-radius:10px; background: var(--secondary-background-color); }
.form-title { grid-column:1/-1; font-weight:500; display:flex; align-items:center; gap:6px; }
.inline-form label { display:flex; flex-direction:column; gap:4px; font-size:12px; color: var(--secondary-text-color); }
.inline-form label.check, label.check { flex-direction:row; align-items:center; gap:6px; font-size:13px; color: var(--primary-text-color); }
input, select { font: inherit; padding:8px 10px; border-radius:8px; border:1px solid var(--divider-color); background: var(--card-background-color);
  color: var(--primary-text-color); }
.form-actions { grid-column:1/-1; display:flex; justify-content:flex-end; align-items:center; gap:8px; flex-wrap:wrap; }
.form-actions .check { margin-right:auto; }
.filters { display:flex; gap:10px; align-items:center; flex-wrap:wrap; margin-bottom:14px; }
.search { flex:1; min-width:200px; }
.grid { display:grid; grid-template-columns: repeat(auto-fill, minmax(280px,1fr)); gap:14px; }
.item { margin:0; display:flex; flex-direction:column; gap:8px; }
.item-head { display:flex; gap:12px; align-items:center; }
.desc { font-size:13px; color: var(--secondary-text-color); display:-webkit-box; -webkit-line-clamp:3; -webkit-box-orient:vertical; overflow:hidden; }
.meta { display:flex; gap:6px; flex-wrap:wrap; align-items:center; }
.item-foot { display:flex; justify-content:space-between; align-items:center; margin-top:auto; gap:8px; }
.item-foot a { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.credit { text-align:center; margin:18px 0; font-size:12px; }
.credit a, a { color: var(--primary-color); }
.empty { text-align:center; padding:40px 16px; color: var(--secondary-text-color); }
@media (max-width: 700px) {
  .row { grid-template-columns: minmax(0,1fr) auto auto; }
  .row.head { display:none; }
  .row > .actions { grid-column: 1 / -1; justify-content:flex-start; }
  .row.cert { grid-template-columns: 1fr; }
}
`;

customElements.define("ha-brew-panel", HaBrewPanel);
