# Changelog

## 0.2.0 - 2026-05-27

### Added

- Rebuilt DeepFrame Studio on Tauri 2, React, TypeScript, Tailwind CSS, and a Python 3.12 FastAPI sidecar.
- Added FFmpeg/ffprobe detection, metadata probing, selected-range export jobs, progress polling, and cancellation.
- Added JSON project save/load, media import, in/out controls, segment scaffolding, and command logging.
- Added a VapourSynth/AviSynth effect registry with StaxRip-derived metadata, renderability filtering, effect chaining, drag reorder, enable/disable, removal, script preview, and typed parameter editing.
- Added rendered preview support, original/processed/split compare modes, draggable split bar, and split sweep control.
- Added focused tests for API behavior, FFmpeg command building, project models, preview rendering, effect parsing, chain behavior, StaxRip import, plugin promotion, and frontend helpers.

### Changed

- Restricted visible `new*` effect buckets to promoted entries that are deduplicated, templated, parameterized, installed or bundled, and runtime-validated.
- Reworked the effect browser into primary and secondary category columns with compact rows and engine selection for VS/AVS variants.
- Kept external crawler workflows out of the published app; raw discovery data remains local-only until reviewed.
- Hardened dev startup by separating backend, Vite, and Tauri processes in `scripts/restart_dev.sh`.
- Limited Vite/Tailwind scanning to app sources and ignored large local folders to prevent white screens and slow startup.

### Fixed

- Fixed Tauri white-screen startup caused by Vite/Tailwind scanning unrelated large directories.
- Fixed missing CSS generation after tightening Tailwind source scanning.
- Added a visible boot error fallback so frontend render failures are no longer silent.
- Improved WSLg/WebKit launch stability with software-renderer environment settings in the restart script.

### Notes

- DeepFrame Studio is still an MVP. Plugin coverage is intentionally limited to components that are present, legal to bundle or reference, and validated as usable.
- Full final-quality VapourSynth/AviSynth export and model-manager workflows remain roadmap items.
