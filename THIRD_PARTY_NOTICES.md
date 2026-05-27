# Third-Party Notices

This file tracks third-party software, tools, assets, models, and plugins bundled with or recommended by DeepFrame Studio.

## Runtime and Build Dependencies

The JavaScript application currently declares dependencies including:
- React and React DOM
- Vite
- TypeScript
- Tailwind CSS
- shadcn-style UI dependencies, including Radix UI primitives, class variance helpers, and utility libraries
- Tauri 2 JavaScript API and CLI
- lucide-react icons

Before release, generate an exact dependency notice report from the lockfile and package metadata.

## External Media Tools

FFmpeg and ffprobe are external configurable tools. They are not assumed to be bundled by this notice file. If future releases bundle FFmpeg or ffprobe binaries, add:
- exact binary source;
- version;
- build configuration;
- enabled codecs/libraries;
- license mode;
- required attribution and license text.

## Models, Plugins, Presets, and Assets

No AI models are bundled or approved for automatic download.

The effect registry includes metadata references for user-managed manual setup only. These references are not bundled components and are not redistribution approval:
- VapourSynth documentation and built-in filters
- KNLMeansCL
- VapourSynth-BM3D
- havsfunc/QTGMC/DeHalo/Deblock metadata
- CAS-compatible scripts/plugins
- neo_f3kdb
- AviSynth+ MCTemporalDenoise metadata
- FFmpeg encode preset metadata
- Real-ESRGAN, RIFE, and GFPGAN future adapter metadata

Raw plugin discovery catalogs remain in `artifacts/` and are not release inventory. `new`, `new2`, and `new3` are not catalogs; they may list only plugins that are installed or bundled, validated, templated, and renderable.

Local development `new3` validation installed lightweight VapourSynth helper wheels into the bundled runtime:
- VSUtil 0.8.0
- vs-rgtools 1.9.2
- vs-kernels 3.4.4
- vsmask 0.5.1
- vs-exprtools 1.8.3
- vs-aa 1.12.3
- vs-dehalo 1.10.3

These helpers require release-time license/source/hash review before public redistribution.

## StaxRip Local Plugin Bundle

A local StaxRip installation can be imported into `vendor/staxrip` for offline development. The import reads `C:\StaxRip\sorgenti\Source\General\Package.vb` and copies installed plugin/script binaries from `C:\StaxRip\StaxRip-v2.52.3-x64`.

Current generated inventory:
- manifest: `vendor/staxrip/manifest.json`
- copied files: 286
- components parsed: 299
- installed components found: 284
- license status counts: MIT 254, GPL 35, LGPL 3, manual review 7

`vendor/staxrip/bundle` and `vendor/staxrip/licenses` are ignored by Git because they are large vendor artifacts. The manifest remains tracked as the reproducible inventory.

Any bundled or one-click-installable item must be added here with:
- name;
- version;
- source URL;
- license;
- hash/checksum when available;
- attribution text;
- redistribution/download permission notes.

## Pending Release Task

This notice file is a policy baseline, not a final release inventory. A release build must include an exact third-party inventory generated from the actual packaged artifacts.
