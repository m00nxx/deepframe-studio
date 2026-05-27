# Codex Tasks

Rules for Codex workers on this project:

- Respect task scope exactly.
- Do not edit `backend/**`, `src/**`, `src-tauri/**`, `package.json`, or other code files when assigned root-docs-only work.
- Do not revert changes made by other workers.
- Keep documentation aligned with the current architecture: Tauri 2, React/TypeScript, Tailwind/shadcn, Python 3.12 FastAPI sidecar.
- Keep sidecar docs explicit: local `127.0.0.1`, dynamic packaged-app port, Tauri-managed startup/shutdown.
- Keep local sidecar security explicit: per-session bearer token, CORS is not the security boundary.
- Keep FFmpeg/ffprobe docs explicit: external configurable binaries.
- Maintain license/plugin policy: no automatic model/plugin downloads, one-click only when license and URL permit it.
- Update `THIRD_PARTY_NOTICES.md` whenever third-party bundled assets, dependencies, binaries, or notices change.

## Suggested Work Split

1. Architecture and lifecycle docs.
2. API contract and sidecar tests.
3. Effect registry schema and validation.
4. UI flows and project persistence.
5. Plugin/license review.
6. Packaging, release, and notices.
