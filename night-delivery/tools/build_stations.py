"""関東の駅一覧 stations.json を作る。

使い方:
  curl -o stations_all.json https://raw.githubusercontent.com/piuccio/open-data-jp-railway-stations/master/stations.json
  python3 tools/build_stations.py stations_all.json > stations.json

出力は [駅名, 緯度, 経度, 路線数, 区市町村名] の配列。区市町村は kanto.geojson の境界で判定する。
"""
import json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
PREFS = ('08', '09', '10', '11', '12', '13', '14')
# 改称された駅・同じ駅の別名
RENAME = {'新線新宿': '新宿', '花月園前': '花月総持寺', '仲木戸': '京急東神奈川',
          '南町田': '南町田グランベリーパーク', '産業道路': '大師橋'}
# 簡略化した境界のせいで隣の区市に入ってしまう駅
MUNI_FIX = {'新橋': '港区', '三鷹': '三鷹市', '落合': '新宿区'}
# データに無い新しい駅 [駅名, 緯度, 経度, 路線数]
EXTRA = [['高輪ゲートウェイ', 35.6355, 139.7407, 1]]

geo = json.load(open(os.path.join(HERE, '..', 'kanto.geojson')))
areas = []
for f in geo['features']:
    rings = [p[0] for p in f['geometry']['coordinates']]
    xs = [c[0] for r in rings for c in r]
    ys = [c[1] for r in rings for c in r]
    areas.append((min(xs), max(xs), min(ys), max(ys), rings, f['properties']['n']))


def inside(ring, lat, lng):
    ins = False
    j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i]
        xj, yj = ring[j]
        if (yi > lat) != (yj > lat) and lng < (xj - xi) * (lat - yi) / (yj - yi) + xi:
            ins = not ins
        j = i
    return ins


def muni(lat, lng):
    for x0, x1, y0, y1, rings, n in areas:
        if x0 <= lng <= x1 and y0 <= lat <= y1 and any(inside(r, lat, lng) for r in rings):
            return n
    # 海沿いで境界の外に出た駅は一番近い区市町村へ（約2km以内）
    best = min(((c[0] - lng) ** 2 + (c[1] - lat) ** 2, n)
               for *_, rings, n in areas for r in rings for c in r)
    return best[1] if best[0] < 0.0004 else None


pts = []
for grp in json.load(open(sys.argv[1])):
    for st in grp['stations']:
        if st['prefecture'] in PREFS:
            name = re.sub(r'[〈（(].*?[〉）)]', '', st['name_kanji']).strip()
            name = re.sub(r'駅$', '', name)
            pts.append((RENAME.get(name, name), st['lat'], st['lon'], st['ekidata_line_id']))

# 同じ名前で800m以内のものは1つの駅にまとめる
merged = []
for name, lat, lon, line in pts:
    for m in merged:
        if m['n'] == name and abs(m['lat'] - lat) < 0.008 and abs(m['lon'] - lon) < 0.009:
            m['lines'].add(line)
            m['pts'].append((lat, lon))
            break
    else:
        merged.append({'n': name, 'lat': lat, 'lon': lon, 'lines': {line}, 'pts': [(lat, lon)]})

out = []
for m in merged:
    lat = sum(p[0] for p in m['pts']) / len(m['pts'])
    lon = sum(p[1] for p in m['pts']) / len(m['pts'])
    mu = MUNI_FIX.get(m['n']) or muni(lat, lon)
    if mu:
        out.append([m['n'], round(lat, 5), round(lon, 5), len(m['lines']), mu])
for n, lat, lon, k in EXTRA:
    out.append([n, lat, lon, k, MUNI_FIX.get(n) or muni(lat, lon)])

print('[' + ',\n'.join(json.dumps(o, ensure_ascii=False, separators=(',', ':')) for o in out) + ']')
