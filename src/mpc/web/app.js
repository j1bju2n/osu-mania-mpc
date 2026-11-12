/* Map Pack Create: the three views (pick maps, thumbnails, metadata) and the export flow.
   Strings that come from files (titles, names) are always written with textContent. */
'use strict';
(function () {
  const TOKEN = new URLSearchParams(location.search).get('t') || '';
  const $ = id => document.getElementById(id);
  const el = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text != null) n.textContent = text; return n; };
  const clamp = (v, a, b) => Math.min(b, Math.max(a, v));
  const SKILL_KO = { Stream: '스트림', Jumpstream: '점프스트림', Handstream: '핸드스트림', Stamina: '스태미나',
    JackSpeed: '잭스피드', Chordjack: '코드잭', Technical: '테크니컬' };
  const MODE_KO = { copy: '원본 mp3 그대로', convert: 'mp3로 변환', resample: '배속, 피치 변경', stretch: '배속, 피치 유지',
    keep: '원본 오디오 그대로' };
  const VIEWS = ['pick', 'pack', 'thumb', 'meta', 'rate', 'edit'];
  const NOTICE_MAX = 80;

  const S = { app: {}, lib: {}, tools: {}, settings: {}, packsDir: '', project: null,
    cur: null, rows: [], total: 0, query: '', keys: 0, loadingRows: false, view: 'pick',
    follow: true, liveSeen: {}, missing: new Set(), replace: null };

  // ------------------------------------------------------------ server
  async function api(path, body, raw) {
    const opts = { headers: { 'X-MPC-Token': TOKEN } };
    if (body !== undefined) {
      opts.method = 'POST';
      opts.body = raw ? body : JSON.stringify(body);
      if (!raw) opts.headers['Content-Type'] = 'application/json';
    }
    const res = await fetch(path, opts);
    if (!res.ok && res.status !== 404) throw new Error('HTTP ' + res.status);
    return res.json();
  }
  const q = s => encodeURIComponent(s);
  const bgSrc = md5 => '/api/bg?md5=' + md5 + '&t=' + q(TOKEN);

  let toastTimer = 0;
  function toast(text) {
    const t = $('toast');
    t.textContent = text; t.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { t.hidden = true; }, 3200);
  }

  /* opts.danger: the answer deletes something; opts.yes: the label of the confirming button. */
  function confirmBox(text, opts) {
    return new Promise(resolve => {
      const dlg = $('confirmDlg'), yes = $('confirmYes');
      $('confirmText').textContent = text;
      yes.textContent = (opts && opts.yes) || '확인';
      yes.className = 'btn ' + (opts && opts.danger ? 'danger' : 'primary');
      const done = v => { dlg.close(); $('confirmYes').onclick = $('confirmNo').onclick = null; resolve(v); };
      $('confirmYes').onclick = () => done(true);
      $('confirmNo').onclick = () => done(false);
      dlg.oncancel = () => resolve(false);
      dlg.showModal();
    });
  }

  function pickFile(accept, many) {
    return new Promise(resolve => {
      const input = $('filePick');
      input.value = ''; input.accept = accept || ''; input.multiple = !!many;
      let settled = false;
      const finish = value => { if (!settled) { settled = true; resolve(value); } };
      input.onchange = () => finish(many ? Array.from(input.files || []) : (input.files && input.files[0]) || null);
      input.oncancel = () => finish(many ? [] : null);
      input.click();
    });
  }

  async function upload(file) {
    try {
      const res = await api('/api/asset?name=' + q(file.name), file, true);
      if (res.ok) return res.id;
    } catch (e) { /* reported below */ }
    toast('파일을 넣지 못했습니다. 지원하지 않는 형식이거나 너무 큽니다.');
    return null;
  }

  // ------------------------------------------------------------ project
  function newRc() {
    return { md5: null, rates: [], followPitch: false, dan: false, rules: [],
      naming: { style: 'x', template: '{version} {rate}x', dropBase: false, two: false } };
  }

  function newProject() {
    return {
      v: 2, rc: newRc(), edit: null, saveName: '',
      pack: { title: '', artist: 'Various Artists', creator: S.lib.player || '', source: '', tags: '', tagsPerMap: false, tagsMode: 'add', resetIds: true,
        od: '', hp: '', template: '{title} [{rate}x] ({creator})' },
      entries: [],
      thumb: Thumb.defaults(),
      delete: { enabled: true, name: 'delete', minutes: 10,
        thumb: { mode: 'entry', uid: null, asset: null, name: '', design: true },
        preview: { mode: 'entry', uid: null, asset: null, name: '', start: 0, length: 30 } },
      followPitch: false,
    };
  }

  function adopt(saved) {
    const base = newProject();
    if (!saved || typeof saved !== 'object' || !Array.isArray(saved.entries)) return base;
    const p = Object.assign(base, saved);
    p.pack = Object.assign(newProject().pack, saved.pack);
    p.thumb = Object.assign(Thumb.defaults(), saved.thumb);
    p.thumb.layers = Array.isArray(p.thumb.layers) ? p.thumb.layers : [];
    const d = newProject().delete;
    p.delete = Object.assign(d, saved.delete);
    p.delete.thumb = Object.assign(newProject().delete.thumb, saved.delete && saved.delete.thumb);
    p.delete.preview = Object.assign(newProject().delete.preview, saved.delete && saved.delete.preview);
    p.entries = p.entries.filter(e => e && e.md5 && e.uid);
    if ((saved.v || 1) < 2) {                      // 0.1: jpg quality 90 looked poor under noise
      if (p.thumb.quality === 90) p.thumb.quality = 100;
      p.v = 2;
    }
    p.rc = Object.assign(newRc(), saved.rc);
    p.rc.naming = Object.assign(newRc().naming, saved.rc && saved.rc.naming);
    p.rc.rates = Array.isArray(p.rc.rates) ? p.rc.rates : [];
    p.rc.rules = Array.isArray(p.rc.rules) ? p.rc.rules : [];
    p.edit = saved.edit && typeof saved.edit === 'object' && Array.isArray(saved.edit.slots) ? saved.edit : null;
    p.saveName = typeof saved.saveName === 'string' ? saved.saveName : '';
    return p;
  }

  /* A place for a map's picture; says so when the map has none. */
  function thumbBox(tag, cls, md5, hasBg) {
    const th = el(tag, cls);
    if (hasBg) th.style.backgroundImage = 'url("' + bgSrc(md5) + '")';
    else { th.classList.add('none'); th.textContent = '썸네일 없음'; }
    return th;
  }

  /* Whether there is anything in the project worth asking about on the next start. */
  function hasWork(p) {
    return !!(p && (p.entries.length || p.pack.title.trim() || p.pack.tags.trim() || p.pack.source.trim()
      || p.thumb.layers.length || p.edit || (p.rc && p.rc.rates.length)));
  }

  let saveTimer = 0;
  function changed() {
    clearTimeout(saveTimer);
    S.project.savedAt = Date.now();
    saveTimer = setTimeout(async () => {
      try {
        await api('/api/project', S.project);
        $('saved').textContent = '자동 저장됨';
        setTimeout(() => { $('saved').textContent = ''; }, 1600);
      } catch (e) { $('saved').textContent = '저장하지 못했습니다'; }
    }, 700);
  }

  /* Put another project in place of the current one (a copy of the old one stays on disk as
     project.backup.json). keepRc: the rate changer is not part of a pack and carries on as it was. */
  async function setProject(project, view, keepRc) {
    try { await api('/api/project/backup', {}); } catch (e) { /* nothing saved yet */ }
    const rc = S.project && S.project.rc;
    S.project = project;
    if (keepRc && rc) S.project.rc = rc;
    S.cur = null; S.replace = null; $('map').hidden = true; $('stageEmpty').hidden = false; stopAudio();
    Thumb.reset();
    addLabel(); renderEntries(); show(view || 'pick'); changed();
    return checkMissing();
  }

  /* Throw the current project away and start empty. */
  const startOver = () => setProject(newProject(), 'pick');

  /* Which of the pack's maps this osu! folder does not have (a saved pack opened on another PC, a map
     deleted since). They are marked in the lists and block the export. */
  async function checkMissing() {
    const md5s = S.project.entries.map(e => e.md5);
    let res = null;
    if (md5s.length) { try { res = await api('/api/check', { md5s }); } catch (e) { return null; } }
    if (res && !res.ready) return null;                 // the map list is still being read
    S.missing = new Set(res ? res.missing : []);
    renderEntries();
    if (S.view === 'meta') renderDiffList();
    return S.project.entries.filter(e => S.missing.has(e.md5));
  }

  /* The label of the add button and the "replace" banner follow what the next click will do. */
  function addLabel() {
    const c = S.cur, r = S.replace;
    $('addBtn').textContent = c && c.editUid ? '변경 저장' : r ? '이 자리에 넣기' : '팩에 넣기';
    $('cancelEdit').hidden = !(c && c.editUid);
    $('replaceBar').hidden = !r;
    if (r) $('replaceText').textContent = '"' + r.label + '" (BeatmapID ' + r.slot + ') 자리에 넣을 맵을 고르고 배속을 정한 뒤 "이 자리에 넣기"를 누르세요. 이 난이도의 ID와 링크를 그대로 물려받습니다.';
  }

  /* Shown in the header while an uploaded set is being rebuilt, so it is clear what the pack tabs work on. */
  function editChip() {
    const e = S.project.edit, chip = $('editChip');
    chip.hidden = !e;
    if (e) chip.textContent = '수정 중  ' + (e.title || e.folder) + '  ID ' + e.setId;
  }

  /* On start: carry on with the pack that was being made, or begin a new one. */
  function askResume() {
    const p = S.project;
    if (!hasWork(p)) return Promise.resolve();
    return new Promise(resolve => {
      const dlg = $('resumeDlg'), name = p.pack.title.trim();
      $('resumeLead').textContent = name ? '"' + name + '" 팩에서 이어서 할까요?' : '이름을 아직 정하지 않은 팩에서 이어서 할까요?';
      const facts = ['넣은 맵 ' + p.entries.length + '개'];
      if (p.thumb.layers.length) facts.push('썸네일 레이어 ' + p.thumb.layers.length + '개');
      if (p.rc && p.rc.rates.length) facts.push('레이트 체인저 배속 ' + p.rc.rates.length + '개');
      if (p.savedAt) facts.push('마지막 작업 ' + new Date(p.savedAt).toLocaleString('ko-KR', { dateStyle: 'medium', timeStyle: 'short' }));
      $('resumeFacts').textContent = facts.join('     ');
      $('resumeFacts').style.whiteSpace = 'pre-wrap';
      const done = async fresh => {
        $('resumeGo').onclick = $('resumeNew').onclick = null;
        dlg.close();
        if (fresh) await startOver();
        resolve();
      };
      $('resumeGo').onclick = () => done(false);
      $('resumeNew').onclick = () => done(true);
      dlg.oncancel = ev => { ev.preventDefault(); done(false); };      // Esc keeps the work
      dlg.showModal();
      $('resumeGo').focus();
    });
  }

  // ------------------------------------------------------------ formatting
  const fmtRate = r => Number(r).toFixed(2);
  function fmtTime(ms) {
    const s = Math.max(0, Math.round(ms / 1000));
    return Math.floor(s / 60) + ':' + String(s % 60).padStart(2, '0');
  }
  function fmtBpm(v) { return Math.abs(v - Math.round(v)) < 0.05 ? String(Math.round(v)) : v.toFixed(1); }
  function bpmText(meta, rate) {
    if (!meta.bpm) return '';
    const main = fmtBpm(meta.bpm * rate);
    if (meta.bpmMax - meta.bpmMin > 0.5) return main + ' (' + fmtBpm(meta.bpmMin * rate) + '~' + fmtBpm(meta.bpmMax * rate) + ')';
    return main;
  }
  function versionFor(entry, index) {
    const withIndex = Object.assign({}, entry, { index });
    return Thumb.fillTokens(S.project.pack.template || '{title} [{rate}x] ({creator})', withIndex, S.project).replace(/\s+/g, ' ').trim();
  }
  function applyTemplate(all) {
    S.project.entries.forEach((e, i) => { if (all || !e.versionEdited) { e.version = versionFor(e, i); if (all) e.versionEdited = false; } });
  }

  // ------------------------------------------------------------ views
  function show(view) {
    S.view = view;
    for (const v of VIEWS) $('view-' + v).hidden = v !== view;
    document.querySelectorAll('.steps button').forEach(b => b.setAttribute('aria-selected', String(b.dataset.view === view)));
    const picking = view === 'pick' || view === 'rate' || (view === 'edit' && !S.project.edit);
    $('main').classList.toggle('nolib', !picking);
    $('followBar').hidden = !picking;
    $('exportBtn').hidden = $('newBtn').hidden = $('saveBtn').hidden = $('loadBtn').hidden = view === 'rate';
    if (view !== 'pick' && S.replace) { S.replace = null; addLabel(); }
    if (view === 'edit' && MPC.edit) MPC.edit.show();
    editChip();
    if (view === 'thumb') Thumb.refresh();
    if (view === 'meta') renderMeta();
    if (view === 'pack' && MPC.pack) MPC.pack.render();
    if (view === 'rate' && MPC.rate) MPC.rate.show();
    if (view !== 'pick') stopAudio();
    if (view !== 'meta') stopDeletePreview();
  }

  function setLib(open, save) {
    S.settings.libOpen = open;
    $('main').classList.toggle('libclosed', !open);
    const b = $('libToggle');
    b.setAttribute('aria-expanded', String(open));
    b.querySelector('.libtoggle-text').textContent = open ? '맵 목록 접기' : '맵 목록';
    if (save) api('/api/settings', { libOpen: open }).catch(() => {});
    if (open && save) $('q').focus();
  }

  /* One floating tooltip for every [data-tip] element: it is never clipped by a scrolling parent. */
  function bindTips() {
    const tip = $('tipFloat');
    let cur = null;
    const place = t => {
      cur = t;
      tip.textContent = t.dataset.tip;
      tip.hidden = false;
      const r = t.getBoundingClientRect(), w = tip.offsetWidth, h = tip.offsetHeight;
      const x = Math.min(window.innerWidth - w - 10, Math.max(10, r.left + r.width / 2 - w / 2));
      let y = r.bottom + 8;
      if (y + h > window.innerHeight - 8) y = Math.max(8, r.top - h - 8);
      tip.style.left = x + 'px'; tip.style.top = y + 'px';
    };
    const hide = () => { cur = null; tip.hidden = true; };
    const find = ev => ev.target && ev.target.closest ? ev.target.closest('[data-tip]') : null;
    document.addEventListener('mouseover', ev => { const t = find(ev); if (t) { if (t !== cur) place(t); } else if (cur) hide(); });
    document.addEventListener('focusin', ev => { const t = find(ev); if (t) place(t); });
    document.addEventListener('focusout', hide);
    document.addEventListener('scroll', hide, true);
  }

  // ------------------------------------------------------------ library
  async function watchLibrary() {
    try { S.lib = await api('/api/library'); } catch (e) { return; }
    renderLibStatus();
    if (S.lib.status === 'loading' || S.lib.status === 'idle') { setTimeout(watchLibrary, 500); return; }
    if (S.lib.status === 'ready') {
      const select = $('keys');
      select.textContent = '';
      const all = el('option', null, '모든 키'); all.value = '0'; select.append(all);
      for (const [k, n] of S.lib.keys) {
        const o = el('option', null, k + 'K  (' + n.toLocaleString() + ')'); o.value = String(k); select.append(o);
      }
      const four = S.lib.keys.find(k => k[0] === 4);
      S.keys = four ? 4 : 0;
      select.value = String(S.keys);
      if (!S.project.pack.creator && S.lib.player) { S.project.pack.creator = S.lib.player; }
      search(true);
      checkMissing().then(list => { if (list && list.length && MPC.saves) MPC.saves.reportMissing(list, '이전에 작업하던 팩'); });
    }
  }

  function renderLibStatus() {
    const host = $('libStatus');
    host.textContent = '';
    if (S.lib.status === 'loading' || S.lib.status === 'idle') { host.textContent = 'osu! 맵 목록을 읽는 중입니다'; return; }
    if (S.lib.status === 'error') {
      host.append(el('span', null, S.lib.message || '맵 목록을 읽지 못했습니다.'));
      const input = el('input'); input.type = 'text'; input.placeholder = 'osu! 폴더 경로'; input.style.cssText = 'width:100%;margin:8px 0 6px';
      const b = el('button', 'btn', '이 폴더에서 읽기'); b.type = 'button';
      b.addEventListener('click', async () => { await api('/api/library/reload', { folder: input.value.trim() }); watchLibrary(); });
      host.append(input, b);
      return;
    }
    host.append(el('span', null, S.total.toLocaleString() + '개'));
    const b = el('button', 'btn quiet', '목록 새로 읽기');
    b.type = 'button'; b.style.cssText = 'height:22px;padding:0 6px;margin-left:6px;font-size:12px';
    b.title = 'osu!를 닫은 뒤에 눌러야 새로 받은 맵이 보입니다';
    b.addEventListener('click', async () => { await api('/api/library/reload', {}); $('rows').textContent = ''; watchLibrary(); });
    host.append(b);
  }

  let searchSeq = 0;
  async function search(reset) {
    if (S.lib.status !== 'ready') return;
    if (reset) { S.rows = []; $('rows').textContent = ''; $('rows').scrollTop = 0; }
    const seq = ++searchSeq;
    S.loadingRows = true;
    let res;
    try { res = await api('/api/search?q=' + q(S.query) + '&keys=' + S.keys + '&offset=' + S.rows.length); }
    catch (e) { S.loadingRows = false; return; }
    if (seq !== searchSeq) return;
    S.loadingRows = false;
    S.total = res.total;
    const list = $('rows');
    const old = list.querySelector('.more'); if (old) old.remove();
    for (const row of res.rows) {
      S.rows.push(row);
      const li = el('li');
      li.dataset.md5 = row.md5;
      li.setAttribute('role', 'option');
      li.setAttribute('aria-selected', String(!!S.cur && S.cur.md5 === row.md5 && !S.cur.editUid));
      li.tabIndex = 0;
      const k = el('span', 'k');
      k.append(el('b', null, row.keys + 'K'), document.createTextNode(fmtTime(row.lengthMs)));
      li.append(el('span', 't', row.title), k, el('span', 'v', row.version), el('span', 'a', row.artist + '   ' + row.creator));
      list.append(li);
    }
    if (S.rows.length < S.total) list.append(el('li', 'more', '아래로 내리면 더 보입니다'));
    if (!S.total) list.append(el('li', 'more', '찾는 맵이 없습니다'));
    renderLibStatus();
  }

  // ------------------------------------------------------------ following osu!
  function renderLive(st) {
    const host = $('liveState');
    let text = '', cls = '';
    if (!S.follow) text = '';
    else if (!st) text = '';
    else if (st.problem === 'access') { text = 'osu!가 관리자 권한으로 실행 중이라 읽을 수 없습니다'; cls = 'warn'; }
    else if (!st.running) text = 'osu!가 꺼져 있습니다. 켜면 자동으로 연결됩니다';
    else if (!st.readable) text = 'osu!와 연결하는 중입니다';
    else if (!st.md5) { text = 'osu!와 연결됨. 맵을 고르면 여기에 뜹니다'; cls = 'on'; }
    else if (!st.known) { text = 'osu!에서 고른 맵이 mania 맵이 아니거나 목록에 없습니다'; cls = 'warn'; }
    else { text = 'osu!와 연결됨' + (st.label ? '  ' + st.label : ''); cls = 'on'; }
    host.textContent = text;
    host.className = 'livestate ' + cls;
  }

  async function pollLive() {
    try {
      const view = S.view;
      const choosing = view === 'edit' && !S.project.edit;
      if (S.follow && (view === 'pick' || view === 'rate' || choosing) && !document.querySelector('dialog[open]')) {
        const st = await api('/api/live');
        renderLive(st);
        const md5 = st.known ? st.md5 : null;
        if (md5 !== S.liveSeen[view]) {              // each part follows on its own
          S.liveSeen[view] = md5;
          if (view === 'rate') { if (md5 && MPC.rate && MPC.rate.md5() !== md5) MPC.rate.select(md5); }
          else if (view === 'edit') { if (md5 && MPC.edit) MPC.edit.select(md5); }
          else if (md5 && !(S.cur && S.cur.editUid) && !(S.cur && S.cur.md5 === md5)) selectMap(md5);
        }
      }
    } catch (e) { /* the connection watcher reports a dead program */ }
    setTimeout(pollLive, 600);
  }

  /* One connection stays open for as long as this window lives; the program ends when it closes. */
  async function hold() {
    let failures = 0;
    for (;;) {
      const began = Date.now();
      try {
        const res = await fetch('/api/hold?t=' + q(TOKEN));
        const reader = res.body.getReader();
        for (;;) { const part = await reader.read(); if (part.done) break; failures = 0; }
      } catch (e) { /* counted below */ }
      failures = Date.now() - began > 5000 ? 1 : failures + 1;
      if (failures >= 4) { $('dead').hidden = false; return; }
      if (failures > 1) await new Promise(r => setTimeout(r, 700));
    }
  }

  // ------------------------------------------------------------ stage (the selected map)
  let ratingTimer = 0, ratingSeq = 0;

  async function selectMap(md5, edit) {
    if (S.view === 'rate' && !edit) { if (MPC.rate) MPC.rate.select(md5); return; }
    if (S.view === 'edit' && !edit) { if (MPC.edit && !S.project.edit) MPC.edit.select(md5); return; }
    stopAudio();
    let detail;
    try { detail = await api('/api/map?md5=' + md5); } catch (e) { detail = null; }
    if (!detail || detail.error) { toast('이 맵의 파일을 찾지 못했습니다.'); return; }
    S.cur = { md5, detail, rate: edit ? edit.rate : 1, follow: edit ? !!edit.followPitch : !!S.project.followPitch,
      rating: edit ? edit.rating : null, editUid: edit ? edit.uid : null };
    $('stageEmpty').hidden = true; $('map').hidden = false;
    const img = $('bannerImg');
    img.hidden = !detail.hasBg;
    $('bannerNone').hidden = detail.hasBg;
    if (detail.hasBg) img.src = bgSrc(md5);
    $('mTitle').textContent = detail.title;
    $('mArtist').textContent = detail.artist;
    $('mVersion').textContent = detail.version; $('mVersion').title = detail.version;
    $('mCreator').textContent = detail.creator;
    $('mKeys').textContent = detail.keys + 'K';
    $('mNotes').textContent = detail.notes.toLocaleString() + (detail.lns ? '  LN ' + Math.round(detail.lns / detail.notes * 100) + '%' : '');
    $('followPitch').checked = S.cur.follow;
    addLabel();
    $('playBtn').hidden = !detail.hasAudio;
    $('addBtn').disabled = !detail.hasAudio;
    $('addNote').textContent = detail.hasAudio ? '' : '오디오 파일이 없어 팩에 넣을 수 없습니다.';
    document.querySelectorAll('#rows li[data-md5]').forEach(li => li.setAttribute('aria-selected', String(li.dataset.md5 === md5 && !edit)));
    renderEntries();
    setRate(S.cur.rate, true);
  }

  function setRate(value, force) {
    if (!S.cur) return;
    const rate = Math.round(clamp(Number(value) || 1, 0.5, 2) * 100) / 100;
    if (!force && rate === S.cur.rate) { $('rateNum').value = fmtRate(rate); return; }
    S.cur.rate = rate;
    $('rate').value = rate;
    $('rateNum').value = fmtRate(rate);
    const d = S.cur.detail;
    $('mLength').textContent = fmtTime(d.lengthMs / rate);
    $('mBpm').textContent = bpmText(d, rate);
    renderPitchHint();
    syncAudio();
    $('estRate').textContent = fmtRate(rate) + '× 기준';
    $('estimate').classList.add('pending');
    clearTimeout(ratingTimer);
    const seq = ++ratingSeq, md5 = S.cur.md5;
    ratingTimer = setTimeout(async () => {
      let res = null;
      try { res = await api('/api/rating?md5=' + md5 + '&rate=' + rate); } catch (e) { /* shown as unavailable */ }
      if (seq !== ratingSeq || !S.cur || S.cur.md5 !== md5) return;
      S.cur.rating = res && res.rating;
      renderRating();
    }, force ? 0 : 140);
    if (force) renderRating(true);
  }

  function renderPitchHint() {
    const c = S.cur, hint = $('pitchHint');
    if (!c) return;
    if (c.rate === 1) hint.textContent = '1.00배속은 원본 음정 그대로입니다.';
    else if (c.follow) {
      const semi = 12 * Math.log2(c.rate);
      hint.textContent = '음정이 ' + Math.abs(semi).toFixed(1) + '반음 ' + (semi > 0 ? '올라갑니다' : '내려갑니다') + ' (DT/NC, HT 방식). 오프셋이 샘플 단위로 정확합니다.';
    } else hint.textContent = '음정은 그대로 두고 속도만 바꿉니다. 내보낼 때 오프셋 밀림을 측정해 보정합니다.';
  }

  function renderRating(pending) {
    const r = S.cur && S.cur.rating, box = $('estimate');
    box.classList.toggle('pending', !!pending);
    const img = $('danImg'), skills = $('skills');
    skills.textContent = '';
    $('danOther').textContent = '';
    if (pending && !r) { $('danText').textContent = '계산 중'; $('msdText').textContent = ''; img.hidden = true; return; }
    if (!r) {
      $('danText').textContent = '계산할 수 없음';
      $('msdText').textContent = S.tools.calc ? '이 맵은 예상 난이도를 지원하지 않습니다' : '계산기 파일이 없습니다';
      img.hidden = true;
      return;
    }
    $('danText').textContent = r.dan ? r.dan.text : '단 추정 없음';
    $('msdText').textContent = r.msd ? 'MSD ' + r.msd.toFixed(2) : '';
    if (r.danOther) $('danOther').textContent = '다른 기준으로는 ' + r.danOther.text;
    img.hidden = !(r.dan && r.dan.image);
    if (r.dan && r.dan.image) img.src = '/dans/' + r.dan.image;
    const top = Math.max(1, ...r.skills.map(s => s[1]));
    for (const [name, value] of r.skills) {
      const li = el('li', value === top ? 'best' : '');
      const bar = el('i'); const fill = el('b'); fill.style.width = (value / top * 100).toFixed(1) + '%'; bar.append(fill);
      li.append(el('span', null, SKILL_KO[name] || name), bar, el('span', null, value.toFixed(1)));
      skills.append(li);
    }
  }

  // ---- volume: one setting for every preview in the program (half by default)
  function setVolume(value, save) {
    const v = clamp(Math.round(Number(value)), 0, 100);
    S.settings.volume = v;
    $('player').volume = $('player2').volume = v / 100;
    document.querySelectorAll('input.volume').forEach(i => { i.value = v; i.nextElementSibling.textContent = v; });
    if (save) api('/api/settings', { volume: v }).catch(() => {});
  }

  // ---- the [delete] preview music, as it will sound inside the placeholder audio
  function stopDeletePreview() {
    const a = $('player2');
    a.pause();
    $('dPrevPlay').textContent = '미리 들어 보기';
  }

  async function toggleDeletePreview() {
    const a = $('player2'), d = S.project.delete.preview;
    if (!a.paused) { stopDeletePreview(); return; }
    stopAudio();
    let src = '', start = 0;
    if (d.mode === 'entry') {
      const e = S.project.entries.find(x => x.uid === d.uid) || S.project.entries[0];
      if (!e) { toast('팩에 넣은 맵이 없습니다.'); return; }
      src = '/api/audio?md5=' + e.md5 + '&t=' + q(TOKEN);
      let detail = null;
      try { detail = await api('/api/map?md5=' + e.md5); } catch (err) { /* plays from 40% in */ }
      start = detail && detail.preview >= 0 ? detail.preview / 1000 : -1;       // the map's own preview point
    } else if (d.mode === 'file') {
      if (!d.asset) { toast('먼저 음악 파일을 골라 주세요.'); return; }
      src = '/api/asset?id=' + q(d.asset) + '&t=' + q(TOKEN);
      start = Math.max(0, Number(d.start) || 0);
    } else return;
    const length = clamp(Number(d.length) || 30, 5, 120);
    a.src = src;
    a.playbackRate = 1;
    a.onloadedmetadata = () => {
      const at = start < 0 ? a.duration * 0.4 : Math.min(start, Math.max(0, a.duration - 1));
      try { a.currentTime = at; } catch (err) { /* not seekable */ }
      a.dataset.end = String(at + length);
    };
    a.ontimeupdate = () => { if (a.dataset.end && a.currentTime >= Number(a.dataset.end)) stopDeletePreview(); };
    a.onended = stopDeletePreview;
    try { await a.play(); $('dPrevPlay').textContent = '정지'; }
    catch (err) { toast('이 음악은 여기서 재생할 수 없습니다.'); }
  }

  // ---- audio preview
  function syncAudio() {
    const a = $('player');
    if (!S.cur) return;
    a.playbackRate = S.cur.rate;
    a.preservesPitch = !S.cur.follow;
  }
  function stopAudio() {
    const a = $('player');
    a.pause();
    $('playBtn').textContent = '미리듣기';
  }
  function toggleAudio() {
    const a = $('player');
    if (!S.cur) return;
    if (!a.paused) { stopAudio(); return; }
    stopDeletePreview();
    const src = '/api/audio?md5=' + S.cur.md5 + '&t=' + q(TOKEN);
    if (a.dataset.md5 !== S.cur.md5) {
      a.dataset.md5 = S.cur.md5;
      a.src = src;
      const at = S.cur.detail.preview >= 0 ? S.cur.detail.preview / 1000 : 0;
      a.addEventListener('loadedmetadata', () => { try { a.currentTime = at; } catch (e) { /* not seekable */ } }, { once: true });
    }
    syncAudio();
    a.play().then(() => { $('playBtn').textContent = '정지'; }).catch(() => toast('이 오디오는 여기서 재생할 수 없습니다.'));
  }

  // ---- add / edit
  function metaOf(d) {
    return { title: d.title, artist: d.artist, creator: d.creator, version: d.version, keys: d.keys, lengthMs: d.lengthMs,
      bpm: d.bpm, bpmMin: d.bpmMin, bpmMax: d.bpmMax, notes: d.notes, lns: d.lns, hasBg: d.hasBg, audioExt: d.audioExt };
  }

  async function addOrSave() {
    const c = S.cur;
    if (!c || !c.detail.hasAudio) return;
    const p = S.project;
    p.followPitch = c.follow;
    let entry;
    const fresh = () => ({ md5: c.md5, rate: c.rate, followPitch: c.follow, version: '', versionEdited: false,
      meta: metaOf(c.detail), rating: c.rating, bg: { x: 50, y: 50, zoom: 1 } });
    const replacing = !c.editUid && S.replace && p.edit ? S.replace : null;
    if (c.editUid) {
      entry = p.entries.find(e => e.uid === c.editUid);
      if (!entry) return;
      Object.assign(entry, { rate: c.rate, followPitch: c.follow, rating: c.rating, meta: metaOf(c.detail) });
    } else if (replacing) {                         // takes the place (and the online id) of an original difficulty
      entry = p.entries.find(e => e.slot === replacing.slot);
      if (entry) {
        for (const k of ['bgAsset', 'fx', 'symbols', 'layers']) delete entry[k];      // those belonged to the old map
        Object.assign(entry, fresh());
      } else {
        entry = Object.assign({ uid: newUid(), slot: replacing.slot }, fresh());
        p.entries.push(entry);
      }
    } else {
      entry = Object.assign({ uid: newUid() }, fresh());
      p.entries.push(entry);
    }
    if (p.edit && MPC.edit && !c.editUid) MPC.edit.named(entry);    // an original difficulty put back keeps its own name
    applyTemplate(false);
    const wasEdit = !!c.editUid;
    c.editUid = null;
    S.replace = null;
    addLabel();
    renderEntries();
    changed();
    toast(wasEdit ? '바꾼 내용을 저장했습니다.' : replacing ? '"' + replacing.label + '" 자리에 ' + entry.meta.title + ' ' + fmtRate(entry.rate) + '× 를 넣었습니다.'
      : entry.meta.title + ' ' + fmtRate(entry.rate) + '× 를 팩에 넣었습니다.');
    if (replacing) show('edit');
    if (!entry.rating || entry.rating.rate !== entry.rate) {       // added before the estimate came back
      try {
        const res = await api('/api/rating?md5=' + entry.md5 + '&rate=' + entry.rate);
        entry.rating = res.rating; applyTemplate(false); renderEntries(); changed();
      } catch (e) { /* stays without an estimate */ }
    }
  }

  const newUid = () => 'e' + Date.now().toString(36) + Math.random().toString(36).slice(2, 6);

  // ------------------------------------------------------------ pack list
  /* The two ladders of one entry. Older saved entries only carry dan/danOther. */
  function dansOf(e) {
    const r = (e && e.rating) || {};
    let rice = r.rice, ln = r.ln;
    if (rice === undefined && ln === undefined) {
      const both = [r.dan, r.danOther].filter(Boolean);
      rice = both.find(d => d.family === 'rice') || null;
      ln = both.find(d => d.family === 'ln') || null;
    }
    return { rice: rice || null, ln: ln || null, primary: r.dan || null };
  }

  /* mode: 'rice' (no LN map), 'ln' (every map is an LN map) or 'mixed'; out: entries more than one
     dan away from the median of their own ladder. */
  function packInfo() {
    const rows = S.project.entries.map(e => ({ e, d: dansOf(e) })).filter(r => r.d.primary && r.d.primary.raw != null);
    const lnCount = rows.filter(r => r.d.primary.family === 'ln').length;
    const mode = !lnCount ? 'rice' : lnCount === rows.length ? 'ln' : 'mixed';
    const out = new Set(), medians = {};
    for (const fam of ['rice', 'ln']) {
      const list = rows.filter(r => r.d.primary.family === fam);
      if (!list.length) continue;
      const raws = list.map(r => r.d.primary.raw).sort((a, b) => a - b);
      const m = raws.length % 2 ? raws[(raws.length - 1) / 2] : (raws[raws.length / 2 - 1] + raws[raws.length / 2]) / 2;
      medians[fam] = m;
      if (list.length >= 3) list.forEach(r => { if (Math.abs(r.d.primary.raw - m) > 1.0) out.add(r.e.uid); });
    }
    return { out, medians, mode, rows };
  }
  const outliers = packInfo;

  function renderSpread(info) {
    $('spread').hidden = info.rows.length < 2;
    if (info.rows.length < 2) return;
    const host = $('spreadRows');
    host.textContent = '';
    const fams = info.mode === 'rice' ? ['rice'] : info.mode === 'ln' ? ['ln', 'rice'] : ['rice', 'ln'];
    for (const fam of fams) {
      const pts = info.rows.filter(r => r.d[fam] && r.d[fam].raw != null);
      if (!pts.length) continue;
      const minor = info.mode === 'ln' && fam === 'rice';
      const raws = pts.map(r => r.d[fam].raw);
      const a = Math.floor(Math.min(...raws) - 0.5), b = Math.ceil(Math.max(...raws) + 0.5), span = Math.max(1, b - a);
      const pos = v => ((v - a) / span * 100).toFixed(2) + '%';
      const row = el('div', 'spread-row' + (minor ? ' minor' : ''));
      if (fams.length > 1) row.append(el('span', 'spread-fam', fam === 'ln' ? '롱놋' : '단놋'));
      const body = el('div', 'spread-body'), axis = el('div', 'spread-axis');
      const med = info.medians[fam];
      if (med != null && !minor) {
        const band = el('div', 'band'), line = el('div', 'med');
        band.style.left = pos(Math.max(a, med - 1));
        band.style.width = (Math.min(b, med + 1) - Math.max(a, med - 1)) / span * 100 + '%';
        line.style.left = pos(med);
        axis.append(band, line);
      }
      pts.forEach(r => {
        const main = r.d.primary.family === fam;
        const dot = el('button', 'dot' + (main ? '' : ' side') + (main && info.out.has(r.e.uid) ? ' out' : '')
          + (S.cur && S.cur.editUid === r.e.uid ? ' on' : ''));
        dot.type = 'button';
        dot.style.left = pos(r.d[fam].raw);
        dot.title = r.e.meta.title + '  ' + fmtRate(r.e.rate) + '×  ' + r.d[fam].text;
        dot.setAttribute('aria-label', dot.title);
        dot.addEventListener('click', () => selectMap(r.e.md5, r.e));
        axis.append(dot);
      });
      const low = pts.reduce((m, r) => (r.d[fam].raw < m.d[fam].raw ? r : m));
      const high = pts.reduce((m, r) => (r.d[fam].raw > m.d[fam].raw ? r : m));
      const scale = el('div', 'spread-scale num');
      scale.append(el('span', null, low.d[fam].text), el('span', null, high.d[fam].text));
      body.append(axis, scale);
      row.append(body);
      host.append(row);
    }
    const note = $('spreadNote');
    note.className = info.out.size ? 'out' : 'dim';
    note.textContent = info.out.size ? '다른 맵들과 1단 넘게 차이 나는 맵 ' + info.out.size + '개' : (info.rows.length >= 3 ? '크게 튀는 맵 없음' : '');
  }

  function danChip(dan, label, small) {
    const c = el('span', 'dn' + (small ? ' small' : ''));
    if (label) c.append(el('i', null, label));
    if (dan.image) { const img = el('img'); img.src = '/dans/' + dan.image; img.alt = ''; c.append(img); }
    c.append(el('span', null, label ? dan.name : dan.text));
    return c;
  }

  let dragFrom = -1;
  function renderEntries() {
    const p = S.project, list = $('entries');
    list.textContent = '';
    $('packEmpty').hidden = p.entries.length > 0;
    $('packClear').hidden = !p.entries.length;
    const info = outliers();
    const total = p.entries.reduce((s, e) => s + (e.meta.lengthMs || 0) / e.rate, 0);
    $('packSummary').textContent = p.entries.length ? p.entries.length + '개  ' + fmtTime(total) : '';
    const gone = p.entries.filter(e => S.missing.has(e.md5)).length;
    $('packMissing').hidden = !gone;
    if (gone) $('packMissing').textContent = '이 PC의 osu!에 없는 맵이 ' + gone + '개 있습니다 (빨간 글씨). 그 맵은 내보낼 수 없습니다. 맵을 받은 뒤 "맵 목록"의 "목록 새로 읽기"를 누르거나 팩에서 빼 주세요.';
    p.entries.forEach((e, i) => {
      const li = el('li', (S.cur && S.cur.editUid === e.uid ? 'on ' : '') + (info.out.has(e.uid) ? 'out' : ''));
      li.draggable = true;
      li.tabIndex = 0;
      const th = thumbBox('span', 'th', e.md5, e.meta.hasBg);
      const text = el('span');
      const sub = el('span', 's');
      sub.append(el('span', 'rate', fmtRate(e.rate) + '×'), el('span', null, e.followPitch && e.rate !== 1 ? '피치 변경' : e.rate !== 1 ? '피치 유지' : ''), el('span', null, fmtTime(e.meta.lengthMs / e.rate)));
      if (S.missing.has(e.md5)) sub.append(el('span', 'missing', 'osu!에 없음'));
      if (p.edit) sub.append(el('span', 'idtag', e.slot ? 'ID ' + e.slot : '새 난이도'));
      text.className = 'tx';
      text.append(el('span', 't', e.meta.title), el('span', 'v', e.meta.version), sub);
      text.title = e.meta.title + '  [' + e.meta.version + ']';
      const d = el('span', 'd'), ds = dansOf(e);
      if (info.mode === 'rice' || !ds.primary) { if (ds.primary) d.append(danChip(ds.primary)); }
      else if (info.mode === 'ln') {                 // an LN pack: the LN dan first, the rice dan small beside it
        if (ds.ln) d.append(danChip(ds.ln, '롱놋'));
        if (ds.rice) d.append(danChip(ds.rice, '단놋', true));
      } else {
        if (ds.rice) d.append(danChip(ds.rice, '단놋', ds.primary.family !== 'rice'));
        if (ds.ln) d.append(danChip(ds.ln, '롱놋', ds.primary.family !== 'ln'));
      }
      if (!d.childNodes.length && e.rating && e.rating.msd) d.append(el('span', null, 'MSD ' + e.rating.msd.toFixed(1)));
      const acts = el('span', 'acts');
      const mk = (label, title, fn, danger) => {
        const b = el('button', 'btn quiet icon' + (danger ? ' danger' : ''), label);
        b.type = 'button'; b.title = title; b.setAttribute('aria-label', title);
        b.addEventListener('click', ev => { ev.stopPropagation(); fn(); });
        acts.append(b);
      };
      mk('↑', '위로', () => moveEntry(i, i - 1));
      mk('↓', '아래로', () => moveEntry(i, i + 1));
      mk('', '팩에서 빼기', () => removeEntry(e.uid), true);
      li.append(el('span', 'idx', String(i + 1)), th, text, d, acts);
      li.addEventListener('click', () => selectMap(e.md5, e));
      li.addEventListener('keydown', ev => { if (ev.key === 'Enter') selectMap(e.md5, e); if (ev.key === 'Delete') removeEntry(e.uid); });
      li.addEventListener('dragstart', ev => { dragFrom = i; li.classList.add('dragging'); ev.dataTransfer.effectAllowed = 'move'; });
      li.addEventListener('dragend', () => { dragFrom = -1; list.querySelectorAll('.over,.dragging').forEach(n => n.classList.remove('over', 'dragging')); });
      li.addEventListener('dragover', ev => { if (dragFrom < 0) return; ev.preventDefault(); list.querySelectorAll('.over').forEach(n => n.classList.remove('over')); li.classList.add('over'); });
      li.addEventListener('drop', ev => { ev.preventDefault(); if (dragFrom >= 0 && dragFrom !== i) moveEntry(dragFrom, dragFrom < i ? i - 1 : i); });
      list.append(li);
    });
    renderSpread(info);
    $('exportBtn').textContent = '내보내기' + (p.entries.length ? ' (' + p.entries.length + ')' : '');
  }

  function moveEntry(from, to) {
    const list = S.project.entries;
    if (to < 0 || to >= list.length || from === to) return;
    list.splice(to, 0, list.splice(from, 1)[0]);
    applyTemplate(false);
    renderEntries(); changed();
  }

  function removeEntry(uid) {
    const p = S.project;
    p.entries = p.entries.filter(e => e.uid !== uid);
    if (S.cur && S.cur.editUid === uid) { S.cur.editUid = null; addLabel(); }
    applyTemplate(false);
    renderEntries(); changed();
  }

  // ------------------------------------------------------------ metadata view
  function entryLabel(e, i) { return (i + 1) + '. ' + e.meta.title + '  ' + fmtRate(e.rate) + '×'; }

  function fillEntrySelect(select, value) {
    select.textContent = '';
    S.project.entries.forEach((e, i) => { const o = el('option', null, entryLabel(e, i)); o.value = e.uid; select.append(o); });
    if (value && S.project.entries.some(e => e.uid === value)) select.value = value;
  }

  function renderMeta() {
    const p = S.project, pk = p.pack, d = p.delete;
    $('pTitle').value = pk.title; $('pArtist').value = pk.artist; $('pCreator').value = pk.creator;
    $('pSource').value = pk.source; $('pTags').value = pk.tags; $('pResetIds').checked = pk.resetIds !== false;
    $('pResetIds').disabled = !!p.edit;
    $('pTagsPer').checked = !!pk.tagsPerMap;
    $('tagsPerBody').hidden = !pk.tagsPerMap;
    document.querySelectorAll('input[name="tagsMode"]').forEach(r => { r.checked = r.value === (pk.tagsMode === 'own' ? 'own' : 'add'); });
    $('pTagsNote').textContent = pk.tagsPerMap ? '띄어쓰기로 구분. 공통 태그: 모든 난이도와 delete 난이도에 들어갑니다' : '띄어쓰기로 구분. 모든 난이도에 똑같이 들어갑니다';
    $('tagsPerHint').textContent = (pk.tagsMode === 'own'
      ? '오른쪽 목록에서 맵마다 태그를 적습니다. 적은 맵은 그 태그만 들어가고, 비워 둔 맵은 공통 태그가 들어갑니다.'
      : '오른쪽 목록에서 맵마다 더 넣을 태그를 적습니다. 공통 태그 뒤에 붙고, 겹치는 말은 한 번만 들어갑니다.')
      + (p.edit && !p.edit.unify ? ' 기존 맵팩 수정에서 "메타데이터도 통일"을 끄면 그대로 둔 난이도의 태그는 바뀌지 않습니다.' : '');
    $('diffHead').textContent = pk.tagsPerMap ? '난이도명 · 맵별 태그' : '난이도명';
    $('pResetHint').textContent = p.edit
      ? '기존 맵셋을 고치는 중이라 이 설정은 쓰지 않습니다. 모든 난이도에 맵셋의 온라인 ID(' + p.edit.setId + ')가 들어가고, 원래 난이도의 자리를 이은 난이도는 그 BeatmapID를 그대로 가집니다.'
      : '모든 난이도의 BeatmapID를 0, BeatmapSetID를 -1로 바꿉니다. 원본 맵의 온라인 ID가 남아 있으면 업로드할 때 다른 사람의 맵으로 인식되므로, 새로 올리는 팩이라면 켜 두세요.';
    $('pOd').value = pk.od; $('pHp').value = pk.hp; $('pTemplate').value = pk.template;
    $('dEnabled').checked = d.enabled; $('dBody').hidden = !d.enabled;
    $('dName').value = d.name; $('dMinutes').value = d.minutes;
    if (!p.entries.some(e => e.uid === d.thumb.uid)) d.thumb.uid = p.entries[0] ? p.entries[0].uid : null;
    if (!p.entries.some(e => e.uid === d.preview.uid)) d.preview.uid = p.entries[0] ? p.entries[0].uid : null;
    fillEntrySelect($('dThumbEntry'), d.thumb.uid);
    fillEntrySelect($('dPrevEntry'), d.preview.uid);
    document.querySelectorAll('input[name="dThumb"]').forEach(r => { r.checked = r.value === d.thumb.mode; });
    document.querySelectorAll('input[name="dPrev"]').forEach(r => { r.checked = r.value === d.preview.mode; });
    $('dThumbEntry').hidden = d.thumb.mode !== 'entry';
    $('dThumbFileRow').hidden = d.thumb.mode !== 'file';
    $('dThumbDesignRow').hidden = d.thumb.mode !== 'file';
    $('dThumbDesign').checked = d.thumb.design !== false;
    $('dThumbName').textContent = d.thumb.asset ? d.thumb.name || '고른 이미지' : '아직 고르지 않았습니다';
    $('dPrevEntry').hidden = d.preview.mode !== 'entry';
    $('dPrevFileRow').hidden = d.preview.mode !== 'file';
    $('dPrevName').textContent = d.preview.asset ? d.preview.name || '고른 음악' : '아직 고르지 않았습니다';
    $('dPrevStart').value = d.preview.start || 0;
    $('dPrevPlayRow').hidden = d.preview.mode === 'none';
    $('dPrevHint').textContent = d.preview.mode === 'none'
      ? '사이트에서 맵팩의 재생 버튼을 눌러도 아무 소리도 나지 않습니다.'
      : 'delete 난이도의 빈 오디오 한가운데에 이 음악이 30초 들어가고, 그 지점이 미리듣기 시작점(PreviewTime)으로 자동 설정됩니다. 전체 길이는 그대로 유지됩니다.';
    renderDiffList();
  }

  const TAGS_MAX = 1000;
  const words = s => String(s || '').split(/\s+/).filter(Boolean);

  /* The tags one map is exported with: the pack's, or with "맵마다 태그를 따로 지정" on, the pack's plus its own
     (no word twice) or its own alone. A map with no tags of its own always gets the pack's. */
  function tagsFor(e) {
    const pk = S.project.pack, common = words(pk.tags), own = words(e.tags);
    if (!pk.tagsPerMap || !own.length) return common.join(' ');
    if (pk.tagsMode === 'own') return own.join(' ');
    const have = new Set(common.map(w => w.toLowerCase())), out = common.slice();
    own.forEach(w => { if (!have.has(w.toLowerCase())) { have.add(w.toLowerCase()); out.push(w); } });
    return out.join(' ');
  }

  function renderDiffList() {
    const p = S.project, list = $('diffList');
    list.textContent = '';
    $('diffEmpty').hidden = p.entries.length > 0;
    const seen = {};
    p.entries.forEach(e => { const k = (e.version || '').toLowerCase(); seen[k] = (seen[k] || 0) + 1; });
    p.entries.forEach((e, i) => {
      const li = el('li', seen[(e.version || '').toLowerCase()] > 1 ? 'dup' : '');
      const th = thumbBox('span', 'th', e.md5, e.meta.hasBg);
      const body = el('div');
      body.style.minWidth = '0';
      const src = el('div', 'src');
      src.append(el('b', null, e.meta.title), el('span', 'clip', '[' + e.meta.version + ']'), el('span', 'num', fmtRate(e.rate) + '×'),
        el('span', null, e.rating && e.rating.dan ? e.rating.dan.text : ''));
      if (p.edit) src.append(el('span', 'idtag', e.slot ? 'ID ' + e.slot : '새 난이도'));
      if (S.missing.has(e.md5)) src.append(el('span', 'missing', 'osu!에 없음'));
      const line = el('div', 'in');
      const input = el('input');
      input.type = 'text'; input.value = e.version || ''; input.spellcheck = false; input.autocomplete = 'off';
      input.setAttribute('aria-label', (i + 1) + '번 난이도명');
      const len = el('span', 'len' + ((e.version || '').length > NOTICE_MAX ? ' over' : ''), (e.version || '').length + '/' + NOTICE_MAX);
      input.addEventListener('input', () => {
        e.version = input.value; e.versionEdited = true;
        len.textContent = input.value.length + '/' + NOTICE_MAX;
        len.classList.toggle('over', input.value.length > NOTICE_MAX);
        changed();
      });
      input.addEventListener('change', renderDiffList);
      const again = el('button', 'btn quiet', '규칙대로');
      again.type = 'button'; again.title = '이름 규칙으로 다시 채우기';
      again.hidden = !e.versionEdited;
      again.addEventListener('click', () => { e.versionEdited = false; e.version = versionFor(e, i); renderDiffList(); changed(); });
      line.append(input, len, again);
      body.append(src, line);
      if (p.pack.tagsPerMap) {
        const row = el('div', 'in tagsin');
        const tags = el('input');
        tags.type = 'text'; tags.value = e.tags || ''; tags.spellcheck = false; tags.autocomplete = 'off';
        tags.placeholder = p.pack.tagsMode === 'own' ? '이 맵의 태그 (비우면 공통 태그)' : '이 맵에만 더 넣을 태그';
        tags.setAttribute('aria-label', (i + 1) + '번 맵의 태그');
        const count = el('span', 'len wide');
        const show = () => { const n = tagsFor(e).length; count.textContent = n + '/' + TAGS_MAX; count.classList.toggle('over', n > TAGS_MAX); };
        show();
        tags.addEventListener('input', () => { e.tags = tags.value; show(); changed(); });
        const orig = el('button', 'btn quiet', '원본 태그');
        orig.type = 'button'; orig.title = '원본 맵에 적혀 있던 태그를 가져옵니다';
        orig.addEventListener('click', async () => {
          const got = await originalTags(e);
          if (got == null) { toast('원본 맵을 읽지 못했습니다.'); return; }
          if (!got) { toast('원본 맵에 태그가 없습니다.'); return; }
          e.tags = got; tags.value = got; show(); changed();
        });
        row.append(el('span', 'lab', '태그'), tags, count, orig);
        body.append(row);
      }
      li.append(el('span', 'idx', String(i + 1)), th, body);
      list.append(li);
    });
  }

  async function originalTags(e) {
    try { const d = await api('/api/map?md5=' + e.md5); return d ? words(d.tags).join(' ') : null; } catch (err) { return null; }
  }

  function bindMeta() {
    const pk = () => S.project.pack, d = () => S.project.delete;
    const text = (id, set, after) => $(id).addEventListener('input', ev => { set(ev.target.value); if (after) after(); changed(); });
    text('pTitle', v => { pk().title = v; });
    text('pArtist', v => { pk().artist = v; });
    text('pCreator', v => { pk().creator = v; });
    text('pSource', v => { pk().source = v; });
    text('pTags', v => { pk().tags = v; }, () => { if (pk().tagsPerMap) renderDiffList(); });
    $('pTagsPer').addEventListener('change', ev => { pk().tagsPerMap = ev.target.checked; renderMeta(); changed(); });
    document.querySelectorAll('input[name="tagsMode"]').forEach(r => r.addEventListener('change', () => { pk().tagsMode = r.value; renderMeta(); changed(); }));
    $('tagsFromOriginal').addEventListener('click', async () => {
      const list = S.project.entries;
      if (!list.length) { toast('팩에 넣은 맵이 없습니다.'); return; }
      if (list.some(e => (e.tags || '').trim()) && !(await confirmBox('이미 적어 둔 맵별 태그를 원본 맵의 태그로 바꿀까요?', { yes: '원본 태그로 바꾸기' }))) return;
      let n = 0;
      for (const e of list) { const got = await originalTags(e); if (got != null) { e.tags = got; if (got) n++; } }
      renderDiffList(); changed();
      toast(n ? '맵 ' + n + '개에 원본 태그를 가져왔습니다.' : '가져올 원본 태그가 없습니다.');
    });
    $('tagsPerClear').addEventListener('click', async () => {
      if (!S.project.entries.some(e => (e.tags || '').trim())) { toast('지울 맵별 태그가 없습니다.'); return; }
      if (!(await confirmBox('맵마다 따로 적은 태그를 모두 지울까요? 공통 태그는 그대로 둡니다.', { danger: true, yes: '맵별 태그 모두 지우기' }))) return;
      S.project.entries.forEach(e => { delete e.tags; });
      renderDiffList(); changed();
    });
    text('pOd', v => { pk().od = v.trim(); });
    text('pHp', v => { pk().hp = v.trim(); });
    text('pTemplate', v => { pk().template = v; }, () => { applyTemplate(false); renderDiffList(); });
    $('pResetIds').addEventListener('change', ev => { pk().resetIds = ev.target.checked; changed(); });
    $('applyTemplate').addEventListener('click', () => { applyTemplate(true); renderDiffList(); renderEntries(); changed(); });
    $('tagsFromMaps').addEventListener('click', () => {
      const have = new Set(pk().tags.toLowerCase().split(/\s+/).filter(Boolean)), add = [];
      S.project.entries.forEach(e => { const c = (e.meta.creator || '').trim(); if (c && !have.has(c.toLowerCase())) { have.add(c.toLowerCase()); add.push(c); } });
      if (!add.length) { toast('더 넣을 제작자 이름이 없습니다.'); return; }
      pk().tags = (pk().tags.trim() + ' ' + add.join(' ')).trim();
      $('pTags').value = pk().tags; changed();
    });
    $('dEnabled').addEventListener('change', ev => { d().enabled = ev.target.checked; renderMeta(); changed(); });
    text('dName', v => { d().name = v; });
    text('dMinutes', v => { d().minutes = v.trim(); });
    $('dMinutes').addEventListener('change', ev => { const v = clamp(parseFloat(ev.target.value) || 10, 5, 30); d().minutes = v; ev.target.value = v; changed(); });
    document.querySelectorAll('input[name="dThumb"]').forEach(r => r.addEventListener('change', () => { d().thumb.mode = r.value; renderMeta(); changed(); }));
    document.querySelectorAll('input[name="dPrev"]').forEach(r => r.addEventListener('change', () => { stopDeletePreview(); d().preview.mode = r.value; renderMeta(); changed(); }));
    $('dPrevPlay').addEventListener('click', toggleDeletePreview);
    $('dPrevEntry').addEventListener('change', stopDeletePreview);
    $('dEnabled').addEventListener('change', stopDeletePreview);
    $('dThumbEntry').addEventListener('change', ev => { d().thumb.uid = ev.target.value; changed(); });
    $('dPrevEntry').addEventListener('change', ev => { d().preview.uid = ev.target.value; changed(); });
    $('dThumbDesign').addEventListener('change', ev => { d().thumb.design = ev.target.checked; changed(); });
    $('dThumbPick').addEventListener('click', async () => {
      const file = await pickFile('image/png,image/jpeg,image/webp,image/gif,image/bmp');
      const id = file && await upload(file);
      if (!id) return;
      Object.assign(d().thumb, { asset: id, name: file.name, mode: 'file' });
      renderMeta(); changed();
    });
    $('dPrevPick').addEventListener('click', async () => {
      const file = await pickFile('.mp3,.ogg,.wav,.flac,.m4a,audio/*');
      const id = file && await upload(file);
      if (!id) return;
      Object.assign(d().preview, { asset: id, name: file.name, mode: 'file' });
      renderMeta(); changed();
    });
    $('dPrevStart').addEventListener('change', ev => { const v = Math.max(0, parseFloat(ev.target.value) || 0); d().preview.start = v; ev.target.value = v; changed(); });
  }

  // ------------------------------------------------------------ export
  let exJob = null, exPoll = 0;

  function problems() {
    const p = S.project, list = [];
    const block = t => list.push({ text: t, block: true }), warn = t => list.push({ text: t, block: false });
    if (!p.entries.length) block('팩에 넣은 맵이 없습니다.');
    if (!p.pack.title.trim()) block('맵팩 이름이 비어 있습니다. 메타데이터에서 적어 주세요.');
    if (!p.pack.creator.trim()) block('제작자(Creator)가 비어 있습니다. 메타데이터에서 적어 주세요.');
    if (!S.tools.ffmpeg) block('ffmpeg.exe가 없습니다. 프로그램과 같은 폴더에 ffmpeg.exe를 넣어 주세요.');
    const gone = p.entries.filter(e => S.missing.has(e.md5)).length;
    if (gone) block('이 PC의 osu!에 없는 맵이 ' + gone + '개 있습니다. 맵을 받은 뒤 목록을 새로 읽거나 팩에서 빼 주세요.');
    if (p.edit && MPC.edit) MPC.edit.problems(block, warn);
    const names = {};
    p.entries.forEach(e => { const k = (e.version || '').trim().toLowerCase(); names[k] = (names[k] || 0) + 1; });
    if (p.delete.enabled) { const k = (p.delete.name || 'delete').trim().toLowerCase(); names[k] = (names[k] || 0) + 1; }
    if (Object.values(names).some(n => n > 1)) block('같은 난이도명이 두 개 이상 있습니다. 메타데이터에서 고쳐 주세요.');
    if (p.entries.some(e => !(e.version || '').trim())) block('비어 있는 난이도명이 있습니다.');
    if (p.delete.enabled && p.delete.thumb.mode === 'file' && !p.delete.thumb.asset) block('delete 난이도 썸네일 이미지를 아직 고르지 않았습니다.');
    if (p.delete.enabled && p.delete.preview.mode === 'file' && !p.delete.preview.asset) block('delete 난이도 미리듣기 음악을 아직 고르지 않았습니다.');
    const od = p.pack.od, hp = p.pack.hp;
    if ((od !== '' && !(parseFloat(od) >= 0 && parseFloat(od) <= 10)) || (hp !== '' && !(parseFloat(hp) >= 0 && parseFloat(hp) <= 10))) block('OD와 HP는 0에서 10 사이 숫자여야 합니다.');
    const out = outliers().out.size;
    if (out) warn('예상 난이도가 다른 맵들과 1단 넘게 차이 나는 맵이 ' + out + '개 있습니다.');
    if (p.entries.some(e => (e.version || '').length > NOTICE_MAX)) warn('난이도명이 80자를 넘는 맵이 있습니다. osu!에서 잘릴 수 있습니다.');
    if (p.thumb.format === 'png') warn('썸네일이 png입니다. 화질은 좋지만 맵팩 용량이 커져 업로드가 힘들 수 있습니다.');
    if (!p.pack.tags.trim()) warn('태그가 비어 있습니다.');
    if (p.pack.tagsPerMap) {
      const each = p.entries.map(tagsFor);
      if (each.some(t => t.length > TAGS_MAX)) warn('태그가 1000자를 넘는 맵이 있습니다. 업로드가 거부될 수 있습니다.');
      if (new Set(each.concat(p.delete.enabled ? [words(p.pack.tags).join(' ')] : [])).size > 1) {
        warn('난이도마다 태그가 다릅니다. 사이트에는 맵셋 태그가 하나만 남고, 공개된 osu! 업로드 서버 코드는 태그가 다른 맵셋을 거부합니다 ("inconsistent Tags"). 업로드가 거부되면 메타데이터의 "맵마다 태그를 따로 지정"을 끄고 다시 내보내세요.');
      }
    }
    if (!p.delete.enabled && !p.edit) warn('delete 난이도를 넣지 않습니다. 용량이 큰 팩은 업로드가 막힐 수 있습니다.');
    return list;
  }

  function exShow(part) { for (const id of ['exStart', 'exRun', 'exDone', 'exFail']) $(id).hidden = id !== part; }

  function openExport() {
    const p = S.project, list = problems();
    exShow('exStart');
    const total = p.entries.reduce((s, e) => s + (e.meta.lengthMs || 0) / e.rate, 0);
    $('exSummary').textContent = '"' + (p.pack.title.trim() || '이름 없는 팩') + '"' + (p.edit ? ' 수정본' : '') + '  난이도 ' + p.entries.length + '개' + (p.delete.enabled ? ' + delete' : '') + ',  합계 ' + fmtTime(total);
    $('exportTitle').textContent = p.edit ? '수정본 내보내기' : '내보내기';
    const host = $('exProblems');
    host.textContent = '';
    list.forEach(item => host.append(el('li', item.block ? 'block' : '', item.text)));
    $('exGo').disabled = list.some(i => i.block);
    $('exGuide').hidden = !p.delete.enabled || !!p.edit;
    $('exGuideEdit').hidden = !p.edit;
    $('exDestBox').hidden = !!p.edit;
    $('destPacks').textContent = S.packsDir;
    $('destSongs').textContent = S.lib.songs || '';
    document.querySelectorAll('input[name="dest"]').forEach(r => { r.checked = r.value === (S.settings.dest || 'packs'); r.disabled = r.value === 'songs' && !S.lib.songs; });
    $('exBitrate').value = String(S.settings.bitrate || 192);
    $('exOsz').checked = !!S.settings.osz;
    if (!$('exportDlg').open) $('exportDlg').showModal();
  }

  async function startExport() {
    const p = S.project;
    if (!p.edit) S.settings.dest = (document.querySelector('input[name="dest"]:checked') || {}).value || 'packs';
    S.settings.bitrate = Number($('exBitrate').value);
    S.settings.osz = $('exOsz').checked;
    api('/api/settings', S.settings).catch(() => {});
    const payload = {
      pack: p.pack, bitrate: S.settings.bitrate, imageFormat: p.thumb.format, osz: S.settings.osz, dest: S.settings.dest,
      entries: p.entries.map(e => ({ uid: e.uid, md5: e.md5, rate: e.rate, followPitch: !!e.followPitch, version: (e.version || '').trim(),
        slot: p.edit ? e.slot || 0 : 0, tags: p.pack.tagsPerMap ? tagsFor(e) : undefined })),
      delete: { enabled: p.delete.enabled, name: p.delete.name, minutes: p.delete.minutes,
        preview: { mode: p.delete.preview.mode, uid: p.delete.preview.uid, asset: p.delete.preview.asset,
          start: p.delete.preview.start, length: p.delete.preview.length } },
    };
    if (p.edit) {
      payload.mode = 'edit';
      payload.edit = { folder: p.edit.folder, setId: p.edit.setId, thumbs: p.edit.thumbs !== false, unify: !!p.edit.unify,
        deleteSlot: p.delete.enabled ? p.edit.deleteSlot || 0 : 0, carry: p.edit.carry || [] };
    }
    $('exportTitle').textContent = p.edit ? '수정본 내보내기' : '내보내기';
    await runExport(payload, plan => {
      const jobs = plan.images.slice();
      if (plan.deleteImage) jobs.push({ uid: 'delete', name: plan.deleteImage });
      return jobs;
    }, uid => Thumb.exportBlob(uid));
  }

  /* begin -> draw and send the pictures -> run -> watch. blobOf(uid) draws one picture. */
  async function runExport(payload, jobsOf, blobOf) {
    if (!$('exportDlg').open) $('exportDlg').showModal();
    exShow('exRun');
    $('exItems').textContent = ''; $('exBar').style.width = '0';
    $('exStep').textContent = '준비하는 중';
    $('exCancel').disabled = false;
    let plan;
    try { plan = await api('/api/export/begin', payload); } catch (e) { plan = { ok: false, message: String(e) }; }
    if (!plan.ok) return exFail(plan.message || '시작하지 못했습니다.');
    exJob = plan.job;
    try {
      const jobs = jobsOf(plan);
      for (let i = 0; i < jobs.length; i++) {
        if (exJob !== plan.job) return;
        $('exStep').textContent = '썸네일을 만드는 중  ' + (i + 1) + ' / ' + jobs.length;
        $('exBar').style.width = (i / jobs.length * 30).toFixed(1) + '%';
        const blob = await blobOf(jobs[i].uid);
        if (!blob) continue;
        const res = await api('/api/export/image?job=' + plan.job + '&name=' + q(jobs[i].name), blob, true);
        if (!res.ok) throw new Error('썸네일을 저장하지 못했습니다.');
      }
      const run = await api('/api/export/run', { job: plan.job });
      if (!run.ok) throw new Error('내보내기를 시작하지 못했습니다.');
    } catch (e) {
      api('/api/export/cancel', {}).catch(() => {});
      return exFail(e.message || String(e));
    }
    pollExport();
  }

  async function pollExport() {
    clearTimeout(exPoll);
    let st;
    try { st = await api('/api/export/status'); } catch (e) { exPoll = setTimeout(pollExport, 800); return; }
    if (st.job !== exJob) return;
    if (st.state === 'running') {
      $('exStep').textContent = (st.step || '작업 중') + (st.total ? '  ' + st.done + ' / ' + st.total : '');
      $('exBar').style.width = (30 + (st.total ? st.done / st.total : 0) * 70).toFixed(1) + '%';
      const host = $('exItems');
      host.textContent = '';
      st.items.forEach(item => {
        const li = el('li');
        li.append(el('span', null, item.version), el('span', 'st ' + item.status, item.status === 'done' ? '완료' : item.status === 'work' ? '변환 중' : '대기'));
        host.append(li);
      });
      exPoll = setTimeout(pollExport, 450);
      return;
    }
    if (st.state === 'done') return exDone(st);
    if (st.state === 'cancelled') { $('exportDlg').close(); toast('내보내기를 취소했습니다.'); return; }
    exFail(st.error || '알 수 없는 오류');
  }

  function exDone(st) {
    exShow('exDone');
    exJob = null;
    const size = (st.size / 1048576).toFixed(1) + ' MB';
    $('exDoneLead').textContent = st.mode === 'rate'
      ? '배속 난이도 ' + st.items.length + '개를 만들었습니다.  ' + size + (st.inPlace ? '   osu! 곡 선택 화면에서 F5를 누르면 보입니다.' : '')
      : st.mode === 'edit' ? '수정본을 만들었습니다.  ' + size + '   원본 폴더는 건드리지 않았습니다.'
        : '내보내기를 마쳤습니다.  ' + size;
    $('exDoneEdit').hidden = st.mode !== 'edit';
    if (st.mode === 'edit' && MPC.edit) MPC.edit.report(st);
    $('exFolder').textContent = st.folder + (st.osz ? '\n' + st.osz : '');
    $('exFolder').style.whiteSpace = 'pre-line';
    $('exDoneGuide').hidden = !st.delete || st.mode === 'edit';
    const body = $('exReport');
    body.textContent = '';
    let worst = 0, stretched = 0;
    st.items.forEach(item => {
      const r = item.report || {}, tr = el('tr');
      const mode = (MODE_KO[r.mode] || '') + (r.trimmed ? ', 태그 없는 mp3 12ms 보정' : '');
      const shift = r.shift_ms == null ? '' : (r.shift_ms > 0 ? '+' : '') + r.shift_ms.toFixed(2) + ' ms';
      const left = r.mode === 'stretch' ? (r.residual_ms == null ? '측정 불가' : (r.residual_ms > 0 ? '+' : '') + r.residual_ms.toFixed(2) + ' ms') : '0 (정확)';
      if (r.mode === 'stretch') { stretched++; if (r.residual_ms != null) worst = Math.max(worst, Math.abs(r.residual_ms)); }
      tr.append(el('td', null, item.version), el('td', 'r', Number(item.rate).toFixed(2) + '×'), el('td', null, mode), el('td', 'r', shift), el('td', 'r', left));
      body.append(tr);
    });
    $('exReportNote').textContent = stretched ? '피치 유지 배속 ' + stretched + '개, 보정 후 최대 오차 ' + worst.toFixed(2) + ' ms' : '모든 오디오가 샘플 단위로 정확합니다';
  }

  function exFail(message) {
    exJob = null;
    exShow('exFail');
    $('exError').textContent = message;
  }

  // ------------------------------------------------------------ wiring
  function buildTicks() {
    const host = $('ticks');
    for (let i = 0; i <= 150; i += 5) {
      const v = 0.5 + i / 100, pct = (i / 150 * 100) + '%';
      const tick = el('i', i % 25 === 0 ? 'big' : i % 10 === 0 ? 'mid' : '');
      tick.style.left = pct;
      host.append(tick);
      if (i % 25 === 0) { const label = el('span', v === 1 ? 'one' : '', v.toFixed(2)); label.style.left = pct; host.append(label); }
    }
  }

  function bind() {
    document.querySelectorAll('.steps button').forEach(b => b.addEventListener('click', () => show(b.dataset.view)));
    $('libToggle').addEventListener('click', () => setLib(!S.settings.libOpen, true));
    // The page itself never scrolls (only the columns inside it do): if anything moves it, put it back.
    const pin = () => {
      if (window.scrollX || window.scrollY) window.scrollTo(0, 0);
      for (const node of [document.body, $('main'), document.querySelector('.views')]) {
        if (node.scrollTop) node.scrollTop = 0;
        if (node.scrollLeft) node.scrollLeft = 0;
      }
    };
    window.addEventListener('scroll', pin, { passive: true });
    document.addEventListener('focusin', () => requestAnimationFrame(pin));
    window.addEventListener('resize', pin);
    bindTips();
    let qTimer = 0;
    $('q').addEventListener('input', ev => { clearTimeout(qTimer); qTimer = setTimeout(() => { S.query = ev.target.value; search(true); }, 160); });
    $('keys').addEventListener('change', ev => { S.keys = Number(ev.target.value); search(true); });
    const rows = $('rows');
    rows.addEventListener('click', ev => { const li = ev.target.closest('li[data-md5]'); if (li) selectMap(li.dataset.md5); });
    rows.addEventListener('keydown', ev => {
      const li = ev.target.closest('li[data-md5]');
      if (!li) return;
      if (ev.key === 'Enter') selectMap(li.dataset.md5);
      if (ev.key === 'ArrowDown' && li.nextElementSibling) { ev.preventDefault(); li.nextElementSibling.focus(); }
      if (ev.key === 'ArrowUp' && li.previousElementSibling) { ev.preventDefault(); li.previousElementSibling.focus(); }
    });
    rows.addEventListener('scroll', () => {
      if (!S.loadingRows && S.rows.length < S.total && rows.scrollTop + rows.clientHeight > rows.scrollHeight - 300) search(false);
    });
    $('rate').addEventListener('input', ev => setRate(ev.target.value));
    $('rateNum').addEventListener('change', ev => setRate(ev.target.value.replace(',', '.')));
    $('rateNum').addEventListener('keydown', ev => {
      if (ev.key === 'Enter') { ev.target.blur(); return; }
      if (ev.key !== 'ArrowUp' && ev.key !== 'ArrowDown') return;
      ev.preventDefault();
      setRate((S.cur ? S.cur.rate : 1) + (ev.key === 'ArrowUp' ? 1 : -1) * (ev.shiftKey ? 0.05 : 0.01));
    });
    $('rateNum').addEventListener('focus', ev => ev.target.select());
    document.querySelector('.ruler').addEventListener('wheel', ev => {
      if (!S.cur) return;
      ev.preventDefault();
      setRate(S.cur.rate + (ev.deltaY < 0 ? 0.01 : -0.01));
    }, { passive: false });
    document.querySelectorAll('[data-step]').forEach(b => b.addEventListener('click', () => { if (S.cur) setRate(S.cur.rate + Number(b.dataset.step)); }));
    $('rateReset').addEventListener('click', () => setRate(1));
    $('followPitch').addEventListener('change', ev => { if (!S.cur) return; S.cur.follow = ev.target.checked; renderPitchHint(); syncAudio(); });
    $('playBtn').addEventListener('click', toggleAudio);
    document.querySelectorAll('input.volume').forEach(i => {
      i.addEventListener('input', () => setVolume(i.value, false));
      i.addEventListener('change', () => setVolume(i.value, true));
    });
    $('player').addEventListener('ended', stopAudio);
    $('addBtn').addEventListener('click', addOrSave);
    $('cancelEdit').addEventListener('click', () => {
      if (!S.cur) return;
      S.cur.editUid = null; addLabel(); renderEntries();
    });
    $('replaceCancel').addEventListener('click', () => { S.replace = null; addLabel(); show('edit'); });
    $('follow').addEventListener('change', ev => {
      S.follow = ev.target.checked; S.settings.follow = S.follow; S.liveSeen = {};
      renderLive(null);
      api('/api/settings', { follow: S.follow }).catch(() => {});
    });
    $('exportBtn').addEventListener('click', openExport);
    $('exGo').addEventListener('click', startExport);
    $('exCancel').addEventListener('click', () => { $('exCancel').disabled = true; $('exStep').textContent = '취소하는 중'; api('/api/export/cancel', {}).catch(() => {}); if (!exJob) $('exportDlg').close(); });
    $('exOpen').addEventListener('click', () => api('/api/open', { what: 'pack' }));
    $('exportDlg').addEventListener('cancel', ev => { if (!$('exRun').hidden) ev.preventDefault(); });
    document.querySelectorAll('dialog [data-close]').forEach(b => b.addEventListener('click', () => b.closest('dialog').close()));
    $('newBtn').addEventListener('click', async () => {
      if (hasWork(S.project) && !(await confirmBox('지금 만들던 팩 구성(넣은 맵, 썸네일 디자인, 메타데이터)을 모두 비우고 새로 시작할까요? 저장해 둔 팩과 내보낸 파일은 그대로 남습니다. 지금 구성을 남기려면 먼저 "저장"을 눌러 주세요.',
        { danger: true, yes: '모두 비우고 새로 시작' }))) return;
      startOver();
    });
    $('packClear').addEventListener('click', async () => {
      if (!(await confirmBox('넣은 맵 ' + S.project.entries.length + '개를 모두 뺄까요? 썸네일 디자인과 메타데이터는 그대로 둡니다.',
        { danger: true, yes: '모두 빼기' }))) return;
      S.project.entries = [];
      if (S.cur) { S.cur.editUid = null; addLabel(); }
      renderEntries(); changed();
    });
    $('metaClear').addEventListener('click', async () => {
      if (!(await confirmBox('맵팩 이름, 출처, 태그, OD/HP, 난이도명 규칙, delete 난이도 설정을 모두 지우고 처음 상태로 되돌릴까요? 넣은 맵과 썸네일 디자인은 그대로 둡니다.',
        { danger: true, yes: '메타데이터 모두 지우기' }))) return;
      const fresh = newProject();
      S.project.pack = fresh.pack;
      S.project.delete = fresh.delete;
      S.project.entries.forEach(e => { delete e.tags; });
      applyTemplate(true);
      renderMeta(); renderEntries(); changed();
      toast('메타데이터를 모두 지웠습니다.');
    });
    bindMeta();
    window.addEventListener('pagehide', () => navigator.sendBeacon('/api/bye?t=' + q(TOKEN), '{}'));
    setInterval(() => api('/api/ping', {}).catch(() => {}), 5000);
  }

  async function boot() {
    buildTicks();
    let state;
    try { state = await api('/api/state'); }
    catch (e) { document.body.textContent = '프로그램과 연결하지 못했습니다. 창을 닫고 다시 실행해 주세요.'; return; }
    S.app = state.app; S.lib = state.library; S.tools = state.tools; S.settings = state.settings; S.packsDir = state.packsDir;
    document.title = state.app.name + ' ' + state.app.byline;
    S.project = adopt(state.project);
    Thumb.init({ project: () => S.project, token: TOKEN, changed, pickFile, upload, toast,
      pickFiles: accept => pickFile(accept, true),
      symbols: () => (Array.isArray(S.settings.customSymbols) ? S.settings.customSymbols : []),
      saveSymbols: list => { S.settings.customSymbols = list; api('/api/settings', { customSymbols: list }).catch(() => {}); } });
    setVolume(S.settings.volume == null ? 50 : S.settings.volume, false);
    S.follow = S.settings.follow !== false;
    setLib(!!S.settings.libOpen, false);
    $('follow').checked = S.follow;
    bind();
    if (MPC.saves) MPC.saves.init();
    if (MPC.edit) MPC.edit.init();
    renderEntries();
    const wanted = new URLSearchParams(location.hash.slice(1)).get('view');      // #view=pack opens that part
    if (!wanted) await askResume();                  // a link straight to a part carries on without asking
    watchLibrary();
    if (MPC.rate) MPC.rate.init();
    if (VIEWS.includes(wanted) && wanted !== 'pick') show(wanted);
    hold();
    pollLive();
    if (!S.tools.ffmpeg) toast('ffmpeg.exe를 찾지 못했습니다. 내보내기에 필요합니다.');
  }

  /* Shared with parts.js (pack overview, rate changer). */
  window.MPC = { S, $, el, api, q, TOKEN, toast, confirmBox, pickFile, upload, changed, fmtRate, fmtTime, fmtBpm, bpmText,
    bgSrc, thumbBox, dansOf, packInfo, danChip, show, selectMap, runExport, renderEntries, applyTemplate, SKILL_KO,
    newProject, adopt, hasWork, setProject, checkMissing, metaOf, newUid, addLabel, openExport, renderMeta,
    exportTitle: text => { $('exportTitle').textContent = text; } };

  boot();
})();
