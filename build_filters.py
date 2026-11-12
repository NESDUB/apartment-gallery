"""Build a searchable field index without fetching any remote data."""
import json, re
from pathlib import Path
from collections import defaultdict
ROOT=Path(__file__).resolve().parent
OUT=ROOT/'dist/data'
records={}; values=defaultdict(set); counts=defaultdict(int)
def flatten(obj,path='',out=None):
    if out is None: out={}
    if isinstance(obj,dict):
        for k,v in obj.items():
            if k not in {'images','photos','primary_photo','advertisers'}: flatten(v,f'{path} / {k}' if path else k,out)
    elif isinstance(obj,list):
        for v in obj:flatten(v,path,out)
    elif obj is not None and str(obj).strip():out.setdefault(path,[]).append(obj)
    return out
raw={}
source=ROOT.parent/'Apartment-Search-33844-2026-11-12/evidence'
for file in sorted(source.glob('homeharvest-*.json')):
    for r in json.loads(file.read_text()).get('results',[]):
        key=str(r.get('property_id'))
        if key not in raw or str(r.get('last_update_date') or '')>str(raw[key].get('last_update_date') or ''):raw[key]=r
for file in (OUT/'listings').glob('*.json'):
    d=json.loads(file.read_text());key=str(d['property_id'])
    rec=flatten({k:v for k,v in d.items() if k not in {'offers','details','images','age_restricted','income_restricted'}})
    # Detection flags are not evidence of explicit absence: retain positives only.
    for k in ['age_restricted','income_restricted']:
        if d.get(k):rec[k]=[True]
    for line in d.get('details',[]):
        if ': ' in line:
            k,v=line.split(': ',1);v=v.strip()
            if re.fullmatch(r'-?\d+(\.\d+)?',v):v=float(v)
            rec.setdefault('Features / '+k,[]).append(v)
        else:rec.setdefault('Features / Listed amenities',[]).append(line)
    r=raw.get(key,{})
    for group in r.get('details') or []:
        for line in group.get('text') or []:rec.setdefault('Source categories / '+str(group.get('category','Other')),[]).append(line)
    # Include remaining source metadata, but preserve offers separately for same-unit matching.
    source_fields=flatten({k:v for k,v in r.items() if k not in {'details','units','description','photos','primary_photo','advertisers'}},'Source')
    rec.update(source_fields)
    offers=[flatten(o,'Offer') for o in d.get('offers',[])]
    records[key]={'fields':rec,'offers':offers}
    combined={k:list(v) for k,v in rec.items()}
    for offer in offers:
        for k,v in offer.items():combined.setdefault(k,[]).extend(v)
    for k,vs in combined.items():
        counts[k]+=1
        for v in vs:values[k].add(json.dumps(v,ensure_ascii=False))
fields=[]
for k in sorted(values):
    vs=[json.loads(v) for v in sorted(values[k])]
    kind='number' if all(isinstance(v,(int,float)) and not isinstance(v,bool) for v in vs) else 'boolean' if all(isinstance(v,bool) for v in vs) else 'date' if all(isinstance(v,str) and re.match(r'^\d{4}-\d\d-\d\d',v) for v in vs) else 'text'
    fields.append({'key':k,'type':kind,'count':counts[k],'values':vs[:150] if all(len(str(v))<180 for v in vs) else []})
(OUT/'filters.json').write_text(json.dumps({'fields':fields,'records':records},ensure_ascii=False,separators=(',',':')))
print(f'{len(fields)} filterable fields; {len(records)} records')
