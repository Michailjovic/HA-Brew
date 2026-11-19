# Samsung VD CA certificates

Public CA certificates that Samsung appends to author and distributor certificates for TVs
(`res/ca/` in Samsung's Tizen certificate extension 2.0.75). They contain no secrets.

| File | Samsung file name | Subject CN | Valid until |
|---|---|---|---|
| `author_ca.pem` | `vd_tizen_dev_author_ca.cer` | Samsung VD Author CA | 2040-06-19 |
| `distributor_public.pem` | `vd_tizen_dev_public2.crt` | VD DEVELOPER Public CA Class | 2029-06-16 |
| `distributor_partner.pem` | `vd_tizen_dev_partner2.crt` | VD DEVELOPER Partner CA Class | 2029-06-16 |

Copied from [gifflet/tizen-cert-cli](https://github.com/gifflet/tizen-cert-cli) (MIT), `internal/samsung/ca/`.
