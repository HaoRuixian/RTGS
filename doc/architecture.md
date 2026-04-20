# RTGS Architecture

This document summarizes the current code layering after the 2026 structure cleanup.

## Directory Layers

### Root Entry
- `gui_main.py`
  Starts the Qt application and hands control to `ui.app.manager.AppManager`.

### UI Layer (`ui/`)
- `ui/app/`
  Application shell and launcher screen.
- `ui/shared/`
  Reusable UI helpers shared by multiple modules, such as the stream configuration dialog and GNSS color palette.
- `ui/monitoring/`
  Real-time monitoring workbench, including live widgets, log settings, and worker threads.
- `ui/positioning/`
  Real-time positioning workbench and its configuration/views.
- `ui/reflectometry/`
  Reflectometry workbench, status helpers, dialogs, and analysis workers.
- `ui/refractometry/`
  Refractometry placeholder workbench.
- `ui/legacy/`
  Archived legacy UI implementations kept only for compatibility. Root-level files such as `ui/main_window.py` now act as thin wrappers.

### Core Layer (`core/`)
- GNSS decoding, RTCM/RINEX handling, threading primitives, geometry, and positioning models.
- `core/reflectometry/`
  Reflectometry domain models, configuration loading, providers, outputs, and business services.

### Config and Runtime Data
- `config/`
  Stream presets, reflectometry configuration, and legacy configs.
- `log/`
  Runtime logs and generated observation products.
- `output/`
  Exported files and analysis outputs.
- `doc/`
  Design notes, reports, and standards references.

## Active Runtime Flow

### Monitoring / Positioning / Reflectometry
1. `IOThread` receives RTCM, serial, or replayed RINEX data.
2. Raw messages enter `core.ring_buffer.RingBuffer`.
3. `DataProcessingThread` parses epochs through `core.rtcm_handler`.
4. The module window receives epochs by Qt signal and updates its own state and widgets.

### Shared Responsibilities
- `ui/shared/config_dialog.py`
  Central place for configuring stream inputs, replay files, and receiver position.
- `ui/shared/colors.py`
  Single source of truth for active GNSS system and signal colors.
- `core/ring_buffer.py`
  Thread-safe producer/consumer buffer used by acquisition, processing, and logging threads.

## Compatibility Strategy

- Root-level files in `ui/` remain as import-compatible wrappers.
- Real implementations now live inside the relevant subpackages.
- Archived PyQt6 code is isolated under `ui/legacy/pyqt_monitoring/` so it no longer mixes with active PySide6 code.

## Cleanup Outcomes

- Active PySide6 modules are grouped by domain instead of being scattered in the `ui/` root.
- Duplicated color and configuration dialog logic is consolidated into `ui/shared/`.
- Legacy implementations are explicitly archived instead of coexisting with active code paths.
