"""Shared constants for BCPI."""

TARGET_SEASON = 2026
BACKTEST_START_SEASON = 2018
BACKTEST_END_SEASON = 2025

# Neutral-field power rating scale (roughly Elo-like points).
RATING_MEAN = 1500.0
RATING_SPREAD = 400.0  # ~400 pts ≈ 14 expected margin points

# Home field advantage in expected margin points (used for game expectations only).
HOME_FIELD_ADVANTAGE = 2.75

# FCS pseudo-opponent handling.
FCS_OPPONENT_KEY = "FCS_AGG"
FCS_MARGIN_CAP = 21.0
FCS_INITIAL_RATING_OFFSET = -120.0  # below mean FBS (~100th team)

# Recency: half-life ≈ 2 weeks (λ ≈ 0.35).
RECENCY_DECAY_LAMBDA = 0.35

# Iterative opponent-adjustment passes.
SOLVER_ITERATIONS = 8

# Preseason prior blend weights (fade in-season).
PRIOR_WEIGHTS = {
    "previous_season": 0.45,
    "talent": 0.35,
    "returning": 0.15,
    "consensus": 0.05,
}

# Power composite weights (predictive / neutral-field).
POWER_WEIGHTS = {
    "quality": 0.65,
    "game_value": 0.20,
    "market": 0.10,
    "talent_prior": 0.05,
}

# Quality sub-weights (when EPA available).
QUALITY_WEIGHTS = {
    "epa_diff": 0.45,
    "success_diff": 0.25,
    "explosiveness_diff": 0.15,
    "passing_diff": 0.10,
    "havoc_diff": 0.05,
}

# 2026 conference overrides for teams not yet updated in CFBD snapshots.
CONFERENCE_OVERRIDES_2026 = {
    "Boise State": "Pac-12",
    "Colorado State": "Pac-12",
    "Fresno State": "Pac-12",
    "San Diego State": "Pac-12",
    "Texas State": "Pac-12",
    "Utah State": "Pac-12",
    "North Dakota State": "Mountain West",
    "Northern Illinois": "Mountain West",
    "UTEP": "Mountain West",
    "Louisiana Tech": "Sun Belt",
    "Sacramento State": "Mid-American",
}

# New FBS programs for 2026 (if missing from API).
FBS_ADDITIONS_2026 = [
    {
        "school": "North Dakota State",
        "conference": "Mountain West",
        "abbreviation": "NDSU",
    },
    {
        "school": "Sacramento State",
        "conference": "Mid-American",
        "abbreviation": "SAC",
    },
]

CFBD_BASE_URL = "https://api.collegefootballdata.com"
