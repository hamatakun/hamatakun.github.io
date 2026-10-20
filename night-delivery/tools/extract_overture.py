"""Overture Maps の places から関東の範囲だけを取り出す。

使い方: python3 tools/extract_overture.py kanto_places.json
S3 の公開バケットを HTTP の範囲指定で読むので、全体（約11GB）はダウンロードしない。
"""
import sys, re, json, urllib.request
sys.path.insert(0, __import__('os').path.dirname(__import__('os').path.abspath(__file__)))
from httpfile import HTTPRangeFile, CTX
import pyarrow.parquet as pq, pyarrow as pa, pyarrow.compute as pc
BASE='https://overturemaps-us-west-2.s3.us-west-2.amazonaws.com/'
PREFIX='release/2026-09-23.1/theme=places/type=place/'
X0,X1,Y0,Y1=138.35,140.95,34.85,37.25
with urllib.request.urlopen(BASE+'?list-type=2&prefix='+PREFIX, context=CTX) as r:
    keys=re.findall(r'<Key>(.*?)</Key>', r.read().decode())
cols=['id','names','brand','basic_category','taxonomy','operating_status','confidence','bbox']
out=[]
for k in keys:
    f=HTTPRangeFile(BASE+k); pf=pq.ParquetFile(f); md=pf.metadata
    idx={md.schema.column(i).path:i for i in range(md.num_columns)}
    sel=[]
    for g in range(md.num_row_groups):
        rg=md.row_group(g)
        st=lambda p: rg.column(idx[p]).statistics
        if st('bbox.xmin').max < X0 or st('bbox.xmin').min > X1 or st('bbox.ymin').max < Y0 or st('bbox.ymin').min > Y1: continue
        sel.append(g)
    print(k.split('/')[-1][:10], 'row groups', len(sel), flush=True)
    for g in sel:
        t=pf.read_row_group(g, columns=cols)
        x=pc.struct_field(t['bbox'],'xmin'); y=pc.struct_field(t['bbox'],'ymin')
        m=pc.and_(pc.and_(pc.greater_equal(x,X0),pc.less_equal(x,X1)),pc.and_(pc.greater_equal(y,Y0),pc.less_equal(y,Y1)))
        t=t.filter(m)
        if t.num_rows==0: continue
        d=t.to_pylist()
        for r in d:
            out.append({'id':r['id'],'n':(r['names'] or {}).get('primary'),
              'b':((r['brand'] or {}).get('names') or {}).get('primary'),
              'bc':r['basic_category'],'tx':(r['taxonomy'] or {}).get('primary'),
              'h':(r['taxonomy'] or {}).get('hierarchy'),
              'os':r['operating_status'],'cf':r['confidence'],
              'x':r['bbox']['xmin'],'y':r['bbox']['ymin']})
    print('  total so far', len(out), 'MB read', f.bytes_read//1_000_000, flush=True)
json.dump(out, open(sys.argv[1],'w'), ensure_ascii=False)
print('done', len(out))
