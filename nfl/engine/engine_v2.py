"""NFL power rating engine v2: adds a data-driven preseason prior, report-based QB starter odds and an injury adjustment
on top of engine_lib (opponent-adjusted ratings + QB term). No betting-market inputs anywhere.

Data (nflverse releases, saved under `data_dir`):
  pbp_<year>.parquet            play_by_play_<year>.parquet        (pbp release)
  injuries_<year>.parquet       injuries release
  snaps_<year>.parquet          snap_counts release
  roster_weekly_<year>.parquet  weekly_rosters release
  players.parquet               players release  (id map)
"""
import numpy as np, pandas as pd
from engine_lib import make_tables, final_ratings, _fit_margin, _fit_epa, qb_team_delta
from qb_status import load_injuries, starter_table

NORM = {'OAK': 'LV', 'SD': 'LAC', 'STL': 'LA'}
nm = lambda t: NORM.get(t, t)
PRIOR_FEATS = lambda c: [c + '1', c + '2', 'coach_new', 'ret_off', 'ret_def', 'inc_off', 'inc_def']
PRIOR_LAMBDA = 5.0
GRP = {'T': 'OL', 'G': 'OL', 'C': 'OL', 'OL': 'OL', 'OT': 'OL', 'DE': 'DL', 'DT': 'DL', 'NT': 'DL', 'DL': 'DL', 'LB': 'LB', 'ILB': 'LB',
       'OLB': 'LB', 'MLB': 'LB', 'CB': 'CB', 'DB': 'CB', 'S': 'S', 'FS': 'S', 'SS': 'S', 'WR': 'WR', 'TE': 'TE', 'RB': 'RB', 'FB': 'RB', 'HB': 'RB'}


# ------------------------------------------------------------------------------------------ preseason prior
def prior_features(D, T, FIN, seasons, last_complete=2025):
    """One row per (season, team) using only information available before week 1:
    last two seasons' final ratings, new head coach flag, share of last year's offensive/defensive snaps that is on the
    week 1 roster (retained, same team) and arrived from other teams (incoming)."""
    fin = {s: df.rename(index=NORM) for s, df in FIN.items()}
    co = []
    for y in range(min(seasons) - 2, max(seasons) + 1):
        d = pd.read_parquet(f'{D}/pbp_{y}.parquet', columns=['game_id', 'season_type', 'week', 'home_team', 'away_team', 'home_coach', 'away_coach'])
        d = d[d.season_type == 'REG'].drop_duplicates('game_id')
        co.append(pd.concat([d[['week', 'home_team', 'home_coach']].rename(columns={'home_team': 'team', 'home_coach': 'coach'}),
                             d[['week', 'away_team', 'away_coach']].rename(columns={'away_team': 'team', 'away_coach': 'coach'})]).assign(season=y))
    co = pd.concat(co); co['team'] = co.team.map(nm); co = co.sort_values(['season', 'team', 'week'])
    first_c, last_c = co.groupby(['season', 'team']).coach.first(), co.groupby(['season', 'team']).coach.last()
    sn = pd.concat([pd.read_parquet(f'{D}/snaps_{y}.parquet') for y in range(min(seasons) - 1, max(seasons))])
    sn = sn[sn.game_type == 'REG'].copy(); sn['team'] = sn.team.map(nm)
    pl = pd.read_parquet(f'{D}/players.parquet')[['gsis_id', 'pfr_id']].dropna()
    sn['gsis'] = sn.pfr_player_id.map(dict(zip(pl.pfr_id, pl.gsis_id))); sn = sn[sn.gsis.notna()]
    ng = sn.groupby(['season', 'team']).game_id.nunique()
    agg = sn.groupby(['season', 'team', 'gsis'])[['offense_pct', 'defense_pct']].sum().reset_index()
    agg['n'] = [ng[(s, t)] for s, t in zip(agg.season, agg.team)]
    agg['off'], agg['def'] = agg.offense_pct / agg.n, agg.defense_pct / agg.n
    tot_p = agg.groupby(['season', 'gsis'])[['off', 'def']].sum()
    rows = []
    for s in seasons:
        ro = pd.read_parquet(f'{D}/roster_weekly_{s}.parquet')
        ro = ro[(ro.week == 1) & (ro.game_type == 'REG') & ro.status.isin(['ACT', 'INA']) & ro.gsis_id.notna()].copy(); ro['team'] = ro.team.map(nm)
        prev = agg[agg.season == s - 1]; tp = tot_p.loc[s - 1]
        for t in sorted(fin[s - 1].index):
            ids = set(ro[ro.team == t].gsis_id); mine = prev[prev.team == t]; ret = mine[mine.gsis.isin(ids)]
            oth = tp.reindex(list(ids - set(mine.gsis))).dropna()
            r = dict(season=s, team=t, pd1=fin[s - 1].pd[t], o1=fin[s - 1].o[t], e1=fin[s - 1].e[t],
                     pd2=fin[s - 2].pd[t], o2=fin[s - 2].o[t], e2=fin[s - 2].e[t],
                     coach_new=float(first_c.get((s, t)) != last_c.get((s - 1, t))),
                     ret_off=ret.off.sum() / 11, ret_def=ret['def'].sum() / 11, inc_off=oth.off.sum() / 11, inc_def=oth['def'].sum() / 11)
            if s <= last_complete: r.update(tgt_pd=fin[s].pd[t], tgt_o=fin[s].o[t], tgt_e=fin[s].e[t])
            rows.append(r)
    return pd.DataFrame(rows)


def _ridge(X, y, lam):
    mu, sd = X.mean(0), X.std(0) + 1e-9
    Z = (X - mu) / sd; ym = y.mean()
    b = np.linalg.solve(Z.T @ Z + lam * np.eye(Z.shape[1]), Z.T @ (y - ym))
    return dict(mu=mu.tolist(), sd=sd.tolist(), b=b.tolist(), ym=float(ym))


def _apply(m, X):
    return m['ym'] + ((X - np.array(m['mu'])) / np.array(m['sd'])) @ np.array(m['b'])


def fit_prior(F, lam=PRIOR_LAMBDA):
    """Ridge models mapping preseason features to a team's end-of-season pd / o / e rating."""
    return {c: dict(cols=PRIOR_FEATS(c), **_ridge(F[PRIOR_FEATS(c)].values, F['tgt_' + c].values, lam)) for c in ('pd', 'o', 'e')}


def prior_for(F, model, s):
    f = F[F.season == s]
    return pd.DataFrame({c: _apply(model[c], f[model[c]['cols']].values) for c in ('pd', 'o', 'e')}, index=f.team.values)


# ------------------------------------------------------------------------------------------ ratings with that prior
def ratings_v2(T, prior, p, s, W):
    """Opponent-adjusted ratings after week W of season s, ridge-shrunk toward the preseason prior (W=0: the prior)."""
    teams = list(T.tmap[s].keys()); n = len(teams)
    pr = prior.reindex([nm(t) for t in teams]); mpd, mo, me = pr.pd.values, pr.o.values, pr.e.values
    sub = T.panel[(T.panel.season == s) & (T.panel.week <= W)]
    if len(sub) == 0: r, o, e = mpd, mo, me
    else:
        r = _fit_margin(sub, n, p['am'], 1.0, mpd); o, e = _fit_epa(sub, n, p['ao'], 1.0, p['ad'], 1.0, mo, me)
    return pd.DataFrame({'season': s, 'W': W, 'team': teams, 'pd': r, 'o': o, 'e': e})


# ------------------------------------------------------------------------------------------ injuries beyond QB
def injury_rows(D, years):
    """Report rows for non-QB players with how big a role they usually have (mean snap share, last 8 appearances)."""
    pl = pd.read_parquet(f'{D}/players.parquet')[['gsis_id', 'pfr_id']].dropna()
    p2g = dict(zip(pl.pfr_id, pl.gsis_id))
    sn = pd.concat([pd.read_parquet(f'{D}/snaps_{y}.parquet') for y in range(min(years) - 1, max(years) + 1)])
    sn = sn[sn.game_type == 'REG'].copy(); sn['gsis'] = sn.pfr_player_id.map(p2g)
    sn['pct'] = np.maximum(sn.offense_pct.fillna(0), sn.defense_pct.fillna(0)); sn['grp'] = sn.position.map(GRP)
    sn = sn[sn.gsis.notna() & sn.grp.notna() & (sn.pct > 0)].copy(); sn['t'] = sn.season * 100 + sn.week
    app = {g: (d.t.values, d.pct.values) for g, d in sn.sort_values('t').groupby('gsis')}
    inj = pd.concat([pd.read_parquet(f'{D}/injuries_{y}.parquet') for y in years])
    inj = inj[inj.week <= 18].copy(); inj['season'] = inj.season.astype(int); inj['week'] = inj.week.astype(int)
    inj['grp'] = inj.position.map(GRP); inj = inj[inj.grp.notna() & inj.gsis_id.notna()].copy()
    inj['status'] = inj.report_status.where(inj.report_status.isin(['Out', 'Doubtful', 'Questionable']), 'none')
    inj['team'] = inj.team.map(nm)
    def usual(g, t, k=8):
        a = app.get(g)
        if a is None: return np.nan
        i = np.searchsorted(a[0], t, side='left')
        return float(a[1][max(0, i - k):i].mean()) if i else np.nan
    inj['usual'] = [usual(g, s * 100 + w) for g, s, w in zip(inj.gsis_id, inj.season, inj.week)]
    return inj[inj.status.isin(['Out', 'Doubtful', 'Questionable']) & inj.usual.notna()].copy()


def new_loss_table(inj, p_miss_questionable=0.38):
    """Starter-equivalents newly lost per (season, week, team): usual snap share x chance of missing, counting only players
    who were not already ruled Out/Doubtful the week before (those are already in the team's recent results)."""
    inj = inj.copy(); inj['loss'] = inj.usual * np.where(inj.status == 'Questionable', p_miss_questionable, 1.0)
    prev = inj[inj.status.isin(['Out', 'Doubtful'])][['season', 'week', 'gsis_id']].copy(); prev['week'] += 1; prev['was_out'] = True
    inj = inj.merge(prev, on=['season', 'week', 'gsis_id'], how='left'); inj['was_out'] = inj.was_out.fillna(False).astype(bool)
    inj['new_loss'] = np.where(inj.was_out, 0.0, inj.loss)
    return inj.groupby(['season', 'week', 'team']).new_loss.sum()


# ------------------------------------------------------------------------------------------ QB starter mix
def qb_mix_deltas(T, p, s, w, tab):
    """Expected QB experience / quality deltas per team given a starter_table (likely starter, alternate, probability)."""
    A, B = tab.likely.to_dict(), tab.alt.to_dict()
    ea, qa = qb_team_delta(T, s, w - 1, p, A); eb, qb = qb_team_delta(T, s, w - 1, p, B)
    pr = tab.p_likely.to_dict()
    de = {t: pr[t] * ea[t] + (1 - pr[t]) * eb[t] for t in tab.index}
    dq = {t: pr[t] * qa[t] + (1 - pr[t]) * qb[t] for t in tab.index}
    return de, dq
