"""QB starter probabilities from the official injury report (nflverse injuries data) plus recent usage.

starter_table(T, inj, season, week) -> one row per team: most likely starter, alternate, probability the first starts.
Probabilities come from 2019-2025 history (how often a QB in each report/practice state actually started):
  last game's QB ruled Out/Doubtful ........ 0%  (never started in 2019-2025)
  last game's QB Questionable, full practice  86%   limited 56%   did not practice 31%
  established QB returning, report shows him cleared after being Out/Doubtful/Questionable ... 85%
  established QB returning but still Questionable ... 39%
  otherwise last game's QB.
Override anything wrong with a CSV (team, starter_id) passed to apply_overrides; news the report misses goes there.
"""
import numpy as np, pandas as pd

RATES = dict(q_full=0.857, q_lim=0.558, q_dnp=0.312, ret_clear=0.848, ret_q=0.393)


def _prac(s):
    if not isinstance(s, str): return 'none'
    s = s.lower()
    return 'full' if s.startswith('full') else 'limited' if s.startswith('limited') else 'dnp' if s.startswith('did not') else 'other'


def load_injuries(frames):
    inj = pd.concat(frames)
    inj = inj[inj.position == 'QB']
    rs, ps = {}, {}
    for r in inj.itertuples():
        rs[(r.season, r.week, r.gsis_id)] = r.report_status if isinstance(r.report_status, str) else 'none'
        ps[(r.season, r.week, r.gsis_id)] = _prac(r.practice_status)
    return rs, ps


def starter_table(T, inj, s, w, teams=None, rates=RATES):
    """Prediction for games in week w of season s, using games through week w-1 and the week-w report."""
    rs, ps = inj
    R = lambda wk, q: rs.get((s, wk, q), 'absent'); P = lambda wk, q: ps.get((s, wk, q), 'absent')
    bad = lambda q: R(w, q) in ('Out', 'Doubtful')
    qg = T.qg
    def tot(team, k):
        g = qg[(qg.team == team) & ((qg.season < s) | ((qg.season == s) & (qg.week < w)))]
        keys = sorted(set(zip(g.season, g.week)))[-k:]
        g = g[[ (a, b) in keys for a, b in zip(g.season, g.week)]]
        return g.groupby('qb').n.sum().to_dict()
    rows = []
    for team in (teams or sorted(T.tmap[s])):
        t1, t3, t6 = tot(team, 1), tot(team, 3), tot(team, 6)
        L = max(t1, key=t1.get); est = max(t6, key=t6.get)
        order = sorted(t3, key=t3.get, reverse=True) + [q for q in sorted(t6, key=t6.get, reverse=True) if q not in t3]
        alt_ok = lambda ex: next((q for q in order if q not in ex and not bad(q)), None)
        a, b, p, why = L, None, 1.0, 'last game QB'
        if R(w, L) in ('Out', 'Doubtful'):
            a = est if (est != L and not bad(est)) else (alt_ok({L}) or L); why = f'last game QB is {R(w, L)}'
        elif est != L and R(w, est) == 'none' and R(w - 1, est) in ('Out', 'Doubtful', 'Questionable'):
            a, b, p, why = est, L, rates['ret_clear'], 'established QB cleared after missing time'
        elif est != L and R(w, est) == 'Questionable':
            a, b, p, why = est, L, rates['ret_q'], 'established QB still Questionable'
        elif R(w, L) == 'Questionable':
            pr = rates['q_full'] if P(w, L) == 'full' else rates['q_dnp'] if P(w, L) == 'dnp' else rates['q_lim']
            alt = est if (est != L and not bad(est)) else alt_ok({L})
            a, b, p, why = L, alt, (pr if alt else 1.0), f'last game QB Questionable ({P(w, L)} practice)'
        rows.append(dict(team=team, likely=a, alt=b if b else a, p_likely=p, last_game_qb=L, established_qb=est, why=why))
    return pd.DataFrame(rows).set_index('team')
