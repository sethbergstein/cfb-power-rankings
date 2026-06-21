"""Build static JSON bundles and site tree for GitHub Pages."""

from __future__ import annotations

import json
import os
import shutil
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from bcpi.cfbd import CFBDClient
from bcpi.config import OUTPUT_DIR, PROJECT_ROOT
from bcpi.constants import TARGET_SEASON
from bcpi.home_field import load_team_hfa
from bcpi.params import get_active_params
from bcpi.pipeline import run_poll_rankings, run_rankings
from bcpi.rankings_io import find_rankings_path
from bcpi.snapshots import Snapshot, discover_snapshots
from bcpi.team_profiles import get_team_profiles
from bcpi.teams import get_fbs_teams

WEB_DIR = PROJECT_ROOT / "web"
DOCS_DIR = PROJECT_ROOT / "docs"
DATA_DIR = DOCS_DIR / "data"

DEFAULT_SITE_URL = "https://sethbergstein.github.io/cfb-power-rankings"


def site_url() -> str:
    return os.environ.get("BCPI_SITE_URL", DEFAULT_SITE_URL).rstrip("/")


def infer_season(today: Optional[date] = None) -> int:
    """Guess the active CFB season for publishing."""
    today = today or date.today()
    if today.month >= 8:
        return today.year
    if today.month <= 2:
        return today.year - 1
    return TARGET_SEASON


def infer_postseason(today: Optional[date] = None) -> bool:
    """Include bowl/CFP games in late-season publishes."""
    today = today or date.today()
    return today.month in (12, 1)


def _snapshot_label(season: int, week: int, postseason: bool) -> str:
    if postseason:
        return f"{season} postseason"
    if week <= 0:
        return f"{season} preseason"
    return f"{season} · week {week}"


def _parse_snapshot_from_path(path: Path) -> Tuple[int, bool, int]:
    stem = path.stem
    season = int(stem.split("_")[2])
    if stem.endswith("_postseason"):
        return season, True, 17
    if stem.endswith("_preseason"):
        return season, False, 0
    if "_week" in stem:
        week = int(stem.rsplit("_week", 1)[-1])
        return season, False, week
    return season, False, 0


def _enrich_rows(kind: str, df: pd.DataFrame, season: int, postseason: bool) -> List[Dict[str, Any]]:
    rows = df.sort_values("rank").to_dict(orient="records")
    other_kind = "poll" if kind == "power" else "power"
    other_path = find_rankings_path(other_kind, season, postseason=postseason)
    if other_path and other_path.exists():
        other_df = pd.read_csv(other_path).set_index("school")
        for row in rows:
            school = row["school"]
            if school not in other_df.index:
                continue
            other = other_df.loc[school]
            if kind == "power":
                row["wins"] = int(other.get("wins", 0))
                row["losses"] = int(other.get("losses", 0))
                row["poll_rank"] = int(other["rank"])
                row["poll_score"] = float(other["poll_score"])
            else:
                row["power_rank"] = int(other["rank"])
                row["power_score"] = float(other["power_score"])
    return rows


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)


def export_snapshot_bundle(
    snap: Snapshot,
    client: Optional[CFBDClient] = None,
) -> Dict[str, Any]:
    """Write one snapshot's JSON bundle under docs/data/snapshots/{id}/."""
    owns_client = client is None
    if owns_client:
        client = CFBDClient(use_cache=True)

    try:
        power_path = find_rankings_path("power", snap.season, postseason=snap.postseason, week=snap.week or None)
        poll_path = find_rankings_path("poll", snap.season, postseason=snap.postseason, week=snap.week or None)
        if power_path is None or poll_path is None:
            raise FileNotFoundError(f"Missing rankings files for snapshot {snap.id}")

        power_df = pd.read_csv(power_path)
        poll_df = pd.read_csv(poll_path)
        power_rows = _enrich_rows("power", power_df, snap.season, snap.postseason)
        poll_rows = _enrich_rows("poll", poll_df, snap.season, snap.postseason)

        teams = get_fbs_teams(client, snap.season)
        profiles = get_team_profiles(client, snap.season)
        team_payload = []
        for team in teams:
            profile = profiles.get(team.school, {})
            team_payload.append(
                {
                    "school": team.school,
                    "abbreviation": team.abbreviation,
                    "conference": profile.get("conference") or team.conference,
                    "color": profile.get("color"),
                    "alternate_color": profile.get("alternate_color"),
                    "logo": profile.get("logo"),
                    "logo_dark": profile.get("logo_dark"),
                    "venue_name": profile.get("venue_name"),
                    "venue_city": profile.get("venue_city"),
                    "venue_state": profile.get("venue_state"),
                    "venue_location": profile.get("venue_location"),
                    "venue_capacity": profile.get("venue_capacity"),
                }
            )

        as_of = power_rows[0].get("as_of") if power_rows else None
        snap_dir = DATA_DIR / "snapshots" / snap.id
        snap_dir.mkdir(parents=True, exist_ok=True)
        _write_json(snap_dir / "teams.json", team_payload)
        _write_json(
            snap_dir / "power.json",
            {
                "id": snap.id,
                "season": snap.season,
                "week": snap.week,
                "postseason": snap.postseason,
                "label": snap.label,
                "as_of": as_of,
                "rows": power_rows,
            },
        )
        _write_json(
            snap_dir / "poll.json",
            {
                "id": snap.id,
                "season": snap.season,
                "week": snap.week,
                "postseason": snap.postseason,
                "label": snap.label,
                "as_of": as_of,
                "rows": poll_rows,
            },
        )
        return {"id": snap.id, "label": snap.label, "as_of": as_of}
    finally:
        if owns_client and client is not None:
            client.close()


def export_all_snapshots(client: Optional[CFBDClient] = None) -> List[Dict[str, Any]]:
    """Export every on-disk snapshot for the static site catalog."""
    snaps = discover_snapshots()
    exported = []
    owns_client = client is None
    if owns_client:
        client = CFBDClient(use_cache=True)
    try:
        for snap in snaps:
            exported.append(export_snapshot_bundle(snap, client=client))
    finally:
        if owns_client and client is not None:
            client.close()

    catalog = {
        "default": snaps[0].id if snaps else None,
        "snapshots": [
            {
                "id": snap.id,
                "season": snap.season,
                "week": snap.week,
                "postseason": snap.postseason,
                "label": snap.label,
            }
            for snap in snaps
        ],
        "min_season": 2018,
        "max_season": TARGET_SEASON + 1,
    }
    _write_json(DATA_DIR / "catalog.json", catalog)
    return exported


def export_data_bundle(
    season: int,
    postseason: bool = False,
    refresh: bool = False,
    client: Optional[CFBDClient] = None,
) -> Dict[str, Any]:
    """Generate rankings and write docs/data/*.json."""
    owns_client = client is None
    if owns_client:
        client = CFBDClient(use_cache=not refresh)

    params = get_active_params()
    try:
        power_path = run_rankings(
            season=season,
            refresh_data=refresh,
            params=params,
            include_postseason=postseason,
        )
        poll_path = run_poll_rankings(
            season=season,
            refresh_data=refresh,
            params=params,
            include_postseason=postseason,
        )

        power_df = pd.read_csv(power_path)
        poll_df = pd.read_csv(poll_path)
        _, inferred_postseason, week = _parse_snapshot_from_path(power_path)
        postseason = postseason or inferred_postseason
        if "week" in power_df.columns and len(power_df):
            week = int(power_df["week"].iloc[0])

        power_rows = _enrich_rows("power", power_df, season, postseason)
        poll_rows = _enrich_rows("poll", poll_df, season, postseason)

        teams = get_fbs_teams(client, season)
        profiles = get_team_profiles(client, season)
        schools = [team.school for team in teams]
        team_payload = []
        for team in teams:
            profile = profiles.get(team.school, {})
            team_payload.append(
                {
                    "school": team.school,
                    "abbreviation": team.abbreviation,
                    "conference": profile.get("conference") or team.conference,
                    "color": profile.get("color"),
                    "alternate_color": profile.get("alternate_color"),
                    "logo": profile.get("logo"),
                    "logo_dark": profile.get("logo_dark"),
                    "venue_name": profile.get("venue_name"),
                    "venue_city": profile.get("venue_city"),
                    "venue_state": profile.get("venue_state"),
                    "venue_location": profile.get("venue_location"),
                    "venue_capacity": profile.get("venue_capacity"),
                }
            )

        as_of = power_rows[0].get("as_of") if power_rows else None
        label = _snapshot_label(season, week, postseason)
        team_hfa = load_team_hfa(client, schools, season, params, refresh=refresh)

        DATA_DIR.mkdir(parents=True, exist_ok=True)
        _write_json(
            DATA_DIR / "manifest.json",
            {
                "mode": "static",
                "season": season,
                "week": week,
                "postseason": postseason,
                "label": label,
                "as_of": as_of,
                "updated": date.today().isoformat(),
            },
        )
        _write_json(DATA_DIR / "teams.json", team_payload)
        _write_json(
            DATA_DIR / "power.json",
            {
                "season": season,
                "week": week,
                "postseason": postseason,
                "label": label,
                "as_of": as_of,
                "rows": power_rows,
            },
        )
        _write_json(
            DATA_DIR / "poll.json",
            {
                "season": season,
                "week": week,
                "postseason": postseason,
                "label": label,
                "as_of": as_of,
                "rows": poll_rows,
            },
        )
        _write_json(
            DATA_DIR / "params.json",
            {
                "margin_scale": params.margin_scale,
                "hfa": params.hfa,
                "hfa_team_max_delta": params.hfa_team_max_delta,
                "win_prob_scale": params.win_prob_scale,
                "team_hfa": team_hfa,
            },
        )

        return {
            "season": season,
            "week": week,
            "postseason": postseason,
            "label": label,
            "power_path": str(power_path),
            "poll_path": str(poll_path),
        }
    finally:
        if owns_client and client is not None:
            client.close()


def _inject_static_config(html: str) -> str:
    snippet = '<script>window.BCPI_CONFIG={mode:"static",dataUrl:"./data"};</script>'
    if snippet in html:
        return html
    for marker in ('<script src="./static/theme.js"', '<script src="/static/theme.js"'):
        if marker in html:
            return html.replace(marker, f"{snippet}\n    {marker}")
    return html


def _rewrite_asset_paths(html: str) -> str:
    return (
        html.replace('href="/static/', 'href="./static/')
        .replace('src="/static/', 'src="./static/')
        .replace('href="/power.html"', 'href="./power.html"')
        .replace('href="/poll.html"', 'href="./poll.html"')
        .replace('href="/"', 'href="./index.html"')
    )


def _apply_site_url(html: str) -> str:
    url = site_url()
    if url != DEFAULT_SITE_URL:
        return html.replace(DEFAULT_SITE_URL, url)
    return html


def export_site_tree(refresh: bool = False, season: Optional[int] = None) -> Path:
    """Publish docs/ for GitHub Pages."""
    season = season or infer_season()
    postseason = infer_postseason()

    if DOCS_DIR.exists():
        shutil.rmtree(DOCS_DIR)
    DOCS_DIR.mkdir(parents=True)

    shutil.copytree(WEB_DIR / "static", DOCS_DIR / "static")

    for name in ("index.html", "power.html", "poll.html"):
        src = WEB_DIR / name
        dst = DOCS_DIR / name
        html = src.read_text(encoding="utf-8")
        html = _rewrite_asset_paths(html)
        html = _apply_site_url(html)
        html = _inject_static_config(html)
        dst.write_text(html, encoding="utf-8")

    meta = export_data_bundle(season=season, postseason=postseason, refresh=refresh)
    export_all_snapshots()
    _write_json(DOCS_DIR / "data" / "build.json", {"exported": meta})
    (DOCS_DIR / ".nojekyll").touch()
    return DOCS_DIR
