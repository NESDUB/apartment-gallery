'use strict';
// Phase C: the live-search panel. Deliberately independent of
// AdvancedFilters/FilterEngine/PresetTools — those stay snapshot-only.
// Live search supports the core query (location, radius, beds, rent) that
// the backend already filters server-side; it does not run the 370-field
// rule engine or description-mention matching against live records. That
// scope boundary is stated in the panel's own help text, not hidden.
window.LiveSearch = (() => {
  const $ = (id) => document.getElementById(id);
  const { element, money, number, typeLabel, safeUrl, makeMedia, makeObserver, caption } = window.AppShared;

  const state = { searchId: null, records: [], state: null, rendered: 0 };
  const liveObserver = makeObserver();
  let detailObserver = makeObserver($('detail-scroll'));

  const STATE_LABELS = {
    resolving: 'Resolving location…',
    fetching: 'Checking more source listings…',
    more_available: 'More source listings may be available.',
    complete: 'Checked every available source listing for this search.',
    limited: 'Stopped early at a safety limit — more may exist. Check for more to continue.',
    rate_limited: 'The source rate-limited this search. Try again later.',
    failed: 'The search failed.',
    canceled: 'Search canceled.',
  };

  function lifecycleText(snapshot) {
    const base = STATE_LABELS[snapshot.state] || snapshot.state;
    const scope = snapshot.geo?.resolved_text ? ` · resolved to ${snapshot.geo.resolved_text}` : '';
    const checked = ` · ${number(snapshot.raw_checked_count)} source record(s) checked`;
    const errors = snapshot.errors.length ? ` · ${snapshot.errors[snapshot.errors.length - 1].message}` : '';
    return base + scope + checked + errors;
  }

  async function api(path, options) {
    const response = await fetch(path, options);
    const body = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(body.message || `Request failed (${response.status})`);
    return body;
  }

  function eligibleOffers(record) { return record.offers; } // already server-filtered to the query's beds/rent
  function pickOffer(record) { return [...record.offers].sort((a, b) => a.rent - b.rent)[0]; }

  function card(record) {
    const article = element('article', 'card');
    article.dataset.propertyId = record.property_id;
    const open = () => openDetails(record);
    const media = makeMedia(record.cover_url, record.name, liveObserver, open);
    media.append(element('span', 'photo-badge', `${number(record.photo_count)} photos`));
    article.append(media);
    const body = element('div', 'card-body');
    const meta = element('div', 'card-meta');
    meta.append(
      element('span', '', record.city || 'Location withheld'),
      element('span', '', record.radius_miles != null ? `${record.radius_miles.toFixed(1)} mi radius` : ''),
    );
    body.append(meta);
    const h3 = element('h3');
    const title = element('button', 'title-button', record.name);
    title.type = 'button'; title.title = record.name; title.addEventListener('click', open);
    h3.append(title); body.append(h3);
    body.append(element('p', 'card-address', record.address || 'Street address withheld'));
    const offer = pickOffer(record);
    const row = element('div', 'card-price');
    const price = element('div', 'price', money(offer.rent));
    price.append(element('small', '', ' / mo'));
    const specs = element('div', 'specs');
    specs.append(
      element('div', '', `${offer.beds} bed${offer.baths ? ` · ${offer.baths} bath` : ''}`),
      element('div', '', offer.sqft ? `${number(offer.sqft)} sq ft` : 'Area not supplied'),
    );
    row.append(price, specs);
    body.append(row, element('div', 'price-note', 'Advertised price · fees may be additional · live source'));
    const bottom = element('div', 'card-bottom');
    const eligibility = record.age_restricted ? 'Age eligibility applies' : record.income_restricted ? 'Check income eligibility' : (typeLabel[record.property_type] || record.property_type);
    bottom.append(element('span', record.age_restricted || record.income_restricted ? 'warn' : '', eligibility));
    const view = element('button', 'view-button', 'Explore →');
    view.type = 'button'; view.addEventListener('click', open);
    bottom.append(view);
    body.append(bottom);
    article.append(body);
    return article;
  }

  function renderAll() {
    liveObserver.disconnect();
    $('live-grid').replaceChildren();
    state.rendered = 0;
    renderMore();
    $('live-result-count').textContent = number(state.records.length);
    const finished = ['complete', 'limited', 'rate_limited', 'failed'].includes(state.state);
    $('live-empty').hidden = state.records.length > 0 || !finished;
    if (!$('live-empty').hidden) {
      const p = $('live-empty').querySelector('p');
      p.textContent = state.state === 'complete'
        ? 'Checked every available source listing for this search — none qualified.'
        : 'Search stopped (' + (STATE_LABELS[state.state] || state.state) + ') before finding any qualifying listing. More may exist.';
    }
  }

  function renderMore() {
    const batch = state.records.slice(state.rendered, state.rendered + 24);
    const fragment = document.createDocumentFragment();
    batch.forEach((r) => fragment.append(card(r)));
    $('live-grid').append(fragment);
    state.rendered += batch.length;
  }

  function clearDetail() {
    detailObserver.disconnect();
    state.detailId = null;
    // Content/overflow cleanup is already handled by app.js's own
    // close-event listener on this shared dialog; this listener only
    // needs to release live.js's own observer and detail-race guard.
  }

  async function openDetails(record) {
    state.detailId = record.property_id;
    detailObserver.disconnect();
    detailObserver = makeObserver($('detail-scroll'));
    const target = $('detail-content');
    target.replaceChildren(element('p', 'detail-loading', 'Loading the photo catalog…'));
    if (!$('details').open) $('details').showModal();
    document.body.style.overflow = 'hidden';
    $('detail-scroll').scrollTop = 0;

    target.replaceChildren();
    const header = element('div', 'detail-heading');
    const names = element('div');
    names.append(element('p', 'eyebrow', `${typeLabel[record.property_type] || record.property_type} · ${record.radius_miles != null ? record.radius_miles.toFixed(1) + ' mi radius' : 'distance unknown'} · LIVE SOURCE`));
    const h2 = element('h2', '', record.name); h2.id = 'detail-title';
    names.append(h2, element('p', '', `${record.address || 'Address withheld'}, ${record.city || ''} ${record.zip || ''}`));
    header.append(names);
    if (safeUrl(record.url)) {
      const link = element('a', 'source-link', 'View source listing ↗');
      link.href = safeUrl(record.url); link.target = '_blank'; link.rel = 'noopener noreferrer';
      header.append(link);
    }
    target.append(header);
    target.append(element('div', 'detail-note', 'Fetched live, just now — not the saved snapshot. Prices, fees and availability require confirmation.'));
    if (record.flags.length) target.append(element('div', 'detail-note', record.flags.join(' · ')));

    const offers = element('div', 'offer-list');
    for (const o of record.offers) {
      const offer = element('div', 'offer', `${o.beds} bed${o.baths ? ` · ${o.baths} bath` : ''}`);
      offer.append(element('strong', '', money(o.rent)), element('small', '', `${o.sqft ? number(o.sqft) + ' sq ft' : 'Area unknown'} · advertised / mo`));
      offers.append(offer);
    }
    target.append(offers);

    if (record.details.length) {
      const features = element('div', 'detail-features');
      record.details.slice(0, 16).forEach((t) => features.append(element('span', 'feature', t)));
      target.append(features);
    }

    if (record.description) {
      const disclosure = element('details', 'detail-description');
      disclosure.append(element('summary', '', 'Read the source description'), element('p', '', record.description));
      target.append(disclosure);
    }

    const photoHeader = element('div', 'photo-heading');
    photoHeader.append(element('h3', '', 'The full picture'), element('span', '', 'Loading photo list…'));
    target.append(photoHeader);
    const gallery = element('div', 'photo-grid');
    target.append(gallery);

    try {
      const { photos } = await api(`/api/live/${encodeURIComponent(state.searchId)}/photos/${encodeURIComponent(record.property_id)}`);
      if (state.detailId !== record.property_id) return; // a later open() superseded this one
      photoHeader.querySelector('h3').textContent = `The full picture · ${number(photos.length)} photos`;
      photoHeader.querySelector('span').textContent = 'Two screens ahead · no full-library preload';
      photos.forEach((image, index) => {
        const alt = `${record.name}: ${caption({ origins: [], title: image.title, tags: image.tags || [] }, index)}`;
        const figure = element('figure', 'photo-figure');
        figure.append(makeMedia(image.url, alt, detailObserver));
        const cap = element('figcaption');
        cap.append(element('span', '', image.title || (image.tags || []).slice(0, 2).join(' · ') || `Property photo ${index + 1}`));
        if (safeUrl(image.url)) {
          const a = element('a', '', 'Open original ↗');
          a.href = image.url; a.target = '_blank'; a.rel = 'noopener noreferrer';
          cap.append(a);
        }
        figure.append(cap);
        gallery.append(figure);
      });
      if (!photos.length) gallery.append(element('p', 'empty', 'No photos were supplied for this listing.'));
    } catch (error) {
      photoHeader.querySelector('span').textContent = 'Could not load photos.';
      gallery.append(element('p', 'empty', `Photo list failed to load: ${error.message}`));
    }
  }

  function readQuery() {
    return {
      location: $('live-location').value.trim(),
      radiusMiles: Number($('live-radius').value),
      minRent: Number($('live-minRent').value || 0),
      maxRent: $('live-maxRent').value === '' ? null : Number($('live-maxRent').value),
      minBeds: Number($('live-minBeds').value),
      maxBeds: $('live-maxBeds').value === '' ? null : Number($('live-maxBeds').value),
    };
  }

  function applySnapshot(snapshot) {
    state.searchId = snapshot.search_id;
    state.state = snapshot.state;
    state.records = snapshot.matched_records;
    $('live-lifecycle').textContent = lifecycleText(snapshot);
    $('live-error').hidden = snapshot.state !== 'failed' && snapshot.state !== 'rate_limited';
    if (!$('live-error').hidden) $('live-error').textContent = snapshot.errors.map((e) => e.message).join(' · ') || 'Search failed.';
    $('live-more').hidden = !['more_available', 'limited'].includes(snapshot.state);
    $('live-cancel').hidden = !['resolving', 'fetching', 'more_available'].includes(snapshot.state);
    $('live-results').hidden = false;
    $('live-scope-label').textContent = snapshot.geo ? `${snapshot.geo.resolved_text} · live source` : '';
    renderAll();
  }

  async function start() {
    const query = readQuery();
    if (!query.location) { $('live-lifecycle').textContent = 'Enter a location first.'; return; }
    $('live-start').disabled = true;
    $('live-lifecycle').textContent = 'Starting live search…';
    try {
      const snapshot = await api('/api/live', { method: 'POST', body: JSON.stringify(query) });
      applySnapshot(snapshot);
    } catch (error) {
      $('live-lifecycle').textContent = `Could not start live search: ${error.message}`;
      $('live-error').hidden = false;
      $('live-error').textContent = error.message;
    } finally {
      $('live-start').disabled = false;
    }
  }

  async function more() {
    if (!state.searchId) return;
    $('live-more').disabled = true;
    try {
      const snapshot = await api(`/api/live/${encodeURIComponent(state.searchId)}/step`, { method: 'POST' });
      applySnapshot(snapshot);
    } catch (error) {
      $('live-lifecycle').textContent = `Could not check for more: ${error.message}`;
    } finally {
      $('live-more').disabled = false;
    }
  }

  async function cancel() {
    if (!state.searchId) return;
    try {
      const snapshot = await api(`/api/live/${encodeURIComponent(state.searchId)}/cancel`, { method: 'POST' });
      applySnapshot(snapshot);
    } catch (error) {
      $('live-lifecycle').textContent = `Could not cancel: ${error.message}`;
    }
  }

  function init() {
    $('live-start').addEventListener('click', start);
    $('live-more').addEventListener('click', more);
    $('live-cancel').addEventListener('click', cancel);
    $('details').addEventListener('close', clearDetail);
  }

  return { init };
})();
window.LiveSearch.init();
