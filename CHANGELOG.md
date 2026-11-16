# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

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
