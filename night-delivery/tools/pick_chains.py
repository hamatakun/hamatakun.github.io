"""指定したチェーンの店舗を1店ずつ取り出して chain-stores.json を作る（足立区版マップ用）。

使い方:
  python3 tools/extract_overture.py kanto_places.json
  python3 tools/pick_chains.py kanto_places.json > chain-stores.json

出力: {"chains": [チェーン名, ...], "stores": [[チェーン番号, 緯度, 経度, 店名, 区市町村, 最寄り駅, 駅までの距離m], ...]}
"""
import json, math, os, re, sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
# (表示名, 店名に一致させる正規表現, 除外する正規表現, 重複とみなす距離m, 店名なしの重複距離m)
# 同じ店が別データ由来で少しずれて入っているので、次のどれかに当たるものは1店にまとめる。
#  - 同じ支店名（「竹の塚店」など）で3km以内
#  - 同じチェーンで「重複とみなす距離」以内
#  - 支店名のない記録（店名がチェーン名だけ）で、同じチェーンの店から「店名なしの重複距離」以内
# 駅前に2店あることもある吉野家は短く、近くに2店置かない魁力屋・デニーズ・宅配ピザは長めにしている。
CHAINS = [
    ('吉野家', r'吉野家|yoshinoya', r'そば処', 100, 100),
    ('デニーズ', r'デニーズ|denny', None, 300, 500),
    ('バーガーキング', r'バーガーキング|burger king', None, 200, 400),
    ('魁力屋', r'魁力屋|kairikiya', None, 350, 600),
    ('ドミノ・ピザ', r'ドミノ|domino', None, 200, 600),
    ('ピザハット', r'ピザハット|pizza hut', None, 200, 600),
    ('ピザーラ', r'ピザーラ|pizza-la', None, 200, 600),
    ('目利きの銀次', r'目利きの銀次', None, 200, 400),
    ('魚民', r'魚民|uotami', r'すし', 200, 400),
    ('福福屋', r'福福屋|ふくふく屋', None, 200, 400),
]
BRANCH_NOISE = r'[\s・･()（）〈〉\-]|京都北白川|ラーメン|ピザ|pizza|海鮮楽屋|店$'


def branch(name, pat):
    """店名からチェーン名を取り除いた支店名（なければ空文字）。"""
    return re.sub(BRANCH_NOISE, '', re.sub(pat, '', name or '', flags=re.I), flags=re.I).lower()


def meters(lat1, lon1, lat2, lon2):
    dy = (lat2 - lat1) * 111_320
    dx = (lon2 - lon1) * 111_320 * math.cos(math.radians((lat1 + lat2) / 2))
    return math.hypot(dx, dy)


geo = json.load(open(os.path.join(HERE, '..', 'kanto.geojson')))
areas = []
for f in geo['features']:
    rings = [p[0] for p in f['geometry']['coordinates']]
    xs = [c[0] for r in rings for c in r]
    ys = [c[1] for r in rings for c in r]
    areas.append((min(xs), max(xs), min(ys), max(ys), rings, f['properties']['n']))


def inside(ring, lat, lng):
    ins, j = False, len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i]
        xj, yj = ring[j]
        if (yi > lat) != (yj > lat) and lng < (xj - xi) * (lat - yi) / (yj - yi) + xi:
            ins = not ins
        j = i
    return ins


def muni(lat, lon):
    for x0, x1, y0, y1, rings, n in areas:
        if x0 <= lon <= x1 and y0 <= lat <= y1 and any(inside(r, lat, lon) for r in rings):
            return n
    return None


stations = json.load(open(os.path.join(HERE, '..', 'stations.json')))
places = json.load(open(sys.argv[1]))
found = defaultdict(list)
for r in places:
    h = r['h'] or []
    if not h or h[0] != 'food_and_drink':
        continue
    # 店名で判定する（ブランド欄はほかの店の名前が入っていることがある）
    text = r['n'] or r['b'] or ''
    for i, (name, pat, ng, *_) in enumerate(CHAINS):
        if re.search(pat, text, re.I) and not (ng and re.search(ng, text)):
            found[i].append(r)
            break

out = []
for i, rows in found.items():
    kept = []
    _, pat, _, near, generic_near = CHAINS[i]
    # 店名の長い方（「〇〇店」まで入っている方）を先に残す
    for r in sorted(rows, key=lambda r: -len(r['n'] or '')):
        b = branch(r['n'], pat)
        dup = False
        for k in kept:
            d = meters(r['y'], r['x'], k['y'], k['x'])
            if d < near or (b and b == k['br'] and d < 3000) or (not b and d < generic_near):
                dup = True
                break
        if not dup:
            r['br'] = b
            kept.append(r)
    for r in kept:
        mu = muni(r['y'], r['x'])
        if not mu:
            continue  # 関東の1都6県の外
        st = min(stations, key=lambda s: meters(r['y'], r['x'], s[1], s[2]))
        out.append([i, round(r['y'], 5), round(r['x'], 5), r['n'] or CHAINS[i][0], mu, st[0],
                    round(meters(r['y'], r['x'], st[1], st[2]))])

print(json.dumps({'chains': [c[0] for c in CHAINS], 'stores': out}, ensure_ascii=False, separators=(',', ':')))
