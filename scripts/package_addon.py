from __future__ import annotations

import argparse
import json
import time
import zipfile
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
ADDON_DIR = ROOT / "addon"
DEFAULT_OUTPUT = ROOT / "dist" / "progress_bar_time_left.ankiaddon"
PACKAGE_ID = "1097423555"

EXCLUDED_DIRS = {"__pycache__"}
EXCLUDED_NAMES = {".DS_Store", "meta.json", "manifest.json"}
EXCLUDED_SUFFIXES = {".pyc", ".pyo"}


def _load_meta() -> dict[str, Any]:
    meta_path = ADDON_DIR / "meta.json"
    with meta_path.open(encoding="utf-8") as handle:
        return json.load(handle)


def _manifest(meta: dict[str, Any], mod_time: int) -> dict[str, Any]:
    manifest = {
        "package": PACKAGE_ID,
        "name": meta.get("name", "Progress Bar Time Left"),
        "mod": mod_time,
        "min_point_version": int(meta.get("min_point_version", 49)),
        "max_point_version": int(meta.get("max_point_version", 260500)),
        "conflicts": list(meta.get("conflicts", [])),
    }
    for optional_key in ("branch_index", "human_version", "homepage"):
        if optional_key in meta:
            manifest[optional_key] = meta[optional_key]
    return manifest


def _iter_package_files() -> list[Path]:
    files: list[Path] = []
    for path in ADDON_DIR.rglob("*"):
        if path.is_dir():
            continue
        relative_parts = path.relative_to(ADDON_DIR).parts
        if any(part in EXCLUDED_DIRS for part in relative_parts):
            continue
        if path.name in EXCLUDED_NAMES:
            continue
        if path.suffix in EXCLUDED_SUFFIXES:
            continue
        files.append(path)
    return sorted(files)


def build_package(output: Path, mod_time: int | None = None) -> Path:
    meta = _load_meta()
    package_mod_time = int(mod_time if mod_time is not None else time.time())
    output.parent.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "manifest.json",
            json.dumps(_manifest(meta, package_mod_time), indent=2, sort_keys=True) + "\n",
        )
        for path in _iter_package_files():
            archive.write(path, path.relative_to(ADDON_DIR).as_posix())

    return output


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a release-ready Anki addon package.")
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="Destination .ankiaddon file.",
    )
    parser.add_argument(
        "--mod-time",
        type=int,
        default=None,
        help="Manifest mod timestamp. Defaults to the current Unix timestamp.",
    )
    args = parser.parse_args()

    output = build_package(args.output, args.mod_time)
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
