# Architecture

DeepFrame Studio uses a Tauri 2 desktop shell with a React/TypeScript frontend and a local Python 3.12 FastAPI sidecar.

## Components

### Tauri 2 Shell

Tauri is the desktop host and lifecycle owner. It is responsible for:
- launching the frontend WebView;
- starting the Python FastAPI sidecar;
- selecting or receiving the sidecar local port;
- exposing the backend base URL to the frontend;
- exposing a per-session local authorization token to the frontend;
- shutting down the sidecar when the app exits;
- mediating filesystem and native OS capabilities.

The app must treat the backend as local-only. The sidecar binds to `127.0.0.1` on a dynamic port and must not expose public network interfaces.

### React/TypeScript Frontend

The UI is built with React, TypeScript, Vite, Tailwind CSS, and shadcn-style primitives. It should own:
- project navigation and editing workflows;
- timeline/effect controls;
- local settings for tool paths and plugin state;
- calls to the FastAPI sidecar through the Tauri-provided local base URL;
- presentation of validation, progress, and error states.

The frontend should not assume a fixed backend port in packaged builds.

### FastAPI Sidecar

The backend is a Python 3.12 FastAPI process launched locally by Tauri. It owns:
- project file validation and serialization;
- effect registry queries;
- media probing and render orchestration;
- adapters around external tools such as `ffmpeg` and `ffprobe`;
- script generation and validation adapters for `vspipe` and AviSynth-compatible pipe tools when available;
- plugin metadata validation.

For direct development, a fixed port can be used through `npm run backend:dev`. In the desktop runtime, the port is dynamic and local. Release builds use Tauri `externalBin`; run `npm run sidecar:build` to create the platform sidecar binary before packaging.

### FFmpeg and ffprobe

`ffmpeg` and `ffprobe` are external configurable tools. DeepFrame Studio should:
- allow explicit binary paths;
- support discovery from `PATH`;
- validate executability and version;
- avoid bundling binaries unless licensing, platform packaging, and notices are reviewed;
- report command failures without hiding stderr diagnostics.

### VapourSynth and AviSynth+

The MVP generates VapourSynth and AviSynth+ script previews from the ordered effect chain. It can detect `vspipe` and an AviSynth pipe tool such as `avs2yuv`/`avs2pipemod` from `PATH`, report versions when available, and validate generated temporary scripts when those tools exist.

Full rendering through `.vpy`/`.avs`, plugin dependency validation, 32-bit bridging, and pipe-to-FFmpeg workflows remain roadmap items.

## API Surface

Current local endpoints include:
- `GET /health`
- `GET /tools/detect`
- `POST /media/probe`
- `POST /export/command`
- `POST /export/jobs`
- `GET /export/jobs/{job_id}`
- `POST /export/jobs/{job_id}/cancel`
- `GET /effects`
- `POST /effects/chain/script`
- `POST /effects/chain/validate`

## Data Flow

1. Tauri starts the app and launches the FastAPI sidecar on `127.0.0.1:<dynamic-port>`.
2. Tauri provides the backend base URL and local token to the WebView.
3. React calls the sidecar for project operations, effect metadata, probes, and render jobs.
4. FastAPI validates inputs and invokes local adapters.
5. The effect chain can generate VapourSynth/AviSynth+ scripts and optionally validate them with local tools.
6. FFmpeg export jobs report status through polling and can be canceled.
7. Tauri shuts down the sidecar during app exit.

## Security Boundaries

The local backend is trusted only as part of the desktop app. Required constraints:
- bind only to `127.0.0.1`;
- require the per-session bearer token when launched by Tauri;
- reject unexpected origins where practical;
- validate all file paths and avoid arbitrary shell execution;
- pass process arguments as arrays, not shell strings;
- keep plugins data-driven until a reviewed execution sandbox exists;
- never auto-download third-party models or code.
