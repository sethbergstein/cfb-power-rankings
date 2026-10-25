# Adding the NFL tabs to the site

Goal: two new tabs next to the existing college football ones.
1. **NFL Power Rankings**: 32 teams ranked by power score.
2. **NFL Matchup Predictor**: pick two teams (and home/neutral), get a predicted margin and win probability.

The engine is finished and runs separately (Python). The site only needs to read `site_data/nfl_power.json`. Do not change
the engine math from the site side. Do not add Vegas lines or win totals as an input anywhere: the whole point is that these
rankings are independent.

## Paste-ready prompt for the Cursor agent

> Read `CURSOR_INTEGRATION.md` and `README.md` in the `nfl_power_engine` folder. First look at how the existing site is built
> (Power, Poll and Matchup tabs for college football): stack, routing, data loading, styling, mobile layout, how team pages and
> the power components are explained. Then add two tabs, NFL Power and NFL Matchup, that follow the same conventions and look.
> They read `site_data/nfl_power.json` (copy it into wherever the site keeps its data, or fetch it the same way the college
> data is loaded). Power tab: ranked list with power score, record, point differential, and the component breakdown in plain
> football terms; show a small "as of week N" label from `meta`, and flag teams whose quarterback situation is uncertain
> (`starter_prob` below 1). Matchup tab: two team pickers and a home / neutral toggle; show predicted margin, favorite, win
> probability, and "why" using the component differences. Port the matchup math exactly as written in this file. Do not change
> the engine, do not add betting lines. Tell me what you changed and what you need from me (stack questions, design choices).

## Data contract: `site_data/nfl_power.json`

    meta:  season, through_week, injury_report_week, generated_utc, home_field (1.45), win_prob_sigma (13.5), units
    teams: [ one per team, sorted by rank ]
      rank, team (abbreviation), name, power (points vs average, neutral field), record, point_diff,
      components: results_margin, offense, quarterback, injuries   (points, league-centered, sum to power)
      ratings: margin_rating (points), offense_epa_per_play, defense_epa_allowed_per_play (lower is better)
      starter, alt_qb, starter_prob (1.0 = settled, below 1 = uncertain), qb_note
      injury_starters_newly_lost (count of starter-equivalents newly out, before centering)

Component meanings, in plain terms for the site:
- **results_margin**: how the team has actually scored and allowed points, adjusted for opponent strength, anchored to a
  preseason expectation that fades over the first several weeks. Defense is inside this.
- **offense**: how efficient the offense is on a per-play basis, opponent-adjusted.
- **quarterback**: who is expected to play QB this week compared with the QB the team's results so far were built on.
- **injuries**: starters newly ruled out or questionable this week, compared with the league average. Because it is
  league-centered, a team with a normal number of injuries shows about 0; "injury_starters_newly_lost" has the raw count.

Team abbreviations follow nflverse (LA = Rams, LV = Raiders, etc).

## Matchup predictor (port exactly)

    margin_home = (neutral ? 0 : 1.45) + power_home - power_away      // positive = home favored by that many points
    p_home      = normalCDF(margin_home / 13.5)
    why         = component_home - component_away  for each component  // points, explains the gap
    favorite    = margin_home >= 0 ? home : away ; spread shown = abs(margin_home), one decimal

JavaScript:

    const erf = x => { const s = Math.sign(x); x = Math.abs(x); const t = 1 / (1 + 0.3275911 * x);
      const y = 1 - (((((1.061405429 * t - 1.453152027) * t) + 1.421413741) * t - 0.284496736) * t + 0.254829592) * t * Math.exp(-x * x);
      return s * y; };
    const normalCDF = z => 0.5 * (1 + erf(z / Math.SQRT2));
    const predict = (P, home, away, neutral) => {
      const T = Object.fromEntries(P.teams.map(t => [t.team, t])); const h = T[home], a = T[away];
      const margin = (neutral ? 0 : P.meta.home_field) + h.power - a.power;
      return { margin, pHome: normalCDF(margin / P.meta.win_prob_sigma),
               why: Object.fromEntries(Object.keys(h.components).map(k => [k, h.components[k] - a.components[k]])) }; };

`engine/matchup.py` has the same math in Python, and `tests/smoke_test.py` checks the JSON. The predicted margins are expected
margins, not guarantees: a typical miss is about 13 points, so a 3-point favorite wins about 59% of the time.

## What the site should say honestly

- Label the date: "through week N". Early in the season (first 4 to 5 weeks) rankings lean on last year plus roster changes, and
  the engine is least accurate then. A one-line note is enough.
- Show a QB flag when `starter_prob < 1`, with `starter` and `alt_qb`. These are the cases where a lineup change moves a team
  several points. The weekly check against the news (below) settles most of them.
- Record and point differential are display-only. They do not feed the score.
- Do not describe the win probability as a betting line.

## Weekly workflow

1. Tuesday or Wednesday (after Monday night): `python3 engine/refresh.py --season 2026`. Read the "QB situations to confirm"
   list at the bottom of the output. Add rows to `overrides.csv` for anything the news contradicts, rerun.
2. Friday or Saturday (after the final injury report): run again. Starter odds and the injury number update.
3. Copy `site_data/nfl_power.json` to wherever the site reads it and deploy. If the site is not Python, a scheduled job (for
   example GitHub Actions on a cron) can run step 1 and commit the JSON; the engine needs only Python and the packages in
   `requirements.txt`, and downloads its own data.
4. When a QB returns or is ruled out for the season, remove or add the override row so it does not go stale.

## Questions to settle with Seth

- What is the site stack, and where do data files live? (Decides how the JSON gets in.)
- Should the NFL tabs share the college "Bergstein Power Index" branding or have their own name?
- Should past weeks be kept (history charts), or only the latest week? The CSV/JSON names include the week, so history is easy to keep.
