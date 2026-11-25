# RTGS architecture

RTGS is a desktop GNSS workbench with a small set of explicit layers. New code
should follow these boundaries so that processing remains usable without the
GUI.

```text
entry points              gui_main.py  batch_main.py  rtcm_batch_gui.py
                              │
                              ▼
UI orchestration           ui/app, ui/batch, ui/<workbench>, ui/shared
                              │
                              ▼
GNSS processing            core/ (streams, RTCM/RINEX, positioning, GNSS-IR)
                              │
                              ▼
shared infrastructure      src/rtgs/infrastructure (logging and package metadata)
```

## Canonical directories

- `core/` contains reusable data contracts, stream adapters, decoders, writers,
  positioning solvers, and reflectometry services. It must not import Qt.
- `ui/` contains PySide6 windows, widgets, workers, and user interaction. The
  workbench implementations live under `ui/app`, `ui/monitoring`,
  `ui/positioning`, `ui/reflectometry`, and `ui/refractometry`.
- `utils/` contains command-line tools and separately deployable services. The
  `utils/realtime_ekf_gnssir/_vendor/` tree is an intentional isolated snapshot
  for that standalone service and is not a second application entry point.
- `src/rtgs/` contains package-wide infrastructure that is shared by `core`,
  `ui`, and `utils` without creating a dependency from infrastructure into a
  workbench.
- `config/` contains checkout-local templates. See `config/README.md` for the
  configuration and runtime-data policy.
- `tests/` is organized by compatibility tests at the root and focused suites
  under `unit/`, `integration/`, `regression/`, and `reflectometry/`.

## Entry points and compatibility modules

Use these commands during development:

| Command | Role |
| --- | --- |
| `python gui_main.py` or `rtgs` | Main desktop launcher |
| `python batch_main.py` or `rtgs-batch` | Multi-station batch console |
| `python rtcm_batch_gui.py` or `rtgs-rtcm-batch` | RTCM batch converter |
| `python -m <utility>` | Headless conversion and service tools |

The modules directly under `ui/` such as `ui/app_manager.py` and
`ui/monitoring_module.py` are compatibility shims. New imports should use the
nested canonical modules. `ui/legacy/` is retained only for the archived PyQt6
monitoring implementation and is excluded from packages.

## Runtime lifecycle

1. An entry point configures the shared logger and creates the Qt application
   when a GUI is requested.
2. `ui/app/manager.py` creates one workbench window at a time.
3. Workbench workers consume adapters from `core/` and send typed results to
   widgets through Qt signals.
4. Configuration paths are resolved by `core/config_paths.py`, which supports
   repository templates, platform user directories, and `RTGS_CONFIG_DIR`.
5. Logs and generated products are written outside source modules and remain
   ignored by version control.

Keep protocol parsing, numerical models, and file formats in `core/`. Keep Qt
state and presentation in `ui/`. Add a command-line wrapper in `utils/` when a
processing capability needs to run without a desktop session.
