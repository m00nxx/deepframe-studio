# StaxRip Local Bundle

DeepFrame can import the locally installed StaxRip plugin/script set from `C:\StaxRip` into `vendor/staxrip`.

The import is offline and does not download components one by one. It reads StaxRip's `Source/General/Package.vb` catalog, copies installed files from the local StaxRip tree, and writes `vendor/staxrip/manifest.json`.

Current bundle status:
- source catalog: `C:\StaxRip\sorgenti\Source\General\Package.vb`
- install source: `C:\StaxRip\StaxRip-v2.52.3-x64`
- imported files: `vendor/staxrip/bundle`
- license/readme files: `vendor/staxrip/licenses`
- manifest: `vendor/staxrip/manifest.json`

The manifest records component names, source URLs, download URLs, AVS/VS filter names, expected paths, installed paths, and best-effort license status.

`vendor/staxrip/bundle` and `vendor/staxrip/licenses` are ignored by Git because they are large binary/vendor artifacts. Regenerate them with:

```bash
PYTHONPATH=backend python3 scripts/import_staxrip_bundle.py
```

Before a public release, review every `manual_review` component in the manifest and include exact notices in `THIRD_PARTY_NOTICES.md`.
