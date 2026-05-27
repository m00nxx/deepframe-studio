# DeepFrame Studio

DeepFrame Studio is an open-source, local-first desktop application for building and previewing video enhancement and effect workflows.

Current architecture:
- Desktop shell: Tauri 2.
- Frontend: React, TypeScript, Vite, Tailwind CSS, shadcn-style components.
- Backend sidecar: Python 3.12 FastAPI process bound to `127.0.0.1` on a dynamic local port.
- Media tools: external `ffmpeg` and `ffprobe` binaries configured by the user or discovered from the local environment.

Tauri owns the desktop lifecycle. It starts the FastAPI sidecar during app startup, passes the selected local port to the frontend, and shuts the sidecar down when the app exits. The backend is not a remote service and must not listen on public interfaces.

The desktop runtime also creates a per-session local token and sends it to the sidecar. Browser CORS is not treated as the security boundary.

## Development

Install JavaScript dependencies:

```bash
npm install
```

Run the frontend only:

```bash
npm run dev
```

Run the backend directly on a fixed development port:

```bash
npm run backend:dev
```

Run backend tests:

```bash
npm run backend:test
```

Run the full desktop app through Tauri:

```bash
npm run tauri:dev
```

Build the web bundle:

```bash
npm run build
```

Build a release sidecar binary for the current platform:

```bash
npm run sidecar:build
```

Build the desktop package:

```bash
npm run tauri:build
```

For release packaging, run `npm run sidecar:build` before `npm run tauri:build`. The generated sidecar is placed under `src-tauri/binaries/` for Tauri `externalBin` packaging. The Linux development wrapper in that folder is only for local development.

## Runtime Tools

DeepFrame Studio expects `ffmpeg` and `ffprobe` to be available as external binaries. The MVP discovers them from system `PATH`; explicit path configuration is planned. The app validates the available binaries before media operations and surfaces version/path information to the user.

The MVP also detects `vspipe` and AviSynth pipe tools from `PATH` when present. It can generate and validate VapourSynth/AviSynth+ scripts, but final rendering through those engines remains a roadmap feature.

## Effect Registry

The MVP ships a YAML effect registry with VapourSynth-first and AviSynth-compatible metadata. Registry entries can describe recommended effects, plugin requirements, install status, license status, CPU/GPU notes, input/output constraints, typed parameters, and script templates.

Current registry entries are metadata and script scaffolds. They do not bundle third-party plugins, models, or effect packs, and they do not trigger automatic downloads.

## Models, Plugins, and Licenses

The application must not download AI models, effect packs, presets, or plugins automatically. One-click install flows are allowed only when the license and source URL explicitly permit redistribution or direct download by the user. Every bundled or recommended third-party component must be tracked in `THIRD_PARTY_NOTICES.md`.

See:
- `docs/architecture.md`
- `docs/roadmap.md`
- `docs/effect_registry.md`
- `docs/licenses.md`
- `docs/legal_policy.md`
- `docs/codex_tasks.md`
