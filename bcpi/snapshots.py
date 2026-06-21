"""Discover published ranking snapshots on disk."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from bcpi.config import OUTPUT_DIR


@dataclass(frozen=True)
class Snapshot:
    id: str
    season: int
    week: int
    postseason: bool
    label: str

    @property
    def season_key(self) -> tuple[int, int, bool]:
        return (self.season, self.week, self.postseason)


def _label(season: int, week: int, postseason: bool) -> str:
    if postseason:
        return f"{season} postseason"
    if week <= 0:
        return f"{season} preseason"
    return f"{season} · week {week}"


def _parse_power_path(path: Path) -> Optional[Snapshot]:
    match = re.match(
        r"bcpi_power_(\d{4})_(postseason|preseason|week(\d+))\.csv$",
        path.name,
    )
    if not match:
        return None
    season = int(match.group(1))
    kind = match.group(2)
    if kind == "postseason":
        week, postseason = 17, True
        snap_id = f"{season}-postseason"
    elif kind == "preseason":
        week, postseason = 0, False
        snap_id = f"{season}-preseason"
    else:
        week = int(match.group(3))
        postseason = False
        snap_id = f"{season}-week{week:02d}"
    return Snapshot(
        id=snap_id,
        season=season,
        week=week,
        postseason=postseason,
        label=_label(season, week, postseason),
    )


def discover_snapshots(output_dir: Path = OUTPUT_DIR) -> List[Snapshot]:
    """Return available power/poll snapshot pairs, newest first."""
    found: dict[str, Snapshot] = {}
    for path in output_dir.glob("bcpi_power_*.csv"):
        snap = _parse_power_path(path)
        if snap is None:
            continue
        poll_path = output_dir / f"bcpi_poll_{snap.season}_{path.stem.split('_', 3)[-1]}.csv"
        if not poll_path.exists():
            continue
        found[snap.id] = snap
    return sorted(
        found.values(),
        key=lambda s: (s.season, s.postseason, s.week),
        reverse=True,
    )


def snapshot_by_id(snapshot_id: str, output_dir: Path = OUTPUT_DIR) -> Optional[Snapshot]:
    for snap in discover_snapshots(output_dir):
        if snap.id == snapshot_id:
            return snap
    return None
