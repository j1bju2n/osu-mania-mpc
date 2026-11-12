/* Saved packs (the `save` folder beside the program) and the "기존 맵팩 수정" part: an uploaded set rebuilt
   with its online ids kept, so uploading it updates the set instead of making a new one.
   A rebuild is an ordinary pack project with `project.edit` set; the pack tabs (maps, thumbnails, metadata)
   work on it as usual. Entries that stand where an original difficulty stood carry its BeatmapID in `slot`. */
'use strict';
(function () {
  const M = window.MPC, S = M.S, $ = M.$, el = M.el;
  const when = ms => new Date(ms).toLocaleString('ko-KR', { dateStyle: 'medium', timeStyle: 'short' });
  const clamp = (v, a, b) => Math.min(b, Math.max(a, v));

  // ============================================================ notices
  function notice(title, lead, items, hint) {
    $('noticeTitle').textContent = title;
    $('noticeLead').textContent = lead;
    const list = $('noticeList');
    list.textContent = '';
    for (const [main, rest] of items) {
      const li = el('li');
      li.append(el('b', null, main), document.createTextNode('  ' + rest));
      list.append(li);
    }
    $('noticeHint').textContent = hint || '';
    if (!$('noticeDlg').open) $('noticeDlg').showModal();
  }

  let lastReported = '';
  /* Say once which maps of the pack this osu! does not have. */
  function reportMissing(list, what) {
    const key = list.map(e => e.md5).sort().join(',');
    if (!list.length || key === lastReported || document.querySelector('dialog[open]')) return;
    lastReported = key;
    notice('osu!에 없는 맵이 있습니다',
      what + '의 맵 ' + S.project.entries.length + '개 중 ' + list.length + '개가 이 PC의 osu!에 없습니다.',
      list.map(e => [e.meta.title, '[' + e.meta.version + ']   ' + (e.meta.creator || '') + '   ' + M.fmtRate(e.rate) + '×']),
      '없는 맵은 목록에 빨간 글씨로 표시되고, 그대로는 내보낼 수 없습니다. 맵을 osu!에 받은 뒤 "맵 목록"의 "목록 새로 읽기"를 누르거나, 팩에서 빼 주세요. 나머지 맵과 썸네일 디자인, 메타데이터는 그대로 불러왔습니다.');
  }

  // ============================================================ saved packs
  async function listSaves() {
    try { return await M.api('/api/saves'); } catch (e) { return { folder: '', saves: [] }; }
  }

  function saveFacts(row) {
    const facts = [];
    if (row.broken) facts.push('읽을 수 없는 파일');
    if (row.title && row.title !== row.name) facts.push(row.title);
    if (row.maps != null) facts.push('맵 ' + row.maps + '개');
    if (row.edit) facts.push('기존 맵셋 수정');
    facts.push(when(row.savedAt));
    return facts.join('    ');
  }

  async function openSave() {
    const p = S.project;
    if (!M.hasWork(Object.assign({}, p, { rc: null }))) { M.toast('저장할 팩 구성이 아직 없습니다.'); return; }
    const res = await listSaves();
    $('saveName').value = p.saveName || p.pack.title.trim() || '이름 없는 팩';
    $('saveFolder').textContent = '저장 위치   ' + res.folder;
    const list = $('saveList');
    list.textContent = '';
    $('saveListLabel').hidden = !res.saves.length;
    const mark = () => list.querySelectorAll('li').forEach(li => li.classList.toggle('on', li.dataset.name.toLowerCase() === $('saveName').value.trim().toLowerCase()));
    res.saves.forEach(row => {
      const li = el('li');
      li.dataset.name = row.name;
      const nm = el('span', 'nm', row.name);
      nm.append(el('span', 'sub', saveFacts(row)));
      li.append(nm);
      li.addEventListener('click', () => { $('saveName').value = row.name; mark(); });
      list.append(li);
    });
    $('saveName').oninput = mark;
    mark();
    $('saveDlg').showModal();
    $('saveName').select();
  }

  async function doSave(overwrite) {
    const name = $('saveName').value.trim();
    if (!name) { M.toast('저장할 이름을 적어 주세요.'); return; }
    let res;
    try { res = await M.api('/api/save', { name, project: S.project, overwrite: !!overwrite || name === S.project.saveName }); }
    catch (e) { res = { ok: false, message: '저장하지 못했습니다.' }; }
    if (res.exists) {
      if (await M.confirmBox('"' + name + '" 이름으로 저장한 팩이 이미 있습니다. 지금 구성으로 덮어쓸까요?', { yes: '덮어쓰기' })) return doSave(true);
      return;
    }
    if (!res.ok) { M.toast(res.message || '저장하지 못했습니다.'); return; }
    S.project.saveName = res.name;
    M.changed();
    $('saveDlg').close();
    M.toast('"' + res.name + '" 이름으로 저장했습니다.');
  }

  async function openLoad() {
    const res = await listSaves();
    $('loadFolder').textContent = '저장 위치   ' + res.folder;
    const list = $('loadList');
    list.textContent = '';
    $('loadEmpty').hidden = res.saves.length > 0;
    res.saves.forEach(row => {
      const li = el('li');
      const nm = el('span', 'nm', row.name);
      nm.append(el('span', 'sub', saveFacts(row)));
      const go = el('button', 'btn', '불러오기');
      go.type = 'button'; go.disabled = !!row.broken;
      go.addEventListener('click', () => doLoad(row));
      const del = el('button', 'btn quiet danger', '삭제');
      del.type = 'button';
      del.addEventListener('click', async () => {
        if (!(await M.confirmBox('저장한 팩 "' + row.name + '"을(를) 지울까요? save 폴더의 파일이 삭제되며 되돌릴 수 없습니다.', { danger: true, yes: '삭제' }))) return;
        try { await M.api('/api/save/delete', { name: row.name }); } catch (e) { /* the list shows what is left */ }
        if (S.project.saveName === row.name) { S.project.saveName = ''; M.changed(); }
        openLoad();
      });
      li.append(nm, go, del);
      list.append(li);
    });
    if (!$('loadDlg').open) $('loadDlg').showModal();
  }

  async function doLoad(row) {
    const p = S.project;
    if (M.hasWork(Object.assign({}, p, { rc: null }))
      && !(await M.confirmBox('지금 만들던 팩을 닫고 "' + row.name + '"을(를) 불러올까요? 저장하지 않은 팩 구성은 사라집니다. 레이트 체인저는 그대로 둡니다.', { yes: '불러오기' }))) return;
    let res;
    try { res = await M.api('/api/save/load', { name: row.name }); } catch (e) { res = { ok: false }; }
    if (!res.ok) { M.toast(res.message || '이 저장 파일을 읽지 못했습니다.'); return; }
    S.settings.customSymbols = res.symbols || S.settings.customSymbols;      // the pack may bring its own symbols
    $('loadDlg').close();
    lastReported = '';
    const missing = await M.setProject(M.adopt(res.project), res.project.edit ? 'edit' : 'pick', true);
    if (missing && missing.length) reportMissing(missing, '"' + res.name + '"');
    else M.toast('"' + res.name + '"을(를) 불러왔습니다.' + (missing ? '' : ' 맵 목록을 다 읽으면 없는 맵이 있는지 확인합니다.'));
    if (S.project.edit) fetchRatings();
  }

  // ============================================================ rebuilding an uploaded set
  const E = { found: null, seq: 0, busy: false };
  const ed = () => S.project.edit;
  const holderOf = slot => (slot.id ? S.project.entries.find(e => e.slot === slot.id) : null);
  const originalOf = entry => ed().slots.find(s => s.kind !== 'other' && s.md5 === entry.md5) || null;
  const untouched = entry => !!originalOf(entry) && Number(entry.rate) === 1;
  const setTitle = f => { const s = f.slots.find(x => x.kind === 'map') || f.slots[0]; return s ? (s.artist ? s.artist + ' - ' : '') + s.title : f.folder; };

  /* An original difficulty put back as it was keeps the name it has online. */
  function named(entry) {
    const o = ed() && originalOf(entry);
    if (o && Number(entry.rate) === 1) { entry.version = o.version; entry.versionEdited = true; }
  }

  // ---- choosing the set
  async function select(md5) {
    const seq = ++E.seq;
    let found = null;
    try { found = await M.api('/api/set?md5=' + md5); } catch (e) { /* reported below */ }
    if (seq !== E.seq || ed()) return;
    if (!found || found.error) { if (S.view === 'edit') M.toast('이 맵셋의 폴더를 읽지 못했습니다.'); return; }
    E.found = found;
    renderChoose();
  }

  const KIND = { map: '', delete: 'delete 난이도', other: 'mania 아님' };

  function renderChoose() {
    const f = E.found;
    $('edEmpty').hidden = !!f;
    $('edFound').hidden = !f;
    if (!f) return;
    $('edFoundTitle').textContent = setTitle(f);
    $('edFoundFacts').textContent = [f.setId > 0 ? 'BeatmapSetID ' + f.setId : '온라인 ID 없음', '난이도 ' + f.slots.length + '개',
      '음악 파일 ' + f.audios + '개', '폴더  ' + f.folder].join('     ');
    const warn = $('edFoundWarn');
    warn.textContent = '';
    const add = (text, block) => warn.append(el('li', block ? 'block' : '', text));
    const usable = f.setId > 0 && f.slots.some(s => s.kind === 'map' && s.hasAudio);
    if (f.setId <= 0) add('이 맵셋에는 온라인 ID(BeatmapSetID)가 없습니다. 업로드된 적이 없거나 ID가 지워진 맵셋이라 기존 맵셋 업데이트용으로는 쓸 수 없습니다. 새 팩으로 만들어 주세요.', true);
    else if (!usable) add('이 맵셋에는 고칠 수 있는 mania 난이도가 없습니다.', true);
    if (f.mixedIds) add('난이도마다 BeatmapSetID가 다릅니다. 가장 많이 쓰인 ' + f.setId + '을(를) 맵셋 ID로 봅니다.');
    const ids = f.slots.filter(s => s.id > 0).map(s => s.id);
    if (new Set(ids).size !== ids.length) add('같은 BeatmapID를 가진 난이도가 있습니다. 먼저 나온 난이도만 그 ID를 가집니다.');
    const noId = f.slots.filter(s => s.id <= 0).length;
    if (noId && f.setId > 0) add('BeatmapID가 없는 난이도 ' + noId + '개는 새 난이도로 올라갑니다.');
    const other = f.slots.filter(s => s.kind === 'other').length;
    if (other) add('mania가 아닌 난이도 ' + other + '개는 손대지 않고 그대로 복사합니다.');
    if (f.slots.some(s => s.format < 14)) add('아주 오래된 형식(v14 미만)의 난이도가 있습니다. 업로드 전에 osu! 에디터에서 한 번 저장해야 받아 줍니다.');
    const mine = S.lib.player, creator = (f.slots[0] || {}).creator;
    if (mine && creator && creator !== mine) add('이 맵셋의 제작자(' + creator + ')가 osu! 계정 이름(' + mine + ')과 다릅니다. 자기 맵셋만 업데이트할 수 있습니다.');
    const list = $('edFoundList');
    list.textContent = '';
    f.slots.forEach(s => {
      const li = el('li');
      li.append(el('span', 'num', s.id > 0 ? 'ID ' + s.id : 'ID 없음'), el('span', 'clip', s.version || '(이름 없음)'),
        el('span', 'dim', KIND[s.kind] || (s.keys + 'K')));
      list.append(li);
    });
    $('edLoad').disabled = !usable || E.busy;
    $('edLoadNote').textContent = E.busy ? '불러오는 중입니다' : '';
  }

  async function load() {
    const f = E.found;
    if (!f || f.setId <= 0 || E.busy) return;
    if (M.hasWork(Object.assign({}, S.project, { rc: null }))
      && !(await M.confirmBox('지금 만들던 팩을 닫고 이 맵셋을 불러올까요? 저장하지 않은 팩 구성은 사라집니다. 남기려면 먼저 "저장"을 눌러 주세요.', { yes: '맵셋 불러오기' }))) return;
    E.busy = true; renderChoose();
    try {
      const p = M.newProject();
      const first = f.slots.find(s => s.kind === 'map') || f.slots[0];
      Object.assign(p.pack, { title: first.title, artist: first.artist || 'Various Artists', creator: first.creator, source: first.source,
        tags: first.tags, titleUnicode: first.titleU || '', artistUnicode: first.artistU || '', resetIds: false });
      const seen = new Set();
      let hasDelete = false;
      const slots = f.slots.map(s => {
        const id = s.id > 0 && !seen.has(s.id) ? s.id : 0;
        if (id) seen.add(id);
        let kind = s.kind;
        if (kind === 'delete') { if (hasDelete) kind = 'map'; hasDelete = true; }
        return { id, file: s.file, md5: s.md5, version: s.version, title: s.title, kind, keys: s.keys, hasBg: s.hasBg,
          hasAudio: s.hasAudio, lengthMs: s.lengthMs };
      });
      const del = slots.find(s => s.kind === 'delete');
      p.edit = { setId: f.setId, folder: f.folder, title: setTitle(f), thumbs: true, unify: f.audios > 1, slots,
        carry: slots.filter(s => s.kind === 'other').map(s => s.file), deleteSlot: del ? del.id : 0 };
      p.delete.enabled = !!del;
      if (del) {
        p.delete.name = del.version || 'delete';
        p.delete.minutes = clamp(Math.round((del.lengthMs - 1000) / 60000), 5, 30);
      }
      for (const s of slots) {
        if (s.kind !== 'map' || !s.hasAudio) continue;
        let detail = null;
        try { detail = await M.api('/api/map?md5=' + s.md5); } catch (e) { /* left out, shown as missing from the rebuild */ }
        if (!detail || detail.error) continue;
        p.entries.push({ uid: M.newUid(), md5: s.md5, rate: 1, followPitch: false, version: s.version, versionEdited: true,
          meta: M.metaOf(detail), rating: null, bg: { x: 50, y: 50, zoom: 1 }, slot: s.id });
      }
      E.found = null;
      await M.setProject(p, 'edit', true);
      fetchRatings();
    } finally { E.busy = false; }
  }

  /* Estimates for entries that came without one (a set just loaded). */
  let ratingTimer = 0;
  async function fetchRatings() {
    const p = S.project;
    for (const e of p.entries.slice()) {
      if (e.rating || S.missing.has(e.md5)) continue;
      let res = null;
      try { res = await M.api('/api/rating?md5=' + e.md5 + '&rate=' + e.rate); } catch (err) { /* no estimate */ }
      if (S.project !== p) return;
      if (res && res.rating) {
        e.rating = res.rating;
        clearTimeout(ratingTimer);
        ratingTimer = setTimeout(() => { M.renderEntries(); M.changed(); if (S.view === 'edit') render(); }, 200);
      }
    }
  }

  // ---- the loaded set
  function summary() {
    const p = S.project, e = p.edit;
    const rows = e.slots.filter(s => s.id > 0).map(s => {
      if (s.kind === 'other') return { s, state: (e.carry || []).includes(s.file) ? 'carry' : 'gone' };
      if (s.kind === 'delete') return { s, state: p.delete.enabled && e.deleteSlot === s.id ? 'delete' : 'gone' };
      const h = holderOf(s);
      return { s, h, state: !h ? 'gone' : h.md5 === s.md5 && Number(h.rate) === 1 ? 'same' : 'swap' };
    });
    const live = rows.filter(r => r.state !== 'gone');
    return { rows, fresh: p.entries.filter(x => !x.slot), gone: rows.filter(r => r.state === 'gone'),
      made: p.entries.filter(x => !untouched(x)).length,
      cover: live.length ? live.reduce((a, b) => (b.s.id < a.s.id ? b : a)).s.id : 0 };
  }

  /* What the export dialog and this page warn about. */
  function problems(block, warn) {
    const p = S.project, e = p.edit, sum = summary();
    if (p.entries.length + (p.delete.enabled ? 1 : 0) + (e.carry || []).length > 128) block('한 맵셋에는 난이도를 128개까지만 올릴 수 있습니다.');
    if (sum.gone.length) warn('원래 있던 난이도 ' + sum.gone.length + '개가 수정본에 없습니다. 업데이트하면 사이트에서 삭제됩니다: ' + sum.gone.map(r => r.s.version).join(', '));
    if (sum.fresh.length) warn('새 BeatmapID를 받는 난이도가 ' + sum.fresh.length + '개 있습니다 (원래 난이도의 자리를 잇지 않음).');
    if (!e.unify && sum.made) warn('갈아끼우거나 새로 넣은 난이도가 있는데 "그대로 둔 난이도도 메타데이터 탭 내용으로 맞추기"가 꺼져 있습니다. 제목·아티스트·제작자·출처·태그가 난이도마다 다르면 업로드가 거부됩니다.');
    const mine = S.lib.player, creator = p.pack.creator.trim();
    if (mine && creator && creator !== mine) warn('제작자(Creator) "' + creator + '"이(가) osu! 계정 이름 "' + mine + '"과(와) 다릅니다. 올리는 계정 이름과 같아야 받아 줍니다.');
    if (p.pack.tags.length > 1000) warn('태그가 1000자를 넘습니다. 업로드가 거부될 수 있습니다.');
  }

  function thumbOf(md5, hasBg) {
    const th = el('span', 'th');
    if (hasBg) th.style.backgroundImage = 'url("' + M.bgSrc(md5) + '")';
    else th.textContent = '그림 없음';
    return th;
  }

  function button(label, fn, cls) {
    const b = el('button', 'btn ' + (cls || ''), label);
    b.type = 'button';
    b.addEventListener('click', fn);
    return b;
  }

  function touched() { M.applyTemplate(false); M.renderEntries(); M.changed(); render(); }

  async function restore(slot) {
    const p = S.project;
    let entry = holderOf(slot);
    const spare = p.entries.find(x => !x.slot && x.md5 === slot.md5 && Number(x.rate) === 1);
    if (!entry && spare) { spare.slot = slot.id; named(spare); touched(); return; }
    let detail = null;
    try { detail = await M.api('/api/map?md5=' + slot.md5); } catch (e) { /* reported below */ }
    if (!detail || detail.error) { M.toast('원래 난이도 파일을 찾지 못했습니다. 원본 폴더가 그대로 있는지 확인해 주세요.'); return; }
    const fresh = { md5: slot.md5, rate: 1, followPitch: false, version: slot.version, versionEdited: true, meta: M.metaOf(detail),
      rating: null, bg: { x: 50, y: 50, zoom: 1 } };
    if (entry) { for (const k of ['bgAsset', 'fx', 'symbols', 'layers']) delete entry[k]; Object.assign(entry, fresh); }
    else p.entries.push(Object.assign({ uid: M.newUid(), slot: slot.id }, fresh));
    touched();
    fetchRatings();
  }

  function replace(slot) {
    S.replace = { slot: slot.id, label: slot.version || 'ID ' + slot.id };
    M.show('pick');
    M.addLabel();
    M.toast('osu!에서 맵을 고르거나 왼쪽 "맵 목록"에서 고른 뒤 "이 자리에 넣기"를 누르세요.');
  }

  function slotRow(r, sum) {
    const s = r.s, h = r.h, p = S.project, e = p.edit;
    const li = el('li', r.state === 'gone' ? 'gone' : r.state === 'swap' ? 'swap' : '');
    const was = el('span', 'was'), now = el('span', 'now'), acts = el('span', 'acts');
    was.append(el('b', null, s.version || '(이름 없음)'), el('span', 'num', 'ID ' + s.id + (KIND[s.kind] ? '   ' + KIND[s.kind] : '')));
    was.title = s.title + '  [' + s.version + ']';
    if (r.state === 'same') {
      now.append(el('b', null, '그대로'), el('span', null, (e.thumbs !== false ? '썸네일만 새로 만듭니다' : '노트, 오디오, 그림 모두 원래대로')
        + (h.version !== s.version ? '   새 이름: ' + h.version : '')));
    } else if (r.state === 'swap') {
      now.append(el('b', null, h.meta.title + '   ' + M.fmtRate(h.rate) + '×'),
        el('span', null, (h.md5 === s.md5 ? '배속만 바뀜' : '[' + h.meta.version + ']') + '   난이도명: ' + h.version));
      now.title = h.meta.title + '  [' + h.meta.version + ']';
    } else if (r.state === 'delete') {
      now.append(el('b', null, 'delete 난이도 다시 만들기'), el('span', null, '"메타데이터" 탭의 설정대로 새로 만들어 이 ID에 넣습니다'));
    } else if (r.state === 'carry') {
      now.append(el('b', null, '그대로 복사'), el('span', null, 'mania 난이도가 아니라 손대지 않습니다'));
    } else {
      now.append(el('b', null, '빠짐'), el('span', null, '업데이트하면 사이트에서 삭제됩니다'));
    }
    if (sum.cover === s.id && r.state !== 'gone') {
      const mark = el('span', 'cover', '맵셋 대표 그림·미리듣기 (추정)');
      mark.dataset.tip = '사이트는 맵셋의 난이도를 등록된 순서로 훑어 처음 나오는 그림과 음악으로 맵셋의 대표 그림과 미리듣기를 만듭니다. BeatmapID가 가장 낮은 이 난이도의 것이 쓰일 가능성이 높습니다 (공개된 osu-web 코드를 보고 추정한 것이라 확실하지는 않습니다).';
      now.append(mark);
    }
    if (s.kind === 'map') {
      acts.append(button('갈아끼우기', () => replace(s)));
      if (r.state !== 'same') acts.append(button('원래대로', () => restore(s), 'quiet'));
      if (h) acts.append(button('빼기', () => { p.entries = p.entries.filter(x => x !== h); touched(); }, 'quiet danger'));
    } else if (s.kind === 'delete') {
      if (r.state === 'delete') acts.append(button('빼기', () => { p.delete.enabled = false; touched(); }, 'quiet danger'));
      else acts.append(button('되살리기', () => { p.delete.enabled = true; e.deleteSlot = s.id; touched(); }, 'quiet'));
    } else if (r.state === 'carry') {
      acts.append(button('빼기', () => { e.carry = e.carry.filter(n => n !== s.file); touched(); }, 'quiet danger'));
    } else acts.append(button('되살리기', () => { e.carry = (e.carry || []).concat(s.file); touched(); }, 'quiet'));
    li.append(thumbOf(s.md5, s.hasBg && s.kind !== 'other'), was, el('span', 'arrow', '→'), now, acts);
    return li;
  }

  function freshRow(entry, sum) {
    const p = S.project, li = el('li');
    const was = el('span', 'was'), now = el('span', 'now'), acts = el('span', 'acts');
    was.append(el('b', null, entry.meta.title), el('span', null, '[' + entry.meta.version + ']   ' + M.fmtRate(entry.rate) + '×'));
    now.append(el('b', null, entry.version || '(난이도명 없음)'), el('span', null, '새 BeatmapID를 받습니다'));
    const free = sum.gone.filter(r => r.s.kind === 'map');
    if (free.length) {
      const pick = el('select');
      pick.setAttribute('aria-label', '물려받을 BeatmapID');
      const none = el('option', null, '빠진 자리의 ID 물려받기'); none.value = ''; pick.append(none);
      free.forEach(r => { const o = el('option', null, 'ID ' + r.s.id + '   ' + r.s.version); o.value = String(r.s.id); pick.append(o); });
      pick.addEventListener('change', () => { if (pick.value) { entry.slot = Number(pick.value); named(entry); touched(); } });
      acts.append(pick);
    }
    acts.append(button('빼기', () => { p.entries = p.entries.filter(x => x !== entry); touched(); }, 'quiet danger'));
    li.append(thumbOf(entry.md5, entry.meta.hasBg), was, el('span', 'arrow', '→'), now, acts);
    return li;
  }

  function render() {
    const p = S.project, e = p.edit;
    if (!e) return;
    const sum = summary();
    $('edTitle').textContent = e.title || e.folder;
    const after = p.entries.length + (p.delete.enabled ? 1 : 0) + sum.rows.filter(r => r.state === 'carry').length;
    $('edFacts').textContent = ['BeatmapSetID ' + e.setId, '난이도 ' + e.slots.length + '개  →  ' + after + '개', '폴더  ' + e.folder].join('     ');
    const warn = $('edWarn');
    warn.textContent = '';
    problems(t => warn.append(el('li', 'block', t)), t => warn.append(el('li', '', t)));
    const gone = p.entries.filter(x => S.missing.has(x.md5)).length;
    if (gone) warn.append(el('li', 'block', '이 PC의 osu!에 없는 맵이 ' + gone + '개 있습니다. 원본 맵셋 폴더가 Songs에 그대로 있는지 확인해 주세요.'));
    const slots = $('edSlots');
    slots.textContent = '';
    sum.rows.forEach(r => slots.append(slotRow(r, sum)));
    const fresh = $('edNew');
    fresh.textContent = '';
    sum.fresh.forEach(x => fresh.append(freshRow(x, sum)));
    $('edNewHead').hidden = $('edNewHint').hidden = !sum.fresh.length;
    $('edThumbs').checked = e.thumbs !== false;
    $('edUnify').checked = !!e.unify;
    $('edGo').textContent = '수정본 내보내기 (' + after + ')';
  }

  /* The table on the "done" page of the export: which id each difficulty went out with. */
  function report(st) {
    const body = $('exEditRows'), info = st.edit || { rows: [], removed: [] };
    const HOW = { asis: '그대로 (노트와 오디오는 원본 그대로)', made: '새로 만듦', delete: 'delete 난이도 다시 만듦', carry: '그대로 복사' };
    body.textContent = '';
    info.rows.forEach(r => {
      const tr = el('tr');
      tr.append(el('td', null, r.version), el('td', 'num', r.id ? String(r.id) : '업로드할 때 새로 받음'), el('td', null, HOW[r.how] || ''));
      body.append(tr);
    });
    info.removed.forEach(r => {
      const tr = el('tr');
      tr.append(el('td', null, r.version), el('td', 'num', String(r.id)), el('td', null, '수정본에 없음: 업데이트하면 사이트에서 삭제'));
      body.append(tr);
    });
    $('exEditNote').textContent = '맵셋 ID ' + info.setId + '.  원본 폴더에서 그대로 가져온 파일 ' + (info.copied || 0) + '개'
      + (info.skipped ? ',  업로드할 수 없는 형식이라 뺀 파일 ' + info.skipped + '개' : '') + '.';
  }

  function show() {
    const loaded = !!ed();
    $('view-edit').classList.toggle('choosing', !loaded);
    $('edChoose').hidden = loaded;
    $('edBody').hidden = $('edSide').hidden = !loaded;
    if (loaded) render(); else renderChoose();
  }

  function init() {
    $('edLoad').addEventListener('click', load);
    $('edThumbs').addEventListener('change', ev => { ed().thumbs = ev.target.checked; M.changed(); render(); });
    $('edUnify').addEventListener('change', ev => { ed().unify = ev.target.checked; M.changed(); render(); });
    document.querySelectorAll('#edSide [data-go]').forEach(b => b.addEventListener('click', () => M.show(b.dataset.go)));
    $('edAdd').addEventListener('click', () => M.show('pick'));
    $('edGo').addEventListener('click', M.openExport);
    $('edClose').addEventListener('click', async () => {
      if (!(await M.confirmBox('이 맵셋 수정을 그만두고 빈 팩으로 돌아갈까요? 저장하지 않은 수정 내용은 사라집니다. 원본 맵셋과 이미 내보낸 수정본은 그대로 남습니다.',
        { danger: true, yes: '수정 그만두기' }))) return;
      E.found = null;
      M.setProject(M.newProject(), 'edit', true);
    });
    if (ed()) fetchRatings();
  }

  function initSaves() {
    $('saveBtn').addEventListener('click', openSave);
    $('loadBtn').addEventListener('click', openLoad);
    $('saveGo').addEventListener('click', () => doSave(false));
    $('saveName').addEventListener('keydown', ev => { if (ev.key === 'Enter') { ev.preventDefault(); doSave(false); } });
    $('loadOpen').addEventListener('click', () => M.api('/api/open', { what: 'saves' }));
  }

  M.saves = { init: initSaves, reportMissing };
  M.edit = { init, show, select, named, problems, report, summary };
})();
