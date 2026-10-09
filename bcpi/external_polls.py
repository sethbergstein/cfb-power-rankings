"""AP, CFP, and ESPN FPI ranks aligned to a ranking snapshot.

CollegeFootballData stores the preseason poll as week 1. Each later poll is
the one released after that many weeks of games minus one: the poll that
includes games through week W is rankings week W + 1. The CFP committee poll
is absent until it has been released, which is usually early November.

ESPN FPI is stored as one rating per season, the latest update (or the final
rating after the year ends). It is attached only where that file matches the
snapshot: the current regular-season week, or a postseason snapshot.
"""

from __future__ import annotations

from typing import Dict, Iterable, Optional

from bcpi.cfbd import CFBDClient
from bcpi.snapshots import discover_snapshots

AP_POLL = "AP Top 25"
CFP_POLLS = ("Playoff Committee Rankings", "CFP Rankings")

PollRanks = Dict[str, int]


def _poll_ranks(entry: Optional[dict], names: Iterable[str]) -> Optional[PollRanks]:
    """Ranks 1–25 for the first matching poll, or None if that poll is absent."""
    if not entry:
        return None
    wanted = set(names)
    poll = next((item for item in entry.get("polls") or [] if item.get("poll") in wanted), None)
    if poll is None:
        return None
    ranks: PollRanks = {}
    for row in poll.get("ranks") or []:
        school = row.get("school")
        raw = row.get("rank")
        if not school or raw is None:
            continue
        try:
            rank = int(raw)
        except (TypeError, ValueError):
            continue
        if 1 <= rank <= 25:
            ranks[str(school)] = rank
    if not ranks:
        return None
    return {school: rank for school, rank in sorted(ranks.items(), key=lambda item: (item[1], item[0]))}


def _by_week(entries: object) -> Dict[int, dict]:
    if not isinstance(entries, list):
        return {}
    found: Dict[int, dict] = {}
    for entry in entries:
        if not isinstance(entry, dict) or entry.get("week") is None:
            continue
        found[int(entry["week"])] = entry
    return found


def _latest(by_week: Dict[int, dict], names: Iterable[str]) -> Optional[PollRanks]:
    found: Optional[PollRanks] = None
    for week in sorted(by_week):
        ranks = _poll_ranks(by_week[week], names)
        if ranks:
            found = ranks
    return found


def _season_rankings(client: CFBDClient, season: int, season_type: str) -> Dict[int, dict]:
    return _by_week(client.get("/rankings", {"year": season, "seasonType": season_type}))


def _fpi_matches_snapshot(season: int, week: int, postseason: bool) -> bool:
    """True when the stored FPI is the rating for this snapshot, not a later week."""
    if postseason:
        return True
    if int(week or 0) <= 0:
        return False
    season_snaps = [snap for snap in discover_snapshots() if snap.season == int(season)]
    if any(snap.postseason for snap in season_snaps):
        return False
    latest = max((snap.week for snap in season_snaps if not snap.postseason), default=0)
    return int(week) == latest


def load_fpi_ranks(client: CFBDClient, season: int) -> Optional[PollRanks]:
    """ESPN FPI rank for every team in the stored season rating. None if missing."""
    data = client.get("/ratings/fpi", {"year": int(season)})
    if not isinstance(data, list) or not data:
        return None
    ranks: PollRanks = {}
    for row in data:
        school = row.get("team")
        raw = (row.get("resumeRanks") or {}).get("fpi")
        if not school or raw is None:
            continue
        try:
            rank = int(raw)
        except (TypeError, ValueError):
            continue
        if rank >= 1:
            ranks[str(school)] = rank
    if not ranks:
        return None
    return {school: rank for school, rank in sorted(ranks.items(), key=lambda item: (item[1], item[0]))}


def load_external_polls(
    client: CFBDClient,
    season: int,
    week: int,
    postseason: bool,
) -> Dict[str, Optional[PollRanks]]:
    """Return AP, CFP, and FPI maps. A null poll has not been released for this snapshot."""
    season = int(season)
    week = int(week or 0)
    regular = _season_rankings(client, season, "regular")

    if postseason:
        postseason_weeks = _season_rankings(client, season, "postseason")
        ap = _latest(postseason_weeks, (AP_POLL,)) or _latest(regular, (AP_POLL,))
        cfp = _latest(regular, CFP_POLLS)
    else:
        # Week 0 is preseason, which CFBD files as rankings week 1.
        poll_week = 1 if week <= 0 else week + 1
        entry = regular.get(poll_week)
        ap = _poll_ranks(entry, (AP_POLL,))
        cfp = _poll_ranks(entry, CFP_POLLS)

    fpi: Optional[PollRanks] = None
    if _fpi_matches_snapshot(season, week, postseason):
        try:
            fpi = load_fpi_ranks(client, season)
        except Exception:
            fpi = None
    return {"ap": ap, "cfp": cfp, "fpi": fpi}


def load_external_polls_for_request(
    season: int,
    week: int,
    postseason: bool,
) -> Dict[str, Optional[PollRanks]]:
    """Same as ``load_external_polls``, but a data failure leaves the polls blank."""
    empty: Dict[str, Optional[PollRanks]] = {"ap": None, "cfp": None, "fpi": None}
    try:
        client = CFBDClient(use_cache=True)
    except Exception:
        return empty
    try:
        return load_external_polls(client, season, week, postseason)
    except Exception:
        return empty
    finally:
        client.close()
