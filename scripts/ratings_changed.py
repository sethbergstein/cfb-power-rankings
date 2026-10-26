#!/usr/bin/env python3
"""Compare published ratings to HEAD; exit 0 if they changed, 1 if unchanged.

Ignores volatile timestamps (as_of, generated_utc, updated) so a daily rebuild
that only refreshes clocks does not count as a ratings change.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
VOLATILE_KEYS = frozenset({"as_of", "generated_utc", "updated", "revision"})

# Published ranking payloads that define "ratings changed".
RATING_PATHS = (
    Path("docs/data/power.json"),
    Path("docs/data/poll.json"),
    Path("docs/data/nfl/nfl_power.json"),
    Path("nfl/site_data/nfl_power.json"),
)


def _strip_volatile(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _strip_volatile(item)
            for key, item in value.items()
            if key not in VOLATILE_KEYS
        }
    if isinstance(value, list):
        return [_strip_volatile(item) for item in value]
    return value


def _load_json(text: str) -> Any:
    return _strip_volatile(json.loads(text))


def _git_show(rel: Path) -> str | None:
    result = subprocess.run(
        ["git", "show", f"HEAD:{rel.as_posix()}"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None
    return result.stdout


def main() -> int:
    changed: list[str] = []
    for rel in RATING_PATHS:
        path = ROOT / rel
        if not path.exists():
            # Missing after a full publish is unexpected; treat as change so CI
            # does not silently skip when the export tree is incomplete.
            if _git_show(rel) is not None:
                changed.append(f"{rel} (deleted)")
            continue
        current = _load_json(path.read_text(encoding="utf-8"))
        previous_text = _git_show(rel)
        if previous_text is None:
            changed.append(f"{rel} (new)")
            continue
        previous = _load_json(previous_text)
        if current != previous:
            changed.append(str(rel))

    if changed:
        print("Ratings changed:")
        for item in changed:
            print(f"  {item}")
        return 0

    print("Ratings unchanged (timestamps ignored).")
    return 1


if __name__ == "__main__":
    sys.exit(main())
