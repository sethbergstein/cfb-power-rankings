"""Quick checks on site_data/nfl_power.json and the matchup predictor.  python3 tests/smoke_test.py"""
import json, os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'engine'))
from matchup import load_power, predict

P = load_power(os.path.join(HERE, '..', 'site_data', 'nfl_power.json'))
T = P['teams']
assert len(T) == 32 and len({t['team'] for t in T}) == 32, 'need 32 teams'
assert abs(sum(t['power'] for t in T)) < 0.05, 'power scores should center on zero'
assert all(abs(sum(t['components'].values()) - t['power']) < 0.05 for t in T), 'components should sum to power'
assert [t['rank'] for t in T] == list(range(1, 33)) and all(T[i]['power'] >= T[i + 1]['power'] for i in range(31)), 'ranks sorted by power'
a, b = T[0]['team'], T[-1]['team']
n1, n2 = predict(P, a, b, neutral=True), predict(P, b, a, neutral=True)
assert abs(n1['margin_home'] + n2['margin_home']) < 0.11 and abs(n1['home_win_prob'] + n2['home_win_prob'] - 1) < 0.002, 'neutral matchups should be symmetric'
h = predict(P, a, b)
assert abs(h['margin_home'] - n1['margin_home'] - P['meta']['home_field']) < 0.11, 'home field should add 1.45'
assert h['home_win_prob'] > 0.5 > predict(P, b, a)['home_win_prob'], 'best team over worst should be favored at home and away'
print('ok:', len(T), 'teams, through week', P['meta']['through_week'], '| top', a, T[0]['power'], '| bottom', b, T[-1]['power'])
