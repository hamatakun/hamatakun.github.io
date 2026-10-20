"""駅ごとに、半径500m以内の深夜営業チェーンの店舗数を数えて stores.json を作る。

使い方:
  python3 tools/extract_overture.py kanto_places.json
  python3 tools/count_stores.py kanto_places.json > stores.json

出力は stations.json と同じ順番の配列で、各駅が
  [22〜24時の店数, 0〜2時の店数, 2時以降の店数, 飲食店の総数, [[チェーン名, 店数, 分類], ...]]
最後の要素 "_wards" に区市町村ごとの [[チェーン名, 店数, 分類], ...] を入れる。
どのチェーンを数えるか（アプリに加盟しているか）はページ側で選ぶので、ここではチェーンごとの数だけ出す。

営業時間はデータに入っていないので、チェーンごとのふだんの閉店時間で3つに分けている。
  24h : 24時間営業の店が多い → 3つの時間帯すべてで数える
  late: 深夜1〜2時頃まで → 22〜24時と0〜2時で数える
  eve : 23〜24時頃まで → 22〜24時だけ数える
"""
import json, math, os, re, sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
RADIUS = 500  # m

# (表示名, 分類, 店名に一致させる正規表現)
CHAINS = [
    ('すき家', '24h', r'すき家|sukiya'),
    ('松屋', '24h', r'^(?!.*(コーヒー|珈琲|銀座|浅草|フーズ)).*(松屋|matsuya)'),
    ('松のや', '24h', r'松のや|matsunoya'),
    ('吉野家', '24h', r'吉野家|yoshinoya'),
    ('なか卯', '24h', r'なか卯|nakau'),
    ('富士そば', '24h', r'富士そば'),
    ('一蘭', '24h', r'一蘭|ichiran'),
    ('山岡家', '24h', r'山岡家'),
    ('マクドナルド', '24h', r'マクドナルド|mcdonald'),
    ('ガスト', 'late', r'^(?!.*ステーキ).*(ガスト|gusto)'),
    ('デニーズ', 'late', r'デニーズ|denny'),
    ('ジョナサン', 'late', r'ジョナサン|jonathan'),
    ('ココス', 'late', r"ココス|coco's"),
    ('バーミヤン', 'late', r'バーミヤン|bamiyan'),
    ('日高屋', 'late', r'日高屋|hidakaya'),
    ('天下一品', 'late', r'天下一品|tenkaippin'),
    ('オリジン', 'late', r'オリジン弁当|キッチンオリジン|origin bento'),
    ('壱角家', 'late', r'壱角家'),
    ('すた丼', 'late', r'すた丼'),
    ('丸源ラーメン', 'late', r'丸源'),
    ('サイゼリヤ', 'eve', r'サイゼリヤ|saizeriya'),
    ('餃子の王将', 'eve', r'餃子の王将'),
    ('大阪王将', 'eve', r'大阪王将'),
    ('かつや', 'eve', r'かつや(?!ま)|katsuya'),
    ('CoCo壱番屋', 'eve', r'coco壱|ココイチ|ichibanya'),
    ('モスバーガー', 'eve', r'モスバーガー|mos burger'),
    ('バーガーキング', 'eve', r'バーガーキング|burger king'),
    ('ドミノ・ピザ', 'eve', r'ドミノ|domino'),
    ('ピザハット', 'eve', r'ピザハット|pizza hut'),
    ('ピザーラ', 'eve', r'ピザーラ|pizza-la'),
    ('からやま', 'eve', r'からやま'),
    ('ロイヤルホスト', 'eve', r'ロイヤルホスト|royal host'),
    ('幸楽苑', 'eve', r'幸楽苑'),
    ('ほっともっと', 'eve', r'ほっともっと|hotto ?motto'),
    ('ステーキガスト', 'eve', r'ステーキガスト'),
]
SLOTS = {'24h': (1, 1, 1), 'late': (1, 1, 0), 'eve': (1, 0, 0)}
RX = [(n, c, re.compile(p, re.I)) for n, c, p in CHAINS]
CLASS = {n: c for n, c, _ in CHAINS}
EATERY = {'restaurant', 'casual_eatery'}


def meters(lat1, lon1, lat2, lon2):
    dy = (lat2 - lat1) * 111_320
    dx = (lon2 - lon1) * 111_320 * math.cos(math.radians((lat1 + lat2) / 2))
    return math.hypot(dx, dy)


def dedupe(points, dist):
    """同じものが別データ由来で重なっているので、dist m 以内は1つにまとめる。"""
    grid, kept = defaultdict(list), []
    cell = dist / 111_320
    for p in points:
        gx, gy = int(p[1] / cell), int(p[0] / cell)
        near = [q for dx in (-1, 0, 1) for dy in (-1, 0, 1) for q in grid[(gx + dx, gy + dy)]]
        if any(meters(p[0], p[1], q[0], q[1]) < dist for q in near):
            continue
        grid[(gx, gy)].append(p)
        kept.append(p)
    return kept


places = json.load(open(sys.argv[1]))
stations = json.load(open(os.path.join(HERE, '..', 'stations.json')))

# チェーン店（チェーンごとに60m以内の重複をまとめる）と、飲食店全体（同じ名前で50m以内をまとめる）
chain_pts = defaultdict(list)
eat_pts = defaultdict(list)
for r in places:
    h = r['h'] or []
    if not h or h[0] != 'food_and_drink':
        continue
    text = (r['n'] or '') + ' | ' + (r['b'] or '')
    for name, cls, rx in RX:
        if rx.search(text):
            chain_pts[name].append((r['y'], r['x']))
            break
    if r['bc'] in EATERY:
        eat_pts[re.sub(r'\s+', '', (r['n'] or '').lower())[:12]].append((r['y'], r['x']))

stores = []  # (lat, lon, チェーン名, 分類)
for name, cls, _ in RX:
    stores += [(lat, lon, name, cls) for lat, lon in dedupe(chain_pts[name], 60)]
eateries = [p for pts in eat_pts.values() for p in dedupe(pts, 50)]
print(f'chains {len(stores)}, eateries {len(eateries)}', file=sys.stderr)


def index(points):
    grid = defaultdict(list)
    for p in points:
        grid[(int(p[0] / 0.005), int(p[1] / 0.006))].append(p)
    return grid


def around(grid, lat, lon):
    gy, gx = int(lat / 0.005), int(lon / 0.006)
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            for p in grid[(gy + dy, gx + dx)]:
                if meters(lat, lon, p[0], p[1]) <= RADIUS:
                    yield p


sg, eg = index(stores), index(eateries)
out = []
for name, lat, lon, k, mu in stations:
    c = [0, 0, 0]
    brands = defaultdict(int)
    for s in around(sg, lat, lon):
        for i, on in enumerate(SLOTS[s[3]]):
            c[i] += on
        brands[s[2]] += 1
    food = sum(1 for _ in around(eg, lat, lon))
    # [チェーン名, 店数, 分類(0=24h 1=late 2=eve)]
    out.append(c + [food, [[n, k, list(SLOTS).index(CLASS[n])] for n, k in sorted(brands.items(), key=lambda b: -b[1])]])

# 区市町村ごとの店数
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


wards = defaultdict(lambda: defaultdict(int))
for lat, lon, name, cls in stores:
    for x0, x1, y0, y1, rings, n in areas:
        if x0 <= lon <= x1 and y0 <= lat <= y1 and any(inside(r, lat, lon) for r in rings):
            wards[n][name] += 1
            break
wards = {n: [[b, k, list(SLOTS).index(CLASS[b])] for b, k in sorted(v.items(), key=lambda x: -x[1])]
         for n, v in wards.items()}

print('[' + ',\n'.join(json.dumps(o, ensure_ascii=False, separators=(',', ':')) for o in out)
      + ',\n' + json.dumps({'_wards': wards}, ensure_ascii=False, separators=(',', ':')) + ']')
