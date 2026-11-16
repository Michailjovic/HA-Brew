# HA-Brew

Keep homebrew apps on your smart TVs up to date from Home Assistant.

HA-Brew downloads new releases of TV apps from GitHub, re-signs them with **your own Samsung certificate** and installs them over the network. You get one native `update` entity per app, so updates show up in *Settings → Updates*, on dashboards, and in automations (for example, "install when the TV is on but nothing is playing").

> **Status: early preview (0.2.x).** Only Samsung Tizen TVs are supported for now. LG webOS support is planned.

![HA-Brew panel](docs/panel.png)

## How it works

1. Your TV is in **Developer Mode**, and its *Host PC IP* points to your Home Assistant.
2. You upload the certificate the app was originally installed with: a TizenBrew Installer config, or an Apps2Samsung / Tizen Studio `.p12` pair.
3. HA-Brew checks GitHub for new releases. When an update is installed, it:
   - re-signs the `.wgt` package with your certificate,
   - pushes it to the TV over `sdb` (TCP 26101),
   - installs it in place, so app data and logins are kept.

No Tizen Studio, no PC and no extra add-on are needed. Everything runs inside Home Assistant using libraries it already ships.

## Requirements

- Home Assistant 2025.8 or newer.
- A Samsung Tizen TV or monitor with Developer Mode enabled:
  1. Open *Apps*.
  2. Type `12345` with the remote (or the SmartThings app's virtual remote).
  3. Switch Developer Mode on and set **Host PC IP** to your Home Assistant's IP.
  4. Restart the TV: hold the power button until the logo appears.
- The signing certificate the app was installed with (see [Certificates](#certificates)).

> Setting the Host PC IP to Home Assistant means other tools on your PC (Apps2Samsung, TizenBrew Installer) cannot reach the TV until you switch it back.

## Installation (HACS)

1. In HACS, open the menu and choose *Custom repositories*. Add this repository's URL with type **Integration**.
2. Install **HA-Brew** and restart Home Assistant.
3. Go to *Settings → Devices & services → Add integration → HA-Brew*, then enter the TV's IP address.

## The HA-Brew panel

HA-Brew adds a **HA-Brew** entry to the sidebar (admins only):

- **TVs**: every app on each TV with the installed and the available version. Install, update, reinstall or remove managed apps. Apps that were installed some other way can be taken over with **Manage**, if the catalog has them.
- **Catalog**: about 200 community Tizen web apps from the [Apps2Samsung catalog](https://github.com/Apps2Samsung/tizen-community-packages), with search, categories, Tizen version requirements and warnings (root, closed source, self-updating, Partner certificate). Add any of them to a TV and install it right away. Downloads are checked against the catalog's SHA-256.
- **Certificates**: the signing certificates of each TV, their expiry and which apps use them.

You can still add apps from any GitHub repository, either in the panel (**Add from GitHub**) or on the integration page.

## Setup

After adding the TV, use the buttons on the integration page:

1. **Add certificate**, choosing one of the two formats:
   - *TizenBrew Installer*: upload `tizenbrewInstallerConfig.json`. It lives in `%USERPROFILE%\share\` on the computer where TizenBrew Installer ran.
   - *author.p12 + distributor.p12*: Apps2Samsung keeps them in `%APPDATA%\Apps2Samsung\Certificate\<profile>\`, with the password in `password.txt`.
2. **Add app**: pick a preset (Nuvio TV) or any GitHub repository plus a regular expression for the release file, for example `\.wgt$`. Then select the certificate.

An `update.<tv>_<app>` entity appears. Press **Install** to update.

## Certificates

A Tizen app can only be updated with the **same author certificate** it was first installed with. If you get the error *"Author certificate not match"*, the app was installed with another tool's certificate. Find that certificate and add it. If you can't find it, the only option is to uninstall the app on the TV and install it fresh through HA-Brew, which loses the app's data.

Certificates are stored in `<config>/.storage/habrew/`, which is not reachable over the web. Samsung certificates expire after about a year. HA-Brew shows the expiry date of each certificate.

## Example automation

Install updates automatically when the TV is on but idle:

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

## Roadmap

- [x] Samsung Tizen: sdb transport, package signing, update entities
- [x] App catalog (Apps2Samsung community packages) and a sidebar panel to browse and install apps
- [ ] Native `.tpk` packages
- [ ] Creating Samsung certificates from Home Assistant
- [ ] LG webOS (Developer Mode: SSH install, automatic Developer Mode renewal)
- [ ] Certificate renewal helper

## Credits

The signing logic follows Samsung's webIDE-common-tizentv (Apache-2.0), as used by
[TizenBrew Installer](https://github.com/reisxd/TizenBrewInstaller) and
[NuvioTVSmart-Installer](https://github.com/NuvioMedia/NuvioTVSmart-Installer).
The app catalog format comes from [Apps2Samsung](https://github.com/Apps2Samsung/tizen-community-packages).

## License

GPL-3.0-only. See [LICENSE](LICENSE).
