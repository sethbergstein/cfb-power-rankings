"""CollegeFootballData.com API client with local file caching."""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

from bcpi.config import CACHE_DIR, CFBD_API_KEY
from bcpi.constants import CFBD_BASE_URL


class CFBDError(Exception):
    """Raised when the CFBD API returns an error response."""


class CFBDClient:
    """Thin wrapper around CFBD REST endpoints."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        cache_dir: Optional[Path] = None,
        use_cache: bool = True,
    ) -> None:
        self.api_key = api_key or CFBD_API_KEY
        if not self.api_key:
            raise ValueError(
                "CFBD_API_KEY is not set. Copy .env.example to .env and add your key."
            )
        self.cache_dir = cache_dir or CACHE_DIR
        self.use_cache = use_cache
        self._client = httpx.Client(
            base_url=CFBD_BASE_URL,
            headers={"Authorization": f"Bearer {self.api_key}"},
            timeout=60.0,
        )

    def _cache_path(self, endpoint: str, params: Dict[str, Any]) -> Path:
        key = json.dumps({"endpoint": endpoint, "params": params}, sort_keys=True)
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
        return self.cache_dir / f"{digest}.json"

    def get(
        self,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
        force_refresh: bool = False,
    ) -> Any:
        params = params or {}
        cache_path = self._cache_path(endpoint, params)

        if self.use_cache and not force_refresh and cache_path.exists():
            with cache_path.open("r", encoding="utf-8") as handle:
                return json.load(handle)

        response = self._client.get(endpoint, params=params)
        if response.status_code == 429:
            for wait in (2.0, 5.0, 10.0):
                time.sleep(wait)
                response = self._client.get(endpoint, params=params)
                if response.status_code != 429:
                    break
        if response.status_code >= 400:
            raise CFBDError(
                f"CFBD {endpoint} failed ({response.status_code}): {response.text}"
            )

        data = response.json()
        if self.use_cache:
            with cache_path.open("w", encoding="utf-8") as handle:
                json.dump(data, handle)
        return data

    def get_fbs_teams(self) -> List[Dict[str, Any]]:
        return self.get("/teams/fbs")

    def get_teams(self, year: int) -> List[Dict[str, Any]]:
        return self.get("/teams", {"year": year})

    def get_games(
        self,
        year: int,
        season_type: str = "regular",
        week: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        params: Dict[str, Any] = {"year": year, "seasonType": season_type}
        if week is not None:
            params["week"] = week
        return self.get("/games", params)

    def get_lines(
        self,
        year: int,
        season_type: str = "regular",
        week: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        params: Dict[str, Any] = {"year": year, "seasonType": season_type}
        if week is not None:
            params["week"] = week
        return self.get("/lines", params)

    def get_team_talent(self, year: int) -> List[Dict[str, Any]]:
        return self.get("/talent", {"year": year})

    def get_advanced_season_stats(self, year: int) -> List[Dict[str, Any]]:
        return self.get(
            "/stats/season/advanced",
            {"year": year, "seasonType": "regular"},
        )

    def get_ppa_teams(self, year: int) -> List[Dict[str, Any]]:
        return self.get("/ppa/teams", {"year": year, "seasonType": "regular"})

    def get_rankings(self, year: int, week: int, season_type: str = "regular") -> List[Dict[str, Any]]:
        return self.get(
            "/rankings",
            {"year": year, "week": week, "seasonType": season_type},
        )

    def get_elo(self, year: int) -> List[Dict[str, Any]]:
        return self.get("/ratings/elo", {"year": year})

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "CFBDClient":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()
