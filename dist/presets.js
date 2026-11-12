'use strict';
(function(root){
const DEFAULT={version:2,name:'My default',query:{location:'33844',radiusMiles:20,minRent:0,maxRent:2300,minBeds:2,maxBeds:3,propertyTypes:[],text:'',sort:'distance'},rules:[]};
const clone=x=>JSON.parse(JSON.stringify(x));
function validate(p,fields){
 const errors=[];const fail=(path,msg)=>errors.push(`${path}: ${msg}`);
 const obj=x=>x&&typeof x==='object'&&!Array.isArray(x);
 const keys=(x,allowed,path)=>{for(const k of Object.keys(x))if(!allowed.includes(k))fail(path+'.'+k,'unsupported property');};
 if(!obj(p))return {valid:false,errors:['Preset must be an object']};
 keys(p,['version','name','query','rules'],'preset');
 if(p.version!==2)fail('version','must be 2');
 if(typeof p.name!=='string'||!p.name.trim()||p.name.length>100)fail('name','must be 1–100 characters');
 const q=p.query;
 if(!obj(q))fail('query','required object');else{
 keys(q,Object.keys(DEFAULT.query),'query');
 if(typeof q.location!=='string'||!q.location.trim()||q.location.length>200)fail('query.location','required, up to 200 characters');
 for(const k of ['radiusMiles','minRent','maxRent','minBeds','maxBeds'])if(!(q[k]===null&&['maxRent','maxBeds'].includes(k))&&(typeof q[k]!=='number'||!Number.isFinite(q[k])||q[k]<0))fail('query.'+k,'must be a nonnegative number (maximums may be null)');
 if(q.radiusMiles===0)fail('query.radiusMiles','must be greater than zero');
 for(const [a,b]of [['minRent','maxRent'],['minBeds','maxBeds']])if(q[b]!==null&&q[a]>q[b])fail('query.'+b,'must be at least '+a);
 for(const k of ['minBeds','maxBeds'])if(q[k]!==null&&!Number.isInteger(q[k]))fail('query.'+k,'must be an integer');
 if(!Array.isArray(q.propertyTypes)||q.propertyTypes.length>50||q.propertyTypes.some(x=>typeof x!=='string'||x.length>100))fail('query.propertyTypes','must be an array of strings');
 if(typeof q.text!=='string'||q.text.length>1000)fail('query.text','must be a string, max 1000 characters');
 if(!['distance','price','space','photos'].includes(q.sort))fail('query.sort','unsupported sort');
 }
 if(!Array.isArray(p.rules)||p.rules.length>100)fail('rules','must be an array of at most 100 rules');else p.rules.forEach((r,i)=>{
 const path=`rules[${i}]`;if(!obj(r)){fail(path,'must be an object');return;}
 keys(r,['field','op','value','mode','allowUnknown','weight','terms','match','caseSensitive','wholeWord','ignoreNegated','negationWindow','excludeTerms'],path);
 if(typeof r.field!=='string'||(fields&&!fields.some(f=>f.key===r.field)))fail(path+'.field','unknown field');
 if(!['require','exclude','prefer'].includes(r.mode))fail(path+'.mode','use require, exclude or prefer');
 const ops=['contains','equals','gte','lte','before','after','known','unknown','mentions'];
 if(!ops.includes(r.op))fail(path+'.op','unsupported operator');
 if(typeof r.allowUnknown!=='boolean')fail(path+'.allowUnknown','must be boolean');
 if(r.weight!==undefined&&(typeof r.weight!=='number'||!Number.isFinite(r.weight)||r.weight<0||r.weight>100))fail(path+'.weight','must be 0–100');
 if(r.op==='mentions'){
 if(r.field!=='description')fail(path+'.field','mentions applies to description');
 for(const k of ['terms','excludeTerms'])if((k==='terms'||r[k]!==undefined)&&(!Array.isArray(r[k])||(k==='terms'&&!r[k].length)||r[k].length>50||r[k].some(t=>typeof t!=='string'||!t.trim()||t.length>200)))fail(path+'.'+k,'use up to 50 nonempty phrases (max 200 characters each)');
 if(!['any','all'].includes(r.match))fail(path+'.match','use any or all');
 for(const k of ['caseSensitive','wholeWord','ignoreNegated'])if(typeof r[k]!=='boolean')fail(path+'.'+k,'must be boolean');
 if(!Number.isInteger(r.negationWindow)||r.negationWindow<0||r.negationWindow>12)fail(path+'.negationWindow','must be integer 0–12');
 }else if(!['known','unknown'].includes(r.op)){
 if(!['string','number','boolean'].includes(typeof r.value)||String(r.value).trim()==='')fail(path+'.value','required scalar value');
 if(['gte','lte'].includes(r.op)&&!Number.isFinite(Number(r.value)))fail(path+'.value','must be numeric');
 if(['before','after'].includes(r.op)&&(!/^\d{4}-\d{2}-\d{2}/.test(String(r.value))||!Number.isFinite(Date.parse(String(r.value)))))fail(path+'.value','use ISO date');
 }
 });
 return {valid:errors.length===0,errors};
}
function mentions(values,r){
 const text=(values||[]).join('\n');const hay=r.caseSensitive?text:text.toLowerCase();
 function hits(term,negation){
 const needle=r.caseSensitive?term:term.toLowerCase();let start=0,result=[];
 while(needle&&(start=hay.indexOf(needle,start))!==-1){const end=start+needle.length;
 const boundary=!r.wholeWord||(!/[\p{L}\p{N}_]/u.test(hay[start-1]||'')&&!/[\p{L}\p{N}_]/u.test(hay[end]||''));
 const prefix=hay.slice(Math.max(0,start-160),start).split(/[.!?;\n]/).pop();
 const words=(prefix.toLowerCase().match(/[\p{L}']+/gu)||[]).slice(-r.negationWindow);
 const negated=negation&&r.ignoreNegated&&r.negationWindow>0&&words.some(w=>['no','not','without','never',"isn't","aren't","doesn't","don't"].includes(w));
 if(boundary&&!negated)result.push({term,snippet:text.slice(Math.max(0,start-65),Math.min(text.length,end+95))});start=end;
 }return result;
 }
 const excluded=(r.excludeTerms||[]).flatMap(t=>hits(t,false));
 const groups=r.terms.map(t=>hits(t,true));
 return {match:!excluded.length&&(r.match==='all'?groups.every(g=>g.length):groups.some(g=>g.length)),evidence:groups.flat().slice(0,10),excluded:excluded.slice(0,5)};
}
function migrate(p){
 if(p.version===2)return clone(p);
 if(p.version!==1||!Array.isArray(p.presets))throw Error('Expected v2 preset, v2 bundle, or legacy v1 preset bundle');
 return p.presets.map(([name,old])=>{const n=clone(DEFAULT),b=old.basic||{};n.name=name;n.query.text=b.search||'';n.query.maxRent=Number(b.max||2300);n.query.sort=b.sort||'distance';if(b.beds)n.query.minBeds=n.query.maxBeds=Number(b.beds);if(b.type)n.query.propertyTypes=b.type==='other'?['multi_family','duplex_triplex']:[b.type];n.rules=(old.rules||[]).map(({id,...r})=>({...r,value:r.value??''}));if(b.city)n.rules.push({field:'city',op:'equals',value:b.city,mode:'require',allowUnknown:false});return n;});
}
root.PresetTools={DEFAULT,clone,validate,mentions,migrate};
})(typeof window!=='undefined'?window:globalThis);
