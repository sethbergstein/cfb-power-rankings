#!/usr/bin/env python3
"""Regenerate OG preview images and home-screen icons.

Usage (from the repo root, with the venv active):

    python scripts/generate_brand_images.py

Or:

    python run_bcpi.py brand-images

Reads the latest published rankings from docs/data/power.json and teams.json,
writes images into web/ (and mirrors into docs/ when that tree exists), and
updates web/manifest.webmanifest.

On a full site publish (`python run_bcpi.py export-site`) this runs automatically
so the weekly OG filename and meta tags stay in sync with the rankings.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bcpi.brand_images import generate_all, write_manifest  # noqa: E402
from bcpi.config import PROJECT_ROOT  # noqa: E402


def main() -> None:
    written = generate_all(out_dir=PROJECT_ROOT / "web")
    write_manifest(PROJECT_ROOT / "web")
    docs = PROJECT_ROOT / "docs"
    if docs.exists():
        import shutil

        for key, path in written.items():
            if key in ("og_filename", "og_meta"):
                continue
            if not getattr(path, "exists", lambda: False)():
                continue
            shutil.copy2(path, docs / path.name)
            static = docs / "static"
            if static.exists():
                shutil.copy2(path, static / path.name)
        weekly = written.get("og-weekly")
        if weekly and weekly.exists() and (docs / "static").exists():
            shutil.copy2(weekly, docs / "static" / "og-preview.png")
        write_manifest(docs)
    print(f"Weekly OG file: {written.get('og_filename')}")
    for key, path in written.items():
        if key in ("og_filename", "og_meta"):
            continue
        print(f"  {path}")


if __name__ == "__main__":
    main()
