# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [0.4.2] - 2026-11-20

### Fixed
- hassfest: no URL inside translation strings (Samsung account link moved to a placeholder).

## [0.4.1] - 2026-11-20

### Added
- Catalog filter by root: all apps, only apps that work without root, or only root apps (Samsung and LG).

### Fixed
- hassfest: translation keys of the certificate privilege selector must be lowercase (`public`, `partner`); Samsung still receives `Public` / `Partner`.

## [0.4.0] - 2026-11-20

### Added
- **Create Samsung certificates in Home Assistant** (*Add certificate → Create a new certificate (Samsung account)*), without Tizen Studio, Apps2Samsung or TizenBrew:
  - Home Assistant creates the keys and CSRs, has Samsung issue an author and a distributor certificate (Public or Partner) for every Samsung TV in HA-Brew plus optional extra DUIDs, and stores them like an uploaded `.p12` pair.
  - Samsung only returns the sign-in to `http://localhost:4794` on the computer with the browser. The dialog shows a one-line command (Windows PowerShell, or `curl | python3` on macOS/Linux) that downloads a small helper from Home Assistant, opens the Samsung sign-in, catches the result once and forwards it. One-time link, valid 15 minutes. Nothing is installed.
  - Later certificates reuse the same author key.
  - Clear messages for an account without e-mail, rate limiting and a rejected sign-in.
- Samsung's public VD CA certificates are bundled (`drivers/tizen/ca/`, from tizen-cert-cli, MIT).
- Installation guide: section on creating a certificate, new troubleshooting rows.

### Changed
- The certificate name is optional (defaults to the certificate type or the account e-mail).
- Diagnostics also redact DUID lists of certificates.

## [0.3.1] - 2026-11-19

### Added
- **Uninstall from the TV**: removing an app in the panel now offers *Only stop managing* or *Uninstall from TV*; unmanaged sideloaded apps get an uninstall button too. HA-Brew checks afterwards that the app is really gone (some Samsung TVs from 2021 on ignore the command; the message then says to remove it on the TV).
- After *Author certificate not match* the panel offers **Uninstall and install again** (the app loses its data).
- **Diagnostics** (*Download diagnostics*): TV model, system version, apps, releases, last errors and a live read-out from the TV; IP/MAC, DUID, serial number, keys, passphrase and certificate details are redacted.
- Step-by-step installation guide in English and Czech (`docs/installation.md`, `docs/installation.cs.md`).
- WebSocket command `habrew/app/uninstall` (with `reinstall`).

### Fixed
- Packages that need a newer Tizen than the TV runs are refused before uploading, with a clear message.
- An app no longer shows an endless update when the catalog describes a release with another version string than the one the TV reports after installing it.

## [0.3.0] - 2026-11-19

### Added
- **LG webOS TVs** (Developer Mode, no root needed).
  - Setup: choose *LG*, then type the passphrase the Developer Mode app shows while **Key Server** is on. Home Assistant downloads the SSH key once and keeps it.
  - Packages (`.ipk`) are streamed to the TV over SSH (port 9922) and installed with the TV's app installer. No signing and no certificates.
  - **Developer Mode session**: HA-Brew restarts the 1000-hour session at LG once a day (also while the TV is off). Sensor *Developer Mode remaining* (hours), button *Extend Developer Mode*, and a repair issue when the session cannot be extended or less than 7 days are left.
  - When Developer Mode was switched off and on (new key), Home Assistant asks for the new passphrase.
  - Catalog: the [webOS Homebrew repository](https://repo.webosbrew.org), checked against its SHA-256.
  - Presets: Nuvio TV (`NuvioTV-webOS-*.ipk`) and YouTube AdFree.
- Panel:
  - LG TVs show the Developer Mode session with an **Extend** button.
  - The catalog tab switches between Samsung and LG when both are set up.
  - Apps that match a preset (Nuvio TV, YouTube AdFree) can be taken over from GitHub in one click.
- WebSocket command `habrew/devmode/extend`; `habrew/catalog` takes `platform`.

### Changed
- The TV name is optional when adding a TV (defaults to the model).
- App and package ids are checked before they are used in commands on the TV.
- Pending state is saved when the integration reloads.

### Dependencies
- `asyncssh` (pure Python, installed automatically; only used for LG TVs).

## [0.2.3] - 2026-11-16

### Added
- Waking up the TV. **Configure** on the integration page offers Wake-on-LAN (MAC address, optional broadcast address) or turning on an entity, for example the `media_player` of SamsungTV Smart. Installing, updating and launching wake the TV first and wait until it answers.
- Launching apps: ▶ next to every installed app in the panel (managed, sideloaded and store apps).
- Panel: **Turn TV on** button when the TV is offline and a wake-up method is set, plus a shortcut to the wake-up settings.
- WebSocket commands `habrew/app/launch` and `habrew/wake`.

### Changed
- Install, Update and Reinstall stay enabled while the TV is off if a wake-up method is set.

## [0.2.2] - 2026-11-16

### Fixed
- The TV device and the app entities belong to the config entry again, not to app subentries. This removes the Home Assistant warning *"assigns an existing device to a different config subentry"*, which would stop working in HA 2027.8. Existing installs are migrated on startup.
- Entities of removed apps are deleted from the entity registry.

### Changed
- Panel: Install, Update and Reinstall are disabled while the TV is off or unreachable, with a hint to turn it on and press *Check now*.

## [0.2.1] - 2026-11-16

### Changed
- Panel, TVs tab: apps that are not managed are split into:
  - **sideloaded apps**: take over from the catalog, or add from GitHub when the catalog doesn't have them
  - **Samsung store / system apps**: collapsed, read-only, because Samsung updates them
- Panel, Catalog tab:
  - Variants of the same app are grouped into one card.
  - Each card shows its state per TV: *managed*, *installed but not managed* (button **Take over**), or not installed (**Add to TV**).
  - Apps managed from GitHub are recognised too.
- Take-over forms only offer the variants that match the installed package, and remind you to pick the original certificate.

### Fixed
- Repository links for catalog providers without their own metadata (e.g. TizenTube).

## [0.2.0] - 2026-11-16

### Added
- **HA-Brew sidebar panel** (admins only), with three tabs:
  - **TVs**: managed apps with installed and available version, install/update/reinstall/remove with live progress. Other apps on the TV can be taken over with **Manage** when the catalog has them. Apps can be added from GitHub.
  - **Catalog**: the Apps2Samsung community catalog (web apps), with search, categories, an optional 18+ filter, and flag and certificate-level warnings. **Add to TV** can install right away.
  - **Certificates**: expiry and usage per certificate.
- Catalog app source. Catalog apps do not need GitHub API calls. Downloads are verified against the catalog's SHA-256.
- WebSocket API (`habrew/overview`, `habrew/catalog`, `habrew/app/add`, `habrew/app/remove`, `habrew/app/install`, `habrew/refresh`).
- App icons from the catalog are used as the entity picture.
- Brand icon.

### Changed
- Install progress is tracked by the coordinator, so the panel and the update entity show the same state.
- The cached package is re-downloaded when the release URL changes.

### Fixed
- hassfest: translation strings no longer contain `<...>`.

## [0.1.0] - 2026-11-16

### Added
- Samsung Tizen TVs, set up through the UI. The TV is identified by its DUID.
- Signing certificate subentries, in two formats:
  - TizenBrew Installer `tizenbrewInstallerConfig.json`
  - `author.p12` + `distributor.p12` (Apps2Samsung, Tizen Studio)
- Certificate checks:
  - Validation of the password and the key.
  - A check that the distributor certificate was issued for this TV's DUID.
- App subentries: a Nuvio TV preset, or any GitHub repository with a release asset pattern. Pre-releases are optional.
- One `update` entity per app:
  - installed version read from the TV, latest version read from the package's `config.xml`
  - release notes
  - install with progress
- Installation on the TV: re-signing (SHA-512 / RSA-SHA512, byte-identical to tizen-js), `sdb` push and `vd_appinstall`.
- Clear errors when the author certificate does not match, the signature is rejected or the platform is incompatible.
- The last known installed versions are kept while the TV is off. Downloaded packages are cached.
- English and Czech translations.
