"""Archive weekly NFL power JSON and sync it into the static site data tree."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional

HERE = Path(__file__).resolve().parent
SITE_DATA = HERE / "site_data"
ENGINE = HERE / "engine"
PROJECT_ROOT = HERE.parent
DOCS_NFL = PROJECT_ROOT / "docs" / "data" / "nfl"


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _snap_id(season: int, week: int) -> str:
    return f"{season}-week{week:02d}"


def _snap_label(season: int, week: int) -> str:
    return f"{season} · week {week}"


def infer_nfl_season(today: Optional[date] = None) -> int:
    today = today or date.today()
    # NFL season year is the year of the regular season opener (Sept).
    if today.month >= 8:
        return today.year
    if today.month <= 2:
        return today.year - 1
    return today.year


def archive_power(power: Dict[str, Any], site_data: Path = SITE_DATA) -> str:
    """Write current power.json, snapshot copy, and catalog. Returns snapshot id."""
    meta = power["meta"]
    season = int(meta["season"])
    week = int(meta["through_week"])
    snap_id = _snap_id(season, week)

    site_data.mkdir(parents=True, exist_ok=True)
    _write_json(site_data / "power.json", power)
    _write_json(site_data / "nfl_power.json", power)
    snap_dir = site_data / "snapshots" / snap_id
    snap_dir.mkdir(parents=True, exist_ok=True)
    _write_json(snap_dir / "power.json", power)

    catalog_path = site_data / "catalog.json"
    snapshots: List[Dict[str, Any]] = []
    if catalog_path.exists():
        existing = _read_json(catalog_path)
        snapshots = list(existing.get("snapshots") or [])

    entry = {"id": snap_id, "season": season, "week": week, "label": _snap_label(season, week)}
    by_id = {row["id"]: row for row in snapshots}
    by_id[snap_id] = entry
    snapshots = sorted(by_id.values(), key=lambda row: (row["season"], row["week"]), reverse=True)
    seasons = [row["season"] for row in snapshots]
    catalog = {
        "default": snap_id,
        "snapshots": snapshots,
        "min_season": min(seasons) if seasons else season,
        "max_season": max(seasons) if seasons else season,
    }
    _write_json(catalog_path, catalog)
    return snap_id


def sync_to_docs(site_data: Path = SITE_DATA, dest: Path = DOCS_NFL) -> Path:
    """Copy durable NFL site_data into docs/data/nfl for GitHub Pages."""
    if not site_data.exists():
        raise FileNotFoundError(f"missing NFL site data at {site_data}")
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)

    for name in ("power.json", "nfl_power.json", "catalog.json", "teams.json"):
        src = site_data / name
        if src.exists():
            shutil.copy2(src, dest / name)

    snaps = site_data / "snapshots"
    if snaps.exists():
        shutil.copytree(snaps, dest / "snapshots")
    return dest


def run_refresh(season: Optional[int] = None, through_week: Optional[int] = None) -> Dict[str, Any]:
    """Run the engine refresh, then archive + sync."""
    season = season or infer_nfl_season()
    cmd = [sys.executable, str(ENGINE / "refresh.py"), "--season", str(season)]
    if through_week is not None:
        cmd.extend(["--through-week", str(through_week)])
    subprocess.run(cmd, cwd=str(HERE), check=True)
    power = _read_json(SITE_DATA / "nfl_power.json")
    snap_id = archive_power(power)
    return {"season": season, "snapshot": snap_id, "through_week": power["meta"]["through_week"]}


def main() -> None:
    ap = argparse.ArgumentParser(description="Publish NFL power rankings into the site data tree")
    ap.add_argument("--refresh", action="store_true", help="run engine/refresh.py first")
    ap.add_argument("--season", type=int)
    ap.add_argument("--through-week", type=int)
    ap.add_argument("--sync-docs", action="store_true", help="copy site_data into docs/data/nfl")
    ap.add_argument("--archive-only", action="store_true", help="archive existing nfl_power.json only")
    args = ap.parse_args()

    if args.refresh:
        info = run_refresh(season=args.season, through_week=args.through_week)
        print(f"refreshed NFL power → {info['snapshot']}")
    elif args.archive_only or (SITE_DATA / "nfl_power.json").exists():
        power = _read_json(SITE_DATA / "nfl_power.json")
        snap_id = archive_power(power)
        print(f"archived NFL power → {snap_id}")
    else:
        sys.exit("no nfl_power.json to publish; pass --refresh")

    if args.sync_docs:
        dest = sync_to_docs()
        print(f"synced to {dest}")


if __name__ == "__main__":
    main()
