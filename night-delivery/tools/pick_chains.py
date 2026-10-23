"""指定したチェーンの店舗を1店ずつ取り出して chain-stores.json を作る（足立区版マップ用）。

使い方:
  python3 tools/extract_overture.py kanto_places.json
  python3 tools/pick_chains.py kanto_places.json > chain-stores.json

出力: {"chains": [チェーン名, ...], "stores": [[チェーン番号, 緯度, 経度, 店名, 区市町村, 最寄り駅, 駅までの距離m], ...]}
"""
import json, math, os, re, sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
# (表示名, 店名に一致させる正規表現, 除外する正規表現, 重複とみなす距離m)
# 同じ店が別データ由来で少しずれて入っているので、この距離以内の同じチェーンは1店にまとめる。
# 駅前に2店あることもある吉野家は短く、近くに2店置かない魁力屋・デニーズは長めにしている。
CHAINS = [
    ('吉野家', r'吉野家|yoshinoya', r'そば処', 100),
    ('デニーズ', r'デニーズ|denny', None, 300),
    ('バーガーキング', r'バーガーキング|burger king', None, 200),
    ('魁力屋', r'魁力屋|kairikiya', None, 350),
]


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
    for i, (name, pat, ng, _) in enumerate(CHAINS):
        if re.search(pat, text, re.I) and not (ng and re.search(ng, text)):
            found[i].append(r)
            break

out = []
for i, rows in found.items():
    kept = []
    # 店名の長い方（「〇〇店」まで入っている方）を残す
    for r in sorted(rows, key=lambda r: -len(r['n'] or '')):
        if any(meters(r['y'], r['x'], k['y'], k['x']) < CHAINS[i][3] for k in kept):
            continue
        kept.append(r)
    for r in kept:
        mu = muni(r['y'], r['x'])
        if not mu:
            continue  # 関東の1都6県の外
        st = min(stations, key=lambda s: meters(r['y'], r['x'], s[1], s[2]))
        out.append([i, round(r['y'], 5), round(r['x'], 5), r['n'] or CHAINS[i][0], mu, st[0],
                    round(meters(r['y'], r['x'], st[1], st[2]))])

print(json.dumps({'chains': [c[0] for c in CHAINS], 'stores': out}, ensure_ascii=False, separators=(',', ':')))
