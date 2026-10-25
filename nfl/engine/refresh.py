"""Weekly refresh: download the latest nflverse data, rebuild the ratings and write the power rankings.

  python3 engine/refresh.py --season 2026   (add --backfill once before running backtest_v2.py; defaults: data in ./data, overrides in ./overrides.csv, output to ./site_data)

Override file (optional), one row per team where you know better than the injury report:
  team,starter,p_start,note        e.g.   BAL,Tyler Huntley,1.0,Lamar out per Harbaugh
  starter = QB name as in the output ("T.Huntley" or "Tyler Huntley" both work); p_start = chance he starts (default 1.0)
"""
import argparse, datetime, json, os, shutil, subprocess, sys
import numpy as np, pandas as pd
from engine_lib import make_tables, final_ratings, expected_starters
from qb_status import load_injuries, starter_table
from engine_v2 import (prior_features, prior_for, ratings_v2, injury_rows, new_loss_table, qb_mix_deltas, nm)

HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.join(HERE, '..')
REL = 'https://github.com/nflverse/nflverse-data/releases/download'
FILES = {'pbp': ('pbp', 'play_by_play_{y}.parquet', 'pbp_{y}.parquet'), 'injuries': ('injuries', 'injuries_{y}.parquet', 'injuries_{y}.parquet'),
         'snaps': ('snap_counts', 'snap_counts_{y}.parquet', 'snaps_{y}.parquet'), 'roster': ('weekly_rosters', 'roster_weekly_{y}.parquet', 'roster_weekly_{y}.parquet')}


def fetch(D, season, full=False):
    """Download what the run needs. Past-season files are fetched once; current-season files and the player id map every run."""
    os.makedirs(D, exist_ok=True)
    jobs = [('players', 'players', 'players.parquet', 'players.parquet', True)]
    for y in range(2017, season + 1):
        jobs.append(('pbp', 'pbp', f'play_by_play_{y}.parquet', f'pbp_{y}.parquet', y == season))
    for y in (range(2018, season + 1) if full else (season - 1, season)):
        jobs.append(('injuries', 'injuries', f'injuries_{y}.parquet', f'injuries_{y}.parquet', y == season))
        jobs.append(('snaps', 'snap_counts', f'snap_counts_{y}.parquet', f'snaps_{y}.parquet', y == season))
    for y in (range(2019, season + 1) if full else (season,)):
        jobs.append(('roster', 'weekly_rosters', f'roster_weekly_{y}.parquet', f'roster_weekly_{y}.parquet', y == season))
    for k, rel, src, dst, always in jobs:
        path = f'{D}/{dst}'
        if os.path.exists(path) and not always: continue
        tmp = path + '.part'
        r = subprocess.run(['curl', '-sS', '-L', '-f', '-o', tmp, f'{REL}/{rel}/{src}'], capture_output=True, text=True)
        if r.returncode == 0: shutil.move(tmp, path)
        else:
            if os.path.exists(tmp): os.remove(tmp)
            print(f'  could not download {src}: {r.stderr.strip()}', file=sys.stderr)
            if not os.path.exists(path): sys.exit(f'missing required file {dst}')


TEAM_NAMES = {'ARI': 'Arizona Cardinals', 'ATL': 'Atlanta Falcons', 'BAL': 'Baltimore Ravens', 'BUF': 'Buffalo Bills', 'CAR': 'Carolina Panthers',
              'CHI': 'Chicago Bears', 'CIN': 'Cincinnati Bengals', 'CLE': 'Cleveland Browns', 'DAL': 'Dallas Cowboys', 'DEN': 'Denver Broncos',
              'DET': 'Detroit Lions', 'GB': 'Green Bay Packers', 'HOU': 'Houston Texans', 'IND': 'Indianapolis Colts', 'JAX': 'Jacksonville Jaguars',
              'KC': 'Kansas City Chiefs', 'LA': 'Los Angeles Rams', 'LAC': 'Los Angeles Chargers', 'LV': 'Las Vegas Raiders', 'MIA': 'Miami Dolphins',
              'MIN': 'Minnesota Vikings', 'NE': 'New England Patriots', 'NO': 'New Orleans Saints', 'NYG': 'New York Giants', 'NYJ': 'New York Jets',
              'PHI': 'Philadelphia Eagles', 'PIT': 'Pittsburgh Steelers', 'SEA': 'Seattle Seahawks', 'SF': 'San Francisco 49ers', 'TB': 'Tampa Bay Buccaneers',
              'TEN': 'Tennessee Titans', 'WAS': 'Washington Commanders'}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--season', type=int, required=True); ap.add_argument('--through-week', type=int)
    ap.add_argument('--overrides', default=os.path.join(ROOT, 'overrides.csv')); ap.add_argument('--data-dir', default=os.path.join(ROOT, 'data')); ap.add_argument('--out', default=os.path.join(ROOT, 'site_data'))
    ap.add_argument('--spec', default=os.path.join(HERE, 'engine_spec_v2.json')); ap.add_argument('--no-download', action='store_true'); ap.add_argument('--backfill', action='store_true', help='download the full 2017-onward history (needed only for backtest_v2.py), then exit')
    a = ap.parse_args()
    D, s = a.data_dir, a.season
    spec = json.load(open(a.spec)); P = dict(spec['params']); w_ = spec['weights']
    if a.backfill:
        fetch(D, s, full=True); print('history downloaded to', D); return
    if not a.no_download: fetch(D, s)
    T = make_tables(D, range(2017, s + 1)); FIN = final_ratings(T)
    W = a.through_week or int(T.panel[T.panel.season == s].week.max())
    F = prior_features(D, T, FIN, [s])
    prior = prior_for(F, spec['prior_model'], s)
    R = ratings_v2(T, prior, P, s, W).set_index('team')
    teams = list(R.index)

    # who has already played the newest injury report week? their next report is not out yet
    inj_df = pd.read_parquet(f'{D}/injuries_{s}.parquet'); rep_w = min(int(inj_df[inj_df.week <= 18].week.max()), W + 1)
    played_rep = set(T.panel[(T.panel.season == s) & (T.panel.week >= rep_w) & (T.panel.week <= W)].team)
    tab = starter_table(T, load_injuries([pd.read_parquet(f'{D}/injuries_{y}.parquet') for y in (s - 1, s)]), s, rep_w, teams=teams)
    last = expected_starters(T, s, W, games_back=1)
    for t in teams:
        if t in played_rep:
            tab.loc[t, ['likely', 'alt', 'p_likely', 'why']] = [last[t], last[t], 1.0, f'played week {rep_w}; next report not out']
    # overrides
    names = T.names
    byname = {}
    for q, n_ in names.items(): byname.setdefault(n_.lower(), q)
    for q, n_ in names.items(): byname.setdefault(n_.lower().replace('.', ''), q)
    notes = {}
    if a.overrides and os.path.exists(a.overrides):
        for r in pd.read_csv(a.overrides).itertuples():
            key = str(r.starter).lower()
            q = byname.get(key) or byname.get(key.replace('.', ''))
            if q is None:
                cand = sorted({qq for nn, qq in byname.items() if key.split()[-1] in nn})
                q = cand[0] if len(cand) == 1 else None
            if q is None: print(f'  override for {r.team}: could not find QB "{r.starter}"', file=sys.stderr); continue
            p = float(getattr(r, 'p_start', 1.0)) if not pd.isna(getattr(r, 'p_start', np.nan)) else 1.0
            old_alt = tab.loc[r.team, 'likely'] if p < 1 else q
            tab.loc[r.team, ['likely', 'alt', 'p_likely', 'why']] = [q, old_alt if p < 1 else q, p, 'OVERRIDE: ' + str(getattr(r, 'note', ''))]
    de, dq = qb_mix_deltas(T, P, s, rep_w, tab)
    # injuries beyond QB (only for teams whose upcoming game is covered by the newest report)
    NL = new_loss_table(injury_rows(D, [s]))
    nl = pd.Series({t: (0.0 if t in played_rep else NL.get((s, rep_w, nm(t)), 0.0)) for t in teams})
    out = R[['pd', 'o', 'e']].copy()
    out['qb_exp'], out['qb_qual'] = pd.Series(de), pd.Series(dq)
    out['inj_new_loss'] = nl
    out['power'] = (w_['pd'] * out.pd + w_['o'] * out.o - w_['nd'] * out.e + w_['qexp'] * out.qb_exp + w_['qqual'] * out.qb_qual
                    - spec['injury_points_per_starter'] * out.inj_new_loss)
    out['power'] -= out.power.mean()
    out['starter'] = tab.likely.map(lambda q: names.get(q, q)); out['alt_qb'] = tab.alt.map(lambda q: names.get(q, q))
    out['p_starter'] = tab.p_likely; out['qb_note'] = tab.why
    p_ = T.panel[(T.panel.season == s) & (T.panel.week <= W)]
    out['record'] = p_.groupby('team').apply(lambda g: f'{int((g.margin > 0).sum())}-{int((g.margin < 0).sum())}' + (f'-{int((g.margin == 0).sum())}' if (g.margin == 0).any() else ''), include_groups=False)
    out['pt_diff'] = p_.groupby('team').margin.sum()
    comp = pd.DataFrame({'results_margin': w_['pd'] * out.pd, 'offense': w_['o'] * out.o, 'defense': -w_['nd'] * out.e,
                         'quarterback': w_['qexp'] * out.qb_exp + w_['qqual'] * out.qb_qual, 'injuries': -spec['injury_points_per_starter'] * out.inj_new_loss})
    comp = comp - comp.mean()
    if w_['nd'] == 0: comp = comp.drop(columns='defense')   # defense is carried inside results_margin (points allowed)
    out = out.sort_values('power', ascending=False); out.insert(0, 'rank', np.arange(1, len(out) + 1)); comp = comp.reindex(out.index)
    os.makedirs(a.out, exist_ok=True)
    f = f'{a.out}/power_{s}_wk{W}.csv'; out.round(3).to_csv(f)
    teams_json = []
    for t, r in out.iterrows():
        teams_json.append(dict(rank=int(r['rank']), team=t, name=TEAM_NAMES.get(t, t), power=round(float(r.power), 2), record=r.record, point_diff=int(r.pt_diff),
                               components={k: round(float(v), 2) for k, v in comp.loc[t].items()},
                               ratings=dict(margin_rating=round(float(r.pd), 2), offense_epa_per_play=round(float(r.o), 3), defense_epa_allowed_per_play=round(float(r.e), 3)),
                               starter=r.starter, alt_qb=r.alt_qb, starter_prob=round(float(r.p_starter), 2), qb_note=r.qb_note,
                               injury_starters_newly_lost=round(float(r.inj_new_loss), 2)))
    meta = dict(season=s, through_week=W, injury_report_week=rep_w, generated_utc=datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%MZ'),
                engine='nfl power engine v2', units='points vs an average team on a neutral field', home_field=round(spec['home_field'], 2),
                win_prob_sigma=spec['win_prob_sigma'], overrides_applied=int(out.qb_note.str.startswith('OVERRIDE').sum()))
    os.makedirs(a.out, exist_ok=True)
    json.dump(dict(meta=meta, teams=teams_json), open(f'{a.out}/nfl_power.json', 'w'), indent=1)
    print(f'ratings through week {W}; injury report week {rep_w}; wrote {f} and {a.out}/nfl_power.json')
    print(out[['rank', 'power', 'record', 'pt_diff', 'starter', 'p_starter', 'inj_new_loss']].round(2).to_string())
    flag = out[(out.p_starter < 1) | out.qb_note.str.contains('OVERRIDE|Out|Doubtful|Questionable|cleared')]
    if len(flag): print('\nQB situations to confirm against the news:'); print(flag[['starter', 'alt_qb', 'p_starter', 'qb_note']].to_string())


if __name__ == '__main__':
    main()
