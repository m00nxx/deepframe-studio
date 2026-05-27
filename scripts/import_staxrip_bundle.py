from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
from time import time

from deepframe_api.staxrip import DEFAULT_STAXRIP_INSTALL, DEFAULT_STAXRIP_SOURCE, scan_staxrip


DEFAULT_DEST = Path("vendor/staxrip")


def main() -> int:
    parser = argparse.ArgumentParser(description="Import locally installed StaxRip plugins/scripts into DeepFrame.")
    parser.add_argument("--source-file", type=Path, default=DEFAULT_STAXRIP_SOURCE)
    parser.add_argument("--install-root", type=Path, default=DEFAULT_STAXRIP_INSTALL)
    parser.add_argument("--dest", type=Path, default=DEFAULT_DEST)
    args = parser.parse_args()

    started = time()
    result = scan_staxrip(args.source_file, args.install_root)
    bundle_root = args.dest / "bundle"
    manifest_path = args.dest / "manifest.json"
    notices_dir = args.dest / "licenses"
    bundle_root.mkdir(parents=True, exist_ok=True)
    notices_dir.mkdir(parents=True, exist_ok=True)

    copied: list[dict[str, str]] = []
    for component in result.components:
        for source in component.installed_paths:
            source_path = Path(source)
            relative = source_path.relative_to(args.install_root)
            target_path = bundle_root / relative
            target_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_path, target_path)
            copied.append({"component": component.name, "source": str(source_path), "target": str(target_path)})

    for runtime_name in ("VapourSynth", "AviSynth"):
        runtime_source = args.install_root / "Apps" / "FrameServer" / runtime_name
        if not runtime_source.exists():
            continue
        runtime_target = bundle_root / "Apps" / "FrameServer" / runtime_name
        if runtime_target.exists():
            shutil.rmtree(runtime_target)
        shutil.copytree(runtime_source, runtime_target)
        for source_path in runtime_source.rglob("*"):
            if source_path.is_file():
                copied.append(
                    {
                        "component": f"{runtime_name} runtime",
                        "source": str(source_path),
                        "target": str(runtime_target / source_path.relative_to(runtime_source)),
                    }
                )

        for license_file in component.license_files:
            license_path = Path(license_file)
            if not license_path.exists():
                continue
            relative = license_path.relative_to(args.install_root) if license_path.is_relative_to(args.install_root) else Path(license_path.name)
            target_path = notices_dir / relative
            target_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(license_path, target_path)

    manifest = result.model_dump()
    manifest["bundle_root"] = str(bundle_root)
    manifest["copied_files"] = copied
    manifest["generated_at_unix"] = int(started)
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"components={result.total} installed={result.installed} copied_files={len(copied)}")
    print(f"manifest={manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
