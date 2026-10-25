# NFL power rating engine (v2)

Power score = how many points better a team is than an average team on a neutral field, right now. No betting-market
inputs anywhere. Vegas appears only in the backtest, as the yardstick.

## Quick start

    pip install -r requirements.txt
    python3 engine/refresh.py --season 2026     # downloads data (first run ~190 MB), writes site_data/
    python3 tests/smoke_test.py                 # sanity checks on the output
    python3 engine/matchup.py KC BUF            # matchup predictor from the command line

Outputs land in `site_data/`: `nfl_power.json` (what the site reads) and `power_<season>_wk<N>.csv` (same data, flat).
See `CURSOR_INTEGRATION.md` for the data format and the notes for wiring this into the site.

## Formula

    power = 0.78 x margin rating
          + 19.5 x offensive EPA/play rating
          + 5.3  x QB experience delta
          + 15.5 x QB quality delta
          - 0.89 x starters newly lost to injury
    (centered so the league averages 0; the defensive EPA rating gets weight 0, it added nothing beyond margin)
    predicted home margin = 1.45 + power(home) - power(away)
    home win probability  = normal CDF(predicted margin / 13.5)

- **Margin rating, offense rating**: opponent-adjusted (ridge regression) over all plays and games of the season, every game
  weighted equally. Garbage-time filtering and recency weighting both tested worse, so neither is used. Defense shows up
  through points allowed inside the margin rating.
- **Preseason prior**: ratings are shrunk toward a preseason expectation, which fades as games accumulate. The expectation is a
  ridge regression of a team's final rating on: last two seasons' ratings, new head coach, share of last year's offensive and
  defensive snaps retained on the week 1 roster, share arriving from other teams. (Draft capital added nothing and was dropped.)
- **QB delta**: starter minus the QB already built into the team's rating. Experience = career dropbacks n/(n+1500); quality =
  career EPA/dropback shrunk with 1200 dropbacks.
- **Who starts**: from the official injury report plus recent usage (`engine/qb_status.py`). Ruled out/doubtful: never started in
  2019-2025. Questionable: started 86% / 56% / 31% with full / limited / no practice. Established QB cleared after missing time:
  85%. The score uses the probability-weighted mix of the likely starter and the alternate.
- **Injury number**: each non-QB player on the report counts as (usual snap share over his last 8 games) x (1 if Out/Doubtful,
  0.38 if Questionable). Players already ruled out the week before are excluded, because that is already in recent results.

## Backtest (2019-2025, 1,871 games, leave-one-season-out, r with actual margin)

| | wk 1-2 | wk 1-5 | wk 6+ | all | avg miss (pts, rmse) |
|---|---|---|---|---|---|
| old prior, QB = last game's starter | .379 | .334 | .420 | .397 | 13.13 |
| old prior, QB from report | .359 | .335 | .426 | .402 | 13.10 |
| new prior, QB from report | .401 | .338 | .427 | .404 | 13.09 |
| **final engine (+ injury number)** | **.425** | **.341** | **.436** | **.411** | **13.04** |
| same, actual starter known (ceiling) | .383 | .340 | .436 | .410 | 13.04 |
| Vegas closing spread (benchmark only) | .434 | .417 | .474 | .458 | 12.72 |

- Final engine vs the last-game-starter version: +.014 (interval +.002 to +.026). The prior (+.002) and the injury number (+.007)
  are each inside the noise alone; together they are a small, consistent gain.
- Win probabilities: Brier score .222 (coin flip .250, Vegas .210); predicted vs actual win rates by bucket agree to within a few points, with some noise.
- Against the spread the engine wins 50.2%. It is a team-strength measure, not a betting tool.
- Record adds nothing to the score (tested, -.001).

Reproduce: `python3 engine/refresh.py --season 2026 --backfill` (one time, downloads the full history), then
`python3 engine/backtest_v2.py` (under a minute). It writes to `backtest_output/` and never overwrites the shipped spec.

## Weekly use

    python3 engine/refresh.py --season 2026

Rebuilds the ratings through the last completed week. The newest injury report applies to teams that have not yet played that
week; teams that have use their last game's QB and no injury adjustment until their next report is out.

`overrides.csv` (header: `team,starter,p_start,note`) is for news the report misses: season-ending injuries, benchings, a QB
returning. Example row: `BAL,Tyler Huntley,1.0,Lamar out per coach`. The run prints every QB situation that is not a plain
"last game's starter" so you can check it against the news. Overrides stay in place until you delete the row.

## Files

- `engine/engine_lib.py`      opponent-adjusted ratings, QB term
- `engine/qb_status.py`       starter probabilities from the injury report
- `engine/engine_v2.py`       preseason prior, ratings with prior, injury number
- `engine/refresh.py`         weekly run (downloads data, writes site_data/)
- `engine/matchup.py`         matchup predictor (importable and command line)
- `engine/backtest_v2.py`     reproduces the table above
- `engine/engine_spec.json`   original engine settings (used by the backtest's comparison rows)
- `engine/engine_spec_v2.json` weights, parameters, fitted prior model, backtest summary
- `site_data/`                latest output; `backtest_output/` backtest results; `data/` downloads (not committed)

## Known weak spots

- Weeks 1-5 are the weakest part (.341 vs Vegas .417). Public football data says little about the coming season: a team's
  preseason rating explains about 20% of its final rating, with or without the extras.
- Rookie and first-year QBs have no history, so the QB term treats them as inexperienced and average.
- The non-QB injury weight (0.89 points per starter) has a wide interval and does not separate positions.
- Only the newest report is used. Gameday inactives, practice-squad call-ups and midweek news are not.
- Settings were chosen on small grids with leave-one-season-out validation. Starter-odds rates were computed on all seasons.
- Built and tested for in-season use. Preseason (before any game is played) and playoffs are not covered. Neutral-site and
  international games are treated as a normal home game unless you pass `neutral=True` to the matchup predictor.
