"""Application configuration."""

import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
CACHE_DIR = DATA_DIR / "cache"
OUTPUT_DIR = PROJECT_ROOT / "output"
TEAMS_DIR = DATA_DIR / "teams"

load_dotenv(PROJECT_ROOT / ".env")

CFBD_API_KEY = os.getenv("CFBD_API_KEY", "")

for path in (DATA_DIR, CACHE_DIR, OUTPUT_DIR, TEAMS_DIR):
    path.mkdir(parents=True, exist_ok=True)
