# HA-Brew

**Keep homebrew apps on your Samsung and LG TVs up to date from Home Assistant.**

Updating a homebrew TV app (Nuvio, TizenTube, YouTube AdFree …) usually means a PC, a special tool, a saved manual and fifteen minutes, every time. On LG TVs Developer Mode expires and wipes everything you installed. HA-Brew does it from Home Assistant instead:

- every app gets a normal **update entity**, so new versions show up in *Settings → Updates* and install with one click (or by automation),
- a **sidebar panel** with a catalog of community apps that you can install with one click,
- **Samsung**: HA-Brew creates your signing certificate through your Samsung account and re-signs every update itself,
- **LG**: HA-Brew keeps the Developer Mode session alive, so your apps are not wiped.

You set it up once. After that no PC is needed.

![HA-Brew panel](docs/panel.png)

> **Status: early preview (0.4.x).** Samsung Tizen and LG webOS (without root).
> 🇨🇿 [Návod v češtině](docs/installation.cs.md)

---

## Contents

1. [What you need](#1-what-you-need)
2. [Install HA-Brew](#2-install-ha-brew)
3. [Samsung TV: step by step](#3-samsung-tv-step-by-step)
4. [LG TV: step by step](#4-lg-tv-step-by-step)
5. [Everyday use](#5-everyday-use)
6. [Problems](#6-problems)
7. [How it works](#7-how-it-works)

---

## 1. What you need

- Home Assistant 2025.8 or newer with [HACS](https://hacs.xyz).
- The TV and Home Assistant in the same network.
- **Samsung**: a Tizen TV or Smart Monitor and a free [Samsung account](https://account.samsung.com). For the one-time sign-in you also need a computer (Windows, macOS or Linux) in the same network.
- **LG**: a webOS TV and a free [LG developer account](https://webostv.developer.lge.com/).

No Tizen Studio, no webOS CLI and no add-on. Everything runs inside Home Assistant.

## 2. Install HA-Brew

1. Open **HACS** → **⋮** (top right) → **Custom repositories**.
2. Repository: `https://github.com/Michailjovic/HA-Brew`, type **Integration** → **Add**.
3. Search for **HA-Brew** in HACS → **Download**.
4. **Restart Home Assistant** (Settings → System → ⋮ → Restart).
5. Refresh the browser page (**Ctrl + F5**) so the new sidebar panel loads.

Then continue with [Samsung](#3-samsung-tv-step-by-step) or [LG](#4-lg-tv-step-by-step).

---

## 3. Samsung TV: step by step

### 3.1 Turn on Developer Mode on the TV

1. On the TV open **Apps**.
2. Type **`12345`** with the remote (or the virtual remote in the SmartThings app). A Developer Mode window opens.
3. Switch **Developer Mode** to **On**.
4. In **Host PC IP** enter the IP address of your Home Assistant (for example `192.168.1.2`).
5. Restart the TV: hold the power button on the remote until the Samsung logo appears.

> While Host PC IP points to Home Assistant, PC tools such as Apps2Samsung or TizenBrew Installer cannot reach the TV.

### 3.2 Add the TV to Home Assistant

1. **Settings → Devices & services → Add integration → HA-Brew**.
2. Choose **Samsung (Tizen)** and enter the TV's IP address → **Submit**.

If it cannot connect: the TV is off, Developer Mode is off, or Host PC IP is not your Home Assistant's address.

### 3.3 Create a signing certificate

Samsung TVs only run signed apps. HA-Brew creates the certificate for you through your Samsung account. You do this **once**.

1. **Settings → Devices & services → HA-Brew** → your TV → **Add certificate**.
2. Choose **Create a new certificate (Samsung account)** → **Submit**.
3. **Author name**: anything, e.g. your name. **Privilege level**: leave **Public**. Leave *Other TVs* empty. → **Submit**.
4. The next window shows **two commands made just for you**: one for Windows, one for macOS/Linux. Copy the one for your computer.

   It looks like this (your address and code will be different, so always copy it from the window, not from here):

   ```
   powershell -NoProfile -ExecutionPolicy Bypass -Command "irm 'http://192.168.1.2:8123/api/habrew/samsung_login/Xy12…/helper.ps1' | iex"
   ```

5. Run it on the computer:
   - **Windows**: press **Win + R**, paste the command (**Ctrl + V**), press **Enter**. A blue PowerShell window opens.
   - **macOS / Linux**: open **Terminal**, paste the command, press **Enter**.
6. Your browser opens the **Samsung sign-in page**. Sign in. When the page says *Signed in*, close it. The PowerShell/Terminal window closes by itself.
7. Go back to Home Assistant. The window there continues on its own and finishes in a few seconds: **Certificate created**.

The certificate works for all your Samsung TVs in HA-Brew and is valid for about a year. It is stored only in your Home Assistant.

<details>
<summary>What does the command do? Is it safe?</summary>

Samsung sends the sign-in result only to `localhost:4794` on the computer where you signed in. The command downloads a small script **from your own Home Assistant** (the link works only once and only for 15 minutes). The script opens the sign-in page, waits for the result on port 4794 and passes it to Home Assistant. Nothing is installed and nothing is sent anywhere else. Home Assistant then creates the keys and asks Samsung for the certificate.

If it reports that port 4794 is busy, close Tizen Studio or any other certificate tool and run the command again. If nothing happens in Home Assistant, check that the computer can open your Home Assistant at the address shown in the command.
</details>

<details>
<summary>I already have a certificate from TizenBrew Installer or Apps2Samsung</summary>

An app that is already on the TV can only be updated with **the same certificate it was installed with**. With a new certificate it has to be uninstalled and installed once, which deletes its data (logins, settings). The panel offers **Uninstall and install again** when that happens.

To keep the data, upload the old certificate instead: in step 2 choose the other format.

| You installed the app with | Upload | Where it is on the PC |
|---|---|---|
| TizenBrew Installer (e.g. Nuvio) | `tizenbrewInstallerConfig.json` | `%USERPROFILE%\share\` |
| Apps2Samsung | `author.p12` + `distributor.p12`, password from `password.txt` | `%APPDATA%\Apps2Samsung\Certificate\<profile>\` |
| Tizen Studio | `author.p12` + `distributor.p12` and their password | your certificate profile folder |

Paste the path into the address bar of Windows Explorer to open the folder.
</details>

### 3.4 Add and install apps

**From the catalog (easiest):**

1. Open **HA-Brew** in the sidebar → **Catalog**.
2. Find the app (search, category, *Root* filter), press **Add to TV** and choose your TV (and on Samsung the certificate).
3. Press **Install**. The app appears on the TV.

**From any GitHub repository:** in the panel **TVs → Add from GitHub**, enter the repository (e.g. `NuvioMedia/NuvioTVSmart`) and the release file pattern (`\.wgt$`).

Each app now has an entity `update.<tv>_<app>`. When a new version is released, it shows up under **Settings → Updates**.

---

## 4. LG TV: step by step

### 4.1 Turn on Developer Mode on the TV

1. Create a free account at [webostv.developer.lge.com](https://webostv.developer.lge.com/).
2. On the TV install the **Developer Mode** app from the LG Content Store and open it.
3. Sign in with the LG developer account.
4. Switch **Dev Mode Status** on. The TV restarts.
5. Open the Developer Mode app again and switch **Key Server** on. Note the **passphrase** shown on screen (6 characters).

Root is not needed. Apps installed with Homebrew Channel keep working, and HA-Brew can take them over.

### 4.2 Add the TV to Home Assistant

1. **Settings → Devices & services → Add integration → HA-Brew**.
2. Choose **LG (webOS)**, enter the TV's IP address → **Submit**.
3. Enter the **passphrase** from the TV → **Submit**.
4. You can switch **Key Server** off again.

### 4.3 Add and install apps

Same as Samsung, but without certificates: **HA-Brew → Catalog** (webOS Homebrew repository), or **Add from GitHub** with the pattern `\.ipk$`. Apps marked *needs root* do not work without root; the **Root** filter in the catalog hides them.

### 4.4 Developer Mode stays alive

Without renewal, LG Developer Mode expires and the TV deletes all apps you installed. HA-Brew renews the session once a day (even with the TV off) and shows:

- `sensor.<tv>_developer_mode_remaining`: hours left,
- `button.<tv>_extend_developer_mode`: renew now (also in the panel).

If renewal fails or less than 7 days are left, a repair appears in Settings. If you switch Developer Mode off and on, the TV gets a new key; Home Assistant asks for the new passphrase (step 4.1, point 5).

---

## 5. Everyday use

### The panel

**HA-Brew** in the sidebar (admins only):

- **TVs**: each app with installed and available version. Install, update, reinstall, launch (▶), stop managing or uninstall from the TV. Apps installed some other way can be taken over with **Manage**.
- **Catalog**: Samsung: ~200 apps from the [Apps2Samsung catalog](https://github.com/Apps2Samsung/tizen-community-packages); LG: the [webOS Homebrew repository](https://repo.webosbrew.org). Search, categories, root filter, warnings (closed source, Partner certificate …). Downloads are checked against the catalog's SHA-256.
- **Certificates** (Samsung): certificates per TV, expiry and which apps use them.

### Waking up the TV

A TV in standby does not answer. Under **Settings → Devices & services → HA-Brew → Configure** choose how HA-Brew wakes it before installing:

- **Wake-on-LAN**: enter the TV's MAC address. On Samsung also enable *Settings → General → Network → Expert Settings → Power On with Mobile*.
- **Turn on an entity**: e.g. the TV's `media_player` from [SamsungTV Smart](https://github.com/ollo69/ha-samsungtv-smart) or the LG webOS integration.

### Automatic updates

Install updates when the TV is on but idle:

```yaml
alias: HA-Brew – auto update TV apps
triggers:
  - trigger: state
    entity_id: update.samsung_tv_nuvio_tv
    to: "on"
  - trigger: state
    entity_id: media_player.samsung_tv
    to: "idle"
conditions:
  - condition: state
    entity_id: update.samsung_tv_nuvio_tv
    state: "on"
  - condition: state
    entity_id: media_player.samsung_tv
    state: ["on", "idle"]
actions:
  - action: update.install
    target:
      entity_id: update.samsung_tv_nuvio_tv
mode: single
```

---

## 6. Problems

| Problem | What to do |
|---|---|
| The panel or a new option is missing after an update | Restart Home Assistant, then **Ctrl + F5** in the browser. In the mobile app: *Settings → Companion app → Debugging → Reset frontend cache*. |
| Samsung: *cannot connect* | TV on? Developer Mode on? Host PC IP = Home Assistant's IP? Restart the TV after changing it. |
| Samsung: the TV refuses an update (*author certificate*) | The app was installed with a different certificate. Upload that one, or use **Uninstall and install again** (deletes the app's data). |
| Samsung: nothing happens after the sign-in | The computer must reach Home Assistant at the address in the command. Port 4794 must be free (close Tizen Studio). |
| LG: *authentication failed* | Developer Mode was reset. Switch Key Server on and enter the new passphrase when Home Assistant asks. |

**Reporting a problem:** *Settings → Devices & services → HA-Brew → ⋮ → Download diagnostics* (with the TV on). Addresses, keys, serial numbers and certificate details are removed. Attach the file to a [GitHub issue](https://github.com/Michailjovic/HA-Brew/issues).

---

## 7. How it works

**Samsung (Tizen):** HA-Brew checks GitHub or the catalog for new releases, re-signs the `.wgt` package with your certificate, pushes it to the TV over `sdb` (TCP 26101) and installs it in place, so app data and logins are kept. Certificates are stored in Home Assistant's private `.storage` folder. Samsung's public CA certificates are bundled in `drivers/tizen/ca/`.

**LG (webOS):** the Developer Mode SSH key is downloaded once from the TV's Key Server and decrypted with the passphrase. Packages (`.ipk`) are streamed over SSH (port 9922) and installed with the TV's own installer, the same way Homebrew Channel does it. No signing. The Developer Mode session is renewed at LG once a day.

### Roadmap

- [x] Samsung Tizen: sdb, package signing, update entities
- [x] App catalog and sidebar panel
- [x] Samsung certificates from Home Assistant (Samsung account)
- [x] LG webOS: SSH install, Developer Mode renewal, webOS Homebrew catalog
- [ ] Native `.tpk` packages
- [ ] Certificate renewal helper

### Credits

The signing logic follows Samsung's webIDE-common-tizentv (Apache-2.0), as used by
[TizenBrew Installer](https://github.com/reisxd/TizenBrewInstaller) and
[NuvioTVSmart-Installer](https://github.com/NuvioMedia/NuvioTVSmart-Installer).
Certificate creation builds on [tizen-cert-cli](https://github.com/gifflet/tizen-cert-cli) (MIT).
The app catalog format comes from [Apps2Samsung](https://github.com/Apps2Samsung/tizen-community-packages).
LG support builds on the [webOS Homebrew Project](https://www.webosbrew.org) and
[Webos-renew-dev](https://github.com/SR-Lut3t1um/Webos-renew-dev).

### License

GPL-3.0-only. See [LICENSE](LICENSE).
