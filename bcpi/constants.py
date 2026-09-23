"""Shared constants for BCPI."""

TARGET_SEASON = 2026
BACKTEST_START_SEASON = 2018
BACKTEST_END_SEASON = 2025

# Neutral-field power rating scale (roughly Elo-like points).
RATING_MEAN = 1500.0
RATING_SPREAD = 400.0  # ~400 pts ≈ 14 expected margin points

# Home field advantage in expected margin points (used for game expectations only).
HOME_FIELD_ADVANTAGE = 2.75

# FCS pseudo-opponent handling. 2018-2025 results imply the typical FCS opponent
# of an FBS team plays at ~950-1110 on this scale, far below the weakest FBS teams.
FCS_OPPONENT_KEY = "FCS_AGG"
FCS_RATING = 1050.0

# AP poll inputs: unranked teams sit one spot below the last ranked team.
CONSENSUS_UNRANKED_RANK = 26

# Recency: weight = exp(-λ * weeks ago); λ = 0.13 is a ~5-week half-life.
RECENCY_DECAY_LAMBDA = 0.13

# Rating solver: iterate until no rating would move more than the tolerance
# (rating points) on another pass, up to the iteration limit.
SOLVER_MAX_ITERATIONS = 100
SOLVER_TOLERANCE = 0.01

# Margins are compressed as C * tanh(margin / C) on both the actual and the
# expected side, so blowouts count less without a hard cap.
MARGIN_COMPRESSION = 30.0

# Preseason prior blend weights (fade in-season).
PRIOR_WEIGHTS = {
    "previous_season": 0.45,
    "talent": 0.35,
    "returning": 0.0,
    "consensus": 0.20,
}

# Power composite weights (predictive / neutral-field). "quality" and "market"
# are in-season signals that share their weight with the preseason prior until
# a team has played ``power_sample_games`` games.
POWER_WEIGHTS = {
    "solver": 0.65,
    "quality": 0.35,
    "market": 0.0,
}

# Quality sub-weights (per-game advanced stats). Havoc is not in the per-game feed.
QUALITY_WEIGHTS = {
    "epa_diff": 0.45,
    "success_diff": 0.30,
    "explosiveness_diff": 0.0,
    "passing_diff": 0.25,
}

# Efficiency differential per point of opponent strength (opponent's expected
# margin vs an average FBS team); through-origin fit on 2018-2025 FBS games.
QUALITY_OPPONENT_SLOPES = {
    "epa_diff": 0.01292,
    "success_diff": 0.00584,
    "explosiveness_diff": 0.0,
    "passing_diff": 0.018,
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
