/* The pack overview ("팩 구성") and the rate changer. Both draw the same kind of line chart:
   where each difficulty sits on the dan ladder. */
'use strict';
(function () {
  const M = window.MPC, S = M.S, $ = M.$, el = M.el;
  const GREEK = ['alpha', 'beta', 'gamma', 'delta', 'epsilon', 'zeta', 'eta', 'theta', 'iota', 'kappa'];
  const SVG = 'http://www.w3.org/2000/svg';
  const clamp = (v, a, b) => Math.min(b, Math.max(a, v));

  function svg(tag, attrs, text) {
    const n = document.createElementNS(SVG, tag);
    for (const k in attrs) n.setAttribute(k, attrs[k]);
    if (text != null) n.textContent = text;
    return n;
  }

  /* The name of a whole dan level on its ladder (4K rice: 1-10 then alpha..kappa; LN: numbers). */
  function levelLabel(level, family, keys) {
    if (keys === 7) return level < 0 ? '' : level <= 10 ? String(level) : ['gamma', 'azimuth', 'zenith', 'stellium'][Math.min(level, 14) - 11];
    if (keys === 6) return level < 0 ? '' : level <= 9 ? String(level) : ['terra', 'celestial', 'mystery', 'nihility', 'finish'][Math.min(level, 14) - 10];
    if (level < 1) return '';
    if (family === 'ln') return String(Math.min(level, 17));
    return level <= 10 ? String(level) : GREEK[Math.min(level, 20) - 11];
  }

  /* points: [{slot, y, main, out, title, data}]   slots: number of positions on the x axis
     xLabel(slot) -> text under the axis.  onPick(point, circle) on click / Enter. */
  function lineChart(host, o) {
    host.textContent = '';
    const W = Math.max(360, host.clientWidth || 600), H = o.height || 250;
    const padL = 66, padR = 20, padT = 14, padB = 30;
    const ys = o.points.map(p => p.y);
    if (!ys.length) return;
    let lo = Math.floor(Math.min(...ys) - 0.5), hi = Math.ceil(Math.max(...ys) + 0.5);
    if (hi - lo < 2) { lo -= 1; hi += 1; }
    const X = i => padL + (o.slots <= 1 ? (W - padL - padR) / 2 : (W - padL - padR) * i / (o.slots - 1));
    const Y = v => padT + (H - padT - padB) * (1 - (v - lo) / (hi - lo));
    const root = svg('svg', { viewBox: '0 0 ' + W + ' ' + H, width: W, height: H, role: 'img', 'aria-label': o.label || '난이도 그래프' });
    if (o.median != null) {
      const top = Y(Math.min(hi, o.median + 1)), bottom = Y(Math.max(lo, o.median - 1));
      root.append(svg('rect', { x: padL, y: top, width: W - padL - padR, height: bottom - top, class: 'c-band' }));
    }
    const every = Math.max(1, Math.ceil((hi - lo) / 9));
    for (let level = lo; level <= hi; level++) {
      const y = Y(level);
      root.append(svg('line', { x1: padL, x2: W - padR, y1: y, y2: y, class: 'c-grid' }));
      if ((level - lo) % every === 0) root.append(svg('text', { x: padL - 10, y: y + 4, class: 'c-ylabel' }, levelLabel(level, o.family, o.keys)));
    }
    if (o.median != null) root.append(svg('line', { x1: padL, x2: W - padR, y1: Y(o.median), y2: Y(o.median), class: 'c-median' }));
    const step = Math.max(1, Math.ceil(o.slots / Math.max(1, Math.floor((W - padL - padR) / 46))));
    for (let i = 0; i < o.slots; i++) {
      root.append(svg('line', { x1: X(i), x2: X(i), y1: H - padB, y2: H - padB + 4, class: 'c-tick' }));
      if (i % step === 0 || i === o.slots - 1) root.append(svg('text', { x: X(i), y: H - 8, class: 'c-xlabel' }, o.xLabel(i)));
    }
    const main = o.points.filter(p => p.main).sort((a, b) => a.slot - b.slot);
    if (main.length > 1) root.append(svg('polyline', { points: main.map(p => X(p.slot).toFixed(1) + ',' + Y(p.y).toFixed(1)).join(' '), class: 'c-line' }));
    for (const p of o.points.filter(p => !p.main)) {
      const c = svg('circle', { cx: X(p.slot), cy: Y(p.y), r: 4, class: 'c-side' });
      c.append(svg('title', {}, p.title));
      root.append(c);
    }
    for (const p of main) {
      const g = svg('g', { class: 'c-point' + (p.out ? ' out' : ''), tabindex: 0, role: 'button', 'aria-label': p.title });
      const dot = svg('circle', { cx: X(p.slot), cy: Y(p.y), r: 6 });
      g.append(svg('circle', { cx: X(p.slot), cy: Y(p.y), r: 15, class: 'c-hit' }), dot, svg('title', {}, p.title));
      const pick = () => { root.querySelectorAll('.c-point.on').forEach(n => n.classList.remove('on')); g.classList.add('on'); if (o.onPick) o.onPick(p, dot); };
      g.addEventListener('click', pick);
      g.addEventListener('keydown', ev => { if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); pick(); } });
      root.append(g);
    }
    host.append(root);
  }

  // ============================================================ pack overview
  const famName = fam => (fam === 'ln' ? '롱놋 단위인정' : '단놋 단위인정');

  function hidePop() { $('pvPop').hidden = true; }

  function showPop(e, index, anchor) {
    const pop = $('pvPop'), d = M.dansOf(e);
    pop.textContent = '';
    const th = M.thumbBox('div', 'pop-thumb', e.md5, e.meta.hasBg);
    const body = el('div', 'pop-body');
    body.append(el('strong', null, (index + 1) + '. ' + e.meta.title), el('span', 'dim', e.meta.version));
    const facts = el('span', 'pop-facts num');
    facts.append(el('b', null, M.fmtRate(e.rate) + '×'), el('span', null, M.fmtTime(e.meta.lengthMs / e.rate)),
      el('span', null, e.rating && e.rating.msd ? 'MSD ' + e.rating.msd.toFixed(2) : ''));
    body.append(facts);
    const dans = el('span', 'pop-dans');
    if (d.rice) dans.append(M.danChip(d.rice, d.ln ? '단놋' : ''));
    if (d.ln) dans.append(M.danChip(d.ln, '롱놋'));
    body.append(dans, el('span', 'dim', e.version || ''));
    const go = el('button', 'btn', '배속 고치기');
    go.type = 'button';
    go.addEventListener('click', () => { hidePop(); M.show('pick'); M.selectMap(e.md5, e); });
    body.append(go);
    pop.append(th, body);
    pop.hidden = false;
    const r = anchor.getBoundingClientRect(), w = pop.offsetWidth, h = pop.offsetHeight;
    let x = clamp(r.left + r.width / 2 - w / 2, 10, window.innerWidth - w - 10);
    let y = r.top - h - 12;
    if (y < 64) y = r.bottom + 12;
    pop.style.left = x + 'px'; pop.style.top = y + 'px';
  }

  function renderPack() {
    hidePop();
    const p = S.project, info = M.packInfo(), n = p.entries.length;
    const title = p.pack.title.trim();
    $('pvTitle').textContent = title || '이름을 아직 정하지 않은 팩';
    $('pvTitle').classList.toggle('unset', !title);
    const total = p.entries.reduce((s, e) => s + (e.meta.lengthMs || 0) / e.rate, 0);
    const ranges = [];
    for (const fam of ['rice', 'ln']) {                       // each ladder has its own range
      const sorted = info.rows.filter(r => r.d.primary.family === fam).sort((a, b) => a.d.primary.raw - b.d.primary.raw);
      if (sorted.length) ranges.push(sorted[0].d.primary.text + (sorted.length > 1 ? ' ~ ' + sorted[sorted.length - 1].d.primary.text : ''));
    }
    const range = ranges.join('  /  ');
    $('pvSub').textContent = n ? ['난이도 ' + n + '개', '합계 ' + M.fmtTime(total), range].filter(Boolean).join('     ')
      : (title ? '' : '메타데이터에서 맵팩 이름을 적으면 여기에 표시됩니다.');
    if (n && !title) $('pvSub').textContent += '     메타데이터에서 맵팩 이름을 적으면 위에 표시됩니다.';
    $('pvEmpty').hidden = n > 0;
    $('pvHint').hidden = info.rows.length < 1;
    $('pvSort').hidden = n < 2;

    const warn = $('pvWarn');
    warn.textContent = '';
    p.entries.forEach((e, i) => {
      if (!info.out.has(e.uid)) return;
      const d = M.dansOf(e).primary, med = info.medians[d.family], diff = d.raw - med;
      warn.append(el('li', null, (i + 1) + '. ' + e.meta.title + '  ' + M.fmtRate(e.rate) + '×  ' + d.text + '   다른 맵들보다 '
        + Math.abs(diff).toFixed(1) + '단 ' + (diff > 0 ? '어렵습니다' : '쉽습니다')));
    });
    const unrated = p.entries.filter(e => !(e.rating && e.rating.dan)).length;
    if (unrated) warn.append(el('li', null, '예상 난이도를 계산하지 못한 맵 ' + unrated + '개는 그래프에 나오지 않습니다.'));
    const keys = new Set(p.entries.map(e => e.meta.keys));
    if (keys.size > 1) warn.append(el('li', null, '키 수가 다른 맵이 섞여 있습니다 (' + Array.from(keys).sort().map(k => k + 'K').join(', ') + ').'));
    if (info.mode === 'mixed') warn.append(el('li', null, '단놋 맵과 롱놋 맵이 섞여 있습니다. 두 단위인정은 기준이 달라 그래프를 따로 그렸습니다.'));

    const charts = $('pvCharts');
    charts.textContent = '';
    const fams = info.mode === 'rice' ? ['rice'] : info.mode === 'ln' ? ['ln', 'rice'] : ['rice', 'ln'];
    const majorityKeys = p.entries.length ? p.entries.map(e => e.meta.keys).sort((a, b) =>
      p.entries.filter(e => e.meta.keys === b).length - p.entries.filter(e => e.meta.keys === a).length)[0] : 4;
    const pending = [];                                // drawn last, once the room left for them is known
    for (const fam of fams) {
      const points = [];
      p.entries.forEach((e, i) => {
        const d = M.dansOf(e);
        if (!d[fam] || d[fam].raw == null || !d.primary) return;
        const isMain = d.primary.family === fam;
        points.push({ slot: i, y: d[fam].raw, main: isMain, out: isMain && info.out.has(e.uid),
          title: (i + 1) + '. ' + e.meta.title + '  ' + M.fmtRate(e.rate) + '×  ' + d[fam].text, data: e });
      });
      if (!points.some(pt => pt.main)) continue;
      const minor = info.mode === 'ln' && fam === 'rice';
      const card = el('div', 'pv-chart' + (minor ? ' minor' : ''));
      const head = el('div', 'pv-charthead');
      head.append(el('h3', null, famName(fam)));
      if (minor) head.append(el('span', 'dim', '롱놋 맵을 단놋 기준으로 봤을 때 (참고)'));
      else if (fams.length > 1) head.append(el('span', 'dim', '속이 빈 작은 점은 다른 쪽이 주된 맵의 참고 값'));
      const area = el('div', 'pv-chartarea');
      card.append(head, area);
      charts.append(card);
      pending.push({ area, minor, options: { points: minor ? points.map(pt => Object.assign(pt, { main: true, out: false })) : points,
        slots: n, family: fam, keys: majorityKeys, median: minor ? null : info.medians[fam],
        label: famName(fam) + ' 그래프', xLabel: i => String(i + 1),
        onPick: (pt, dot) => showPop(pt.data, p.entries.indexOf(pt.data), dot) } });
    }

    const list = $('pvList');
    list.textContent = '';
    p.entries.forEach((e, i) => {
      const d = M.dansOf(e), li = el('li', info.out.has(e.uid) ? 'out' : '');
      li.tabIndex = 0;
      const th = M.thumbBox('span', 'th', e.md5, e.meta.hasBg);
      const name = el('span', 'nm');
      name.append(el('b', null, e.meta.title), el('span', null, e.meta.version));
      const dans = el('span', 'ds');
      if (info.mode === 'ln') { if (d.ln) dans.append(M.danChip(d.ln, '롱놋')); if (d.rice) dans.append(M.danChip(d.rice, '단놋', true)); }
      else if (info.mode === 'mixed') { if (d.rice) dans.append(M.danChip(d.rice, '단놋', d.primary && d.primary.family !== 'rice')); if (d.ln) dans.append(M.danChip(d.ln, '롱놋', d.primary && d.primary.family !== 'ln')); }
      else if (d.primary) dans.append(M.danChip(d.primary));
      let off = '';
      if (d.primary && d.primary.raw != null && info.medians[d.primary.family] != null) {
        const diff = d.primary.raw - info.medians[d.primary.family];
        off = (diff >= 0 ? '+' : '') + diff.toFixed(1) + '단';
      }
      const skills = (e.rating && e.rating.skills) || [];
      const topSkill = skills.length ? skills.reduce((m, s) => (s[1] > m[1] ? s : m)) : null;
      li.append(el('span', 'idx num', String(i + 1)), th, name, el('span', 'rt num', M.fmtRate(e.rate) + '×'), dans,
        el('span', 'off num', off), el('span', 'msd num', e.rating && e.rating.msd ? 'MSD ' + e.rating.msd.toFixed(1) : ''),
        el('span', 'sk', topSkill ? (M.SKILL_KO[topSkill[0]] || topSkill[0]) : ''), el('span', 'ln num', M.fmtTime(e.meta.lengthMs / e.rate)));
      const open = () => showPop(e, i, li.querySelector('.th'));
      li.addEventListener('click', ev => { ev.stopPropagation(); open(); });
      li.addEventListener('keydown', ev => { if (ev.key === 'Enter') open(); });
      list.append(li);
    });

    /* The charts take the height the window has left, so that one chart alone fills the page the way
       two do. A long list keeps only a third of the window; the rest of it is reached by scrolling. */
    if (pending.length) {
      const view = $('view-pack'), body = view.querySelector('.pv');
      const listShown = Math.min(list.offsetHeight, view.clientHeight * 0.34);
      const spare = view.clientHeight - (body.scrollHeight - list.offsetHeight + listShown);   // chart areas are still empty
      const weight = c => (c.minor ? 0.6 : 1);
      const total = pending.reduce((sum, c) => sum + weight(c), 0);
      const room = clamp(spare, pending.length * 190, 780);
      for (const c of pending) {
        c.options.height = Math.round(Math.max(c.minor ? 150 : 200, room * weight(c) / total));
        lineChart(c.area, c.options);
      }
    }
  }

  function sortPack() {
    // each ladder on its own: rice maps first, then LN maps, then the ones without an estimate
    const rank = e => { const d = M.dansOf(e).primary; return !d || d.raw == null ? [2, 0] : [d.family === 'ln' ? 1 : 0, d.raw]; };
    S.project.entries.sort((a, b) => { const x = rank(a), y = rank(b); return x[0] - y[0] || x[1] - y[1]; });
    M.applyTemplate(false);
    M.renderEntries();
    M.changed();
    renderPack();
  }

  // ============================================================ rate changer
  const R = { detail: null, ratings: {}, seq: 0, timer: 0 };
  const rc = () => S.project.rc;
  const key = rate => Number(rate).toFixed(2);
  const FX0 = () => Object.assign({}, window.Thumb.FX_DEFAULT);

  function rateText(rate) {
    const two = Number(rate).toFixed(2);
    return rc().naming.two ? two : two.replace(/0$/, '');           // 1.10 -> 1.1, 1.00 -> 1.0, 1.25 stays
  }

  function entryLike(rate, index) {
    const d = R.detail, rule = ruleFor(rate);
    return { md5: d.md5, rate, index, version: '', rating: R.ratings[key(rate)] || null, bg: { x: 50, y: 50, zoom: 1 },
      bgAsset: (rule && rule.asset) || undefined,
      meta: { title: d.title, artist: d.artist, creator: d.creator, version: d.version, hasBg: d.hasBg, bpm: d.bpm, keys: d.keys, lengthMs: d.lengthMs } };
  }

  function nameFor(rate, style) {
    const n = rc().naming, base = R.detail ? R.detail.version : '', text = rateText(rate);
    style = style || n.style;
    if (style === 'custom') {
      const filled = window.Thumb.fillTokens((n.template || '{version} {rate}x').replace(/\{rate\}/g, text), entryLike(rate, 0), S.project);
      return filled.replace(/\s+/g, ' ').trim();
    }
    const tail = text + (style === 'x' ? 'x' : '');
    return n.dropBase && Math.abs(rate - 1) > 1e-9 ? tail : (base + ' ' + tail).trim();
  }

  function ruleFor(rate) {
    let best = null;
    for (const r of rc().rules) if (r.from <= rate + 1e-9 && (!best || r.from > best.from)) best = r;
    return best;
  }

  function designFor(rate) {
    const rule = ruleFor(rate), layers = [];
    if (rc().dan) layers.push({ id: 'rcdan', type: 'autodan', x: 1920 - 230, y: 1080 - 230, w: 300, h: 300, rot: 0, opacity: 1, shadow: 30, visible: true });
    return { bgMode: 'each', commonAsset: null, fx: rule ? rule.fx : {}, layers };
  }

  const wantsImage = rate => !!(rc().dan || ruleFor(rate));

  async function selectRate(md5) {
    let detail = null;
    try { detail = await M.api('/api/map?md5=' + md5); } catch (e) { /* reported below */ }
    if (!detail || detail.error) { if (S.view === 'rate') M.toast('이 맵의 파일을 찾지 못했습니다.'); return; }
    if (rc().md5 !== md5) { rc().md5 = md5; M.changed(); }
    R.detail = detail;
    R.ratings = {};
    renderRate();
    fetchRatings();
  }

  async function fetchRatings() {
    const seq = ++R.seq, md5 = R.detail && R.detail.md5;
    if (!md5) return;
    for (const rate of rc().rates.slice()) {
      if (R.ratings[key(rate)] !== undefined) continue;
      let res = null;
      try { res = await M.api('/api/rating?md5=' + md5 + '&rate=' + rate); } catch (e) { /* no estimate */ }
      if (seq !== R.seq || !R.detail || R.detail.md5 !== md5) return;
      R.ratings[key(rate)] = (res && res.rating) || null;
      clearTimeout(R.timer);
      R.timer = setTimeout(renderRate, 60);
    }
  }

  function addRates(list) {
    const have = new Set(rc().rates.map(key));
    let added = 0;
    for (const r of list) {
      const v = Math.round(r * 100) / 100;
      if (!(v >= 0.5 && v <= 2) || have.has(key(v))) continue;
      have.add(key(v)); rc().rates.push(v); added++;
    }
    rc().rates.sort((a, b) => a - b);
    if (!added) M.toast('더 넣을 배속이 없습니다. 0.50 ~ 2.00 사이에서 정해 주세요.');
    M.changed();
    renderRate();
    fetchRatings();
  }

  function addRange() {
    const num = id => parseFloat($(id).value.replace(',', '.'));
    let from = num('rcFrom'), to = num('rcTo');
    const step = num('rcStep');
    if (!isFinite(from) || !isFinite(to) || !(step >= 0.01)) { M.toast('시작, 끝, 간격을 숫자로 적어 주세요. 간격은 0.01 이상입니다.'); return; }
    if (from > to) [from, to] = [to, from];
    const list = [];
    for (let i = 0; i < 200; i++) {
      const v = from + step * i;
      if (v > to + 1e-9) break;
      list.push(v);
    }
    if (list.length > 60) { M.toast('한 번에 60개까지만 넣을 수 있습니다. 간격을 넓혀 주세요.'); return; }
    addRates(list);
  }

  function ruleCard(rule) {
    const li = el('li', 'rc-rule');
    const head = el('div', 'row');
    head.append(el('span', null, '배속'));
    const from = el('input', 'num short');
    from.type = 'text'; from.inputMode = 'decimal'; from.value = key(rule.from); from.autocomplete = 'off';
    from.setAttribute('aria-label', '이 배속부터 적용');
    from.addEventListener('change', () => {
      const v = Math.round(parseFloat(from.value.replace(',', '.')) * 100) / 100;
      if (!(v >= 0.5 && v <= 2)) { from.value = key(rule.from); return; }
      rule.from = v; M.changed(); renderRate();
    });
    const del = el('button', 'btn quiet danger', '삭제');
    del.type = 'button';
    del.addEventListener('click', () => { rc().rules = rc().rules.filter(r => r !== rule); M.changed(); renderRate(); });
    head.append(from, el('span', null, '부터'), el('span', 'grow'), del);
    const canvas = document.createElement('canvas');
    canvas.width = 320; canvas.height = 180; canvas.className = 'rc-preview';
    const redraw = () => {
      if (!R.detail) return;
      const first = rc().rates.find(r => r >= rule.from - 1e-9);
      const rate = first == null ? rule.from : first;
      window.Thumb.render(canvas.getContext('2d'), 320, 180, { bgMode: 'each', fx: rule.fx, layers: designFor(rate).layers },
        Object.assign(entryLike(rate, 0), { bgAsset: rule.asset || undefined }), true);
    };
    const imgRow = el('div', 'row');
    const pick = el('button', 'btn', rule.asset ? '다른 이미지로' : '이미지 바꾸기');
    pick.type = 'button';
    pick.addEventListener('click', async () => {
      const file = await M.pickFile('image/png,image/jpeg,image/webp,image/gif,image/bmp');
      const id = file && await M.upload(file);
      if (!id) return;
      rule.asset = id; rule.name = file.name; M.changed(); renderRate();
    });
    imgRow.append(pick);
    if (rule.asset) {
      const back = el('button', 'btn quiet', '원래 이미지로');
      back.type = 'button';
      back.addEventListener('click', () => { rule.asset = null; rule.name = ''; M.changed(); renderRate(); });
      imgRow.append(el('span', 'dim clip', rule.name || ''), back);
    }
    li.append(head, canvas, imgRow);
    const slider = (label, k, min, max) => {
      const line = el('label', 'slider');
      const input = el('input'), out = el('output', 'num', String(rule.fx[k]));
      input.type = 'range'; input.min = min; input.max = max; input.step = 1; input.value = rule.fx[k];
      input.addEventListener('input', () => { rule.fx[k] = Number(input.value); out.textContent = input.value; M.changed(); redraw(); });
      line.append(el('span', null, label), input, out);
      li.append(line);
    };
    slider('어둡게', 'dim', 0, 90); slider('흐림', 'blur', 0, 40); slider('채도', 'saturate', 0, 200);
    slider('노이즈', 'noise', 0, 100); slider('비네트', 'vignette', 0, 100);
    const tint = el('div', 'row tintrow');
    const color = el('input');
    color.type = 'color'; color.value = rule.fx.tintColor || '#000000'; color.setAttribute('aria-label', '입힐 색');
    color.addEventListener('input', () => { rule.fx.tintColor = color.value; if (!rule.fx.tint) rule.fx.tint = 40; M.changed(); redraw(); syncTint(); });
    const mode = el('select');
    [['source-over', '덮기'], ['multiply', '곱하기'], ['screen', '스크린'], ['overlay', '오버레이'], ['color', '색조만']].forEach(([v, t]) => { const o = el('option', null, t); o.value = v; mode.append(o); });
    mode.value = rule.fx.tintMode || 'source-over';
    mode.addEventListener('change', () => { rule.fx.tintMode = mode.value; M.changed(); redraw(); });
    tint.append(el('span', null, '색 입히기'), color, mode);
    li.append(tint);
    slider('색 세기', 'tint', 0, 100);
    const syncTint = () => { const s = li.querySelectorAll('.slider'); const last = s[s.length - 1]; last.querySelector('input').value = rule.fx.tint; last.querySelector('output').textContent = rule.fx.tint; };
    redraw();
    return li;
  }

  function renderRate() {
    const c = rc(), d = R.detail;
    $('rcEmpty').hidden = !!d;
    $('rcBody').hidden = !d;
    // options: always in step with the saved state
    document.querySelectorAll('input[name="rcStyle"]').forEach(r => { r.checked = r.value === c.naming.style; });
    $('rcTemplate').value = c.naming.template;
    $('rcTemplate').hidden = $('rcTplHint').hidden = c.naming.style !== 'custom';
    $('rcDropBase').checked = !!c.naming.dropBase;
    $('rcDropBase').disabled = c.naming.style === 'custom';
    $('rcTwo').checked = !!c.naming.two;
    $('rcPitch').checked = !!c.followPitch;
    $('rcDan').checked = !!c.dan;
    document.querySelectorAll('input[name="rcDest"]').forEach(r => { r.checked = r.value === (S.settings.rateDest || 'source'); });
    const rules = $('rcRules');
    rules.textContent = '';
    c.rules.sort((a, b) => a.from - b.from).forEach(rule => rules.append(ruleCard(rule)));
    const go = $('rcGo');
    go.textContent = c.rates.length ? '배속 난이도 ' + c.rates.length + '개 만들기' : '배속 난이도 만들기';
    go.disabled = !d || !c.rates.length || !d.hasAudio || !S.tools.ffmpeg;
    if (!d) return;

    const sample = c.rates.find(r => Math.abs(r - 1) > 1e-9) || 1.1;
    $('rcEx1').textContent = nameFor(sample, 'space');
    $('rcEx2').textContent = nameFor(sample, 'x');
    const th = $('rcThumb');
    th.style.backgroundImage = d.hasBg ? 'url("' + M.bgSrc(d.md5) + '")' : '';
    th.classList.toggle('none', !d.hasBg);
    th.textContent = d.hasBg ? '' : '썸네일 없음';
    $('rcTitle').textContent = d.title;
    $('rcArtist').textContent = d.artist;
    $('rcFacts').textContent = ['[' + d.version + ']', '제작자 ' + d.creator, M.fmtTime(d.lengthMs), M.bpmText(d, 1) + ' BPM', d.keys + 'K',
      d.hasAudio ? '' : '오디오 파일 없음'].filter(Boolean).join('     ');

    const list = $('rcList');
    list.textContent = '';
    $('rcNone').hidden = c.rates.length > 0;
    if (c.rates.length) {
      const head = el('li', 'head');
      const est = el('span', null, '예상 난이도 ');
      const mark = el('button', 'warn', '!');
      mark.type = 'button';
      mark.setAttribute('aria-label', '예상 난이도 안내');
      mark.dataset.tip = '배속마다 계산기가 추정한 값입니다. 100% 신뢰하지 말고 어느 배속이 어느 정도인지 가늠하는 참고용으로만 사용해 주세요.';
      est.append(mark);
      head.append(el('span', null, '배속'), el('span', null, '난이도명'), el('span', null, 'BPM'), el('span', null, '길이'), est, el('span', null, '썸네일'), el('span'));
      list.append(head);
    }
    const names = {};
    c.rates.forEach(rate => { const k = nameFor(rate).toLowerCase(); names[k] = (names[k] || 0) + 1; });
    c.rates.forEach(rate => {
      const li = el('li', names[nameFor(rate).toLowerCase()] > 1 ? 'dup' : '');
      const rating = R.ratings[key(rate)];
      const dans = el('span', 'ds');
      if (rating === undefined) dans.append(el('span', 'dim', '계산 중'));
      else if (rating && rating.dan) { dans.append(M.danChip(rating.dan)); if (rating.msd) dans.append(el('span', 'dim num', 'MSD ' + rating.msd.toFixed(1))); }
      else dans.append(el('span', 'dim', rating && rating.msd ? 'MSD ' + rating.msd.toFixed(1) : '계산할 수 없음'));
      const rule = ruleFor(rate);
      const thumb = !wantsImage(rate) ? '원래 그대로' : rule ? key(rule.from) + '부터의 규칙' + (c.dan ? ' + 심볼' : '') : '심볼 추가';
      const del = el('button', 'btn quiet icon danger', '');
      del.type = 'button'; del.title = '이 배속 빼기'; del.setAttribute('aria-label', key(rate) + '배속 빼기');
      del.addEventListener('click', () => { c.rates = c.rates.filter(r => r !== rate); M.changed(); renderRate(); });
      li.append(el('span', 'rt num', key(rate) + '×'), el('span', 'nm', nameFor(rate)), el('span', 'num', M.bpmText(d, rate)),
        el('span', 'num', M.fmtTime(d.lengthMs / rate)), dans, el('span', 'dim', thumb), del);
      list.append(li);
    });

    const points = [];
    c.rates.forEach((rate, i) => {
      const r = R.ratings[key(rate)];
      if (r && r.dan && r.dan.raw != null) points.push({ slot: i, y: r.dan.raw, main: true, out: false, title: key(rate) + '×  ' + r.dan.text, data: rate });
    });
    const chart = $('rcChart');
    chart.hidden = points.length < 2;
    if (points.length >= 2) {
      const fam = (R.ratings[key(c.rates[0])] || R.ratings[key(points[0].data)]).dan.family;
      lineChart(chart, { points, slots: c.rates.length, family: fam, keys: d.keys, height: 210, label: '배속별 예상 난이도',
        xLabel: i => key(c.rates[i]) });
    } else chart.textContent = '';
  }

  async function goRate() {
    const c = rc(), d = R.detail;
    if (!d || !c.rates.length) return;
    const names = c.rates.map(r => nameFor(r));
    if (new Set(names.map(n => n.toLowerCase())).size !== names.length) { M.toast('같은 난이도명이 두 개 이상 나옵니다. 난이도명 규칙을 바꿔 주세요.'); return; }
    if (names.some(n => !n)) { M.toast('비어 있는 난이도명이 있습니다.'); return; }
    const uid = rate => 'r' + key(rate);
    const payload = { mode: 'rate', md5: d.md5, dest: S.settings.rateDest || 'source', bitrate: S.settings.bitrate || 192,
      entries: c.rates.map(rate => ({ uid: uid(rate), rate, version: nameFor(rate), followPitch: !!c.followPitch, image: wantsImage(rate) })) };
    M.exportTitle('레이트 체인저');
    await M.runExport(payload, plan => plan.images, id => {
      const rate = c.rates.find(r => uid(r) === id);
      return rate == null ? null : window.Thumb.blobWith(designFor(rate), entryLike(rate, 0), 1920, 1080, 1);
    });
  }

  function initRate() {
    const c = rc;
    $('rcAddRange').addEventListener('click', addRange);
    const one = () => { const v = parseFloat($('rcOne').value.replace(',', '.')); if (isFinite(v)) { addRates([v]); $('rcOne').value = ''; } };
    $('rcAddOne').addEventListener('click', one);
    $('rcOne').addEventListener('keydown', ev => { if (ev.key === 'Enter') one(); });
    for (const id of ['rcFrom', 'rcTo', 'rcStep']) $(id).addEventListener('keydown', ev => { if (ev.key === 'Enter') addRange(); });
    $('rcClear').addEventListener('click', () => { c().rates = []; M.changed(); renderRate(); });
    document.querySelectorAll('input[name="rcStyle"]').forEach(r => r.addEventListener('change', () => { c().naming.style = r.value; M.changed(); renderRate(); }));
    $('rcTemplate').addEventListener('input', ev => { c().naming.template = ev.target.value; M.changed(); });
    $('rcTemplate').addEventListener('change', renderRate);
    $('rcDropBase').addEventListener('change', ev => { c().naming.dropBase = ev.target.checked; M.changed(); renderRate(); });
    $('rcTwo').addEventListener('change', ev => { c().naming.two = ev.target.checked; M.changed(); renderRate(); });
    $('rcPitch').addEventListener('change', ev => { c().followPitch = ev.target.checked; M.changed(); });
    $('rcDan').addEventListener('change', ev => { c().dan = ev.target.checked; M.changed(); renderRate(); });
    $('rcAddRule').addEventListener('click', () => {
      const from = c().rates.find(r => r > 1 && !c().rules.some(x => Math.abs(x.from - r) < 1e-9)) || 1.3;
      c().rules.push({ from, asset: null, name: '', fx: Object.assign(FX0(), { dim: 30 }) });
      M.changed(); renderRate();
    });
    document.querySelectorAll('input[name="rcDest"]').forEach(r => r.addEventListener('change', () => {
      S.settings.rateDest = r.value; M.api('/api/settings', { rateDest: r.value }).catch(() => {});
    }));
    $('rcGo').addEventListener('click', goRate);
    $('pvSort').addEventListener('click', sortPack);
    document.addEventListener('click', ev => { if (!$('pvPop').hidden && !ev.target.closest('#pvPop, .c-point, .pv-list li')) hidePop(); });
    document.addEventListener('keydown', ev => { if (ev.key === 'Escape') hidePop(); });
    let resizeTimer = 0;
    window.addEventListener('resize', () => {
      clearTimeout(resizeTimer);
      resizeTimer = setTimeout(() => { if (S.view === 'pack') renderPack(); if (S.view === 'rate') renderRate(); }, 150);
    });
  }

  function showRate() {
    const c = rc();
    if (c.md5 && (!R.detail || R.detail.md5 !== c.md5)) { renderRate(); selectRate(c.md5); return; }
    if (!c.md5) R.detail = null;
    renderRate();
    fetchRatings();
  }

  M.pack = { render: renderPack };
  M.rate = { init: initRate, show: showRate, select: selectRate, md5: () => (R.detail ? R.detail.md5 : null) };
})();
