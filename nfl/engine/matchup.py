"""Matchup predictor on top of the power scores.

    from matchup import load_power, predict
    P = load_power()                       # reads ../site_data/nfl_power.json
    predict(P, home='KC', away='BUF')      # home field applied
    predict(P, 'KC', 'BUF', neutral=True)  # neutral site

CLI:  python engine/matchup.py KC BUF [--neutral]

predicted home margin = home field (1.45, 0 if neutral) + power(home) - power(away)
home win probability  = normal CDF(margin / sigma), sigma 13.5 (fitted on the 2019-2025 backtest; calibration checked)
"""
import json, math, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT = os.path.join(HERE, '..', 'site_data', 'nfl_power.json')


def load_power(path=DEFAULT):
    return json.load(open(path))


def _phi(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def predict(P, home, away, neutral=False):
    T = {t['team']: t for t in P['teams']}
    h, a = T[home], T[away]
    hf = 0.0 if neutral else P['meta']['home_field']
    margin = hf + h['power'] - a['power']
    p_home = _phi(margin / P['meta']['win_prob_sigma'])
    fav, dog = (home, away) if margin >= 0 else (away, home)
    # where the gap comes from, in points, from the home team's side (components sum to power)
    why = {k: round(h['components'][k] - a['components'][k], 2) for k in h['components']}
    return dict(home=home, away=away, neutral=neutral, margin_home=round(margin, 1), favorite=fav, underdog=dog,
                spread=round(abs(margin), 1), home_win_prob=round(p_home, 3), away_win_prob=round(1 - p_home, 3),
                home_field_points=hf, why_points_home_minus_away=why,
                qb_flags=[f"{t['team']}: {t['starter']} ({int(round(t['starter_prob'] * 100))}% to start)" for t in (h, a) if t['starter_prob'] < 1])


if __name__ == '__main__':
    args = [x for x in sys.argv[1:] if not x.startswith('--')]
    if len(args) != 2:
        sys.exit('usage: python matchup.py HOME AWAY [--neutral]')
    r = predict(load_power(), args[0].upper(), args[1].upper(), neutral='--neutral' in sys.argv)
    print(json.dumps(r, indent=2))
