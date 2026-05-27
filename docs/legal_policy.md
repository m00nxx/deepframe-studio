# Legal Policy

This document defines project rules for third-party software, plugins, models, media samples, and generated outputs.

## No Automatic Downloads

The application must not automatically download:
- AI models or weights;
- effect packs;
- plugins;
- presets;
- sample media;
- external binaries.

Downloads require explicit user action and a license/source review. AI/model packages are never downloaded automatically.

## One-Click Installs

One-click installs are allowed only when all of the following are true:
- the license permits the download and intended use;
- the URL permits direct user-initiated download;
- attribution requirements are understood;
- required notices are added to `THIRD_PARTY_NOTICES.md`;
- checksum/provenance metadata is recorded;
- the user is shown the source and license before installation.

External plugin records must keep source, license, and checksum/hash when available. Raw plugin discovery remains in `artifacts/`; `new`, `new2`, and `new3` may contain only installed, validated, renderable entries.

`new3` is a runtime promotion bucket, not a forum/catalog import. Entries from AVSRepo, VSDB, Doom9, or GitHub can reach it only when their code is locally present, templated, parameterized, and validated; otherwise they remain artifact metadata for review.

## External Tools

FFmpeg and ffprobe must be treated as user-configurable external tools unless a future packaging review approves bundling. The app should show configured paths and versions where relevant.

## User Content

Projects and media files remain user-controlled local content. The local FastAPI sidecar should process only user-selected files and should not upload content unless a future feature explicitly adds remote services with clear consent.

The local sidecar must bind only to `127.0.0.1` and require the Tauri-provided session token whenever Tauri launches it.
