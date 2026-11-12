/* Thumbnail rendering and the thumbnail editor.
   One render function draws a map's thumbnail from the shared design (effects + layers); the editor
   preview, the film strip and the export all go through it, so what is shown is what is exported.
   Layout units are a 1920 x 1080 canvas whatever the output size. */
'use strict';
(function () {
  const BASE_W = 1920, BASE_H = 1080;
  const FONTS = ['Bahnschrift', 'Segoe UI', 'Malgun Gothic', 'Impact', 'Arial Black', 'Georgia', 'Times New Roman', 'Consolas'];
  const FX_DEFAULT = { dim: 0, blur: 0, contrast: 100, saturate: 100, noise: 0, grain: 2, noiseColor: false,
    vignette: 0, scan: 0, tint: 0, tintColor: '#000000', tintMode: 'source-over', tintGrad: null };
  const TIERS = [['--', '-low'], ['-', '-mid-low'], ['', ''], ['+', '-mid-high'], ['++', '-high']];
  const GREEK = ['alpha', 'beta', 'gamma', 'delta', 'epsilon', 'zeta', 'eta', 'theta', 'iota', 'kappa'];
  const FAMILIES = [
    { id: '4k', label: '4K', dir: 'reform', prefix: '', levels: range(1, 10).concat(GREEK), webp: GREEK },
    { id: '4kln', label: '4K LN', dir: 'ln', prefix: '', levels: range(1, 17), webp: [] },
    { id: '6k', label: '6K', dir: '6k', prefix: '', levels: range(0, 9).concat(['terra', 'celestial', 'mystery', 'nihility', 'finish']), webp: [] },
    { id: '6kln', label: '6K LN', dir: '6k', prefix: 'ln-', levels: range(0, 9).concat(['terra', 'celestial', 'mystery', 'nihility', 'finish']), webp: [] },
    { id: '7k', label: '7K', dir: '7k', prefix: '', levels: range(0, 10).concat(['gamma', 'azimuth', 'zenith', 'stellium']), webp: [] },
    { id: '7kln', label: '7K LN', dir: '7k', prefix: 'ln-', levels: range(0, 10).concat(['gamma', 'azimuth', 'zenith', 'stellium']), webp: [] },
  ];

  function range(a, b) { const out = []; for (let i = a; i <= b; i++) out.push(String(i)); return out; }
  function clamp(v, a, b) { return Math.min(b, Math.max(a, v)); }
  function $(id) { return document.getElementById(id); }
  function el(tag, cls, text) {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }

  let app = null;                    // set by init(): { project(), token, changed(), pickFile(), upload(), toast() }

  // ------------------------------------------------------------ images
  const images = new Map();
  function loadImage(url) {
    if (!url) return Promise.resolve(null);
    if (!images.has(url)) {
      const p = new Promise(resolve => {
        const img = new Image();
        img.onload = () => resolve(img);
        img.onerror = () => resolve(null);
        img.src = url;
      });
      p.img = null;                              // kept beside the promise: sizes without awaiting
      p.then(img => { p.img = img; });
      images.set(url, p);
    }
    return images.get(url);
  }
  const assetUrl = id => id ? '/api/asset?id=' + encodeURIComponent(id) + '&t=' + encodeURIComponent(app.token) : null;
  const danUrl = src => !src ? null : src.startsWith('asset:') ? assetUrl(src.slice(6)) : '/dans/' + src;
  const TIER_SUFFIX = { '--': '-low', '-': '-mid-low', '': '', '+': '-mid-high', '++': '-high' };
  const tierOf = name => { const m = /(\+\+|--|\+|-)$/.exec(String(name || '').trim()); return m ? m[1] : ''; };
  const baseOf = name => String(name || '').trim().replace(/(\+\+|--|\+|-)$/, '').trim().toLowerCase();

  function bgUrl(thumb, entry) {
    if (entry.bgAsset) return assetUrl(entry.bgAsset);
    if (thumb.bgMode === 'common' && thumb.commonAsset) return assetUrl(thumb.commonAsset);
    if (entry.md5 && entry.meta && entry.meta.hasBg) return '/api/bg?md5=' + entry.md5 + '&t=' + encodeURIComponent(app.token);
    return null;
  }

  // ------------------------------------------------------------ noise
  const noiseTiles = {};
  function noiseTile(color) {
    const key = color ? 'c' : 'm';
    if (noiseTiles[key]) return noiseTiles[key];
    const size = 256, c = document.createElement('canvas');
    c.width = c.height = size;
    const g = c.getContext('2d'), data = g.createImageData(size, size);
    let seed = 0x9e3779b9;                       // fixed seed: every thumbnail gets the same grain
    const rnd = () => { seed |= 0; seed = seed + 0x6D2B79F5 | 0; let t = Math.imul(seed ^ seed >>> 15, 1 | seed);
      t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t; return ((t ^ t >>> 14) >>> 0) / 4294967296; };
    for (let i = 0; i < data.data.length; i += 4) {
      const v = Math.round(rnd() * 255);
      data.data[i] = v;
      data.data[i + 1] = color ? Math.round(rnd() * 255) : v;
      data.data[i + 2] = color ? Math.round(rnd() * 255) : v;
      data.data[i + 3] = 255;
    }
    g.putImageData(data, 0, 0);
    noiseTiles[key] = c;
    return c;
  }

  // ------------------------------------------------------------ text
  function fillTokens(text, entry, project) {
    const meta = entry.meta || {}, rating = entry.rating || {};
    const rate = Number(entry.rate || 1);
    const values = {
      title: meta.title || '', artist: meta.artist || '', creator: meta.creator || '', version: meta.version || '',
      diff: entry.version || '', rate: rate.toFixed(2),
      bpm: meta.bpm ? String(Math.round(meta.bpm * rate)) : '',
      dan: rating.dan ? rating.dan.text : '', msd: rating.msd ? rating.msd.toFixed(1) : '',
      n: entry.index != null ? String(entry.index + 1) : '', pack: (project && project.pack.title) || '',
    };
    return String(text || '').replace(/\{(\w+)\}/g, (m, k) => (k in values ? values[k] : m));
  }

  function fontOf(layer, s) {
    return (layer.bold ? '700 ' : '400 ') + Math.max(1, layer.size * s) + 'px "' + (layer.font || 'Bahnschrift') + '", "Malgun Gothic", sans-serif';
  }

  const measurer = document.createElement('canvas').getContext('2d');
  function textBox(layer, entry) {
    const lines = fillTokens(layer.text, entry, app.project()).split('\n');
    measurer.font = fontOf(layer, 1);
    let w = 0;
    for (const line of lines) w = Math.max(w, measurer.measureText(line).width);
    return { w: Math.max(20, w), h: lines.length * layer.size * 1.18, lines };
  }

  /* Size of a layer in layout units for one entry (text depends on the entry's own words). */
  function boxOf(layer, entry) {
    if (layer.type === 'text') { const b = textBox(layer, entry); return { w: b.w, h: b.h }; }
    return { w: layer.w, h: layer.h };
  }

  // ------------------------------------------------------------ render
  /* preview: drawn for the screen, where a map without a picture says so. Exports never carry that text. */
  async function render(ctx, W, H, thumb, entry, preview) {
    const s = W / BASE_W, fx = Object.assign({}, FX_DEFAULT, entry.fx || thumb.fx);   // a map may carry its own
    ctx.save();
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.globalAlpha = 1; ctx.globalCompositeOperation = 'source-over'; ctx.filter = 'none';
    ctx.fillStyle = '#151515';
    ctx.fillRect(0, 0, W, H);

    // where each layer sits among the effects: under all of them (part of the picture), under the grain
    // and scan lines only, or on top of everything (the default)
    const shown = (thumb.layers || []).filter(l => l.visible !== false).map(l => placed(l, entry));
    const below = shown.filter(l => l.under === 'all'), middle = shown.filter(l => l.under === 'grain');
    const above = shown.filter(l => l.under !== 'all' && l.under !== 'grain');
    const img = await loadImage(bgUrl(thumb, entry));
    const filters = [], blurPx = fx.blur > 0 ? fx.blur * s : 0;
    if (blurPx) filters.push('blur(' + blurPx.toFixed(2) + 'px)');
    if (fx.contrast !== 100) filters.push('contrast(' + fx.contrast + '%)');
    if (fx.saturate !== 100) filters.push('saturate(' + fx.saturate + '%)');
    const filter = filters.join(' ') || 'none', margin = blurPx * 3;   // grow past the edges: no faded rim
    if (below.length) {
      const sheet = document.createElement('canvas');
      sheet.width = W; sheet.height = H;
      const g = sheet.getContext('2d');
      g.fillStyle = '#151515';
      g.fillRect(0, 0, W, H);
      drawBackground(g, W, H, img, entry, preview, 'none', 0);
      for (const layer of below) await drawLayer(g, layer, s, entry, preview);
      ctx.filter = filter;
      ctx.imageSmoothingQuality = 'high';
      ctx.drawImage(sheet, -margin, -margin * H / W, W + 2 * margin, H + 2 * margin * H / W);
      ctx.filter = 'none';
    } else drawBackground(ctx, W, H, img, entry, preview, filter, margin);
    if (fx.tint > 0) {
      ctx.globalCompositeOperation = fx.tintMode || 'source-over';
      ctx.globalAlpha = fx.tint / 100;
      ctx.fillStyle = paint(ctx, fx.tintColor || '#000000', fx.tintGrad, 0, 0, W, H);
      ctx.fillRect(0, 0, W, H);
      ctx.globalCompositeOperation = 'source-over'; ctx.globalAlpha = 1;
    }
    if (fx.dim > 0) {
      ctx.fillStyle = 'rgba(0,0,0,' + (fx.dim / 100) + ')';
      ctx.fillRect(0, 0, W, H);
    }
    if (fx.vignette > 0) {
      const r = Math.hypot(W, H) / 2;
      const g = ctx.createRadialGradient(W / 2, H / 2, r * 0.42, W / 2, H / 2, r * 1.02);
      g.addColorStop(0, 'rgba(0,0,0,0)');
      g.addColorStop(1, 'rgba(0,0,0,' + (fx.vignette / 100) + ')');
      ctx.fillStyle = g;
      ctx.fillRect(0, 0, W, H);
    }
    for (const layer of middle) await drawLayer(ctx, layer, s, entry, preview);
    if (fx.scan > 0) {
      const period = Math.max(2, Math.round(6 * s)), line = Math.max(1, Math.round(period / 2));
      ctx.fillStyle = 'rgba(0,0,0,' + (fx.scan / 100 * 0.6) + ')';
      for (let y = 0; y < H; y += period) ctx.fillRect(0, y, W, line);
    }
    if (fx.noise > 0) {
      const pattern = ctx.createPattern(noiseTile(fx.noiseColor), 'repeat');
      const g = Math.max(0.5, fx.grain * s);
      pattern.setTransform(new DOMMatrix().scale(g, g));
      ctx.imageSmoothingEnabled = false;
      ctx.globalCompositeOperation = 'overlay';
      ctx.globalAlpha = fx.noise / 100;
      ctx.fillStyle = pattern;
      ctx.fillRect(0, 0, W, H);
      ctx.globalCompositeOperation = 'source-over'; ctx.globalAlpha = 1;
      ctx.imageSmoothingEnabled = true;
    }
    for (const layer of above) await drawLayer(ctx, layer, s, entry, preview);
    ctx.restore();
  }

  /* The map's picture cropped to 16:9 (or a plain ground when it has none). margin: how far to grow it
     past the edges when it is blurred. */
  function drawBackground(ctx, W, H, img, entry, preview, filter, margin) {
    if (img && img.naturalWidth) {
      const bg = entry.bg || {}, zoom = clamp(Number(bg.zoom) || 1, 1, 3);
      const scale = Math.max(W / img.naturalWidth, H / img.naturalHeight) * zoom;
      let dw = img.naturalWidth * scale, dh = img.naturalHeight * scale;
      let x = (W - dw) * clamp(bg.x == null ? 50 : bg.x, 0, 100) / 100;
      let y = (H - dh) * clamp(bg.y == null ? 50 : bg.y, 0, 100) / 100;
      if (margin > 0) {
        const grow = (dw + 2 * margin) / dw;
        x -= margin; y -= (dh * grow - dh) / 2; dw *= grow; dh *= grow;
      }
      ctx.filter = filter;
      ctx.imageSmoothingQuality = 'high';
      ctx.drawImage(img, x, y, dw, dh);
      ctx.filter = 'none';
      return;
    }
    const g = ctx.createLinearGradient(0, 0, W, H);
    g.addColorStop(0, '#242424'); g.addColorStop(1, '#141414');
    ctx.fillStyle = g;
    ctx.fillRect(0, 0, W, H);
    if (preview) {
      ctx.fillStyle = '#8a8a8a';
      ctx.font = '500 ' + Math.max(11, Math.round(H * 0.06)) + 'px "Segoe UI", "Malgun Gothic", sans-serif';
      ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
      ctx.fillText('썸네일 없음', W / 2, H / 2);
    }
  }

  /* What to fill with: the colour, or a blend from it to a second colour across the box x, y, w, h
     (grad = {color, angle, kind}; angle 0 runs left to right, 90 top to bottom; kind 'radial' runs from the
     middle outwards). */
  function paint(ctx, color, grad, x, y, w, h) {
    if (!grad || !grad.color) return color;
    const cx = x + w / 2, cy = y + h / 2;
    let g;
    if (grad.kind === 'radial') g = ctx.createRadialGradient(cx, cy, 0, cx, cy, Math.max(1, Math.hypot(w, h) / 2));
    else {
      const a = (grad.angle == null ? 90 : Number(grad.angle) || 0) * Math.PI / 180, dx = Math.cos(a), dy = Math.sin(a);
      const half = Math.max(0.5, (Math.abs(dx) * w + Math.abs(dy) * h) / 2);
      g = ctx.createLinearGradient(cx - dx * half, cy - dy * half, cx + dx * half, cy + dy * half);
    }
    try { g.addColorStop(0, color); g.addColorStop(1, grad.color); } catch (e) { return color; }
    return g;
  }

  const ownSymbol = (layer, entry) => (entry.symbols && entry.symbols[layer.id]) || null;
  const GEO = ['x', 'y', 'w', 'h', 'rot', 'size'];
  const STYLE = ['hue', 'tint', 'tintColor', 'tintMode', 'tintGrad', 'opacity', 'shadow'];
  const UNDER_TAG = { grain: '노이즈 아래', all: '효과 아래' };
  const hasKeys = o => !!o && Object.keys(o).length > 0;

  /* A layer as one picture shows it: the shared layer, or moved / resized / turned for that picture alone
     when the picture has a place of its own for it (entry.layers[layer.id]). */
  function placed(layer, entry) {
    const own = entry && entry.layers && entry.layers[layer.id];
    return own ? Object.assign({}, layer, own) : layer;
  }

  function layerImageUrl(layer, entry) {
    if (layer.type === 'symbol' || layer.type === 'autodan') {
      const own = ownSymbol(layer, entry);                       // "this map only" choice wins
      if (own) return danUrl(own);
      return layer.type === 'symbol' ? danUrl(layer.src) : danUrl(entry.rating && entry.rating.dan && entry.rating.dan.image);
    }
    if (layer.type === 'image') return assetUrl(layer.asset);
    return null;
  }

  /* The picture recoloured: hue turned, and/or a colour laid over it, inside the picture's own outline. */
  function tinted(img, layer, w, h) {
    const hue = layer.hue || 0, amount = layer.tint || 0;
    if (!hue && !amount) return img;
    const c = document.createElement('canvas');
    c.width = Math.max(1, Math.round(w)); c.height = Math.max(1, Math.round(h));
    const g = c.getContext('2d');
    g.imageSmoothingQuality = 'high';
    if (hue) g.filter = 'hue-rotate(' + hue + 'deg)';
    g.drawImage(img, 0, 0, c.width, c.height);
    g.filter = 'none';
    if (amount) {
      g.globalCompositeOperation = layer.tintMode || 'color';
      g.globalAlpha = amount / 100;
      g.fillStyle = paint(g, layer.tintColor || '#ffffff', layer.tintGrad, 0, 0, c.width, c.height);
      g.fillRect(0, 0, c.width, c.height);
      g.globalAlpha = 1;
      g.globalCompositeOperation = 'destination-in';
      g.drawImage(img, 0, 0, c.width, c.height);
    }
    return c;
  }

  async function drawLayer(ctx, layer, s, entry, preview) {
    ctx.save();
    ctx.translate(layer.x * s, layer.y * s);
    ctx.rotate((layer.rot || 0) * Math.PI / 180);
    ctx.globalAlpha = clamp(layer.opacity == null ? 1 : layer.opacity, 0, 1);
    if (layer.shadow > 0) {
      ctx.shadowColor = 'rgba(0,0,0,.75)';
      ctx.shadowBlur = layer.shadow * 0.6 * s;
      ctx.shadowOffsetY = layer.shadow * 0.12 * s;
    }
    if (layer.type === 'rect') {
      const w = layer.w * s, h = layer.h * s, r = clamp((layer.radius || 0) * s, 0, Math.min(w, h) / 2);
      ctx.fillStyle = paint(ctx, layer.color || '#000000', layer.colorGrad, -w / 2, -h / 2, w, h);
      ctx.beginPath();
      ctx.roundRect(-w / 2, -h / 2, w, h, r);
      ctx.fill();
    } else if (layer.type === 'text') {
      const box = textBox(layer, entry), lh = layer.size * 1.18 * s;
      ctx.font = fontOf(layer, s);
      ctx.textBaseline = 'middle';
      const align = layer.align || 'center';
      ctx.textAlign = align;
      const ax = align === 'left' ? -box.w * s / 2 : align === 'right' ? box.w * s / 2 : 0;
      // a blend runs across the whole block of text, not line by line
      const bx = -box.w * s / 2, by = -box.h * s / 2, bw = box.w * s, bh = box.h * s;
      const fill = paint(ctx, layer.color || '#ffffff', layer.colorGrad, bx, by, bw, bh);
      const edge = paint(ctx, layer.strokeColor || '#000000', layer.strokeGrad, bx, by, bw, bh);
      box.lines.forEach((line, i) => {
        const y = (i - (box.lines.length - 1) / 2) * lh;
        if (layer.stroke > 0) {
          ctx.lineJoin = 'round';
          ctx.lineWidth = layer.stroke * s * 2;
          ctx.strokeStyle = edge;
          ctx.strokeText(line, ax, y);
          ctx.shadowColor = 'transparent';
        }
        ctx.fillStyle = fill;
        ctx.fillText(line, ax, y);
      });
    } else {
      const img = await loadImage(layerImageUrl(layer, entry));
      if (img && img.naturalWidth) {
        const h = layer.h * s;
        // a per-map symbol keeps the layer's height and takes each symbol's own width
        const own = layer.type === 'autodan' || ownSymbol(layer, entry);
        const w = own ? h * img.naturalWidth / img.naturalHeight : layer.w * s;
        ctx.imageSmoothingQuality = 'high';
        ctx.drawImage(tinted(img, layer, w, h), -w / 2, -h / 2, w, h);
      } else if (preview && layer.type === 'autodan') {
        // on screen only: this picture has no estimated dan, so say why the spot is empty
        const h = layer.h * s;
        ctx.shadowColor = 'transparent';
        ctx.setLineDash([h * 0.06, h * 0.05]);
        ctx.lineWidth = Math.max(1, h * 0.012);
        ctx.strokeStyle = 'rgba(245,245,245,.75)';
        ctx.strokeRect(-h / 2, -h / 2, h, h);
        ctx.fillStyle = 'rgba(245,245,245,.9)';
        ctx.font = '500 ' + Math.max(9, h * 0.1) + 'px "Segoe UI", "Malgun Gothic", sans-serif';
        ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
        ctx.fillText('예상 난이도 없음', 0, -h * 0.08);
        ctx.fillText('심볼을 골라 주세요', 0, h * 0.08);
      }
    }
    ctx.restore();
  }

  // ------------------------------------------------------------ what to draw for whom
  function entryFor(uid) {
    const p = app.project();
    if (uid === 'delete') return deleteEntry(p);
    const i = p.entries.findIndex(e => e.uid === uid);
    return i < 0 ? null : Object.assign({}, p.entries[i], { index: i });
  }

  /* The [delete] picture: an added image or one of the pack's maps, plus what was set for it alone in the
     editor (delete.thumb.own: a symbol, effects, the crop). */
  function deleteEntry(p) {
    const d = p.delete || {}, t = d.thumb || {}, own = t.own || {};
    let base;
    if (t.mode === 'file' && t.asset) {
      base = { uid: 'delete', bgAsset: t.asset, bg: {}, rate: 1, version: d.name || 'delete', plain: !t.design,
        meta: { title: p.pack.title || '', artist: p.pack.artist || '', creator: p.pack.creator || '', version: '' }, rating: null };
    } else {
      const i = Math.max(0, p.entries.findIndex(e => e.uid === t.uid));
      if (!p.entries[i]) return null;
      base = Object.assign({}, p.entries[i], { index: i });
    }
    if (own.fx) base.fx = own.fx;
    if (own.bg) base.bg = own.bg;
    if (hasKeys(own.symbols)) base.symbols = Object.assign({}, base.symbols, own.symbols);
    if (hasKeys(own.layers)) base.layers = Object.assign({}, base.layers, own.layers);
    return base;
  }

  /* plain: an added [delete] image that is NOT to take the pack's design. It still shows the symbols picked
     for it alone, so "the photo with just a dan symbol on it" is possible. */
  function designFor(entry) {
    const thumb = app.project().thumb;
    if (!entry.plain) return thumb;
    return { bgMode: 'each', fx: {}, layers: (thumb.layers || []).filter(l => ownSymbol(l, entry)) };
  }

  async function exportBlob(uid) {
    const p = app.project(), entry = entryFor(uid);
    if (!entry) return null;
    const [w, h] = (p.thumb.size || '1920x1080').split('x').map(Number);
    const c = document.createElement('canvas');
    c.width = w || BASE_W; c.height = h || BASE_H;
    await render(c.getContext('2d'), c.width, c.height, designFor(entry), entry);
    const png = p.thumb.format === 'png';
    return new Promise(resolve => c.toBlob(resolve, png ? 'image/png' : 'image/jpeg', clamp((p.thumb.quality || 100) / 100, 0.5, 1)));
  }

  /* One picture from any design (the rate changer brings its own). */
  async function blobWith(design, entry, width, height, quality) {
    const c = document.createElement('canvas');
    c.width = width || BASE_W; c.height = height || BASE_H;
    await render(c.getContext('2d'), c.width, c.height, design, entry);
    return new Promise(resolve => c.toBlob(resolve, 'image/jpeg', quality || 1));
  }

  // ============================================================ editor
  const ed = { uid: null, sel: null, undo: [], k: 1, drag: null, drawing: false, again: false, filmTimer: 0, fxScope: 'all' };
  const thumb = () => app.project().thumb;
  const layerById = id => (thumb().layers || []).find(l => l.id === id) || null;

  function defaults() {
    return { bgMode: 'each', commonAsset: null, commonName: '', fx: Object.assign({}, FX_DEFAULT), layers: [],
      format: 'jpg', quality: 100, size: '1920x1080' };
  }

  function snapshot() {
    const p = app.project();
    ed.undo.push(JSON.stringify({ thumb: p.thumb,
      per: p.entries.map(e => ({ uid: e.uid, fx: e.fx || null, symbols: e.symbols || null, layers: e.layers || null })),
      del: (p.delete && p.delete.thumb && p.delete.thumb.own) || null }));
    if (ed.undo.length > 60) ed.undo.shift();
  }

  function undo() {
    const last = ed.undo.pop();
    if (!last) return;
    const data = JSON.parse(last), p = app.project();
    p.thumb = data.thumb;
    for (const o of data.per || []) {
      const e = p.entries.find(x => x.uid === o.uid);
      if (!e) continue;
      if (o.fx) e.fx = o.fx; else delete e.fx;
      if (o.symbols) e.symbols = o.symbols; else delete e.symbols;
      if (o.layers) e.layers = o.layers; else delete e.layers;
    }
    if (p.delete && p.delete.thumb) {
      if (data.del) p.delete.thumb.own = data.del; else delete p.delete.thumb.own;
    }
    if (!layerById(ed.sel)) ed.sel = null;
    syncControls();
    changed(false);
  }

  function changed(save) {
    if (save !== false) app.changed();
    draw();
    renderLayerList();
    renderProps();
    clearTimeout(ed.filmTimer);
    ed.filmTimer = setTimeout(renderFilm, 260);
  }

  // ---- sizing and drawing
  function fit() {
    const stage = $('canvasStage'), box = $('canvasBox');
    const availW = stage.clientWidth - 36, availH = stage.clientHeight - 36;
    if (availW <= 0 || availH <= 0) return;
    const w = Math.floor(Math.min(availW, availH * 16 / 9));
    box.style.width = w + 'px';
    box.style.height = Math.round(w * 9 / 16) + 'px';
    ed.k = w / BASE_W;
    const canvas = $('canvas'), px = Math.min(BASE_W, Math.round(w * (window.devicePixelRatio || 1)));
    if (canvas.width !== px) { canvas.width = px; canvas.height = Math.round(px * 9 / 16); }
  }

  async function draw() {
    if (ed.drawing) { ed.again = true; return; }
    ed.drawing = true;
    try {
      do {
        ed.again = false;
        const entry = ed.uid ? entryFor(ed.uid) : null;
        const canvas = $('canvas');
        $('thumbEmpty').hidden = !!entry;
        $('canvasBox').hidden = !entry;
        if (entry) await render(canvas.getContext('2d'), canvas.width, canvas.height, designFor(entry), entry, true);
        placeSelection();
      } while (ed.again);
    } finally { ed.drawing = false; }
  }

  function placeSelection() {
    const box = $('selBox'), shared = layerById(ed.sel), entry = ed.uid ? entryFor(ed.uid) : null;
    if (!shared || !entry) { box.hidden = true; return; }
    const layer = placed(shared, entry);
    const size = visibleBox(layer, entry), k = ed.k;
    box.hidden = false;
    box.style.width = size.w * k + 'px';
    box.style.height = size.h * k + 'px';
    box.style.left = (layer.x - size.w / 2) * k + 'px';
    box.style.top = (layer.y - size.h / 2) * k + 'px';
    box.style.transform = 'rotate(' + (layer.rot || 0) + 'deg)';
    box.classList.toggle('fixed', layer.type !== 'rect');
  }

  function visibleBox(layer, entry) {
    if (layer.type === 'autodan' || (layer.type === 'symbol' && ownSymbol(layer, entry))) {
      const url = layerImageUrl(layer, entry), cached = url && images.get(url);
      if (cached && cached.img) return { w: layer.h * cached.img.naturalWidth / cached.img.naturalHeight, h: layer.h };
      return { w: layer.h, h: layer.h };
    }
    return boxOf(layer, entry);
  }

  // ---- film strip
  async function renderFilm() {
    const p = app.project(), film = $('film');
    const want = p.entries.map(e => e.uid);
    if (p.delete && p.delete.enabled && p.entries.length) want.push('delete');
    const have = Array.from(film.children).map(b => b.dataset.uid);
    if (have.join('|') !== want.join('|')) {
      film.textContent = '';
      for (const uid of want) {
        const b = el('button');
        b.type = 'button'; b.dataset.uid = uid;
        const c = document.createElement('canvas');
        c.width = 248; c.height = 140;
        b.append(c, el('span'));
        if (uid === 'delete') {
          b.className = 'del';
          const mark = el('i', 'warn', '!');
          mark.dataset.tip = '[delete] 난이도의 썸네일은 맵팩의 대표 이미지가 됩니다. [delete]를 가장 먼저 업로드하기 때문에, 사이트의 맵팩 목록과 카드에 이 그림이 걸립니다. 팩의 얼굴이니 한 번 확인해 주세요. 어떤 그림을 쓸지는 메타데이터 창의 "delete 난이도"에서 고릅니다.';
          b.insertBefore(mark, b.firstChild);
        }
        b.addEventListener('click', () => {
          ed.uid = uid;
          const shown = currentEntry();                  // a map with effects of its own opens on them
          ed.fxScope = shown && (shown.fx || hasKeys(shown.layers)) ? 'one' : 'all';
          syncControls(); renderProps(); markFilm(); draw();
        });
        film.append(b);
      }
    }
    if (ed.uid && !want.includes(ed.uid)) ed.uid = null;
    if (!ed.uid && want.length) ed.uid = want[0];
    markFilm();
    for (const b of Array.from(film.children)) {
      const entry = entryFor(b.dataset.uid);
      if (!entry) continue;
      const own = b.dataset.uid !== 'delete' && (entry.fx || entry.bgAsset || hasKeys(entry.symbols) || hasKeys(entry.layers));
      b.classList.toggle('own', !!own);
      b.lastChild.textContent = b.dataset.uid === 'delete' ? '[' + ((p.delete && p.delete.name) || 'delete') + '] 확인 필요'
        : (entry.index + 1) + '. ' + (own ? '(개별) ' : '') + (entry.meta ? entry.meta.title : '');
      await render(b.querySelector('canvas').getContext('2d'), 248, 140, designFor(entry), entry, true);
    }
  }

  function markFilm() {
    for (const b of $('film').children) b.setAttribute('aria-pressed', String(b.dataset.uid === ed.uid));
  }

  // ---- layers
  let nextId = 1;
  function newId() { return 'L' + Date.now().toString(36) + (nextId++); }

  async function addLayer(type) {
    const layers = thumb().layers;
    let layer = { id: newId(), type, x: BASE_W / 2, y: BASE_H / 2, w: 300, h: 300, rot: 0, opacity: 1, shadow: 0, visible: true };
    if (type === 'symbol') {
      const src = await pickSymbol();
      if (!src) return;
      const img = await loadImage(danUrl(src));
      layer.src = src; layer.h = 300; layer.w = img ? 300 * img.naturalWidth / img.naturalHeight : 300;
      layer.x = BASE_W - 230; layer.y = BASE_H - 230; layer.shadow = 30;
    } else if (type === 'autodan') {
      layer.h = 300; layer.x = BASE_W - 230; layer.y = BASE_H - 230; layer.shadow = 30;
    } else if (type === 'text') {
      Object.assign(layer, { text: '{title}', font: 'Bahnschrift', size: 110, bold: true, color: '#ffffff', align: 'center',
        stroke: 0, strokeColor: '#000000', shadow: 40 });
    } else if (type === 'rect') {
      Object.assign(layer, { w: BASE_W, h: 220, y: BASE_H - 110, color: '#000000', opacity: 0.6, radius: 0 });
    } else if (type === 'image') {
      const file = await app.pickFile('image/png,image/jpeg,image/webp,image/gif');
      if (!file) return;
      const id = await app.upload(file);
      if (!id) return;
      const img = await loadImage(assetUrl(id));
      if (!img) { app.toast('이미지를 읽지 못했습니다.'); return; }
      const fitScale = Math.min(1, 700 / img.naturalWidth, 500 / img.naturalHeight);
      Object.assign(layer, { asset: id, name: file.name, w: img.naturalWidth * fitScale, h: img.naturalHeight * fitScale });
    }
    snapshot();
    layers.push(layer);
    ed.sel = layer.id;
    changed();
  }

  function layerName(layer) {
    if (layer.type === 'symbol') return '단 심볼 ' + (layer.src || '').replace(/^.*\//, '').replace(/\.\w+$/, '');
    if (layer.type === 'autodan') return '맵별 예상 난이도 심볼';
    if (layer.type === 'text') return '글자 ' + (layer.text || '').split('\n')[0];
    if (layer.type === 'rect') return '도형';
    return '이미지 ' + (layer.name || '');
  }
  const ICON = { symbol: '단', autodan: '자동', text: '가', rect: '□', image: '그림' };

  function renderLayerList() {
    const list = $('layerList'), layers = thumb().layers || [];
    list.textContent = '';
    $('layerEmpty').hidden = layers.length > 0;
    layers.slice().reverse().forEach(layer => {
      const li = el('li', (layer.id === ed.sel ? 'on ' : '') + (layer.visible === false ? 'off' : ''));
      const nm = el('span', 'nm', layerName(layer));
      if (UNDER_TAG[layer.under]) nm.append(el('i', 'under', UNDER_TAG[layer.under]));
      li.append(el('span', 'ic', ICON[layer.type]), nm);
      const acts = el('span', 'acts');
      const mk = (label, title, fn, danger) => {
        const b = el('button', 'btn quiet icon' + (danger ? ' danger' : ''), label);
        b.type = 'button'; b.title = title; b.setAttribute('aria-label', title);
        b.addEventListener('click', ev => { ev.stopPropagation(); snapshot(); fn(); changed(); });
        acts.append(b);
      };
      mk('↑', '앞으로', () => moveLayer(layer.id, 1));
      mk('↓', '뒤로', () => moveLayer(layer.id, -1));
      mk(layer.visible === false ? '○' : '●', layer.visible === false ? '보이기' : '숨기기', () => { layer.visible = layer.visible === false; });
      mk('', '레이어 삭제', () => removeLayer(layer.id), true);
      li.append(acts);
      li.addEventListener('click', () => { ed.sel = layer.id; renderLayerList(); renderProps(); placeSelection(); });
      list.append(li);
    });
  }

  function moveLayer(id, dir) {
    const layers = thumb().layers, i = layers.findIndex(l => l.id === id), j = i + dir;
    if (i < 0 || j < 0 || j >= layers.length) return;
    [layers[i], layers[j]] = [layers[j], layers[i]];
  }

  function removeLayer(id) {
    const t = thumb();
    t.layers = t.layers.filter(l => l.id !== id);
    if (ed.sel === id) ed.sel = null;
  }

  // ---- properties
  function numberInput(label, value, onChange, step) {
    const wrap = el('label');
    wrap.append(el('span', null, label));
    const input = el('input');
    input.type = 'text'; input.inputMode = 'decimal'; input.value = String(Math.round(value * 100) / 100);
    input.autocomplete = 'off';
    input.addEventListener('change', () => {
      const v = parseFloat(input.value);
      if (!isFinite(v)) { input.value = String(value); return; }
      snapshot(); onChange(v); changed();
    });
    input.addEventListener('keydown', ev => {
      if (ev.key !== 'ArrowUp' && ev.key !== 'ArrowDown') return;
      ev.preventDefault();
      const v = (parseFloat(input.value) || 0) + (ev.key === 'ArrowUp' ? 1 : -1) * (step || 1) * (ev.shiftKey ? 10 : 1);
      input.value = String(Math.round(v * 100) / 100);
      input.dispatchEvent(new Event('change'));
      requestAnimationFrame(() => { const again = $('props').querySelector('[data-k="' + label + '"]'); if (again) again.focus(); });
    });
    input.dataset.k = label;
    wrap.append(input);
    return wrap;
  }

  function sliderLine(label, value, min, max, step, onInput) {
    const line = el('label', 'slider');
    line.append(el('span', null, label));
    const input = el('input'), out = el('output', 'num', String(value));
    input.type = 'range'; input.min = min; input.max = max; input.step = step; input.value = value;
    let armed = false;
    input.addEventListener('input', () => {
      if (!armed) { snapshot(); armed = true; }
      onInput(Number(input.value)); out.textContent = input.value; app.changed(); draw();
    });
    input.addEventListener('change', () => { armed = false; changed(); });
    line.append(input, out);
    return line;
  }

  const lightOf = hex => { const m = /^#?([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i.exec(hex || '');
    return m ? (0.299 * parseInt(m[1], 16) + 0.587 * parseInt(m[2], 16) + 0.114 * parseInt(m[3], 16)) / 255 : 0; };

  /* The controls that turn a colour into a blend: a switch, the end colour, straight or round, the direction.
     grad() gives what is stored now ({color, angle, kind} or nothing), store(v) keeps a new value (null = off),
     first() is the colour the blend starts from. hooks: begin (before a change), live (while dragging),
     done (a change is finished). Used by every colour setting, here and in the rate changer. */
  function gradControls(grad, store, first, hooks) {
    const now = grad() || null, box = el('div', 'grad');
    const sw = el('label', 'check');
    const cb = el('input');
    cb.type = 'checkbox'; cb.checked = !!now;
    sw.append(cb, el('span', 'box'), document.createTextNode('그라디언트'));
    const set = el('div', 'gradset');
    set.hidden = !now;
    const line = el('div', 'line');
    const color = el('input');
    color.type = 'color'; color.value = (now && now.color) || '#ffffff'; color.setAttribute('aria-label', '그라디언트 끝 색');
    const kind = el('select');
    [['linear', '직선'], ['radial', '원형 (가운데에서 바깥으로)']].forEach(([v, t]) => { const o = el('option', null, t); o.value = v; kind.append(o); });
    kind.value = now && now.kind === 'radial' ? 'radial' : 'linear';
    kind.setAttribute('aria-label', '그라디언트 모양');
    line.append(el('span', null, '끝 색'), color, kind);
    const dir = el('label', 'slider');
    const range = el('input'), out = el('output', 'num');
    range.type = 'range'; range.min = 0; range.max = 360; range.step = 5;
    range.value = now && now.angle != null ? now.angle : 90;
    out.textContent = range.value + '°';
    dir.append(el('span', null, '방향'), range, out);
    dir.hidden = kind.value === 'radial';
    set.append(line, dir);
    let armed = false;
    const begin = () => { if (!armed) { hooks.begin(); armed = true; } };
    const write = () => store({ color: color.value, angle: Number(range.value), kind: kind.value });
    cb.addEventListener('change', () => {
      hooks.begin();
      if (cb.checked) { color.value = lightOf(first()) > 0.5 ? '#000000' : '#ffffff'; write(); } else store(null);
      set.hidden = !cb.checked;
      hooks.done();
    });
    color.addEventListener('input', () => { begin(); write(); hooks.live(); });
    color.addEventListener('change', () => { armed = false; hooks.done(); });
    range.addEventListener('input', () => { begin(); out.textContent = range.value + '°'; write(); hooks.live(); });
    range.addEventListener('change', () => { armed = false; hooks.done(); });
    kind.addEventListener('change', () => { hooks.begin(); dir.hidden = kind.value === 'radial'; write(); hooks.done(); });
    box.append(sw, set);
    return box;
  }
  const GRAD_HOOKS = { begin: () => snapshot(), live: () => { app.changed(); draw(); }, done: () => changed() };

  function renderProps() {
    const host = $('props'), layer = layerById(ed.sel);
    const focused = document.activeElement && host.contains(document.activeElement) && document.activeElement.tagName === 'TEXTAREA';
    if (focused) return;                             // typing in the text box: do not rebuild under the caret
    host.textContent = '';
    host.hidden = !layer;
    if (!layer) return;
    const entry = ed.uid ? entryFor(ed.uid) : null;
    const g = placed(layer, entry), T = () => placeTarget(layer);      // shown values / where edits go
    const ST = () => ownTarget(layer);                                 // the same for colour, opacity, shadow
    host.append(el('h3', null, layerName(layer)));
    const grid = el('div', 'grid4');
    grid.append(
      numberInput('X', g.x, v => { T().x = v; }),
      numberInput('Y', g.y, v => { T().y = v; }),
      layer.type === 'text' ? numberInput('크기', g.size, v => { T().size = clamp(v, 8, 600); })
        : numberInput('높이', g.h, v => { const t = T(), r = t.w / t.h; t.h = clamp(v, 4, 4000); if (layer.type !== 'rect') t.w = t.h * r; }),
      numberInput('회전', g.rot || 0, v => { T().rot = ((v % 360) + 360) % 360; }));
    host.append(grid);
    if (layer.type === 'rect') {
      const g2 = el('div', 'grid4');
      g2.append(numberInput('너비', g.w, v => { T().w = clamp(v, 4, 4000); }),
        numberInput('모서리', layer.radius || 0, v => { layer.radius = clamp(v, 0, 2000); }));
      host.append(g2);
    }
    const holder = currentEntry(), isDeletePic = ed.uid === 'delete';
    const mine = holder && holder.layers && holder.layers[layer.id];
    if (hasKeys(mine)) {                                               // this picture has its own settings for the layer
      const what = [GEO.some(k => mine[k] != null) ? '위치·크기' : '', STYLE.some(k => mine[k] != null) ? '색·불투명도' : ''].filter(Boolean).join(', ');
      const box = el('div', 'onlythis');
      box.append(el('strong', null, (isDeletePic ? '[delete] 썸네일' : '이 맵') + '만의 ' + what));
      box.append(el('p', 'hint', '이 레이어는 ' + (isDeletePic ? '[delete] 썸네일' : '지금 보는 맵') + '에서만 ' + what + '이(가) 따로 정해져 있습니다. 다른 맵은 공통 설정 그대로입니다.'));
      const back = el('button', 'btn quiet', '공통 설정으로 되돌리기');
      back.type = 'button';
      back.addEventListener('click', () => { snapshot(); delete holder.layers[layer.id]; changed(); });
      box.append(back);
      host.append(box);
    } else if (ed.fxScope === 'one' && holder) {
      host.append(el('p', 'hint', '"이 맵만 다르게"가 켜져 있습니다. 지금 옮기거나 크기·회전·색·불투명도를 바꾸면 ' + (isDeletePic ? '[delete] 썸네일' : '지금 보는 맵') + '에만 적용됩니다.'));
    }
    const align = el('div', 'align');
    const size = entry ? visibleBox(g, entry) : { w: g.w, h: g.h }, margin = 60;
    [['왼쪽', () => { T().x = margin + size.w / 2; }], ['가운데', () => { T().x = BASE_W / 2; }],
      ['오른쪽', () => { T().x = BASE_W - margin - size.w / 2; }], ['위', () => { T().y = margin + size.h / 2; }],
      ['중간', () => { T().y = BASE_H / 2; }], ['아래', () => { T().y = BASE_H - margin - size.h / 2; }]].forEach(([label, fn]) => {
      const b = el('button', 'btn', label);
      b.type = 'button';
      b.addEventListener('click', () => { snapshot(); fn(); changed(); });
      align.append(b);
    });
    host.append(align);
    host.append(sliderLine('불투명도', Math.round((g.opacity == null ? 1 : g.opacity) * 100), 0, 100, 1, v => { ST().opacity = v / 100; }));
    host.append(sliderLine('그림자', g.shadow || 0, 0, 100, 1, v => { ST().shadow = v; }));
    const orderLine = el('div', 'line');
    orderLine.append(el('span', null, '효과와의 순서'));
    const order = el('select');
    [['', '효과 위에 (기본)'], ['grain', '노이즈·주사선 아래'], ['all', '모든 효과 아래']].forEach(([v, t]) => { const o = el('option', null, t); o.value = v; order.append(o); });
    order.value = UNDER_TAG[layer.under] ? layer.under : '';
    order.setAttribute('aria-label', '효과와의 순서');
    order.addEventListener('change', () => { snapshot(); if (order.value) layer.under = order.value; else delete layer.under; changed(); });
    orderLine.append(order);
    host.append(orderLine);
    if (layer.under === 'grain') host.append(el('p', 'hint', '이 레이어 위로 노이즈와 주사선이 덮입니다. 흐림·어둡게·색 입히기·비네트는 받지 않습니다.'));
    else if (layer.under === 'all') host.append(el('p', 'hint', '이 레이어가 배경 그림의 일부가 됩니다. 흐림·대비·채도·어둡게·색 입히기·비네트·주사선·노이즈가 그림 전체에 함께 적용됩니다.'));

    if (layer.type === 'symbol') {
      const b = el('button', 'btn symbtn');
      b.type = 'button';
      const img = el('img'); img.src = danUrl(layer.src); img.alt = '';
      b.append(img, el('span', null, '다른 심볼로 바꾸기'));
      b.addEventListener('click', async () => {
        const src = await pickSymbol();
        if (!src) return;
        const loaded = await loadImage(danUrl(src));
        snapshot();
        layer.src = src;
        if (loaded) layer.w = layer.h * loaded.naturalWidth / loaded.naturalHeight;
        changed();
      });
      host.append(b);
    } else if (layer.type === 'autodan') {
      host.append(el('p', 'hint', '맵마다 그 맵의 예상 난이도 심볼이 같은 자리에 들어갑니다. 예상 난이도를 계산할 수 없는 맵에는 아무것도 들어가지 않습니다.'));
    }
    if (layer.type === 'symbol' || layer.type === 'autodan') {
      const cur = currentEntry();
      if (cur) {                                                   // this picture only
        const mine = ownSymbol(layer, cur), isDelete = ed.uid === 'delete';
        const box = el('div', 'onlythis');
        box.append(el('strong', null, isDelete ? '[delete] 썸네일에 넣을 심볼' : '이 맵만 다른 심볼'));
        box.append(el('p', 'hint', mine ? (isDelete ? '[delete] 썸네일은 따로 고른 심볼을 쓰고 있습니다.' : '지금 보는 맵은 따로 고른 심볼을 쓰고 있습니다.')
          : isDelete ? (layer.type === 'autodan' ? '[delete] 난이도에는 예상 난이도가 없어서 이 자리가 비어 있습니다. 넣을 심볼을 직접 고르세요.'
            : '[delete] 썸네일에만 다른 단 심볼을 넣을 수 있습니다.')
            : '예: 팩에 감마와 델타가 섞여 있을 때 이 맵에만 다른 단 심볼을 넣습니다.'));
        const pick = el('button', 'btn', mine ? '다른 심볼로 다시 고르기' : isDelete ? '[delete]에 넣을 심볼 고르기' : '이 맵만 심볼 바꾸기');
        pick.type = 'button';
        pick.addEventListener('click', async () => {
          const src = await pickSymbol();
          if (!src) return;
          await loadImage(danUrl(src));
          snapshot();
          cur.symbols = Object.assign({}, cur.symbols);
          cur.symbols[layer.id] = src;
          changed();
        });
        box.append(pick);
        if (mine) {
          const back = el('button', 'btn quiet', isDelete && layer.type === 'autodan' ? '심볼 빼기' : '공통 심볼로 되돌리기');
          back.type = 'button';
          back.addEventListener('click', () => { snapshot(); delete cur.symbols[layer.id]; changed(); });
          box.append(back);
        }
        host.append(box);
      }
    }
    if (layer.type === 'symbol' || layer.type === 'autodan' || layer.type === 'image') {
      host.append(el('h3', 'sub', '색 바꾸기'));
      host.append(sliderLine('색조 돌리기', g.hue || 0, 0, 360, 1, v => { ST().hue = v; }));
      const line = el('div', 'line');
      line.append(el('span', null, '색 입히기'));
      const color = el('input');
      color.type = 'color'; color.value = g.tintColor || '#ffffff';
      let armed = false;
      color.addEventListener('input', () => {
        if (!armed) { snapshot(); armed = true; }
        const t = ST();
        t.tintColor = color.value;
        if (!placed(layer, shownEntry()).tint) t.tint = 100;
        app.changed(); draw();
      });
      color.addEventListener('change', () => { armed = false; changed(); });
      const mode = el('select');
      [['color', '색조만'], ['overlay', '오버레이'], ['multiply', '곱하기'], ['screen', '스크린'], ['source-atop', '단색으로 덮기']].forEach(([v, t]) => { const o = el('option', null, t); o.value = v; mode.append(o); });
      mode.value = g.tintMode || 'color';
      mode.addEventListener('change', () => { snapshot(); ST().tintMode = mode.value; changed(); });
      line.append(color, mode);
      host.append(line, gradControls(() => g.tintGrad, v => {
        const t = ST();
        t.tintGrad = v;
        if (v && !placed(layer, shownEntry()).tint) t.tint = 100;
      }, () => g.tintColor || '#ffffff', GRAD_HOOKS), sliderLine('색 세기', g.tint || 0, 0, 100, 1, v => { ST().tint = v; }));
    }
    if (layer.type === 'image') {
      const b = el('button', 'btn', '다른 이미지로 바꾸기');
      b.type = 'button'; b.style.marginTop = '10px';
      b.addEventListener('click', async () => {
        const file = await app.pickFile('image/png,image/jpeg,image/webp,image/gif');
        const id = file && await app.upload(file);
        const img = id && await loadImage(assetUrl(id));
        if (!img) return;
        snapshot();
        layer.asset = id; layer.name = file.name; layer.w = layer.h * img.naturalWidth / img.naturalHeight;
        changed();
      });
      host.append(b);
    } else if (layer.type === 'rect') {
      host.append(colorLine('색', layer.color || '#000000', v => { layer.color = v; }),
        gradControls(() => layer.colorGrad, v => { layer.colorGrad = v; }, () => layer.color || '#000000', GRAD_HOOKS));
    } else if (layer.type === 'text') {
      const area = el('textarea');
      area.rows = 2; area.value = layer.text || ''; area.spellcheck = false;
      let armed = false;
      area.addEventListener('input', () => {
        if (!armed) { snapshot(); armed = true; }
        layer.text = area.value; app.changed(); draw();
      });
      area.addEventListener('blur', () => { armed = false; changed(); });
      host.append(area, el('p', 'tokens', '맵마다 바뀌는 말: {title} {artist} {creator} {version} {diff} {rate} {bpm} {dan} {msd} {n} {pack}'));
      const fontLine = el('div', 'line');
      fontLine.append(el('span', null, '글꼴'));
      const select = el('select');
      FONTS.forEach(f => { const o = el('option', null, f); o.value = f; select.append(o); });
      select.value = layer.font || 'Bahnschrift';
      select.addEventListener('change', () => { snapshot(); layer.font = select.value; changed(); });
      fontLine.append(select);
      const bold = el('label', 'check');
      bold.style.margin = '0';
      const cb = el('input'); cb.type = 'checkbox'; cb.checked = !!layer.bold;
      cb.addEventListener('change', () => { snapshot(); layer.bold = cb.checked; changed(); });
      bold.append(cb, el('span', 'box'), document.createTextNode('굵게'));
      fontLine.append(bold);
      host.append(fontLine);
      const alignLine = el('div', 'line');
      alignLine.append(el('span', null, '정렬'));
      const sel2 = el('select');
      [['left', '왼쪽'], ['center', '가운데'], ['right', '오른쪽']].forEach(([v, t]) => { const o = el('option', null, t); o.value = v; sel2.append(o); });
      sel2.value = layer.align || 'center';
      sel2.addEventListener('change', () => { snapshot(); layer.align = sel2.value; changed(); });
      alignLine.append(sel2);
      host.append(alignLine, colorLine('글자 색', layer.color || '#ffffff', v => { layer.color = v; }),
        gradControls(() => layer.colorGrad, v => { layer.colorGrad = v; }, () => layer.color || '#ffffff', GRAD_HOOKS),
        sliderLine('테두리', layer.stroke || 0, 0, 30, 1, v => { layer.stroke = v; }),
        colorLine('테두리 색', layer.strokeColor || '#000000', v => { layer.strokeColor = v; }),
        gradControls(() => layer.strokeGrad, v => { layer.strokeGrad = v; }, () => layer.strokeColor || '#000000', GRAD_HOOKS));
    }
    const dup = el('button', 'btn quiet', '복제');
    dup.type = 'button'; dup.style.marginTop = '12px';
    dup.addEventListener('click', duplicate);
    host.append(dup);
  }

  function colorLine(label, value, onChange) {
    const line = el('div', 'line');
    line.append(el('span', null, label));
    const input = el('input');
    input.type = 'color'; input.value = value;
    let armed = false;
    input.addEventListener('input', () => { if (!armed) { snapshot(); armed = true; } onChange(input.value); app.changed(); draw(); });
    input.addEventListener('change', () => { armed = false; changed(); });
    line.append(input);
    return line;
  }

  function duplicate() {
    const layer = layerById(ed.sel);
    if (!layer) return;
    snapshot();
    const copy = Object.assign(JSON.parse(JSON.stringify(layer)), { id: newId(), x: layer.x + 40, y: layer.y + 40 });
    thumb().layers.push(copy);
    ed.sel = copy.id;
    changed();
  }

  // ---- symbol picker
  let symState = { family: '4k', tier: '' }, symResolve = null;
  function pickSymbol() {
    return new Promise(resolve => {
      symResolve = resolve;
      renderSymbols();
      $('symbolDlg').showModal();
    });
  }

  const builtinNames = () => { const out = new Set(); FAMILIES.forEach(f => f.levels.forEach(l => out.add(String(l).toLowerCase()))); return out; };

  /* A custom name is free as long as it is not a built-in dan name and not already used. */
  function nameProblem(name, except) {
    const base = baseOf(name);
    if (!base) return '이름을 적어 주세요.';
    if (builtinNames().has(base)) return '"' + base + '"은(는) 기존 단위인정 심볼 이름이라 쓸 수 없습니다.';
    const full = String(name).trim().toLowerCase();
    if (app.symbols().some(c => c !== except && String(c.name).trim().toLowerCase() === full)) return '같은 이름의 커스텀 심볼이 이미 있습니다.';
    return '';
  }

  function renderSymbols() {
    const custom = symState.family === 'custom';
    const fam = FAMILIES.find(f => f.id === symState.family) || FAMILIES[0];
    const famHost = $('symFamily'), tierHost = $('symTier'), grid = $('symGrid');
    famHost.textContent = ''; tierHost.textContent = ''; grid.textContent = '';
    FAMILIES.concat([{ id: 'custom', label: '커스텀' }]).forEach(f => {
      const b = el('button', null, f.label);
      b.type = 'button'; b.setAttribute('role', 'radio'); b.setAttribute('aria-checked', String(f.id === symState.family));
      b.addEventListener('click', () => { symState.family = f.id; renderSymbols(); });
      famHost.append(b);
    });
    TIERS.forEach(([label, suffix]) => {
      const b = el('button', null, label || '기본');
      b.type = 'button'; b.setAttribute('role', 'radio'); b.setAttribute('aria-checked', String(suffix === symState.tier));
      b.addEventListener('click', () => { symState.tier = suffix; renderSymbols(); });
      tierHost.append(b);
    });
    const choose = src => { $('symbolDlg').close(); const r = symResolve; symResolve = null; if (r) r(src); };
    const tierLabel = (TIERS.find(t => t[1] === symState.tier) || ['', ''])[0];
    if (custom) {
      const mine = app.symbols().filter(c => TIER_SUFFIX[tierOf(c.name)] === symState.tier);
      mine.forEach(c => {
        const b = el('button');
        b.type = 'button';
        const img = el('img'); img.src = danUrl('asset:' + c.asset); img.alt = '';
        b.append(img, el('span', null, c.name));
        b.addEventListener('click', () => choose('asset:' + c.asset));
        grid.append(b);
      });
      if (!mine.length) grid.append(el('p', 'hint', app.symbols().length ? '이 단계에 해당하는 커스텀 심볼이 없습니다. 위에서 다른 단계를 골라 보세요.' : '아직 추가한 커스텀 심볼이 없습니다. 아래에서 이미지를 추가하세요.'));
    } else {
      fam.levels.forEach(level => {
        const src = fam.dir + '/' + fam.prefix + level + symState.tier + (fam.webp.includes(level) ? '.webp' : '.svg');
        const b = el('button');
        b.type = 'button';
        const img = el('img'); img.src = danUrl(src); img.alt = ''; img.loading = 'lazy';
        b.append(img, el('span', null, level + tierLabel));
        b.addEventListener('click', () => choose(src));
        grid.append(b);
      });
    }
    renderCustomList();
  }

  function renderCustomList() {
    const host = $('symCustomList'), list = app.symbols();
    host.textContent = '';
    list.forEach(c => {
      const li = el('li');
      const img = el('img'); img.src = danUrl('asset:' + c.asset); img.alt = '';
      const input = el('input');
      input.type = 'text'; input.value = c.name; input.maxLength = 40; input.spellcheck = false; input.autocomplete = 'off';
      input.setAttribute('aria-label', '커스텀 심볼 이름');
      const tier = el('span', 'dim num', '단계 ' + (tierOf(c.name) || '기본'));
      input.addEventListener('change', () => {
        const problem = nameProblem(input.value, c);
        if (problem) { app.toast(problem); input.value = c.name; return; }
        c.name = input.value.trim();
        app.saveSymbols(list);
        renderSymbols();
      });
      const del = el('button', 'btn quiet danger', '삭제');
      del.type = 'button';
      del.addEventListener('click', () => { app.saveSymbols(list.filter(x => x !== c)); renderSymbols(); });
      li.append(img, input, tier, del);
      host.append(li);
    });
  }

  async function addCustomSymbols() {
    const files = await app.pickFiles('image/png,image/webp,image/svg+xml,image/jpeg,image/gif');
    if (!files || !files.length) return;
    const list = app.symbols().slice();
    let last = null;
    for (const file of files) {
      const id = await app.upload(file);
      if (!id) continue;
      if (list.some(c => c.asset === id)) continue;                 // the very same picture again
      let name = file.name.replace(/\.[^.]+$/, '').trim().slice(0, 40) || 'symbol';
      const tier = tierOf(name);
      const taken = n => builtinNames().has(baseOf(n)) || list.some(c => String(c.name).trim().toLowerCase() === n.toLowerCase());
      if (builtinNames().has(baseOf(name))) name = 'my ' + name;     // "alpha+.png" would shadow the real alpha
      for (let n = 2; taken(name); n++) name = (baseOf(name).replace(/ \d+$/, '') || 'symbol') + ' ' + n + tier;
      last = { asset: id, name };
      list.push(last);
    }
    app.saveSymbols(list);
    if (last) { symState.family = 'custom'; symState.tier = TIER_SUFFIX[tierOf(last.name)]; }
    renderSymbols();
  }

  // ---- pointer work on the canvas
  function toLayout(ev) {
    const r = $('overlay').getBoundingClientRect();
    return { x: (ev.clientX - r.left) / ed.k, y: (ev.clientY - r.top) / ed.k };
  }

  function hit(p) {
    const entry = ed.uid ? entryFor(ed.uid) : null, layers = thumb().layers || [];
    if (!entry) return null;
    for (let i = layers.length - 1; i >= 0; i--) {
      if (layers[i].visible === false) continue;
      const l = placed(layers[i], entry);
      const size = visibleBox(l, entry), a = -(l.rot || 0) * Math.PI / 180;
      const dx = p.x - l.x, dy = p.y - l.y;
      const lx = dx * Math.cos(a) - dy * Math.sin(a), ly = dx * Math.sin(a) + dy * Math.cos(a);
      if (Math.abs(lx) <= size.w / 2 + 6 && Math.abs(ly) <= size.h / 2 + 6) return layers[i];
    }
    return null;
  }

  function onDown(ev) {
    if (ev.button !== 0) return;
    const p = toLayout(ev), handle = ev.target.dataset && ev.target.dataset.h;
    let layer = handle ? layerById(ed.sel) : hit(p);
    if (!layer) {
      if (ed.sel) { ed.sel = null; renderLayerList(); renderProps(); placeSelection(); }
      return;
    }
    if (layer.id !== ed.sel) { ed.sel = layer.id; renderLayerList(); renderProps(); placeSelection(); }
    const entry = entryFor(ed.uid), now = placed(layer, entry), size = visibleBox(now, entry);
    ed.drag = { mode: handle || 'move', start: p, layer, target: null, moved: false,
      orig: { x: now.x, y: now.y, w: now.w, h: now.h, size: now.size, rot: now.rot || 0 },
      dist: Math.hypot(p.x - now.x, p.y - now.y) || 1, box: size };
    $('overlay').setPointerCapture(ev.pointerId);
    ev.preventDefault();
  }

  function onMove(ev) {
    const d = ed.drag;
    if (!d) return;
    const p = toLayout(ev), o = d.orig, type = d.layer.type;
    if (!d.moved) {
      if (Math.hypot(p.x - d.start.x, p.y - d.start.y) < 2) return;
      d.moved = true; snapshot();
      d.target = placeTarget(d.layer);               // the shared layer, or this picture's own place for it
    }
    const l = d.target;
    let gv = null, gh = null;
    if (d.mode === 'move') {
      let x = o.x + p.x - d.start.x, y = o.y + p.y - d.start.y;
      const snap = 10 / Math.max(ed.k, 0.3) * 0.5;
      const xs = [[BASE_W / 2, 0], [d.box.w / 2, -d.box.w / 2], [BASE_W - d.box.w / 2, d.box.w / 2]];
      const ys = [[BASE_H / 2, 0], [d.box.h / 2, -d.box.h / 2], [BASE_H - d.box.h / 2, d.box.h / 2]];
      if (!ev.altKey && !((l.rot || 0) % 180)) {
        for (const [target, off] of xs) if (Math.abs(x - target) < snap) { x = target; gv = target + off; break; }
        for (const [target, off] of ys) if (Math.abs(y - target) < snap) { y = target; gh = target + off; break; }
      }
      l.x = Math.round(x); l.y = Math.round(y);
    } else if (d.mode === 'rot') {
      let deg = Math.atan2(p.y - l.y, p.x - l.x) * 180 / Math.PI + 90;
      deg = ((deg % 360) + 360) % 360;
      const near = Math.round(deg / 45) * 45;
      if (Math.abs(deg - near) < 3) deg = near % 360;
      l.rot = Math.round(deg * 10) / 10;
    } else if (d.mode.length === 2) {
      const f = clamp(Math.hypot(p.x - l.x, p.y - l.y) / d.dist, 0.03, 40);
      if (type === 'text') l.size = clamp(Math.round(o.size * f), 8, 600);
      else { l.w = Math.max(4, o.w * f); l.h = Math.max(4, o.h * f); }
    } else {
      const a = -(l.rot || 0) * Math.PI / 180, dx = p.x - l.x, dy = p.y - l.y;
      const lx = dx * Math.cos(a) - dy * Math.sin(a), ly = dx * Math.sin(a) + dy * Math.cos(a);
      if (d.mode === 'e' || d.mode === 'w') l.w = Math.max(4, Math.abs(lx) * 2);
      else l.h = Math.max(4, Math.abs(ly) * 2);
    }
    const v = $('guideV'), h = $('guideH');
    v.hidden = gv == null; h.hidden = gh == null;
    if (gv != null) v.style.left = gv * ed.k + 'px';
    if (gh != null) h.style.top = gh * ed.k + 'px';
    draw();
  }

  function onUp() {
    const d = ed.drag;
    if (!d) return;
    ed.drag = null;
    $('guideV').hidden = true; $('guideH').hidden = true;
    if (d.moved) changed();
  }

  function onKey(ev) {
    if ($('view-thumb').hidden || document.querySelector('dialog[open]')) return;
    const tag = (ev.target.tagName || '').toLowerCase();
    if (tag === 'input' || tag === 'textarea' || tag === 'select') return;
    if ((ev.ctrlKey || ev.metaKey) && ev.key.toLowerCase() === 'z') { ev.preventDefault(); undo(); return; }
    const layer = layerById(ed.sel);
    if (!layer) return;
    if ((ev.ctrlKey || ev.metaKey) && ev.key.toLowerCase() === 'd') { ev.preventDefault(); duplicate(); return; }
    const step = ev.shiftKey ? 10 : 1;
    const moves = { ArrowLeft: [-step, 0], ArrowRight: [step, 0], ArrowUp: [0, -step], ArrowDown: [0, step] };
    if (moves[ev.key]) {
      ev.preventDefault(); snapshot();
      const t = placeTarget(layer);
      t.x += moves[ev.key][0]; t.y += moves[ev.key][1];
      changed();
    } else if (ev.key === 'Delete' || ev.key === 'Backspace') {
      ev.preventDefault(); snapshot(); removeLayer(layer.id); changed();
    } else if (ev.key === 'Escape') {
      ed.sel = null; renderLayerList(); renderProps(); placeSelection();
    }
  }

  // ---- left panel controls
  /* The object that holds what belongs to the picture on screen alone (a symbol, effects, the crop):
     the pack entry itself, or for the [delete] picture its own box in the project. */
  function currentEntry() {
    const p = app.project();
    if (ed.uid === 'delete') {
      if (!p.delete || !deleteEntry(p)) return null;
      p.delete.thumb = p.delete.thumb || {};
      p.delete.thumb.own = p.delete.thumb.own || {};
      return p.delete.thumb.own;
    }
    return p.entries.find(e => e.uid === ed.uid) || null;
  }

  /* What is actually drawn for the picture on screen (for [delete]: its base picture with its own settings). */
  const shownEntry = () => (ed.uid ? entryFor(ed.uid) : null);

  /* Where a move, resize or turn is written: the shared layer, or, while "이 맵만 다르게" is on, the place this
     picture keeps for the layer (made on the first change, starting from where the layer is now). */
  function placeTarget(layer) {
    const own = ownTarget(layer);
    if (own === layer) return layer;
    const now = placed(layer, shownEntry());
    GEO.forEach(k => { if (own[k] == null && now[k] != null) own[k] = now[k]; });
    return own;
  }

  /* Where a change that belongs to one layer is written: the shared layer, or, while "이 맵만 다르게" is on,
     what this picture keeps for the layer. Colour, opacity and shadow go straight here; a move goes through
     placeTarget, which also pins the layer's place for this picture. */
  function ownTarget(layer) {
    const holder = currentEntry();
    if (ed.fxScope !== 'one' || !holder) return layer;
    holder.layers = holder.layers || {};
    if (!holder.layers[layer.id]) holder.layers[layer.id] = {};
    return holder.layers[layer.id];
  }

  function syncBgControls() {
    const entry = currentEntry(), shown = shownEntry(), bg = (shown && shown.bg) || {}, isDelete = ed.uid === 'delete';
    const set = (id, value) => { const i = $(id); i.value = value; i.nextElementSibling.textContent = id === 'bgZoom' ? Number(value).toFixed(2) : value; i.disabled = !entry; };
    set('bgZoom', bg.zoom || 1); set('bgX', bg.x == null ? 50 : bg.x); set('bgY', bg.y == null ? 50 : bg.y);
    $('bgReplace').disabled = !entry || isDelete;          // the [delete] picture is chosen on the metadata page
    $('bgReplace').title = isDelete ? '[delete] 썸네일의 그림은 메타데이터 창의 "delete 난이도"에서 고릅니다' : '';
    $('bgRestore').hidden = isDelete || !(entry && entry.bgAsset);
  }

  /* The effect values on screen and where edits go: the shared design, or the picture being shown. */
  function fxShown() {
    const entry = currentEntry(), shown = shownEntry();
    if (ed.fxScope === 'one' && entry) return Object.assign({}, FX_DEFAULT, entry.fx || (shown && shown.fx) || thumb().fx);
    return Object.assign({}, FX_DEFAULT, thumb().fx);
  }

  function fxTarget() {
    const entry = currentEntry(), shown = shownEntry(), t = thumb();
    if (ed.fxScope === 'one' && entry) {
      if (!entry.fx) entry.fx = Object.assign({}, FX_DEFAULT, (shown && shown.fx) || t.fx);
      return entry.fx;
    }
    t.fx = Object.assign({}, FX_DEFAULT, t.fx);
    return t.fx;
  }

  function syncControls() {
    const t = thumb(), entry = currentEntry();
    if (!entry) ed.fxScope = 'all';
    const fx = fxShown(), one = ed.fxScope === 'one';
    document.querySelectorAll('[data-fx]').forEach(input => {
      const key = input.dataset.fx;
      if (input.type === 'checkbox') input.checked = !!fx[key];
      else input.value = fx[key];
      if (input.type === 'range') input.nextElementSibling.textContent = fx[key];
    });
    document.querySelectorAll('input[name="fxScope"]').forEach(r => { r.checked = r.value === ed.fxScope; r.disabled = r.value === 'one' && !entry; });
    const what = ed.uid === 'delete' ? '[delete] 썸네일' : '지금 보는 맵';
    $('fxScopeNote').textContent = one ? what + '에만 적용됩니다: 효과, 그리고 심볼·글자 등을 옮기거나 크기·색조·불투명도를 바꾸는 것. 나머지는 그대로입니다.'
      : (entry && entry.fx ? '모든 맵에 똑같이 적용됩니다. 단, ' + what + '은(는) 따로 정한 효과를 쓰고 있어 여기서 바꿔도 달라지지 않습니다.' : '모든 맵에 똑같이 적용됩니다.');
    $('fxOneClear').hidden = !(entry && entry.fx);
    const gradHost = $('fxTintGrad');
    gradHost.textContent = '';
    gradHost.append(gradControls(() => fxShown().tintGrad, v => {
      const target = fxTarget();
      target.tintGrad = v;
      if (v && !target.tint) target.tint = 40;
    }, () => fxShown().tintColor || '#000000',
    { begin: () => snapshot(), live: () => { app.changed(); draw(); }, done: () => { changed(); syncControls(); } }));
    document.querySelectorAll('input[name="bgMode"]').forEach(r => { r.checked = r.value === (t.bgMode || 'each'); });
    $('commonRow').hidden = t.bgMode !== 'common';
    $('commonName').textContent = t.commonAsset ? (t.commonName || '고른 이미지') : '아직 고르지 않았습니다';
    document.querySelectorAll('input[name="imgFormat"]').forEach(r => { r.checked = r.value === (t.format || 'jpg'); });
    $('pngNote').hidden = t.format !== 'png';
    $('qualityRow').hidden = t.format === 'png';
    $('imgQuality').value = t.quality || 100;
    $('imgQuality').nextElementSibling.textContent = t.quality || 100;
    $('imgSize').value = t.size || '1920x1080';
    syncBgControls();
  }

  function bindControls() {
    let armed = false;
    document.querySelectorAll('[data-fx]').forEach(input => {
      const key = input.dataset.fx;
      const apply = () => {
        if (!armed) { snapshot(); armed = true; }
        fxTarget()[key] = input.type === 'checkbox' ? input.checked : input.type === 'range' ? Number(input.value) : input.value;
        if (input.type === 'range') input.nextElementSibling.textContent = input.value;
        app.changed(); draw();
      };
      input.addEventListener('input', apply);
      input.addEventListener('change', () => { apply(); armed = false; changed(); syncControls(); });
    });
    $('fxReset').addEventListener('click', () => { snapshot(); Object.assign(fxTarget(), FX_DEFAULT); syncControls(); changed(); });
    $('fxOneClear').addEventListener('click', () => {
      const entry = currentEntry();
      if (!entry) return;
      snapshot(); delete entry.fx; ed.fxScope = 'all'; syncControls(); changed();
    });
    document.querySelectorAll('input[name="fxScope"]').forEach(r => r.addEventListener('change', () => { ed.fxScope = r.value; syncControls(); renderProps(); }));
    $('symAdd').addEventListener('click', addCustomSymbols);
    document.querySelectorAll('input[name="bgMode"]').forEach(r => r.addEventListener('change', () => {
      snapshot(); thumb().bgMode = r.value; syncControls(); changed();
    }));
    $('commonPick').addEventListener('click', async () => {
      const file = await app.pickFile('image/png,image/jpeg,image/webp,image/gif,image/bmp');
      const id = file && await app.upload(file);
      if (!id) return;
      snapshot();
      Object.assign(thumb(), { commonAsset: id, commonName: file.name, bgMode: 'common' });
      syncControls(); changed();
    });
    [['bgZoom', 'zoom'], ['bgX', 'x'], ['bgY', 'y']].forEach(([id, key]) => {
      const input = $(id);
      input.addEventListener('input', () => {
        const entry = currentEntry();
        if (!entry) return;
        entry.bg = Object.assign({ x: 50, y: 50, zoom: 1 }, entry.bg);
        entry.bg[key] = Number(input.value);
        input.nextElementSibling.textContent = key === 'zoom' ? Number(input.value).toFixed(2) : input.value;
        app.changed(); draw();
      });
      input.addEventListener('change', () => changed());
    });
    $('bgReplace').addEventListener('click', async () => {
      const entry = currentEntry();
      if (!entry || ed.uid === 'delete') return;
      const file = await app.pickFile('image/png,image/jpeg,image/webp,image/gif,image/bmp');
      const id = file && await app.upload(file);
      if (!id) return;
      entry.bgAsset = id;
      syncBgControls(); changed();
    });
    $('bgRestore').addEventListener('click', () => {
      const entry = currentEntry();
      if (!entry) return;
      delete entry.bgAsset;
      syncBgControls(); changed();
    });
    document.querySelectorAll('input[name="imgFormat"]').forEach(r => r.addEventListener('change', () => {
      thumb().format = r.value; syncControls(); app.changed();
    }));
    $('imgQuality').addEventListener('input', ev => { thumb().quality = Number(ev.target.value); ev.target.nextElementSibling.textContent = ev.target.value; app.changed(); });
    $('imgSize').addEventListener('change', ev => { thumb().size = ev.target.value; app.changed(); });
    document.querySelectorAll('[data-add]').forEach(b => b.addEventListener('click', () => {
      if (!app.project().entries.length) { app.toast('먼저 팩에 맵을 넣어 주세요.'); return; }
      addLayer(b.dataset.add);
    }));
    $('undoBtn').addEventListener('click', undo);
    const overlay = $('overlay');
    overlay.addEventListener('pointerdown', onDown);
    overlay.addEventListener('pointermove', onMove);
    overlay.addEventListener('pointerup', onUp);
    overlay.addEventListener('pointercancel', onUp);
    document.addEventListener('keydown', onKey);
    new ResizeObserver(() => { if (!$('view-thumb').hidden) { fit(); draw(); } }).observe($('canvasStage'));
    $('symbolDlg').addEventListener('close', () => { const r = symResolve; symResolve = null; if (r) r(null); });
  }

  function init(host) {
    app = host;
    bindControls();
  }

  /* Called when the thumbnail view is shown or the project changed elsewhere. */
  function refresh() {
    const p = app.project();
    if (ed.uid && ed.uid !== 'delete' && !p.entries.some(e => e.uid === ed.uid)) ed.uid = null;
    if (!ed.uid && p.entries.length) ed.uid = p.entries[0].uid;
    if (!layerById(ed.sel)) ed.sel = null;
    fit();
    syncControls();
    renderLayerList();
    renderProps();
    draw();
    renderFilm();
  }

  function reset() { ed.undo = []; ed.sel = null; ed.uid = null; ed.fxScope = 'all'; }

  window.Thumb = { init, refresh, reset, defaults, render, exportBlob, blobWith, fillTokens, entryFor, FX_DEFAULT, gradControls,
    show(uid) { ed.uid = uid; } };
})();
