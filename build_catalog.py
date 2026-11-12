from pathlib import Path
import json,re,urllib.parse
HERE=Path(__file__).resolve().parent
SOURCE=HERE.parent/'Apartment-Search-33844-2026-11-12'
OUT=HERE/'dist/data'
base=json.loads((SOURCE/'SCREENED_CANDIDATES.json').read_text())
cat=json.loads((SOURCE/'evidence/original-photo-catalog.json').read_text())
raw={}
for path in sorted((SOURCE/'evidence').glob('homeharvest-*.json')):
 for r in json.loads(path.read_text())['results']:
  key=str(r.get('property_id') or r.get('href'));old=raw.get(key)
  if not old or (r.get('last_update_date') or '',len(r.get('units') or []))>(old.get('last_update_date') or '',len(old.get('units') or [])):raw[key]=r

def ident(url):
 p=urllib.parse.urlsplit(url);return p.netloc+re.sub(r'[sor](?:d-[^.]*)?\.(?:jpg|jpeg|png|webp)$','',p.path,flags=re.I)
def save(p,data):p.write_text(json.dumps(data,ensure_ascii=False,separators=(',',':'))+'\n')
index=[];total=0
for b in base['candidates']:
 x=dict(b);key=x['property_id'];old=raw[key];photos=cat['records'][key].get('photos') or [];mapping={ident(p['href']):p['href'] for p in photos if p.get('href')};images={}
 def add(photo,kind,unit=None):
  u=photo.get('href')
  if not u:return
  k=ident(u)
  if k not in images:
   images[k]={'url':mapping.get(k) or re.sub(r'[so]\.jpg$','r.jpg',u),'title':photo.get('title'),'tags':[],'primary':False,'origins':[],'source_urls':[],'resolution_source':'API size:MAX' if k in mapping else 'MAX convention / supplied original'}
  i=images[k]
  if u not in i['source_urls']:i['source_urls'].append(u)
  i['origins'].append({'kind':kind,**(unit or {})})
  if kind=='primary':i['primary']=True
  for tag in photo.get('tags') or []:
   label=tag.get('label') if isinstance(tag,dict) else tag
   if label and label not in i['tags']:i['tags'].append(label)
 add(old.get('primary_photo') or {},'primary')
 for p in old.get('photos') or []:add(p,'listing')
 for n,u in enumerate(old.get('units') or []):
  d=u.get('description') or {};rent=u.get('list_price');beds=d.get('beds')
  unit={'unit_index':n,'beds':beds,'advertised_rent':rent,'matches_filters':beds in [2,3] and isinstance(rent,(int,float)) and 0<rent<=2300}
  for p in u.get('photos') or []:add(p,'unit_or_floorplan',unit)
 for p in photos:add(p,'api_gallery')
 x['images']=list(images.values());x['photo_count']=len(images);x['cover_url']=next((i['url'] for i in x['images'] if i['primary']),x['images'][0]['url'] if x['images'] else None)
 total+=len(images);save(OUT/'listings'/f'{key}.json',x)
 index.append({k:x[k] for k in ['property_id','name','property_type','address','city','zip','radius_miles','offers','min_rent','url','age_restricted','income_restricted','flags','photo_count','cover_url']})
summary={'listing_count':len(index),'photo_count':total,'research_date':'2026-11-12','max_rent':2300,'radius_miles':20,'center':[28.08616,-81.58717],'distance_type':'straight-line radius, not driving distance','network_policy':'Images load on demand from the original photo CDN; this is not an offline image archive.'}
save(OUT/'index.json',{'summary':summary,'listings':index})
save(OUT/'manifest.json',summary)
print(summary)
