# Effect Registry

The effect registry is the canonical metadata source for effects available to DeepFrame Studio. It is served by the local FastAPI sidecar and consumed by the React UI.

## Goals

- Provide typed effect metadata for UI controls.
- Keep effect definitions data-driven.
- Track compatibility with media types and external tools.
- Support built-in effects, user presets, and reviewed plugin metadata.
- Make licensing status visible before distribution or installation.
- Prefer VapourSynth for modern workflows while keeping AviSynth+ compatibility metadata.

## Supported Categories

The MVP registry uses these categories:

`denoise`, `deinterlace`, `sharpen`, `blur`, `resize`, `upscale`, `repair`, `stabilize`, `color`, `deband`, `degrain`, `artifact removal`, `face restore`, `frame interpolation`, `encode`, `custom`.

Each category may contain many effects. Recommended badges are capped to a small set per category so the browser remains useful when the catalog grows.

## Registry Entry

Each effect should define:
- `id`: stable unique identifier.
- `name`: display name.
- `engine`: `vapoursynth` or `avisynth`.
- `category`: one of the supported effect categories.
- `description`: short functional description.
- `recommended`: whether it should receive a recommended badge.
- `renderable`: computed by the sidecar; true only when runtime files are available and the effect has an executable script template.
- `render_status`: `renderable`, `missing_runtime`, or `not_renderable`.
- `required_plugins`: external scripts or binaries needed by the effect.
- `install_status`: `installed`, `missing`, `manual`, or another reviewed status.
- `install_method`: short user-facing installation guidance.
- `install_policy`: `builtin`, `manual`, `metadata_only`, or `allowed_download`.
- `install_allowed`: whether the UI may expose an installer action. This should remain `false` unless license/source review explicitly approves it.
- `manual_steps`: optional manual setup instructions.
- `source_url`: upstream project or documentation URL.
- `download_url`: direct download URL only when legally reviewed.
- `license_status`: `built_in`, `redistributable`, `manual_review`, or `unclear`.
- `license_notes`: redistribution and upstream license notes.
- `cpu_gpu_notes`: CPU, GPU, CUDA, OpenCL, or compatibility notes.
- `parameters`: typed UI controls with defaults, labels, help text, ranges, steps, and options.
- `defaults`: values used when an effect is first added to the chain.
- `script_template` or `script_templates`: VapourSynth/AviSynth command templates.
- `script_imports`: optional import lines required by VapourSynth templates.
- `input_constraints` and `output_constraints`: media format limits.

## Parameters

Each parameter may define:
- `name`: stable key used in script templates.
- `type`: `int`, `float`, `bool`, `enum`, or `string`.
- `default`: initial value.
- `min`, `max`, `step`: numeric control range.
- `label`: compact UI label.
- `description`: short explanation of what the value changes.
- `unit`: optional unit such as `px`.
- `options`: allowed values for `enum` controls.

When `min` and `max` are present for numeric parameters, the UI can show both a slider and a numeric input. The numeric input remains the precise source for values that are awkward to tune by dragging.

## Validation Rules

The sidecar should reject registry entries that:
- omit license and install metadata;
- include executable code in data-only plugin definitions;
- reference auto-download URLs without explicit license approval;
- define unsafe shell fragments;
- use duplicate IDs;
- expose parameters without type/range validation.

MVP script templates generate chain previews for VapourSynth and AviSynth+. User-supplied template overrides are limited to `custom` effects.

Implemented validation currently covers duplicate IDs, basic typed schema loading, safe template defaults, and script generation. Full plugin-install validation, dependency probing, and shell-safety review for third-party installer actions remain roadmap items.

## Plugin Policy

Plugins may contribute metadata, presets, and effect definitions only through reviewed formats. Automatic execution of downloaded plugin code is out of scope until a sandbox and security model are approved.

One-click plugin or asset installation is allowed only when:
- the upstream license allows it;
- the URL is stable and legal for direct user-initiated download;
- checksum and provenance metadata are recorded;
- `THIRD_PARTY_NOTICES.md` is updated when required.

The runtime registry must not expose catalog-only discoveries as usable effects. `new`, `new2`, and `new3` are runtime groups, not catalogs: entries can appear there only after they are deduplicated, installed or bundled, templated, validated, and renderable. Metadata-only discoveries stay in `artifacts/` until promoted.

## Discovery Notes

External registry crawling is kept as a local research workflow and is not published with the application. Raw crawled metadata belongs in ignored `artifacts/` files until a component is reviewed, deduplicated, installed or bundled, templated, parameterized, and validated.

Reviewed source families include:

- `vapoursynth/vsrepo` package metadata.
- AviSynth external filter references.
- VSDB and AVSRepoGUI listings.
- Selected GitHub organizations and repositories such as Jaded Encoding Thaumaturgy, theChaosCoder, and `AviSynth/avs-scripts`.
- VirtualDub filter references, treated only as AviSynth-compatible research metadata.
- Doom9 links, rate-limited and metadata-only.

Runtime `new3` currently uses a stricter promotion path:

- source candidates come from the bundled local StaxRip/VapourSynth script folders plus reviewed external-source metadata;
- helper Python wheels may be installed only when lightweight and non-model/non-GPU-runtime;
- each entry must generate a concrete script template with editable parameters;
- VSPipe must render the synthetic validation script before the entry is written to the app registry.

Promotion policy for discovered entries:

- `new`, `new2`, and `new3` are not catalog buckets in the app;
- an entry may be promoted only when plugin files are present, a script template exists, parameters are editable, validation succeeds, and the effect is renderable;
- duplicates already covered by StaxRip or stable categories must stay out of `new*`;
- `suggested_category` stores the internal best-effort mapping for later review;
- `install_allowed` is always `false`;
- `validation_status` must distinguish metadata validation from runtime-render validation.

This keeps the app focused on working effects instead of a long list of dead entries. Raw crawled metadata is still useful for review, but it is not loaded into the visible effect browser.
