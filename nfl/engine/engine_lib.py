"""NFL power rating engine (library).

Data: nflverse play-by-play, one file per season named pbp_<year>.parquet in `data_dir`
  https://github.com/nflverse/nflverse-data/releases/download/pbp/play_by_play_<year>.parquet

Rating for team T before week w uses only games from weeks < w of the same season, plus last season's
final ratings as a prior. Three components, each opponent-adjusted by ridge regression:
  pd   margin rating (points vs an average team), fit toward beta_m * last season's value
  o    offensive EPA/play rating (all plays), fit toward beta_o * last season's value
  e    defensive EPA/play allowed rating, fit toward beta_d * last season's value (lower = better)
Plus a QB term: starter minus the QB already baked into the team's rating, on two scales:
  experience  n/(n+ke) where n = career dropbacks since 2018
  quality     shrunk career EPA/dropback vs average, shrink kq dropbacks
Power score (points vs league average, neutral field):
  w_pd*pd + w_o*o + w_nd*(-e) + w_qexp*qb_exp_delta + w_qqual*qb_qual_delta
Predicted home margin = home field + power(home) - power(away).
"""
from collections import namedtuple

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

Tables = namedtuple('Tables', 'panel games qg first tmap names')

PLAY_COLS = ['game_id', 'season', 'week', 'season_type', 'home_team', 'away_team', 'posteam', 'play_type', 'pass',
             'qb_scramble', 'epa', 'play_id', 'passer_player_id', 'rusher_player_id', 'passer_player_name',
             'rusher_player_name', 'two_point_attempt', 'home_score', 'away_score', 'result', 'spread_line']

DEFAULT_PARAMS = dict(am=16.0, bm=0.4,      # margin rating: prior strength (game-equivalents), carryover
                      ao=8.0, bo=0.5,       # offense EPA rating
                      ad=8.0, bd=0.5,       # defense EPA rating
                      ke=1500, kq=1200, K=4)  # QB experience scale, QB quality shrink, baked-in blend (games)


# ------------------------------------------------------------------------------------------ data
def make_tables(data_dir, years):
    frames = []
    for y in years:
        f = f'{data_dir}/pbp_{y}.parquet'
        names = set(pq.read_schema(f).names)
        d = pd.read_parquet(f, columns=[c for c in PLAY_COLS if c in names])
        frames.append(d[d.season_type == 'REG'])
    pbp = pd.concat(frames, ignore_index=True)
    games = (pbp.drop_duplicates('game_id')
             [['game_id', 'season', 'week', 'home_team', 'away_team', 'home_score', 'away_score', 'result', 'spread_line']]
             .reset_index(drop=True))
    b = pbp[pbp.play_type.isin(['pass', 'run']) & pbp.epa.notna() & pbp.posteam.notna() &
            (pbp.two_point_attempt.fillna(0) != 1)]
    off = (b.groupby(['game_id', 'posteam']).epa.agg(['sum', 'size']).reset_index()
           .rename(columns={'posteam': 'team', 'sum': 'epa', 'size': 'plays'}).merge(games, on='game_id'))
    home = off.team == off.home_team
    off['is_home'] = home.astype(int)
    off['opp'] = np.where(home, off.away_team, off.home_team)
    off['pf'] = np.where(home, off.home_score, off.away_score)
    off['pa'] = np.where(home, off.away_score, off.home_score)
    off['margin'] = off.pf - off.pa
    opp = off[['game_id', 'team', 'epa', 'plays']].rename(columns={'team': 'opp', 'epa': 'd_epa', 'plays': 'd_plays'})
    panel = off.merge(opp, on=['game_id', 'opp']).sort_values(['season', 'team', 'week']).reset_index(drop=True)
    tmap = {s: {t: i for i, t in enumerate(sorted(g.team.unique()))} for s, g in panel.groupby('season')}
    panel['t_i'] = [tmap[s][t] for s, t in zip(panel.season, panel.team)]
    panel['o_i'] = [tmap[s][t] for s, t in zip(panel.season, panel.opp)]
    panel['home_sign'] = np.where(panel.is_home == 1, 1.0, -1.0)

    db = b[(b['pass'] == 1) | (b.qb_scramble == 1)].copy()
    isp = db['pass'] == 1
    db['qb'] = np.where(isp, db.passer_player_id, db.rusher_player_id)
    db['qbname'] = np.where(isp, db.passer_player_name, db.rusher_player_name)
    db = db[db.qb.notna()]
    qg = (db.groupby(['season', 'week', 'game_id', 'posteam', 'qb']).agg(n=('epa', 'size'), epa=('epa', 'sum'))
          .reset_index().rename(columns={'posteam': 'team'}))
    first = (db.sort_values('play_id').groupby(['game_id', 'posteam']).head(1)[['game_id', 'posteam', 'qb', 'qbname']]
             .rename(columns={'posteam': 'team', 'qb': 'starter', 'qbname': 'starter_name'})
             .merge(games[['game_id', 'season', 'week']], on='game_id'))
    names = db.drop_duplicates('qb').set_index('qb').qbname
    return Tables(panel, games, qg, first, tmap, names)


# ------------------------------------------------------------------------------- team ratings
def _solve(X, y, w, alpha, m):
    w = w / w.mean()
    XtW = X.T * w
    return np.linalg.solve(XtW @ X + np.diag(alpha), XtW @ y + alpha * m)


def _fit_margin(sub, n, am, bm, mpd):
    k = len(sub)
    X = np.zeros((k, n + 2))
    idx = np.arange(k)
    X[idx, sub.t_i.values] += 1
    X[idx, sub.o_i.values] -= 1
    X[:, n] = 1
    X[:, n + 1] = sub.home_sign.values
    alpha = np.r_[np.full(n, am), 0.0, 0.0]
    m = np.r_[bm * mpd, 0.0, 0.0]
    return _solve(X, sub.margin.values.astype(float), np.ones(k), alpha, m)[:n]


def _fit_epa(sub, n, ao, bo, ad, bd, mo, me):
    k = len(sub)
    X = np.zeros((k, 2 * n + 1))
    idx = np.arange(k)
    X[idx, sub.t_i.values] = 1
    X[idx, n + sub.o_i.values] = 1
    X[:, -1] = 1
    alpha = np.r_[np.full(n, ao), np.full(n, ad), 0.0]
    m = np.r_[bo * mo, bd * me, 0.0]
    b = _solve(X, (sub.epa / sub.plays).values, sub.plays.values.astype(float), alpha, m)
    return b[:n], b[n:2 * n]


def final_ratings(T):
    """End-of-season ratings with a light penalty (alpha 4), used as next season's prior."""
    out = {}
    for s, g in T.panel.groupby('season'):
        n = len(T.tmap[s])
        z = np.zeros(n)
        r = _fit_margin(g, n, 4.0, 0.0, z)
        o, e = _fit_epa(g, n, 4.0, 0.0, 4.0, 0.0, z, z)
        out[s] = pd.DataFrame({'pd': r, 'o': o, 'e': e}, index=list(T.tmap[s].keys()))
    return out


def ratings_at(T, FIN, p, s, W):
    """Ratings for every team using games through week W of season s (W=0: prior only)."""
    teams = list(T.tmap[s].keys())
    n = len(teams)
    pr = FIN[s - 1].rename(index={'OAK': 'LV'}).reindex(teams)
    mpd, mo, me = pr.pd.values, pr.o.values, pr.e.values
    sub = T.panel[(T.panel.season == s) & (T.panel.week <= W)]
    if len(sub) == 0:
        r, o, e = p['bm'] * mpd, p['bo'] * mo, p['bd'] * me
    else:
        r = _fit_margin(sub, n, p['am'], p['bm'], mpd)
        o, e = _fit_epa(sub, n, p['ao'], p['bo'], p['ad'], p['bd'], mo, me)
    return pd.DataFrame({'season': s, 'W': W, 'team': teams, 'pd': r, 'o': o, 'e': e})


def build_ratings(T, FIN, p, seasons):
    out = []
    for s in seasons:
        maxw = int(T.panel[T.panel.season == s].week.max())
        for W in range(0, maxw):
            out.append(ratings_at(T, FIN, p, s, W))
    return pd.concat(out, ignore_index=True)


def rating_diffs(R, games):
    """Home minus away for each game, using ratings through the previous week."""
    Ri = R.set_index(['season', 'W', 'team'])
    H = Ri.reindex(pd.MultiIndex.from_arrays([games.season, games.week - 1, games.home_team]))
    A = Ri.reindex(pd.MultiIndex.from_arrays([games.season, games.week - 1, games.away_team]))
    d = H.values - A.values
    return pd.DataFrame({'d_pd': d[:, 0], 'd_o': d[:, 1], 'd_nd': -d[:, 2]}, index=games.index)


# --------------------------------------------------------------------------------------- QB term
def _qb_state(T, s, W, p):
    qg = T.qg
    m = (qg.season < s) | ((qg.season == s) & (qg.week <= W))
    t = qg[m].groupby('qb')[['n', 'epa']].sum()
    mu = t.epa.sum() / t.n.sum()
    return t.n / (t.n + p['ke']), (t.epa / t.n - mu) * t.n / (t.n + p['kq'])


def _baked(T, s, W, r, K):
    """Dropback-weighted QB rating already inside the team's rating: this season to date blended with last season."""
    qg = T.qg
    cur = qg[(qg.season == s) & (qg.week <= W)]
    ac = (cur.n * cur.qb.map(r).fillna(0.0)).groupby(cur.team).sum() / cur.n.groupby(cur.team).sum()
    nc = cur.groupby('team').game_id.nunique()
    prv = qg[qg.season == s - 1]
    ap = (prv.n * prv.qb.map(r).fillna(0.0)).groupby(prv.team).sum() / prv.n.groupby(prv.team).sum()
    if s == 2020:
        ap = ap.rename(index={'OAK': 'LV'})
    tab = pd.DataFrame({'ac': ac, 'nc': nc, 'ap': ap}).reindex(list(T.tmap[s].keys())).fillna(0.0)
    w = tab.nc / (tab.nc + K)
    return w * tab.ac + (1 - w) * tab.ap


def qb_team_delta(T, s, W, p, starters):
    """starters: {team: qb_id}. Returns ({team: experience delta}, {team: quality delta})."""
    r_exp, r_qual = _qb_state(T, s, W, p)
    be, bq = _baked(T, s, W, r_exp, p['K']), _baked(T, s, W, r_qual, p['K'])
    de = {t: r_exp.get(q, 0.0) - be.get(t, 0.0) for t, q in starters.items()}
    dq = {t: r_qual.get(q, 0.0) - bq.get(t, 0.0) for t, q in starters.items()}
    return de, dq


def qb_game_features(T, games, p):
    """Home minus away QB deltas per game; starter = QB on the team's first dropback of that game."""
    st = dict(zip(zip(T.first.game_id, T.first.team), T.first.starter))
    rows = {}
    for (s, w), g in games.groupby(['season', 'week']):
        starters = {}
        for r in g.itertuples():
            starters[r.home_team] = st[(r.game_id, r.home_team)]
            starters[r.away_team] = st[(r.game_id, r.away_team)]
        de, dq = qb_team_delta(T, s, w - 1, p, starters)
        for r in g.itertuples():
            rows[r.game_id] = (de[r.home_team] - de[r.away_team], dq[r.home_team] - dq[r.away_team])
    out = pd.DataFrame.from_dict(rows, orient='index', columns=['d_qexp', 'd_qqual'])
    return out.loc[games.game_id].reset_index(drop=True)


# -------------------------------------------------------------------------------- power scores
def expected_starters(T, s, W, games_back=3):
    """QB with the most dropbacks over each team's last `games_back` games through week W (falls back to last
    season early on). Robust to one-game rests; picks up a replacement after an injury."""
    qg = T.qg
    cur = qg[(qg.season == s) & (qg.week <= W)]
    prev = qg[qg.season == s - 1].copy()
    prev['team'] = prev.team.replace({'OAK': 'LV'})
    out = {}
    for team in T.tmap[s]:
        g = cur[cur.team == team]
        if len(g) == 0:
            g = prev[prev.team == team]
        wks = sorted(g.week.unique())[-games_back:]
        out[team] = g[g.week.isin(wks)].groupby('qb').n.sum().idxmax()
    return out


def power_scores(T, FIN, p, w, s, W, starters=None):
    """Power score per team after week W of season s. starters defaults to expected_starters (pass your own to
    override, e.g. when the depth chart says the usual starter is out)."""
    R = ratings_at(T, FIN, p, s, W).set_index('team')
    if starters is None:
        starters = expected_starters(T, s, W)
    names = {t: T.names.get(q, q) for t, q in starters.items()}
    teams = list(R.index)
    starters = {t: starters.get(t, None) for t in teams}
    de, dq = qb_team_delta(T, s, W, p, starters)
    out = R[['pd', 'o', 'e']].copy()
    out['qb_exp_delta'] = pd.Series(de)
    out['qb_qual_delta'] = pd.Series(dq)
    out['power'] = (w['pd'] * out.pd + w['o'] * out.o + w['nd'] * (-out.e) +
                    w['qexp'] * out.qb_exp_delta + w['qqual'] * out.qb_qual_delta)
    out['power'] -= out.power.mean()
    out['starter'] = pd.Series(names)
    return out.sort_values('power', ascending=False)
