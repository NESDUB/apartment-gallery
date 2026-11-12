'use strict';
(function(root){
  const norm=v=>String(v).toLowerCase().trim();
  function test(values,rule){
    const known=Array.isArray(values)&&values.length>0;
    if(rule.op==='known')return known;
    if(rule.op==='unknown')return !known;
    if(!known)return false;
    if(rule.op==='mentions')return root.PresetTools.mentions(values,rule).match;
    return values.some(v=>{
      if(rule.op==='contains')return norm(v).includes(norm(rule.value));
      if(rule.op==='equals')return norm(v)===norm(rule.value);
      if(rule.op==='gte'||rule.op==='lte'){
        const a=Number(v),b=Number(rule.value);
        return String(v).trim()!==''&&String(rule.value).trim()!==''&&Number.isFinite(a)&&Number.isFinite(b)&&(rule.op==='gte'?a>=b:a<=b);
      }
      if(rule.op==='before'||rule.op==='after'){
        const a=Date.parse(v),b=Date.parse(rule.value);
        return Number.isFinite(a)&&Number.isFinite(b)&&(rule.op==='before'?a<=b:a>=b);
      }
      return false;
    });
  }
  function passes(values,r){
    if((!values||!values.length)&&!['known','unknown'].includes(r.op))return !!r.allowUnknown;
    const result=test(values,r);return r.mode==='exclude'?!result:result;
  }
  function evaluate(record,rules,offers){
    rules=rules.filter(r=>['known','unknown','mentions'].includes(r.op)||String(r.value??'').trim()!=='');
    const fields=record?.fields||{};
    const hard=rules.filter(r=>r.mode!=='prefer');
    if(!hard.filter(r=>!r.field.startsWith('Offer / ')).every(r=>passes(fields[r.field],r)))return {match:false,score:0};
    const unitRules=hard.filter(r=>r.field.startsWith('Offer / '));
    const matching=(offers||record?.offers||[]).filter(o=>unitRules.every(r=>passes(o[r.field],r)));
    if(unitRules.length&&!matching.length)return {match:false,score:0};
    const preferred=rules.filter(r=>r.mode==='prefer');
    const base=preferred.filter(r=>!r.field.startsWith('Offer / ')).reduce((s,r)=>s+Number(test(fields[r.field],r))*(r.weight??1),0);
    const score=base+Math.max(0,...matching.map(o=>preferred.filter(r=>r.field.startsWith('Offer / ')).reduce((s,r)=>s+Number(test(o[r.field],r))*(r.weight??1),0)));
    return {match:true,score};
  }
  root.FilterEngine={test,passes,evaluate};
  if(typeof module!=='undefined')module.exports=root.FilterEngine;
})(typeof window!=='undefined'?window:globalThis);
