# Bergstein CFB Power Index (BCPI)

Data-driven, neutral-field **power rankings** for FBS college football. BCPI estimates who the best teams are right now — not a poll-style resume ranking.

## What BCPI measures

- **Primary output:** Power ranking (predictive, neutral-field strength)
- **Inputs:** Game margins (opponent-adjusted, recency-weighted), advanced efficiency stats (EPA/success/explosiveness via CFBD), closing spreads, and 247 talent composite priors
- **FCS opponents:** Handled as a single background opponent class (not ranked in output)
- **Target season:** 2026 (trained/backtested on 2018–2025)

## Quick start

### 1. Python version

Your Mac has **Python 3.9.6**, which is enough to run BCPI locally.

GitHub Actions uses **Python 3.11** for weekly automated runs — you do **not** need to upgrade your laptop for the cron job to work.

Optional: install a newer Python later with [python.org](https://www.python.org/downloads/) or `brew install python@3.11` if you want faster local development.

### 2. Setup

```bash
cd "College Football Rankings"
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Edit .env and set CFBD_API_KEY
```

### 3. Generate rankings

```bash
python run_bcpi.py rank --season 2026
```

Output is written to `output/bcpi_power_2026_preseason.csv` (preseason) or `output/bcpi_power_2026_weekXX.csv` during the season.

### 4. Backtest

```bash
python run_bcpi.py backtest --start 2018 --end 2025
```

Walk-forward evaluation: train through week *t*, predict week *t+1* FBS games.

### 5. Tune weights

```bash
python run_bcpi.py tune --start 2018 --end 2025
```

Searches for better weights via random search + local refinement. Saves results to `config/tuned_params.json` (used automatically by `rank` unless `--use-defaults`).


## GitHub Actions (weekly cron)

1. Push this repo to GitHub.
2. In the repo: **Settings → Secrets and variables → Actions → New repository secret**
3. Name: `CFBD_API_KEY`, value: your CollegeFootballData API key
4. The workflow runs every **Tuesday 06:00 UTC** and commits updated `output/` files.

You can also trigger manually from the **Actions** tab (`workflow_dispatch`).

## Web UI (mobile-friendly)

Local dev:

```bash
python run_bcpi.py serve
# → http://127.0.0.1:8765
```

On phones/tablets the layout switches to a bottom tab bar (Power · Poll · Matchup), touch-sized controls, and horizontally scrollable ranking tables.

### Free hosting (GitHub Pages — recommended for mobile)

Rankings publish automatically **Monday and Tuesday at noon UTC** via `.github/workflows/static-site.yml` (Tuesday catches rare Monday games). The workflow runs `export-site`, commits `docs/`, and you serve from GitHub Pages — no Netlify, no Render, no API key on your phone.

**One-time setup:**
1. Push repo to GitHub with `CFBD_API_KEY` in **Settings → Secrets → Actions**
2. **Settings → Pages → Build and deployment → Deploy from branch → `main` → `/docs`**
3. Site URL: `https://<user>.github.io/<repo>/`

Manual publish locally:

```bash
python run_bcpi.py export-site --refresh   # needs CFBD_API_KEY in .env
```

The static site reads pre-built JSON in `docs/data/` — rankings, matchups, logos all work offline after load. **Recalculate** is hidden; data updates when the Action runs.

### Free hosting (Render — live API)

For on-demand Recalculate, use `render.yaml` (see above). Set `CFBD_API_KEY` once in Render's dashboard.

## Project layout

```
bcpi/           Core library (API client, model, pipeline)
data/teams/     Season FBS team snapshots
data/cache/     Cached CFBD API responses (local only)
output/         Published ranking CSV/JSON
run_bcpi.py     CLI entrypoint
web/            Press Box Ledger UI (Flask + static assets)
docs/           GitHub Pages static site (auto-generated)
wsgi.py         Production entrypoint for gunicorn
render.yaml     Optional Render deploy (live API)
```

## Data source

[CollegeFootballData.com](https://collegefootballdata.com) — games, lines, advanced stats, talent composite, team metadata.

## Security

Never commit `.env` or API keys. If a key is exposed, regenerate it at collegefootballdata.com.

## License

MIT (add your preference if different)
