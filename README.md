# Bergstein CFB Power Index (BCPI)

Two rankings for FBS college football, built from the same games:

- **Power** estimates who would win a game on a neutral field.
- **Poll** estimates who has earned the highest ranking so far.

They share a solver (opponent-adjusted, recency-weighted ratings) and then answer different questions.

## Methodology

Ratings live on a 1500-centered scale. Expected margin is the rating gap divided by a points-per-rating scale, plus home field. Blowouts are compressed with `C · tanh(margin / C)` so a 60-point win is not twice as informative as a 30-point win. The solver finds the rating vector that is a fixed point of that update (Newton's method). Isolated conference islands (the 2020 Pac-12) keep the level their prior assigned; only relative ratings inside the island are determined.

**Power.** Score = solver weight × z(solver) + quality weight × [c × quality + (1 − c) × prior], with those weights retuned on 2018–2025. Quality is opponent-adjusted EPA, success rate, explosiveness and passing, blended with scoring form. Credibility `c` reaches 1 after six FBS games. A site-adjusted head-to-head step closes small gaps when the winner still wins after home field is removed. FCS opponents are one background team rated 1050. Walk-forward, after refitting the published scale and home field: about 12.6 points of error (12.9 in weeks 2–4), 73% straight-up.

**Poll.** Every game is scored against a benchmark team, the average of the top 25 by solver rating, playing the same opponent at the same site. Strength of record is wins minus the wins that benchmark would expect; performance is the compressed margin beyond the benchmark's expected margin. Resume = z(0.8 × z(SOR) + 0.2 × z(performance)). The published poll is `K / (K + games)` of the preseason (K = 2; FCS games count half) plus the rest resume, then a wider head-to-head pass. Preseason is last season's final poll, roster talent, and the AP preseason (unranked = 26th), plus a bump for the defending champion. After the title game, the preseason weight is 0. A capped playoff-round bonus in wins units is added to SOR, and the national champion is forced to #1 in the final poll.

**Matchups.** The site converts a power-rating gap to a spread with a separately fitted scale and league-wide home field, then a logistic win probability. Team-level home-field deviations are shrunk toward that league average.

**Checks.** Every snapshot runs seven ranking invariants (warnings) and five health checks (errors that fail the publish). See `bcpi/checks.py`.

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
python run_bcpi.py poll --season 2026
python run_bcpi.py check --season 2026
```

Output is written to `output/bcpi_power_2026_weekXX.csv` and `output/bcpi_poll_2026_weekXX.csv`. `check` prints health and invariant annotations and exits 1 on a health error.

### 4. Backtest

```bash
python run_bcpi.py backtest --start 2018 --end 2025
```

Walk-forward evaluation: train through week *t*, predict week *t+1* FBS games. Reports both the published matchup-page error and a fitted error that ignores the published scale.

### 5. Tune weights

```bash
python run_bcpi.py tune --start 2018 --end 2025
python run_bcpi.py tune --holdout 2024 --holdout 2025 --no-save
```

Coordinate search from the active params, then refits the matchup scale, home field, and win-probability curve. Saves `config/tuned_params.json` unless `--no-save`.


## GitHub Actions (weekly cron)

1. Push this repo to GitHub.
2. In the repo: **Settings → Secrets and variables → Actions → New repository secret**
3. Name: `CFBD_API_KEY`, value: your CollegeFootballData API key
4. The workflow runs **Monday and Tuesday at noon UTC** and commits updated `output/` and `docs/` files.

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
