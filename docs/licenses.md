# Licenses

DeepFrame Studio uses a conservative licensing policy for application code, dependencies, media tools, plugins, models, presets, and sample assets.

## Project License

DeepFrame Studio application code is distributed under the MIT License in `LICENSE`.

The MIT License applies to this project's own source code and documentation only. Third-party tools, plugins, scripts, models, presets, media, and generated binaries remain governed by their respective licenses.

## Dependency Policy

Allowed by default:
- permissive open-source dependencies such as MIT, BSD, ISC, and Apache-2.0;
- LGPL components only when dynamic linking, notices, and user replacement rights are reviewed;
- GPL components only when the whole distribution strategy has been explicitly approved.

Every bundled third-party component that requires attribution must be listed in `THIRD_PARTY_NOTICES.md`.

## FFmpeg and ffprobe

`ffmpeg` and `ffprobe` are external configurable binaries. The app should not silently bundle them. If future packaging includes binaries, the exact build configuration, codecs, license mode, and notices must be reviewed before release.

## Models and Large Assets

DeepFrame Studio must not automatically download models, checkpoints, weights, LoRAs, sample packs, or plugin assets.

One-click download may be implemented only when:
- the license permits direct download and intended use;
- the source URL permits the access pattern;
- the user explicitly initiates the action;
- attribution and notices are recorded;
- checksums are stored for reproducibility.

## Plugin Licenses

Plugin metadata must include source and license fields. External plugins must also record a checksum or hash when available. Plugins with unclear, missing, or incompatible licenses must remain disabled for installation and distribution.

The effect registry may reference third-party projects as metadata for discovery and manual setup. A metadata reference is not approval to bundle, redistribute, auto-download, or execute that third-party component.

`new`, `new2`, and `new3` are not discovery catalogs. Raw discoveries remain in `artifacts/`; runtime entries may be promoted only after the plugin is installed or bundled, validated, templated, and renderable.

`new3` entries are promoted from locally bundled/runtime-installed script code only after render validation. Lightweight Python helper wheels are acceptable when they are needed by those scripts; AI models, large runtime stacks, and GPU-only packages remain excluded from automatic bundling.

## StaxRip Local Bundle

DeepFrame can import a local StaxRip installation into `vendor/staxrip` for offline integration. This is treated as a vendor bundle, not as DeepFrame-owned code.

The generated `vendor/staxrip/manifest.json` is the source of truth for imported component paths, source URLs, download URLs, AVS/VS filter names, and license status. Components marked `manual_review` must be reviewed before public redistribution.
