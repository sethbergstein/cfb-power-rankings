"""Backtest of the combined engine (v2), 2019-2025, leave-one-season-out.
usage: python3 engine/backtest_v2.py   (needs data for 2017-2025; run refresh.py --season 2025 first to download it)
writes backtest_output/engine_v2_backtest.csv, engine_v2_predictions.csv, engine_spec_v2_refit.json"""
import json, numpy as np, pandas as pd
from scipy.optimize import nnls
from engine_lib import make_tables, final_ratings, build_ratings, rating_diffs, qb_team_delta
from qb_status import load_injuries, starter_table, RATES
from engine_v2 import *
pd.set_option('display.width', 220); pd.set_option('display.float_format', lambda x: f'{x:.4f}')
import os
HERE = os.path.dirname(os.path.abspath(__file__)); D = os.environ.get('NFL_DATA_DIR', os.path.join(HERE, '..', 'data')); OUT = os.path.join(HERE, '..', 'backtest_output'); SEAS = list(range(2019, 2026))
spec = json.load(open(os.path.join(HERE, 'engine_spec.json'))); P = dict(spec['params'])
T = make_tables(D, range(2017, 2026)); FIN = final_ratings(T)
G = T.games[T.games.season >= 2019].reset_index(drop=True)
y = G.result.values.astype(float); seas = G.season.values; wk = G.week.values; spread = G.spread_line.values.astype(float)

# ---- preseason priors, leave-one-season-out
F = prior_features(D, T, FIN, SEAS)
PRI = {s: prior_for(F, fit_prior(F[F.season != s]), s) for s in SEAS}
R = pd.concat([ratings_v2(T, PRI[s], P, s, W) for s in SEAS for W in range(0, int(T.panel[T.panel.season == s].week.max()))], ignore_index=True)
Dn = rating_diffs(R, G); base_new = np.c_[Dn.d_pd, Dn.d_o, Dn.d_nd]
Do = rating_diffs(build_ratings(T, FIN, P, SEAS), G); base_old = np.c_[Do.d_pd, Do.d_o, Do.d_nd]

# ---- QB: soft starters from the injury report (week 1: actual starter)
inj = load_injuries([pd.read_parquet(f'{D}/injuries_{y_}.parquet') for y_ in range(2018, 2026)])
first = {(r.game_id, r.team): r.starter for r in T.first.itertuples()}
qb_soft, qb_last, qb_act = {}, {}, {}
for (s, w), g in G.groupby(['season', 'week']):
    teams = sorted(set(g.home_team) | set(g.away_team))
    if w == 1:
        st = {t: first[(gid, t)] for gid, h, a in zip(g.game_id, g.home_team, g.away_team) for t in (h, a)}
        de, dq = qb_team_delta(T, s, 0, P, st); ds = {t: (de[t], dq[t]) for t in teams}; dl = dict(ds)
    else:
        tab = starter_table(T, inj, s, w, teams=teams)
        de, dq = qb_mix_deltas(T, P, s, w, tab); ds = {t: (de[t], dq[t]) for t in teams}
        last = {t: max((x for x in [tab.last_game_qb[t]]), key=lambda q: 1) for t in teams}
        e2, q2 = qb_team_delta(T, s, w - 1, P, last); dl = {t: (e2[t], q2[t]) for t in teams}
    st_act = {t: first[(gid, t)] for gid, h, a in zip(g.game_id, g.home_team, g.away_team) for t in (h, a)}
    ea, qa = qb_team_delta(T, s, w - 1, P, st_act); da = {t: (ea[t], qa[t]) for t in teams}
    for gid, h, a in zip(g.game_id, g.home_team, g.away_team):
        qb_soft[gid] = np.array(ds[h]) - np.array(ds[a]); qb_last[gid] = np.array(dl[h]) - np.array(dl[a]); qb_act[gid] = np.array(da[h]) - np.array(da[a])
Qs, Ql, Qa = (np.array([m[g] for g in G.game_id]) for m in (qb_soft, qb_last, qb_act))

# ---- injury layer
NL = new_loss_table(injury_rows(D, SEAS))
inj_c = np.array([NL.get((s, w, nm(h)), 0.0) - NL.get((s, w, nm(a)), 0.0) for s, w, h, a in zip(G.season, G.week, G.home_team, G.away_team)])

def loso(X, tgt=None, base=None):
    out = np.zeros(len(y))
    for s in SEAS:
        tr, te = seas != s, seas == s
        if base is None:
            xm, ym = X[tr].mean(0), y[tr].mean(); b, _ = nnls(X[tr] - xm, y[tr] - ym); out[te] = ym - xm @ b + X[te] @ b
        else:                                    # residual layer on top of base predictions
            Z = -X; res = y - base; zm = Z[tr].mean(0); b, _ = nnls(Z[tr] - zm, res[tr] - res[tr].mean()); out[te] = base[te] + (Z[te] - zm) @ b
    return out
rr = lambda p, m=None: np.corrcoef(p if m is None else p[m], y if m is None else y[m])[0, 1]
M = {}
M['A. delivered engine (old prior, actual starter)'] = loso(np.c_[base_old, Qa])
M['B. old prior, QB = last game starter'] = loso(np.c_[base_old, Ql])
M['C. old prior, QB from report'] = loso(np.c_[base_old, Qs])
M['D. new prior, QB from report'] = loso(np.c_[base_new, Qs])
M['E. D + injury number (final engine)'] = loso(inj_c[:, None], base=M['D. new prior, QB from report'])
M['F. new prior, actual starter (ceiling)'] = loso(np.c_[base_new, Qa])
M['Vegas (benchmark only)'] = spread
tab = pd.DataFrame({k: {'wk1-2': rr(v, wk <= 2), 'wk1-5': rr(v, wk <= 5), 'wk6+': rr(v, wk >= 6), 'all': rr(v), 'rmse': np.sqrt(np.mean((v - y) ** 2))} for k, v in M.items()}).T
print(tab); tab.to_csv(f'{OUT}/engine_v2_backtest.csv')
rng = np.random.default_rng(0); idx = [rng.integers(0, len(y), len(y)) for _ in range(1000)]
def bd(a, b, m=None):
    d = [np.corrcoef(a[i[m[i]] if m is not None else i], y[i[m[i]] if m is not None else i])[0, 1] - np.corrcoef(b[i[m[i]] if m is not None else i], y[i[m[i]] if m is not None else i])[0, 1] for i in idx]
    return np.mean(d), np.percentile(d, [2.5, 97.5])
E_, C_, B_ = (M[k] for k in ['E. D + injury number (final engine)', 'C. old prior, QB from report', 'B. old prior, QB = last game starter'])
for lab, a, b, m in [('E - B (everything vs last-game starter, old prior)', E_, B_, None), ('E - C (new prior + injuries vs old prior)', E_, C_, None),
                     ('D - C (new prior only)', M['D. new prior, QB from report'], C_, None), ('E - D (injury number only)', E_, M['D. new prior, QB from report'], None),
                     ('E - B, weeks 1-5', E_, B_, wk <= 5), ('Vegas - E', spread, E_, None)]:
    d, ci = bd(a, b, m); print(f'  {lab:<54} {d:+.4f} [{ci[0]:+.4f}, {ci[1]:+.4f}]')
print('\nby season, r: ', {int(s): (round(rr(E_, seas == s), 3), round(rr(spread, seas == s), 3)) for s in SEAS}, '(engine, Vegas)')
edge = E_ - spread; push = y == spread; m = (edge != 0) & ~push
win = np.where(edge[m] > 0, y[m] > spread[m], y[m] < spread[m]); print('against the spread: %.3f over %d games' % (win.mean(), m.sum()))

# ---- final fit (all seasons) and spec
Xf = np.c_[base_new, Qs]; xm, ym = Xf.mean(0), y.mean(); b, _ = nnls(Xf - xm, y - ym); home = ym - xm @ b
pf = Xf @ b + home; res = y - pf; Z = -inj_c[:, None]; zm = Z.mean(0); bi, _ = nnls(Z - zm, res - res.mean())
model_all = fit_prior(F)
spec2 = dict(params={k: P[k] for k in ('am', 'ao', 'ad', 'ke', 'kq', 'K')}, weights=dict(zip(['pd', 'o', 'nd', 'qexp', 'qqual'], map(float, b))), home_field=float(home),
             injury_points_per_starter=float(bi[0]), p_miss_questionable=0.38, qb_rates=RATES, prior_lambda=PRIOR_LAMBDA, prior_model=model_all,
             backtest={k: {c: float(v) for c, v in r.items()} for k, r in tab.iterrows()})
spec2['win_prob_sigma'] = 13.5
json.dump(spec2, open(f'{OUT}/engine_spec_v2_refit.json', 'w'), indent=1)  # copy over engine/engine_spec_v2.json to adopt
print('\nweights', {k: round(v, 3) for k, v in spec2['weights'].items()}, '| home', round(home, 2), '| injury pts per starter lost', round(float(bi[0]), 2))
print('prior coefficients (pd model, per 1 sd of feature):', dict(zip(model_all['pd']['cols'], np.round(np.array(model_all['pd']['b']), 2))))

pd.DataFrame({'game_id': G.game_id, 'season': G.season, 'week': G.week, 'home': G.home_team, 'away': G.away_team, 'margin': y, 'engine': E_, 'spread': spread}).to_csv(f'{OUT}/engine_v2_predictions.csv', index=False)
