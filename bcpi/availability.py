"""Official conference availability reports for the matchup page.

The Power 4 conferences publish football availability through the same public
report (the page embedded on each conference site). This module reads that
feed and keeps offensive players listed out or doubtful. Questionable,
probable, exempt, and first-half-only designations are left alone.
"""

from __future__ import annotations

import json
import logging
import re
import urllib.request
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional

logger = logging.getLogger(__name__)

REPORT_URL = "https://app.hdintelligence.com/api/get-publish-public"
CONFERENCES = ("SEC", "B10", "ACC", "B12")

# Report position -> skill group. Offensive line is recognized and then
# skipped later, because these reports do not come with a snap or usage share.
OFFENSE_GROUPS = {
    "QB": "QB",
    "RB": "RB",
    "HB": "RB",
    "FB": "RB",
    "TB": "RB",
    "WR": "WR",
    "TE": "TE",
    "OL": "OL",
    "OT": "OL",
    "OG": "OL",
    "C": "OL",
    "IOL": "OL",
}

_COUNTED_STATUS = {"out", "doubtful"}
_ROW_RE = re.compile(
    r"^(?P<pos>[A-Za-z][A-Za-z0-9]{0,5})\s+#?(?P<num>\d+)\s+(?P<name>.+)$"
)


@dataclass(frozen=True)
class Absence:
    school_name: str
    player: str
    position: str
    group: str
    status: str
    conference: str
    report_type: str
    published: str


def _post(conference: str) -> dict:
    body = json.dumps(
        {"sport": "Football", "organization": conference, "conference": conference}
    ).encode()
    request = urllib.request.Request(
        REPORT_URL,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Origin": "https://app.hdintelligence.com",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def _status_key(status: str) -> str:
    return re.sub(r"\s+", " ", (status or "").strip().lower())


def _published_key(report: dict) -> str:
    """Sort key so a later report for the same team replaces an earlier one."""
    day = str(report.get("publishDate") or "")
    clock = str(report.get("postedTime") or "")
    parts = clock.split(":")
    try:
        seconds = int(parts[0]) * 3600 + int(parts[1]) * 60 + int(float(parts[2]))
    except (ValueError, IndexError):
        seconds = 0
    return f"{day}T{seconds:05d}"


def _parse_row(raw_name: str, status: str) -> Optional[tuple]:
    if _status_key(status) not in _COUNTED_STATUS:
        return None
    match = _ROW_RE.match((raw_name or "").strip())
    if not match:
        return None
    position = match.group("pos").upper()
    group = OFFENSE_GROUPS.get(position)
    if group is None:
        return None
    return match.group("name").strip(), position, group


def fetch_offensive_absences(
    conferences: Iterable[str] = CONFERENCES,
) -> List[Absence]:
    """Latest out/doubtful offensive names from each conference report."""
    latest: Dict[str, tuple] = {}
    for conference in conferences:
        try:
            payload = _post(conference)
        except Exception:
            logger.warning("Availability report failed for %s", conference, exc_info=True)
            continue
        reports = payload.values() if isinstance(payload, dict) else payload
        for report in reports:
            if not isinstance(report, dict):
                continue
            published = _published_key(report)
            report_type = str(report.get("ReportType") or "")
            for game in report.get("games") or []:
                school = str(game.get("teamDisplayName") or game.get("teamName") or "").strip()
                if not school:
                    continue
                found: List[Absence] = []
                for row in game.get("rows") or []:
                    parsed = _parse_row(str(row.get("name") or ""), str(row.get("status") or ""))
                    if parsed is None:
                        continue
                    player, position, group = parsed
                    found.append(
                        Absence(
                            school_name=school,
                            player=player,
                            position=position,
                            group=group,
                            status=_status_key(row.get("status") or ""),
                            conference=conference,
                            report_type=report_type,
                            published=published,
                        )
                    )
                key = f"{conference}:{school}"
                previous = latest.get(key)
                if previous is None or published >= previous[0]:
                    latest[key] = (published, found)

    absences: List[Absence] = []
    for _published, rows in latest.values():
        absences.extend(rows)
    return absences
