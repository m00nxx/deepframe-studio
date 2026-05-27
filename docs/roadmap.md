# Roadmap

This roadmap keeps the original six-phase structure and updates it for the Tauri 2 + React/TypeScript + FastAPI sidecar architecture.

## Phase 1 - Foundations

- Establish the Tauri 2 desktop shell.
- Build the React/TypeScript/Vite frontend with Tailwind CSS and shadcn-style UI primitives.
- Define the Python 3.12 FastAPI sidecar contract.
- Implement local sidecar lifecycle: launch, health check, dynamic `127.0.0.1` port, per-session token, shutdown.
- Define project file format and baseline validation.

## Phase 2 - Media Tooling

- Add configurable `ffmpeg` and `ffprobe` paths.
- Implement version checks and capability diagnostics.
- Add media probe endpoints.
- Add render command planning without unsafe shell interpolation.
- Build user-facing errors for missing tools, invalid inputs, and failed commands.
- Current MVP status: `ffmpeg`/`ffprobe` PATH detection, probe, export command preview, export progress polling, and cancel are implemented. Explicit binary path configuration is still partial.

## Phase 3 - Effect Registry

- Define the effect registry schema.
- Separate built-in effects, user presets, and plugin-provided metadata.
- Add compatibility fields for media type, parameters, preview support, and required binaries.
- Validate registry entries in backend tests.
- Expose registry data to the React UI through FastAPI.
- Current MVP status: YAML registry, supported categories, recommended badges, install/license metadata, typed parameters, chain script generation, and basic script validation are implemented.

## Phase 4 - Editing Workflow

- Build project creation/open/save flows.
- Add timeline or stack-based effect composition.
- Add parameter editing with typed controls.
- Add preview/probe workflows.
- Persist project state with explicit schema versioning.

## Phase 5 - Plugins and Distribution

- Add plugin metadata discovery without arbitrary code execution.
- Add license checks before enabling one-click installs.
- Require explicit user action for downloads.
- Update `THIRD_PARTY_NOTICES.md` for bundled or recommended third-party assets.
- Prepare platform packaging rules for Tauri builds.
- Build per-platform sidecar artifacts through `scripts/build_sidecar.py`.

## Phase 6 - Hardening and Release

- Add integration tests for sidecar lifecycle and API contracts.
- Add render regression fixtures where licensing allows.
- Complete legal and license review.
- Harden path validation and process spawning.
- Add real VapourSynth/AviSynth render path: validate required plugins, generate temp `.vpy`/`.avs`, pipe frames to FFmpeg, map progress/errors, and keep 32-bit bridge research separate.
- Prepare signed release builds and release notes.
- Document migration from any historical prototypes without presenting them as the current stack.
