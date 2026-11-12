'use strict';
const $ = (id) => document.getElementById(id);
const state = { listings: [], filtered: [], rendered: 0, saved: new Set(), savedOnly: false, detailAbort: null, detailId: null };
const metrics = { requested: 0, loaded: 0, failed: 0, active: 0 };
const queue = [];
const PHOTO_CONCURRENCY = 8;
const LOOKAHEAD_PX = Math.max(1200, Math.min(2400, Math.round(window.innerHeight * 2)));
function imagePriority(img) {
  const dialog = img.closest('dialog');
  if ($('details').open && !dialog) return 100000;
  const bounds = img.closest('.media').getBoundingClientRect();
  const viewport = dialog ? $('detail-scroll').getBoundingClientRect() : {top:0,bottom:innerHeight};
  if (bounds.bottom >= viewport.top && bounds.top <= viewport.bottom) return 0;
  return bounds.top > viewport.bottom ? bounds.top - viewport.bottom : 5000 + viewport.top - bounds.bottom;
}
const money = (n) => new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 }).format(n);
const number = (n) => new Intl.NumberFormat('en-US').format(n);
const typeLabel = { apartment: 'Apartment', townhomes: 'Townhome', condos: 'Condo', multi_family: 'Multifamily', duplex_triplex: 'Duplex / triplex' };
const element = (tag, className, text) => { const el = document.createElement(tag); if (className) el.className = className; if (text !== undefined) el.textContent = text; return el; };
const safeUrl = (value) => { try { const u = new URL(value); return u.protocol === 'https:' ? u.href : null; } catch { return null; } };
const imageUrl = (value) => { const u = safeUrl(value); return u && ['ap.rdcpix.com', 'ar.rdcpix.com'].includes(new URL(u).hostname) ? u : null; };
function updateNetwork() { $('network-count').textContent = `${number(metrics.loaded)} photos loaded on demand${metrics.failed ? ` · ${metrics.failed} failed attempts` : ''}`; }
function isVisibleContext(img) { const d = img.closest('dialog'); return img.isConnected && (!d || d.open); }
function pump() {
  queue.sort((a,b) => imagePriority(a) - imagePriority(b));
  while (metrics.active < PHOTO_CONCURRENCY && queue.length) {
    const img = queue.shift();
    if (!isVisibleContext(img) || img.dataset.stage === 'loaded') { img.dataset.stage = 'idle'; continue; }
    const media = img.closest('.media');
    metrics.active++; metrics.requested++; img.dataset.stage = 'loading';
    media.classList.remove('failed'); media.querySelector('.image-retry')?.remove();
    let done = false;
    const finish = (ok) => {
      if (done) return; done = true; clearTimeout(timer); metrics.active--;
      img.onload = null; img.onerror = null;
      if (ok) { img.dataset.stage = 'loaded'; media.classList.add('loaded'); metrics.loaded++; }
      else {
        img.dataset.stage = 'error'; img.removeAttribute('src'); media.classList.add('failed'); metrics.failed++;
        const retry = element('button', 'image-retry', 'Retry photo'); retry.type = 'button'; retry.setAttribute('aria-label', `Retry photo: ${img.alt}`);
        retry.addEventListener('click', (e) => { e.stopPropagation(); enqueue(img); }); media.append(retry);
      }
      updateNetwork(); pump();
    };
    const timer = setTimeout(() => finish(false), 25000);
    img.onload = () => finish(img.naturalWidth > 0); img.onerror = () => finish(false);
    img.fetchPriority = imagePriority(img) === 0 ? 'high' : 'low';
    img.src = img.dataset.originalUrl;
  }
}
function enqueue(img) {
  if (['loading', 'queued', 'loaded'].includes(img.dataset.stage)) return;
  img.dataset.stage = 'queued'; queue.push(img); pump();
}
function makeObserver(root = null) {
  if (!('IntersectionObserver' in window)) return { observe: (media) => { const img=media.querySelector('img'); if(img)enqueue(img); }, unobserve() {}, disconnect() {} };
  return new IntersectionObserver((entries, obs) => {
    for (const entry of entries) if (entry.isIntersecting) {
      const img = entry.target.querySelector('img[data-original-url]');
      obs.unobserve(entry.target); if (img) enqueue(img);
    }
  }, { root, rootMargin: `200px 0px ${LOOKAHEAD_PX}px 0px`, threshold: 0.01 });
}

const cardObserver = makeObserver();
let detailObserver = makeObserver($('detail-scroll'));
function makeMedia(url, alt, observer, action = null) {
  const media = element('div', 'media');
  const placeholder = element('div', 'image-placeholder', url ? 'Photo loads as you browse' : 'No source photos'); media.append(placeholder);
  const valid = imageUrl(url);
  if (valid) {
    const img = document.createElement('img'); img.alt = alt; img.decoding = 'async'; img.loading = 'eager'; img.referrerPolicy = 'no-referrer'; img.dataset.originalUrl = valid; img.dataset.stage = 'idle';
    if (action) { const button = element('button', 'image-link'); button.type = 'button'; button.setAttribute('aria-label', `View photos for ${alt}`); button.append(img); button.addEventListener('click', action); media.append(button); }
    else media.append(img);
    requestAnimationFrame(() => { if (img.isConnected) observer.observe(media); });
  } else if (action) { const button = element('button', 'image-link'); button.type = 'button'; button.setAttribute('aria-label', `View details for ${alt}`); button.addEventListener('click', action); media.append(button); }
  return media;
}
function eligibleOffers(listing) { return listing.offers.filter(AdvancedFilters.offerMatches); }
function pickOffer(listing) { return [...eligibleOffers(listing)].sort(AdvancedFilters.query.sort === 'space' ? (a,b) => (b.sqft || 0) - (a.sqft || 0) || a.rent - b.rent : (a,b) => a.rent - b.rent)[0]; }
function updateSaved() { $('saved-count').textContent = state.saved.size; $('shortlist-filter').setAttribute('aria-pressed', String(state.savedOnly)); }
function card(listing) {
  const article = element('article', 'card'); article.dataset.propertyId = listing.property_id;
  const open = () => openDetails(listing);
  const media = makeMedia(listing.cover_url, listing.name, cardObserver, open);
  media.append(element('span', 'photo-badge', `${number(listing.photo_count)} photos`));
  const save = element('button', `save-button${state.saved.has(listing.property_id) ? ' saved' : ''}`, state.saved.has(listing.property_id) ? '♥' : '♡'); save.type = 'button';
  save.setAttribute('aria-label', `Shortlist ${listing.name}`); save.setAttribute('aria-pressed', String(state.saved.has(listing.property_id)));
  save.addEventListener('click', () => {
    if (state.saved.has(listing.property_id)) state.saved.delete(listing.property_id); else state.saved.add(listing.property_id);
    updateSaved(); if (state.savedOnly) applyFilters(); else { save.classList.toggle('saved', state.saved.has(listing.property_id)); save.textContent = state.saved.has(listing.property_id) ? '♥' : '♡'; save.setAttribute('aria-pressed', String(state.saved.has(listing.property_id))); }
  }); media.append(save); article.append(media);
  const body = element('div', 'card-body'); const meta = element('div', 'card-meta'); meta.append(element('span', '', listing.city || 'Location withheld'), element('span', '', `${listing.radius_miles.toFixed(1)} mi radius`)); body.append(meta);
  const h3 = element('h3'); const title = element('button', 'title-button', listing.name); title.type = 'button'; title.title = listing.name; title.addEventListener('click', open); h3.append(title); body.append(h3);
  body.append(element('p', 'card-address', listing.address || 'Street address withheld'));
  const offer = pickOffer(listing); const row = element('div', 'card-price'); const price = element('div', 'price', money(offer.rent)); price.append(element('small', '', ' / mo'));
  const specs = element('div', 'specs'); specs.append(element('div', '', `${offer.beds} bed${offer.baths ? ` · ${offer.baths} bath` : ''}`), element('div', '', offer.sqft ? `${number(offer.sqft)} sq ft` : 'Area not supplied')); row.append(price, specs); body.append(row, element('div', 'price-note', 'Advertised price · fees may be additional'));
  const bottom = element('div', 'card-bottom'); const eligibility = listing.age_restricted ? 'Age eligibility applies' : listing.income_restricted ? 'Check income eligibility' : (typeLabel[listing.property_type] || listing.property_type);
  bottom.append(element('span', listing.age_restricted || listing.income_restricted ? 'warn' : '', eligibility)); const view = element('button', 'view-button', 'Explore →'); view.type = 'button'; view.addEventListener('click', open); bottom.append(view); body.append(bottom); article.append(body); return article;
}
function renderMore() {
  const batch = state.filtered.slice(state.rendered, state.rendered + 24); const fragment = document.createDocumentFragment(); batch.forEach(l => fragment.append(card(l))); $('grid').append(fragment); state.rendered += batch.length;
  $('load-more').hidden = state.rendered >= state.filtered.length;
  $('render-count').textContent = state.filtered.length ? `Showing ${number(state.rendered)} of ${number(state.filtered.length)} records` : '';
}
function applyFilters() {
  state.filtered = state.listings.filter(l => (!state.savedOnly || state.saved.has(l.property_id)) && AdvancedFilters.matches(l));
  state.filtered.sort((a,b) => AdvancedFilters.evaluate(b,eligibleOffers(b)).score - AdvancedFilters.evaluate(a,eligibleOffers(a)).score || AdvancedFilters.sortValue(a,b));
  cardObserver.disconnect(); $('grid').replaceChildren(); state.rendered = 0;
  $('result-count').textContent = number(state.filtered.length);
  $('result-note').textContent = (state.savedOnly ? 'Session shortlist' : 'Source-reported listings') + (AdvancedFilters.rules.some(r=>r.mode==='prefer') ? ' · preferred matches first' : '');
  $('empty').hidden = state.filtered.length > 0; renderMore();
}
function clearDetail() { state.detailAbort?.abort(); detailObserver.disconnect(); state.detailId = null; $('detail-content').replaceChildren(); document.body.style.overflow = ''; }
function caption(image, index) {
  const unit = image.origins.find(o => o.kind === 'unit_or_floorplan');
  if (unit) return `${unit.beds || '?'}BR floor-plan / unit image · may depict a different unit`;
  return image.title || image.tags.slice(0,2).map(t => t.replaceAll('_',' ')).join(' · ') || `Property photo ${index + 1}`;
}
async function openDetails(listing) {
  state.detailAbort?.abort(); state.detailAbort = new AbortController(); state.detailId = listing.property_id; detailObserver.disconnect(); detailObserver = makeObserver($('detail-scroll'));
  const target = $('detail-content'); target.replaceChildren(element('p', 'detail-loading', 'Opening the photo catalog…'));
  if (!$('details').open) $('details').showModal(); document.body.style.overflow = 'hidden'; $('detail-scroll').scrollTop = 0;
  try {
    const response = await fetch(`data/listings/${encodeURIComponent(listing.property_id)}.json`, { signal: state.detailAbort.signal }); if (!response.ok) throw new Error(`Catalog request failed (${response.status})`);
    const data = await response.json(); if (state.detailId !== listing.property_id) return;
    target.replaceChildren(); const header = element('div', 'detail-heading'); const names = element('div'); names.append(element('p','eyebrow',`${typeLabel[data.property_type] || data.property_type} · ${data.radius_miles.toFixed(1)} mi radius`));
    const h2 = element('h2','',data.name); h2.id = 'detail-title'; names.append(h2,element('p','',`${data.address || 'Address withheld'}, ${data.city}, ${data.zip}`)); header.append(names);
    if (safeUrl(data.url)) { const link = element('a','source-link','View source listing ↗'); link.href = safeUrl(data.url); link.target = '_blank'; link.rel = 'noopener noreferrer'; header.append(link); } target.append(header);
    target.append(element('div','detail-note','Original-resolution photos preload ahead of your scroll. Community, model-unit and floor-plan photos may not depict the exact unit offered. Prices, fees and availability require confirmation.'));
    if (data.flags.length) target.append(element('div','detail-note',data.flags.join(' · ')));
    const offers = element('div','offer-list'); const unique = new Set();
    for (const o of data.offers) { const key = [o.beds,o.baths,o.rent,o.sqft].join('|'); if (unique.has(key)) continue; unique.add(key); const offer = element('div','offer',`${o.beds} bed${o.baths ? ` · ${o.baths} bath` : ''}`); offer.append(element('strong','',money(o.rent)),element('small','',`${o.sqft ? number(o.sqft) + ' sq ft' : 'Area unknown'} · advertised / mo`)); offers.append(offer); } target.append(offers);
    const features = element('div','detail-features'); data.details.slice(0,16).forEach(t => features.append(element('span','feature',t))); target.append(features);
    if (window.nearby && AdvancedFilters.rules.length) {
      const explanation=window.nearby.explain(listing.property_id);
      const evidence=element('details','detail-description');evidence.append(element('summary','',`Why this listing matches · preference score ${explanation.score}`));
      for (const r of explanation.rules) {
        evidence.append(element('p','',`${r.rule.mode}: ${r.rule.field} · ${r.known ? (r.matched ? 'matched' : 'not matched') : 'unknown'}`));
        for (const e of [...(r.evidence||[]),...(r.excluded||[])]) evidence.append(element('blockquote','',e.snippet));
      }
      evidence.append(element('p','','Description evidence is source text, not confirmation of an amenity.'));target.append(evidence);
    }
    if (data.description) { const disclosure = element('details','detail-description'); disclosure.append(element('summary','','Read the source description'),element('p','',data.description)); target.append(disclosure); }
    const photoHeader = element('div','photo-heading'); photoHeader.append(element('h3','',`The full picture · ${number(data.images.length)} photos`),element('span','','Two screens ahead · no full-library preload')); target.append(photoHeader);
    const gallery = element('div','photo-grid'); data.images.forEach((image,index) => {
      const figure = element('figure','photo-figure'); figure.append(makeMedia(image.url,`${data.name}: ${caption(image,index)}`,detailObserver));
      const cap = element('figcaption'); cap.append(element('span','',caption(image,index)));
      if (imageUrl(image.url)) { const a = element('a','','Open original ↗'); a.href = image.url; a.target = '_blank'; a.rel = 'noopener noreferrer'; cap.append(a); } figure.append(cap); gallery.append(figure);
    }); target.append(gallery); if (!data.images.length) target.append(element('p','empty','No photos were supplied for this listing.'));
  } catch (error) { if (error.name === 'AbortError') return; target.replaceChildren(element('p','detail-loading',`Could not load this listing. ${error.message}`)); }
}
$('close-detail').addEventListener('click', () => $('details').close()); $('details').addEventListener('close', clearDetail);
$('details').addEventListener('click', (e) => { if (e.target === $('details')) { const r = $('details').getBoundingClientRect(); if (e.clientX < r.left || e.clientX > r.right || e.clientY < r.top || e.clientY > r.bottom) $('details').close(); } });
$('shortlist-filter').addEventListener('click', () => { state.savedOnly=!state.savedOnly; updateSaved(); applyFilters(); }); $('load-more').addEventListener('click',renderMore);
if ('IntersectionObserver' in window) new IntersectionObserver(entries => { if (entries.some(e => e.isIntersecting) && state.rendered < state.filtered.length) renderMore(); }, { rootMargin:`0px 0px ${LOOKAHEAD_PX}px 0px` }).observe($('sentinel'));
Object.defineProperty(window,'galleryStats',{get:() => ({...metrics,lookaheadPx:LOOKAHEAD_PX,maxConcurrent:PHOTO_CONCURRENCY,queued:queue.length,totalListings:state.listings.length,matchingListings:state.filtered.length,renderedCards:state.rendered,detailId:state.detailId})});
async function init() {
  try {
    const response = await fetch('data/index.json'); if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const catalog = await response.json(); state.listings = catalog.listings;
    await AdvancedFilters.init(applyFilters,()=>state.listings);
  } catch (error) {
    $('result-note').textContent='Catalog unavailable'; $('error').hidden=false;
    $('error').textContent=`Could not initialize the explorer. Start the included server. ${error.message}`;
    $('workspace-status').textContent='Initialization failed';
  }
}
if (matchMedia('(max-width: 760px)').matches) $('workspace').open=false;
init();

// Purely additive: a small set of already-tested rendering utilities,
// exposed for live.js (Phase C's live-search panel) to reuse rather than
// duplicate. Nothing above this line changes; existing behavior/tests are
// unaffected by this export existing.
window.AppShared = Object.freeze({ element, money, number, typeLabel, safeUrl, imageUrl, makeMedia, makeObserver, caption });
