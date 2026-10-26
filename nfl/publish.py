"""Archive weekly NFL power JSON and sync it into the static site data tree."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

HERE = Path(__file__).resolve().parent
SITE_DATA = HERE / "site_data"
ENGINE = HERE / "engine"
PROJECT_ROOT = HERE.parent
DOCS_NFL = PROJECT_ROOT / "docs" / "data" / "nfl"
LA = ZoneInfo("America/Los_Angeles")
PBP_URL = (
    "https://github.com/nflverse/nflverse-data/releases/download/pbp/play_by_play_{season}.parquet"
)
SUMMARY_NAME = "nfl_refresh_summary.md"


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
    """Season year is the year the NFL season starts.

    March or later uses the current year. January and February use the previous
    year. The clock is America/Los_Angeles unless a date is passed in.
    """
    if today is None:
        today = datetime.now(LA).date()
    if today.month >= 3:
        return today.year
    return today.year - 1


def pbp_http_status(season: int) -> str:
    """HTTP status of this season's nflverse play-by-play file. Raises on network failure."""
    url = PBP_URL.format(season=season)
    proc = subprocess.run(
        ["curl", "-sS", "-I", "-L", "-o", "/dev/null", "-w", "%{http_code}", url],
        capture_output=True,
        text=True,
        timeout=90,
    )
    code = (proc.stdout or "").strip()
    if proc.returncode != 0 or not code or code == "000":
        detail = (proc.stderr or "").strip() or f"curl exit {proc.returncode}"
        raise RuntimeError(f"could not check play-by-play for {season}: {detail}")
    return code


def completed_reg_games(path: Path, season: int) -> int:
    """Regular-season games in a play-by-play file that have a final score."""
    import pandas as pd

    if not path.exists() or path.stat().st_size == 0:
        return 0
    frame = pd.read_parquet(
        path, columns=["game_id", "season", "season_type", "home_score", "away_score"]
    )
    if frame.empty:
        return 0
    regular = frame[(frame["season"] == season) & (frame["season_type"].astype(str) == "REG")]
    done = regular[regular["home_score"].notna() & regular["away_score"].notna()]
    if done.empty:
        return 0
    return int(done["game_id"].nunique())


def skip_reason_for_pbp(season: int, output: str, pbp_path: Path) -> Optional[str]:
    """Why to skip after a failed refresh, or None when the failure is real."""
    if f"play_by_play_{season}" in output and "404" in output:
        return f"play-by-play for {season} is not published yet"
    if not pbp_path.exists():
        return None
    try:
        games = completed_reg_games(pbp_path, season)
    except Exception as exc:
        print(f"warning: could not read {pbp_path.name}: {exc}", file=sys.stderr)
        return None
    if games == 0:
        return f"play-by-play for {season} has no completed games"
    return None


def _qb_markdown(output: str) -> str:
    marker = "QB situations to confirm"
    idx = output.find(marker)
    if idx < 0:
        return "None. This refresh did not flag any quarterback situations."
    return "```\n" + output[idx:].strip() + "\n```"


def _overrides_markdown() -> str:
    path = HERE / "overrides.csv"
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        return f"Could not read `nfl/overrides.csv` ({exc})."
    text = raw.strip()
    if not text or text == "team,starter,p_start,note":
        return "No rows. The file has only the header."
    return "```csv\n" + text + "\n```"


def write_refresh_summary(season: int, note: str, qb_text: str) -> None:
    """Write the QB check and current overrides for the Actions job summary.

    The workflow appends this file to $GITHUB_STEP_SUMMARY. A write failure is
    logged and does not fail the refresh.
    """
    try:
        lines = [
            "## NFL refresh",
            "",
            note.strip(),
            "",
            "## QB situations to confirm",
            "",
            qb_text.strip(),
            "",
            "## overrides.csv",
            "",
            "Current rows in `nfl/overrides.csv`:",
            "",
            _overrides_markdown(),
            "",
        ]
        text = "\n".join(lines)
        base = os.environ.get("RUNNER_TEMP") or "/tmp"
        path = Path(base) / SUMMARY_NAME
        path.write_text(text, encoding="utf-8")
        print(f"Wrote NFL job summary to {path}")
    except Exception as exc:
        print(f"warning: could not write the NFL job summary: {exc}", file=sys.stderr)


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
    """Run the engine refresh, then archive.

    The season year is computed when omitted. If that season's play-by-play file
    is not published yet, or it has no completed games, the last published
    rankings are left untouched and the result is marked skipped.
    """
    season = int(season) if season is not None else infer_nfl_season()
    print(f"NFL season {season} (America/Los_Angeles)")
    status = pbp_http_status(season)
    if status == "404":
        reason = f"play-by-play for {season} is not published yet"
        write_refresh_summary(
            season,
            f"Season {season} was skipped: {reason}. Last published NFL rankings were kept.",
            "No new list. The NFL refresh did not run.",
        )
        return {"skipped": True, "season": season, "reason": reason}
    if status != "200":
        raise RuntimeError(f"play-by-play check for {season} returned HTTP {status}")

    cmd = [sys.executable, str(ENGINE / "refresh.py"), "--season", str(season)]
    if through_week is not None:
        cmd.extend(["--through-week", str(through_week)])
    shown = ["python3", "engine/refresh.py", "--season", str(season)]
    if through_week is not None:
        shown.extend(["--through-week", str(through_week)])
    print("Running:", " ".join(shown))
    proc = subprocess.run(cmd, cwd=str(HERE), capture_output=True, text=True)
    if proc.stdout:
        print(proc.stdout, end="" if proc.stdout.endswith("\n") else "\n")
    if proc.stderr:
        print(proc.stderr, file=sys.stderr, end="" if proc.stderr.endswith("\n") else "\n")
    output = proc.stdout or ""
    if proc.returncode != 0:
        combined = output + "\n" + (proc.stderr or "")
        reason = skip_reason_for_pbp(season, combined, HERE / "data" / f"pbp_{season}.parquet")
        if reason:
            write_refresh_summary(
                season,
                f"Season {season} was skipped: {reason}. Last published NFL rankings were kept.",
                "No new list. The NFL refresh did not run.",
            )
            return {"skipped": True, "season": season, "reason": reason}
        write_refresh_summary(
            season,
            f"Season {season} refresh failed. See the step log.",
            "No list. The refresh failed before it finished.",
        )
        raise SystemExit(proc.returncode)

    power = _read_json(SITE_DATA / "nfl_power.json")
    snap_id = archive_power(power)
    write_refresh_summary(
        season,
        f"Season {season} refresh finished. Snapshot {snap_id}.",
        _qb_markdown(output),
    )
    return {
        "skipped": False,
        "season": season,
        "snapshot": snap_id,
        "through_week": power["meta"]["through_week"],
    }


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
        if info.get("skipped"):
            print(
                f"Skipping NFL refresh ({info['season']}): {info['reason']}. "
                "Keeping the last published NFL rankings."
            )
        else:
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
