# Configuration layout

The `config/` directory contains source-controlled templates and station
profiles used by a checkout. It is intentionally excluded from release
artifacts because deployments should keep credentials and machine-specific
paths outside the package.

| Directory | Responsibility |
| --- | --- |
| `streams/` | Observation, ephemeris, SSR, and RTK stream profiles. `example_config.yaml` is the credential-free schema reference. |
| `ir/` | GNSS-IR station and processing profiles. |
| `antex/` and `blq/` | Optional station-specific PPP model overrides. |
| `legacy/` | Writable compatibility files created by older configuration flows. |

At runtime, `core.config_paths` selects the repository configuration when RTGS
runs from a source checkout. Installed applications use the platform user
directory, or the path supplied by `RTGS_CONFIG_DIR`. Generated logs and
processing products belong in the ignored `log/` and `output/` directories.

Do not put credentials in committed profiles. Use `<user>`, `<password>`, or
environment-variable placeholders and keep deployment values in a local
configuration directory.
