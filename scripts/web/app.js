/* Tiny League — v2 front-end.
   Inlined into out/index.html by scripts/generate_html.py.
   Placeholders filled at build time: __MODELS__ __BENCHES__ __BENCH_COV__
   __AXES__ __PRESETS__ __CORE_MIN__ __DEFAULT_CHARTS__ */

const MODELS = __MODELS__;
const BENCHES = __BENCHES__;
const BENCH_COV = __BENCH_COV__;
const AXES = __AXES__;
const PRESETS = __PRESETS__;
/* A benchmark column counts as "core" when at least this many models report it;
   the heatmap opens on the core view so it is readable at a glance. */
const CORE_MIN = __CORE_MIN__;
const CORE_ALWAYS = __CORE_ALWAYS__;
/* How many comparison bar charts the page shows before "show all". */
const DEFAULT_CHARTS = __DEFAULT_CHARTS__;
/* A per-benchmark bar chart is only drawn when this many models can be compared. */
var MIN_CHART_MODELS = 4;

function escJS(s) {
  return String(s).replace(/[&<>"']/g, function (c) {
    return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
  });
}

var charts = [];
function destroyCharts() {
  for (var i = 0; i < charts.length; i++) { try { charts[i].destroy(); } catch (e) { } }
  charts = [];
}

/* ---------- filter state ---------- */

var pfMin = document.getElementById('pf-min');
var pfMax = document.getElementById('pf-max');
var pfVision = document.getElementById('pf-vision');
var pfMoe = document.getElementById('pf-moe');
var pfFab = document.getElementById('pf-fab');
var pfPanel = document.getElementById('pf-panel');
var pfBadge = document.getElementById('pf-badge');
var pfClose = document.getElementById('pf-close');
var mfFab = document.getElementById('mf-fab');
var mfPanel = document.getElementById('mf-panel');
var mfList = document.getElementById('mf-list');
var mfBadge = document.getElementById('mf-badge');
var mfClose = document.getElementById('mf-close');

var chartTabs = document.getElementById('chart-tabs');
var chartCustom = document.getElementById('chart-custom');
var chartX = document.getElementById('chart-x');
var chartY = document.getElementById('chart-y');
var chartPane = document.getElementById('chart-pane');
var chartMode = (PRESETS.length ? PRESETS[0].id : 'custom');

function onlyVision() { return !!(pfVision && pfVision.checked); }
function onlyMoe() { return !!(pfMoe && pfMoe.checked); }

/* ---------- theme (auto / light / dark) ---------- */

var THEME_KEY = 'tl-theme';
var THEME_NEXT = { auto: 'light', light: 'dark', dark: 'auto' };
var themeMQ = window.matchMedia ? window.matchMedia('(prefers-color-scheme: dark)') : null;
var themeBtn = document.getElementById('theme-btn');
var themeMeta = document.getElementById('theme-color');
var printTheme = null;

function themeMode() {
  var m = document.documentElement.getAttribute('data-theme-mode');
  return (m === 'light' || m === 'dark') ? m : 'auto';
}
function prefersDark() { return !!(themeMQ && themeMQ.matches); }
/* The palette actually in use — data-theme, which the head script and
   applyTheme() always set. (beforeprint() flips it to light without touching
   the visitor's chosen mode.) */
function resolvedTheme() {
  var t = document.documentElement.getAttribute('data-theme');
  if (t === 'light' || t === 'dark') { return t; }
  return prefersDark() ? 'dark' : 'light';
}
/* Accessible name for the cycling button: current mode + what the next click does. */
function themeCopy() {
  var m = themeMode(), cur = resolvedTheme();
  if (m === 'auto') {
    return 'Theme: auto (' + cur + ') — following your system. Click for light.';
  }
  if (m === 'light') { return 'Theme: light. Click for dark.'; }
  return 'Theme: dark. Click for auto.';
}
function syncThemeChrome() {
  var t = resolvedTheme();
  if (themeMeta) { themeMeta.setAttribute('content', t === 'dark' ? '#0b0e13' : '#fcfcfd'); }
  if (themeBtn) {
    var msg = themeCopy();
    themeBtn.setAttribute('aria-label', msg);
    themeBtn.title = msg;
  }
}
function applyTheme(mode, persist) {
  if (mode !== 'light' && mode !== 'dark') { mode = 'auto'; }
  var t = (mode === 'auto') ? (prefersDark() ? 'dark' : 'light') : mode;
  var root = document.documentElement;
  root.setAttribute('data-theme-mode', mode);
  root.setAttribute('data-theme', t);
  if (persist) {
    try {
      if (mode === 'auto') { localStorage.removeItem(THEME_KEY); }
      else { localStorage.setItem(THEME_KEY, mode); }
    } catch (e) { }
  }
  syncThemeChrome();
  CHART_CC = null;
  recolorHeatmap();
  lastSig = null;
  buildCharts();
}
if (themeBtn) {
  themeBtn.addEventListener('click', function () {
    applyTheme(THEME_NEXT[themeMode()] || 'light', true);
  });
}
/* In auto mode, follow the OS live — no reload needed. */
if (themeMQ) {
  var onSchemeChange = function () {
    if (themeMode() === 'auto') { applyTheme('auto', false); }
  };
  if (themeMQ.addEventListener) { themeMQ.addEventListener('change', onSchemeChange); }
  else if (themeMQ.addListener) { themeMQ.addListener(onSchemeChange); }
}
/* Paper is always light: the dark palette would print light text on white.
   Restore the chosen mode once the print dialog closes. */
window.addEventListener('beforeprint', function () {
  if (resolvedTheme() === 'light' || printTheme) { return; }
  printTheme = themeMode();
  document.documentElement.setAttribute('data-theme', 'light');
  CHART_CC = null;
  recolorHeatmap();
  lastSig = null;
  buildCharts();
});
window.addEventListener('afterprint', function () {
  if (!printTheme) { return; }
  var m = printTheme;
  printTheme = null;
  applyTheme(m, false);
});

/* Explicit model selection (whitelist): only the checked models show anywhere.
   An empty selection means "no filter" — the same as reset. */
var selectedModels = {};
function selActive() { for (var k in selectedModels) { return true; } return false; }
function selCount() { var n = 0; for (var k in selectedModels) { n++; } return n; }
function curRange() {
  var a = parseInt(pfMin.value, 10), b = parseInt(pfMax.value, 10);
  if (isNaN(a)) a = 0; if (isNaN(b)) b = 0;
  if (a > b) { var t = a; a = b; b = t; }
  return [a, b];
}
function visibleModels() {
  var r = curRange(), ov = onlyVision(), om = onlyMoe(), sa = selActive();
  return MODELS.filter(function (m) {
    return typeof m.params === 'number' && m.params >= r[0] && m.params <= r[1]
      && (!ov || m.vision) && (!om || m.moe) && (!sa || selectedModels[m.id]);
  });
}

/* ---------- URL state (shareable filters) ---------- */

var lastQs = '';

function saveState() {
  var r = curRange(), p = new URLSearchParams();
  if (r[0] > parseInt(pfMin.min, 10)) { p.set('min', r[0]); }
  if (r[1] < parseInt(pfMax.max, 10)) { p.set('max', r[1]); }
  if (onlyVision()) { p.set('vision', '1'); }
  if (onlyMoe()) { p.set('moe', '1'); }
  if (selActive()) { p.set('sel', Object.keys(selectedModels).join(',')); }
  if (chartMode && chartMode !== (PRESETS.length ? PRESETS[0].id : 'custom')) { p.set('chart', chartMode); }
  if (bfInput && bfInput.value) { p.set('bf', bfInput.value); }
  if (heatView !== 'core') { p.set('hv', heatView); }
  lastQs = p.toString();
  updateShareButton();
  if (!window.history || !history.replaceState) { return; }
  try { history.replaceState(null, '', location.pathname + (lastQs ? '?' + lastQs : '') + location.hash); } catch (e) { }
}

/* Absolute URL of the current view — falls back to string assembly when
   replaceState is unavailable (file:// in some browsers). */
function viewUrl() {
  var base = location.href.split('#')[0].split('?')[0];
  return base + (lastQs ? '?' + lastQs : '');
}

/* ---------- share: copy a link to the current view ---------- */

var shareFab = document.getElementById('share-fab');
var shareLabel = document.getElementById('share-label');
var shareStatus = document.getElementById('share-status');
var shareTimer = null;

function resetShare() {
  if (shareTimer) { clearTimeout(shareTimer); shareTimer = null; }
  if (shareFab) {
    shareFab.classList.remove('copied');
    shareFab.setAttribute('aria-label', 'Share — copy a link to this view');
    shareFab.title = 'Copy a link to this view';
  }
  if (shareLabel) { shareLabel.textContent = 'Share'; }
}

function flashShare(ok) {
  if (shareTimer) { clearTimeout(shareTimer); }
  if (shareFab) {
    shareFab.classList.toggle('copied', ok);
    var msg = ok ? 'Copied — link to this view is on the clipboard'
                 : 'Press Ctrl+C to copy the link from the dialog';
    shareFab.setAttribute('aria-label', msg);
    shareFab.title = ok ? 'Link copied' : 'Copy failed';
  }
  if (shareLabel) { shareLabel.textContent = ok ? 'Copied' : 'Copy failed'; }
  if (shareStatus) { shareStatus.textContent = ok ? 'Link copied to the clipboard.' : 'Could not copy the link.'; }
  shareTimer = setTimeout(resetShare, 2000);
}

/* Shown only when the view differs from the default (i.e. the URL carries state). */
function updateShareButton() {
  if (!shareFab) { return; }
  var on = lastQs !== '';
  if (shareFab.hidden === on) { shareFab.hidden = !on; }
  if (!on) { resetShare(); }
}

function fallbackCopy(text) {
  var ta = document.createElement('textarea');
  ta.value = text;
  ta.setAttribute('readonly', '');
  ta.style.position = 'fixed';
  ta.style.top = '-1000px';
  ta.style.opacity = '0';
  document.body.appendChild(ta);
  ta.select();
  ta.setSelectionRange(0, text.length);
  var ok = false;
  try { ok = document.execCommand('copy'); } catch (e) { ok = false; }
  document.body.removeChild(ta);
  return ok;
}

function copyShareLink() {
  var url = viewUrl();
  function finish(ok) {
    flashShare(ok);
    if (!ok) { window.prompt('Copy this link:', url); }
  }
  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(url).then(
      function () { finish(true); },
      function () { finish(fallbackCopy(url)); });
  } else {
    finish(fallbackCopy(url));
  }
}

if (shareFab) { shareFab.addEventListener('click', copyShareLink); }

function restoreState() {
  var p;
  try { p = new URLSearchParams(location.search); } catch (e) { return; }
  function num(k) { var v = parseInt(p.get(k), 10); return isNaN(v) ? null : v; }
  var mn = num('min'), mx = num('max');
  if (mn !== null) { pfMin.value = mn; }
  if (mx !== null) { pfMax.value = mx; }
  if (p.get('vision') === '1' && pfVision) { pfVision.checked = true; }
  if (p.get('moe') === '1' && pfMoe) { pfMoe.checked = true; }
  var sel = p.get('sel');
  if (sel) { sel.split(',').forEach(function (id) { if (id) { selectedModels[id] = true; } }); }
  var bf = p.get('bf');
  if (bf && bfInput) { bfInput.value = bf; }
  var hv = p.get('hv');
  if (hv === 'all' || hv === 'core') { heatView = hv; }
  var ch = p.get('chart');
  if (ch) { chartMode = ch; }
}

/* ---------- heatmap helpers ---------- */

var SCORES = {};
MODELS.forEach(function (m) { SCORES[m.id] = m.scores; });

/* Heatmap ramps. Light goes pale → deep indigo; dark goes near-surface navy
   → bright indigo, so "more = brighter" reads correctly on a dark page. The
   medal cell is gold in both. Keep in sync with generate_html.py's initial
   server-side render (JS re-colours on load and on every theme change). */
var HEAT = {
  light: { lo: [238, 240, 255], hi: [45, 49, 166],
           bestBg: '#fef0c7', bestFg: '#7a2e0e', bestLine: '#fec84b' },
  dark: { lo: [27, 33, 64], hi: [141, 144, 255],
          bestBg: '#3a2a0a', bestFg: '#ffe0a3', bestLine: '#7a5a12' }
};
function heatPalette() { return resolvedTheme() === 'dark' ? HEAT.dark : HEAT.light; }

function heatColor(t) {
  var p = heatPalette();
  t = t < 0 ? 0 : (t > 1 ? 1 : t);
  var r = Math.round(p.lo[0] + (p.hi[0] - p.lo[0]) * t);
  var g = Math.round(p.lo[1] + (p.hi[1] - p.lo[1]) * t);
  var b = Math.round(p.lo[2] + (p.hi[2] - p.lo[2]) * t);
  return 'rgb(' + r + ',' + g + ',' + b + ')';
}
/* Matches heat_style() in generate_html.py: background + a text colour that always
   clears WCAG AA (mid-ramp steps are nudged darker instead of failing). */
function heatStyle(t) {
  var p = heatPalette();
  t = t < 0 ? 0 : (t > 1 ? 1 : t);
  var r = p.lo[0] + (p.hi[0] - p.lo[0]) * t;
  var g = p.lo[1] + (p.hi[1] - p.lo[1]) * t;
  var b = p.lo[2] + (p.hi[2] - p.lo[2]) * t;

  function relLum(cr, cg, cb) {
    function ch(c) {
      c = c / 255;
      return c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
    }
    return 0.2126 * ch(cr) + 0.7152 * ch(cg) + 0.0722 * ch(cb);
  }
  var lum = relLum(r, g, b);
  var white = 1.05 / (lum + 0.05);
  if (white >= 4.5) { return ['rgb(' + Math.round(r) + ',' + Math.round(g) + ',' + Math.round(b) + ')', '#ffffff']; }
  var inkLum = relLum(16, 24, 40);
  var ink = (Math.max(lum, inkLum) + 0.05) / (Math.min(lum, inkLum) + 0.05);
  if (ink >= 4.5) { return ['rgb(' + Math.round(r) + ',' + Math.round(g) + ',' + Math.round(b) + ')', '#101828']; }
  var k = 1.0;
  while (k > 0.35) {
    k -= 0.02;
    if ((1.05 / (relLum(r * k, g * k, b * k) + 0.05)) >= 4.5) { break; }
  }
  return ['rgb(' + Math.round(r * k) + ',' + Math.round(g * k) + ',' + Math.round(b * k) + ')', '#ffffff'];
}

/* ---------- chart axes ---------- */

function axisVal(m, k) {
  if (k === 'params') { return (typeof m.params === 'number') ? m.params : null; }
  if (k === 'kvGib') { return (typeof m.kvGib === 'number') ? m.kvGib : null; }
  if (k === 'perfFresh') { return (typeof m.perfFresh === 'number') ? m.perfFresh : null; }
  if (k === 'perfRef') { return (typeof m.perfRef === 'number') ? m.perfRef : null; }
  if (k === 'release') { return (typeof m.released === 'number') ? m.released : null; }
  if (k.indexOf('bench:') === 0) { var v = m.scores[k.slice(6)]; return (typeof v === 'number') ? v : null; }
  return null;
}
function axisLabel(k) {
  for (var i = 0; i < AXES.length; i++) { if (AXES[i].k === k) { return AXES[i].label; } }
  return k;
}
function axisLowerIsBetter(k) {
  for (var i = 0; i < AXES.length; i++) { if (AXES[i].k === k) { return !!AXES[i].low; } }
  return false;
}
function specFor(mode) {
  for (var i = 0; i < PRESETS.length; i++) {
    var p = PRESETS[i];
    if (p.id !== mode) { continue; }
    if (!p.custom) { return { x: p.x, y: p.y, note: p.note || '', preset: true }; }
    break;
  }
  var x = (chartX && chartX.value) ? chartX.value : 'params';
  var y = (chartY && chartY.value) ? chartY.value : 'kvGib';
  return { x: x, y: y, note: '', preset: false };
}
function currentSpec() { return specFor(chartMode); }
function isCustomMode() { return !specFor(chartMode).preset; }

/* ---------- chart rendering ---------- */

var lastSig = null;
var chartTimer = null;
function scheduleCharts() {
  if (chartTimer) { clearTimeout(chartTimer); }
  chartTimer = setTimeout(buildCharts, 120);
}

var showAllCharts = false;

function buildCharts() {
  var vm = visibleModels();
  var spec = currentSpec();
  var sig = vm.map(function (m) { return m.id; }).join('|')
    + '#' + spec.x + '|' + spec.y + '#' + (showAllCharts ? 'all' : 'top');
  if (sig === lastSig) { return; }
  lastSig = sig;
  destroyCharts();
  buildBars(vm);
  renderScatter(vm, spec);
}

/* Canvas cannot resolve CSS variables, so the chart palette is read from the
   active theme's tokens and cached — a draw loop must not force style recalcs.
   Invalidated whenever the theme changes. */
var CHART_CC = null;
function cssVar(name, fallback) {
  var v = '';
  try { v = getComputedStyle(document.documentElement).getPropertyValue(name); } catch (e) { }
  v = v ? v.trim() : '';
  return v || fallback;
}
function chartColors() {
  if (CHART_CC) { return CHART_CC; }
  CHART_CC = {
    bar1: cssVar('--chart-bar-1', '#3538cd'),
    bar2: cssVar('--chart-bar-2', '#a5a8ef'),
    grid: cssVar('--chart-grid', '#eaecf0'),
    tick: cssVar('--chart-tick', '#667085'),
    tickStrong: cssVar('--chart-tick-strong', '#344054'),
    label: cssVar('--chart-label', '#475467'),
    halo: cssVar('--chart-halo', 'rgba(255,255,255,.92)'),
    point: cssVar('--chart-point', 'rgba(53,56,205,.85)'),
    pointBorder: cssVar('--chart-point-border', '#ffffff'),
    tooltipBg: cssVar('--tooltip-bg', '#101828'),
    tooltipFg: cssVar('--tooltip-fg', '#f6f7f9')
  };
  return CHART_CC;
}

/* Draws the value at the end of each bar (Chart.js has no datalabels plugin here). */
var BAR_LABEL = {
  id: 'barLabel',
  afterDatasetsDraw: function (ch) {
    var ctx = ch.ctx, meta = ch.getDatasetMeta(0);
    ctx.save();
    ctx.font = '600 11px ui-sans-serif, -apple-system, "Segoe UI", Roboto, sans-serif';
    ctx.fillStyle = chartColors().label;
    ctx.textAlign = 'left';
    ctx.textBaseline = 'middle';
    for (var i = 0; i < meta.data.length; i++) {
      var bar = meta.data[i];
      var v = ch.data.datasets[0].data[i];
      if (typeof v !== 'number') { continue; }
      ctx.fillText(String(Math.round(v * 10) / 10), bar.x + 6, bar.y);
    }
    ctx.restore();
  }
};

/* Bar-chart tick labels: long model ids get wrapped onto two lines at a natural
   boundary (hyphen / dot / slash) so the axis stays narrow but nothing is clipped. */
function wrapName(name, max) {
  max = max || 20;
  if (name.length <= max) { return name; }
  var mid = Math.ceil(name.length / 2);
  var best = -1, bestDist = 1e9;
  for (var i = 1; i < name.length - 1; i++) {
    var c = name.charAt(i);
    if (c === '-' || c === '.' || c === '/' || c === '_') {
      var d = Math.abs(i - mid);
      if (d < bestDist) { bestDist = d; best = i; }
    }
  }
  if (best < 0) { return name; }
  return [name.slice(0, best + 1), name.slice(best + 1)];
}

function buildBars(vm) {
  var grid = document.getElementById('charts-grid');
  if (!grid) { return; }
  grid.innerHTML = '';
  var made = 0, eligible = [];
  var cc = chartColors();

  BENCHES.forEach(function (b) {
    var all = vm.filter(function (m) { return typeof m.scores[b] === 'number'; })
      .map(function (m) { return { name: m.name, v: m.scores[b] }; })
      .sort(function (x, y) { return y.v - x.v; });
    if (all.length < MIN_CHART_MODELS) { return; }
    eligible.push({ b: b, all: all });
  });

  eligible.sort(function (a, b) { return b.all.length - a.all.length; });
  var limit = showAllCharts ? eligible.length : Math.min(DEFAULT_CHARTS, eligible.length);

  eligible.slice(0, limit).forEach(function (e) {
    var b = e.b, all = e.all, rows = all.slice(0, 10);
    made++;
    var box = document.createElement('div'); box.className = 'chart-box';
    var h3 = document.createElement('h3');
    h3.innerHTML = escJS(b) + ' <span class="note">('
      + (all.length > rows.length ? 'top ' + rows.length + ' of ' + all.length : rows.length + ' models')
      + ')</span>';
    var wrap = document.createElement('div'); wrap.className = 'chart-wrap';
    wrap.style.height = Math.max(190, rows.length * 30) + 'px';
    var cv = document.createElement('canvas'); wrap.appendChild(cv);
    box.appendChild(h3); box.appendChild(wrap); grid.appendChild(box);
    charts.push(new Chart(cv, {
      type: 'bar',
      data: {
        labels: rows.map(function (r) { return wrapName(r.name); }),
        datasets: [{
          data: rows.map(function (r) { return r.v; }),
          /* Opaque colours: a translucent fill lets the grid lines show through the bar. */
          backgroundColor: rows.map(function (r, i) { return i === 0 ? cc.bar1 : cc.bar2; }),
          borderRadius: 4,
          maxBarThickness: 26
        }]
      },
      options: {
        indexAxis: 'y', responsive: true, maintainAspectRatio: false,
        layout: { padding: { right: 34 } },
        plugins: {
          legend: { display: false },
          tooltip: {
            backgroundColor: cc.tooltipBg, titleColor: cc.tooltipFg, bodyColor: cc.tooltipFg,
            callbacks: { label: function (c) { return ' ' + c.parsed.x; } }
          }
        },
        scales: {
          x: { beginAtZero: true, grid: { color: cc.grid }, ticks: { color: cc.tick, font: { size: 11 } }, border: { display: false } },
          y: { autoSkip: false, grid: { display: false }, ticks: { color: cc.tickStrong, font: { size: 11 }, crossAlign: 'far' }, border: { display: false } }
        }
      },
      plugins: [BAR_LABEL]
    }));
  });

  var actions = document.getElementById('cmp-actions');
  if (actions) {
    actions.hidden = (eligible.length <= DEFAULT_CHARTS);
    var btn = actions.querySelector('button');
    if (btn) { btn.textContent = showAllCharts ? 'Show fewer' : 'Show all ' + eligible.length; }
  }
  if (made === 0) {
    var p0 = document.createElement('p'); p0.className = 'empty';
    p0.textContent = 'No benchmark is reported by four or more models in this range.';
    grid.appendChild(p0);
  }
}

/* Radial corner glow anchored on the top-left corner (high score / few params
   = the interesting corner), fading toward the far corner. Only used when X is
   parameters. The colour is a bare "r,g,b" triplet read from a theme token at
   draw time, so the same shape can be green (the sweet spot) or red (the corner
   to avoid) in either palette. */
function cornerGlow(id, token, fallback) {
  return {
    id: id,
    beforeDraw: function (ch) {
      var a = ch.chartArea; if (!a) { return; }
      var rgb = cssVar(token, fallback);
      var ctx = ch.ctx, w = a.right - a.left, h = a.bottom - a.top;
      if (w <= 0 || h <= 0) { return; }
      ctx.save();
      ctx.beginPath(); ctx.rect(a.left, a.top, w, h); ctx.clip();
      ctx.translate(a.left, a.top); ctx.scale(w, h);
      var g = ctx.createRadialGradient(0, 0, 0, 0, 0, 1);
      g.addColorStop(0, 'rgba(' + rgb + ',0.13)');
      g.addColorStop(0.30, 'rgba(' + rgb + ',0.06)');
      g.addColorStop(0.55, 'rgba(' + rgb + ',0.02)');
      g.addColorStop(0.80, 'rgba(' + rgb + ',0)');
      g.addColorStop(1, 'rgba(' + rgb + ',0)');
      ctx.fillStyle = g; ctx.fillRect(0, 0, 1, 1);
      ctx.restore();
    }
  };
}
var GLOW_PLUGIN = cornerGlow('cornerGlow', '--glow-good', '2,122,72');
var WARN_PLUGIN = cornerGlow('cornerWarn', '--glow-warn', '180,35,24');

/* Draws each point's model name next to it, avoiding overlaps. */
var LABEL_PLUGIN = {
  id: 'pt',
  afterDatasetsDraw: function (ch) {
    var ctx = ch.ctx, a = ch.chartArea; if (!a) { return; }
    var cc = chartColors();
    var placed = [];
    /* Seed the occupied boxes with every point so a label never lands on a dot. */
    var meta = ch.getDatasetMeta(0);
    for (var pi = 0; pi < meta.data.length; pi++) {
      var pt = meta.data[pi];
      if (!pt) { continue; }
      placed.push({ x: pt.x - 5, y: pt.y - 5, w: 10, h: 10 });
    }
    function hits(r) {
      for (var i = 0; i < placed.length; i++) {
        var o = placed[i];
        if (r.x < o.x + o.w && r.x + r.w > o.x && r.y < o.y + o.h && r.y + r.h > o.y) { return true; }
      }
      return false;
    }
    var narrow = ch.width < 560;
    var fs = narrow ? 10 : 11;
    ch.data.datasets[0].data.forEach(function (d, i) {
      var p = ch.getDatasetMeta(0).data[i]; if (!p) { return; }
      ctx.save(); ctx.font = fs + 'px ui-sans-serif, -apple-system, "Segoe UI", Roboto, sans-serif';
      var w = ctx.measureText(d.label).width, h = fs + 1;
      var cands = [[10, -3], [10, -16], [10, 11], [-10 - w, -3], [-10 - w, -16], [-10 - w, 11], [10, -29], [10, 25]];
      var best = null;
      for (var k = 0; k < cands.length; k++) {
        var x = p.x + cands[k][0], y = p.y + cands[k][1];
        if (x < a.left || x + w > a.right || y < a.top + h || y > a.bottom) { continue; }
        var r = { x: x, y: y - h + 2, w: w, h: h };
        if (!hits(r)) { best = r; break; }
      }
      /* On a phone there is no free slot for most labels; drawing them anyway
         produced an unreadable pile. Leave them out — the tooltip still names
         the point. */
      if (!best && narrow) { ctx.restore(); return; }
      if (best) { placed.push(best); }
      var bx = best ? best.x : Math.min(Math.max(p.x + 10, a.left), a.right - w);
      var by = best ? best.y : p.y - 3;
      /* A halo in the page colour keeps a label readable even when it sits
         over the plot grid (white in light mode, near-black in dark). */
      ctx.lineWidth = 3;
      ctx.strokeStyle = cc.halo;
      ctx.lineJoin = 'round';
      ctx.strokeText(d.label, bx, by);
      ctx.fillStyle = best ? cc.tickStrong : cc.tick;
      ctx.fillText(d.label, bx, by);
      ctx.restore();
    });
  }
};

function fmtNum(v) { return (Math.round(v * 10) / 10).toString(); }function isDateAxis(k) { return k === 'release'; }
function fmtDate(ms) { var d = new Date(ms); return isNaN(d.getTime()) ? '' : d.toISOString().slice(0, 10); }
function fmtAxisVal(k, v) { return isDateAxis(k) ? fmtDate(v) : fmtNum(v); }
function axisScale(k, label) {
  var cc = chartColors();
  var s = {
    title: { display: true, text: label, color: cc.tick, font: { size: 11.5 } },
    grid: { color: cc.grid },
    ticks: { color: cc.tick, font: { size: 11 } },
    border: { display: false }
  };
  if (isDateAxis(k)) { s.ticks.callback = function (v) { return fmtDate(v); }; }
  if (axisLowerIsBetter(k)) { s.type = 'logarithmic'; }
  return s;
}

function renderScatter(vm, spec) {
  if (!chartPane) { return; }
  chartPane.innerHTML = '';
  var xn = axisLabel(spec.x), yn = axisLabel(spec.y);
  var pts = [];
  vm.forEach(function (m) {
    var xv = axisVal(m, spec.x), yv = axisVal(m, spec.y);
    if (xv === null || yv === null) { return; }
    pts.push({ x: xv, y: yv, label: m.name, url: m.url });
  });
  if (!pts.length) {
    var p1 = document.createElement('p'); p1.className = 'empty';
    p1.textContent = 'No model in this range reports both ' + xn + ' and ' + yn + '.';
    chartPane.appendChild(p1); return;
  }
  var box = document.createElement('div'); box.className = 'chart-box';
  var h3 = document.createElement('h3');
  h3.textContent = yn + ' vs ' + xn;
  var wrap = document.createElement('div'); wrap.className = 'chart-wrap chart-big';
  var cv = document.createElement('canvas'); wrap.appendChild(cv);
  box.appendChild(h3); box.appendChild(wrap);

  var plugins = [];
  /* On a params chart the top-left corner is either the sweet spot (high score on
     few parameters, green) or the worst place to be (a low parameter count still
     carrying a huge KV cache, red). */
  var sweetCorner = (spec.x === 'params' && !axisLowerIsBetter(spec.y));
  var worstCorner = (spec.x === 'params' && axisLowerIsBetter(spec.y));
  if (sweetCorner) { plugins.push(GLOW_PLUGIN); }
  else if (worstCorner) { plugins.push(WARN_PLUGIN); }
  plugins.push(LABEL_PLUGIN);

  var cc = chartColors();
  var sChart = new Chart(cv, {
    type: 'scatter',
    data: {
      datasets: [{
        data: pts, pointRadius: 6, pointHoverRadius: 9,
        backgroundColor: cc.point, borderColor: cc.pointBorder, borderWidth: 1.5
      }]
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: {
          backgroundColor: cc.tooltipBg, titleColor: cc.tooltipFg, bodyColor: cc.tooltipFg,
          callbacks: {
            label: function (c) {
              var d = c.raw;
              return d.label + ' — ' + yn + ': ' + fmtAxisVal(spec.y, d.y)
                + ' · ' + xn + ': ' + fmtAxisVal(spec.x, d.x);
            }
          }
        }
      },
      scales: { x: axisScale(spec.x, xn), y: axisScale(spec.y, yn) }
    },
    plugins: plugins
  });
  cv.addEventListener('click', function (evt) {
    var pp = sChart.getElementsAtEventForMode(evt, 'nearest', { intersect: true });
    if (pp && pp.length) { var d = pts[pp[0].index]; if (d && d.url) { window.open(d.url, '_blank'); } }
  });
  charts.push(sChart);

  var note = document.createElement('p'); note.className = 'note';
  var touch = !!(window.matchMedia && window.matchMedia('(hover: none)').matches);
  if (spec.preset && spec.note) { note.textContent = spec.note; }
  else {
    note.textContent = (touch
      ? 'Tap a point to open its model card.'
      : 'Hover a point for the model name; click to open its model card.')
      + (sweetCorner ? ' The shaded corner is the sweet spot: a high score on few parameters.' : '')
      + (worstCorner ? ' The red glow marks the corner to avoid: a small model paying for a big KV cache.' : '');
  }
  box.appendChild(note);
  chartPane.appendChild(box);
}

/* ---------- filter application ---------- */

function onFilter() {
  var r = curRange();
  document.getElementById('pf-min-lbl').textContent = r[0];
  document.getElementById('pf-max-lbl').textContent = r[1];
  var ov = onlyVision(), om = onlyMoe(), sa = selActive();
  var rows = document.querySelectorAll('tr[data-params]');
  for (var i = 0; i < rows.length; i++) {
    var p = parseFloat(rows[i].getAttribute('data-params'));
    var mid = rows[i].getAttribute('data-model');
    var ok = (!sa || selectedModels[mid])
      && (!ov || rows[i].getAttribute('data-vision') === '1')
      && (!om || rows[i].getAttribute('data-moe') === '1')
      && !isNaN(p) && p >= r[0] && p <= r[1];
    rows[i].style.display = ok ? '' : 'none';
  }
  var shown = visibleModels().length;
  var tags = [];
  if (ov) { tags.push('vision only'); }
  if (om) { tags.push('MoE only'); }
  var tagStr = tags.length ? ' (' + tags.join(' + ') + ')' : '';
  var selStr = sa ? ' · ' + selCount() + ' selected' : '';
  document.getElementById('pf-count').textContent = 'showing ' + shown + ' of ' + MODELS.length + ' models' + tagStr + selStr;

  var label = 'Params ' + shown + '/' + MODELS.length + ' — filter by parameters';
  var pfActive = (r[0] > parseInt(pfMin.min, 10)) || (r[1] < parseInt(pfMax.max, 10)) || ov || om || sa;
  /* Idle state is "36/36" on every visit — noise on a phone. Only show the
     count once a filter actually narrows the roster. */
  if (pfBadge) { pfBadge.textContent = pfActive ? shown + '/' + MODELS.length : ''; }
  if (mfBadge) { mfBadge.textContent = sa ? selCount() + '/' + MODELS.length : ''; }
  if (pfFab) {
    pfFab.classList.toggle('active', pfActive);
    pfFab.setAttribute('aria-label', label);
    pfFab.title = label;
  }
  if (mfFab) {
    var ml = 'Models' + (sa ? ' ' + selCount() + '/' + MODELS.length : '') + ' — select models to compare';
    mfFab.classList.toggle('active', sa);
    mfFab.setAttribute('aria-label', ml);
    mfFab.title = 'Select models to compare';
  }

  recolorHeatmap();
  filterBenchmarks();
  scheduleCharts();
  saveState();
}

pfMin.addEventListener('input', function () {
  if (parseInt(pfMin.value, 10) > parseInt(pfMax.value, 10)) { pfMin.value = pfMax.value; }
  onFilter();
});
pfMax.addEventListener('input', function () {
  if (parseInt(pfMax.value, 10) < parseInt(pfMin.value, 10)) { pfMax.value = pfMin.value; }
  onFilter();
});
if (pfVision) { pfVision.addEventListener('change', onFilter); }
if (pfMoe) { pfMoe.addEventListener('change', onFilter); }
document.getElementById('pf-reset').addEventListener('click', function () {
  pfMin.value = pfMin.min; pfMax.value = pfMax.max;
  if (pfVision) { pfVision.checked = false; }
  if (pfMoe) { pfMoe.checked = false; }
  selectedModels = {};
  var cbs = mfList ? mfList.querySelectorAll('input[type=checkbox]') : [];
  for (var i = 0; i < cbs.length; i++) { cbs[i].checked = false; }
  onFilter();
});

/* ---------- mobile section menu ---------- */

(function () {
  var btn = document.getElementById('nav-toggle');
  var nav = document.getElementById('head-nav');
  if (!btn || !nav) { return; }
  function setOpen(open) {
    nav.classList.toggle('open', open);
    btn.setAttribute('aria-expanded', open ? 'true' : 'false');
  }
  btn.addEventListener('click', function (e) {
    e.stopPropagation();
    setOpen(!nav.classList.contains('open'));
  });
  nav.addEventListener('click', function (e) {
    if (e.target && e.target.closest && e.target.closest('a')) { setOpen(false); }
  });
  document.addEventListener('click', function (e) {
    if (!nav.contains(e.target) && !btn.contains(e.target)) { setOpen(false); }
  });
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') { setOpen(false); }
  });
  window.addEventListener('resize', function () {
    if (!window.matchMedia('(max-width: 860px)').matches) { setOpen(false); }
  });
})();

/* ---------- floating panels ---------- */

/* On a phone the two pills sit over the bottom of the tables and charts.
   Tuck them away while scrolling down, bring them back on an upward scroll
   (or as soon as one is tapped). */
(function () {
  var fabs = document.querySelector('.fabs');
  if (!fabs) { return; }
  var mq = window.matchMedia('(max-width: 700px)');
  var lastY = window.scrollY, queued = false;
  function step() {
    queued = false;
    var y = window.scrollY;
    if (!mq.matches) { fabs.classList.remove('away'); lastY = y; return; }
    var dy = y - lastY;
    if (Math.abs(dy) < 6) { return; }
    var open = !!document.querySelector('.panel:not([hidden])');
    fabs.classList.toggle('away', dy > 0 && y > 220 && !open);
    lastY = y;
  }
  window.addEventListener('scroll', function () {
    if (!queued) { queued = true; window.requestAnimationFrame(step); }
  }, { passive: true });
  document.addEventListener('click', function (e) {
    if (fabs.contains(e.target)) { fabs.classList.remove('away'); }
  }, true);
})();

function closeOtherPanel(panel, fab) {
  if (panel) { panel.hidden = true; }
  if (fab) { fab.setAttribute('aria-expanded', 'false'); }
}
function setPfOpen(open) {
  if (!pfPanel) { return; }
  pfPanel.hidden = !open;
  if (pfFab) { pfFab.setAttribute('aria-expanded', open ? 'true' : 'false'); }
  if (open) { closeOtherPanel(mfPanel, mfFab); if (pfMin.focus) { pfMin.focus(); } }
}
if (pfFab) { pfFab.addEventListener('click', function (e) { e.stopPropagation(); setPfOpen(pfPanel.hidden); }); }
if (pfClose) { pfClose.addEventListener('click', function () { setPfOpen(false); }); }
document.addEventListener('click', function (e) {
  if (!pfPanel || pfPanel.hidden) { return; }
  if (pfPanel.contains(e.target) || (pfFab && pfFab.contains(e.target))) { return; }
  setPfOpen(false);
});
document.addEventListener('keydown', function (e) {
  if (e.key === 'Escape' && pfPanel && !pfPanel.hidden) { setPfOpen(false); }
});

/* ---------- model selection ---------- */

function setMfOpen(open) {
  if (!mfPanel) { return; }
  mfPanel.hidden = !open;
  if (mfFab) { mfFab.setAttribute('aria-expanded', open ? 'true' : 'false'); }
  if (open) { closeOtherPanel(pfPanel, pfFab); }
}
(function () {
  if (!mfList) { return; }
  var byName = MODELS.slice().sort(function (a, b) {
    var x = a.name.toLowerCase(), y = b.name.toLowerCase();
    return x < y ? -1 : (x > y ? 1 : 0);
  });
  byName.forEach(function (m) {
    var lab = document.createElement('label'); lab.className = 'mf-item';
    var cb = document.createElement('input'); cb.type = 'checkbox'; cb.setAttribute('data-mid', m.id);
    cb.checked = !!selectedModels[m.id];
    cb.addEventListener('change', function () {
      if (cb.checked) { selectedModels[m.id] = true; } else { delete selectedModels[m.id]; }
      onFilter();
    });
    var nm = document.createElement('span'); nm.textContent = m.name;
    lab.appendChild(cb); lab.appendChild(nm);
    mfList.appendChild(lab);
  });
  function setAll(on) {
    var cbs = mfList.querySelectorAll('input[type=checkbox]');
    selectedModels = {};
    for (var i = 0; i < cbs.length; i++) {
      cbs[i].checked = on;
      if (on) { selectedModels[cbs[i].getAttribute('data-mid')] = true; }
    }
    onFilter();
  }
  var bAll = document.getElementById('mf-all'), bClear = document.getElementById('mf-clear');
  if (bAll) { bAll.addEventListener('click', function () { setAll(true); }); }
  if (bClear) { bClear.addEventListener('click', function () { setAll(false); }); }
  if (mfFab) { mfFab.addEventListener('click', function (e) { e.stopPropagation(); setMfOpen(mfPanel.hidden); }); }
  if (mfClose) { mfClose.addEventListener('click', function () { setMfOpen(false); }); }
  document.addEventListener('click', function (e) {
    if (!mfPanel || mfPanel.hidden) { return; }
    if (mfPanel.contains(e.target) || (mfFab && mfFab.contains(e.target))) { return; }
    setMfOpen(false);
  });
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape' && mfPanel && !mfPanel.hidden) { setMfOpen(false); }
  });
})();

/* ---------- heatmap: column visibility (core / all / search) ---------- */

var heatTable = document.getElementById('heat-table');
var bfInput = document.getElementById('bf-input');
var heatView = 'core';
var MIN_BENCH_LIVE = 2;

function setHeatView(v) {
  heatView = v;
  var btns = document.querySelectorAll('.seg button[data-hv]');
  for (var i = 0; i < btns.length; i++) {
    btns[i].setAttribute('aria-pressed', btns[i].getAttribute('data-hv') === v ? 'true' : 'false');
  }
  filterBenchmarks();
  saveState();
}

function filterBenchmarks() {
  if (!heatTable) { return; }
  var q = (bfInput && bfInput.value ? bfInput.value : '').trim().toLowerCase();
  var head = heatTable.tHead.rows[0].cells;
  var rows = heatTable.tBodies[0].rows;

  /* coverage per column across the rows that are currently visible */
  var cov = {};
  for (var r = 0; r < rows.length; r++) {
    if (rows[r].style.display === 'none') { continue; }
    var sc = SCORES[rows[r].getAttribute('data-model')] || {};
    for (var k = 0; k < BENCHES.length; k++) {
      var bn = BENCHES[k];
      if (typeof sc[bn] === 'number') { cov[bn] = (cov[bn] || 0) + 1; }
    }
  }

  var shown = 0, hiddenCov = 0, hiddenSearch = 0, hiddenCore = 0;
  var rangeActive = (parseInt(pfMin.value, 10) > parseInt(pfMin.min, 10))
    || (parseInt(pfMax.value, 10) < parseInt(pfMax.max, 10));
  var filtering = selActive() || onlyVision() || onlyMoe() || rangeActive || (q !== '');
  /* Core view hides thin columns; an explicit search always reaches every one. */
  var coreOnly = (heatView === 'core') && (q === '');

  for (var j = 1; j < head.length; j++) {
    var th = head[j];
    if (th.hasAttribute('data-nobench')) { th.style.display = ''; continue; }
    var name = th.getAttribute('data-bench');
    if (name == null) { name = BENCHES[j - 1]; }
    var match = (q === '') || (name.toLowerCase().indexOf(q) !== -1);
    var n = cov[name] || 0;
    var isCore = (BENCH_COV[name] || 0) >= CORE_MIN
      || CORE_ALWAYS.indexOf(name) !== -1;
    var vis = match && (!coreOnly || isCore) && (!filtering || n >= MIN_BENCH_LIVE);
    if (!match) { hiddenSearch++; }
    else if (coreOnly && !isCore) { hiddenCore++; }
    else if (!vis) { hiddenCov++; }
    if (vis) { shown++; }
    th.style.display = vis ? '' : 'none';
    for (var i = 0; i < rows.length; i++) {
      var td = rows[i].cells[j];
      if (td) { td.style.display = vis ? '' : 'none'; }
    }
  }

  var cnt = document.getElementById('bf-count');
  if (cnt) {
    var total = 0;
    for (var t2 = 1; t2 < head.length; t2++) {
      if (!head[t2].hasAttribute('data-nobench')) { total++; }
    }
    if (shown === 0 && filtering) {
      cnt.textContent = 'no benchmark is reported by two or more of the filtered models';
    } else {
      var bits = ['showing ' + shown + ' of ' + total + ' benchmarks'];
      if (hiddenCore) { bits.push(hiddenCore + ' hidden by the core view'); }
      if (hiddenCov) { bits.push(hiddenCov + ' with fewer than ' + MIN_BENCH_LIVE + ' visible models'); }
      if (hiddenSearch) { bits.push(hiddenSearch + ' not matching search'); }
      cnt.textContent = bits.join(' · ');
    }
  }
  updateHeatScroll();
}

if (bfInput) {
  bfInput.addEventListener('input', function () { filterBenchmarks(); saveState(); });
  document.getElementById('bf-clear').addEventListener('click', function () {
    bfInput.value = ''; filterBenchmarks(); saveState(); bfInput.focus();
  });
}
(function () {
  var btns = document.querySelectorAll('.seg button[data-hv]');
  for (var i = 0; i < btns.length; i++) {
    btns[i].addEventListener('click', function () { setHeatView(this.getAttribute('data-hv')); });
  }
})();

/* ---------- horizontal scroll arrows for the wide heatmap ---------- */

var heatWrap = document.querySelector('.heat');
var heatLeft = document.getElementById('heat-left');
var heatRight = document.getElementById('heat-right');
function updateHeatScroll() {
  if (!heatWrap) { return; }
  var max = heatWrap.scrollWidth - heatWrap.clientWidth;
  if (heatLeft) { heatLeft.hidden = (max <= 1) || (heatWrap.scrollLeft <= 1); }
  if (heatRight) { heatRight.hidden = (max <= 1) || (heatWrap.scrollLeft >= max - 1); }
}
function heatStep() { return Math.max(200, Math.round(heatWrap.clientWidth * 0.8)); }
if (heatWrap) {
  heatWrap.addEventListener('scroll', updateHeatScroll);
  window.addEventListener('resize', updateHeatScroll);
  if (heatLeft) { heatLeft.addEventListener('click', function () { heatWrap.scrollBy({ left: -heatStep(), behavior: 'smooth' }); }); }
  if (heatRight) { heatRight.addEventListener('click', function () { heatWrap.scrollBy({ left: heatStep(), behavior: 'smooth' }); }); }
}

/* The legend's five swatches are rendered in light colours by the builder;
   repaint them from the active palette (and on every theme change). */
function paintHeatLegend() {
  var p = heatPalette();
  var sws = document.querySelectorAll('.heat-legend .sw[data-t]');
  for (var i = 0; i < sws.length; i++) {
    sws[i].style.background = heatStyle(parseFloat(sws[i].getAttribute('data-t')))[0];
  }
  var best = document.querySelector('.heat-legend .sw[data-best]');
  if (best) {
    best.style.background = p.bestBg;
    best.style.boxShadow = 'inset 0 0 0 1px ' + p.bestLine;
  }
}

function recolorHeatmap() {
  paintHeatLegend();
  var table = document.getElementById('heat-table');
  if (!table) { return; }
  var palette = heatPalette();
  var head = table.tHead.rows[0].cells;
  var cols = [];
  for (var j = 1; j < head.length; j++) {
    if (head[j].hasAttribute('data-nobench')) { continue; }
    var b = head[j].getAttribute('data-bench');
    if (b == null) { b = BENCHES[j - 1]; }
    cols.push([b, j]);
  }
  var rows = table.tBodies[0].rows;
  var mm = {};
  for (var r = 0; r < rows.length; r++) {
    if (rows[r].style.display === 'none') { continue; }
    var sc = SCORES[rows[r].getAttribute('data-model')] || {};
    for (var c = 0; c < cols.length; c++) {
      var v = sc[cols[c][0]];
      if (typeof v !== 'number') { continue; }
      var e = mm[cols[c][0]];
      if (!e) { mm[cols[c][0]] = [v, v, 1]; }
      else { if (v < e[0]) { e[0] = v; } if (v > e[1]) { e[1] = v; } e[2]++; }
    }
  }
  for (var r2 = 0; r2 < rows.length; r2++) {
    if (rows[r2].style.display === 'none') { continue; }
    var sc2 = SCORES[rows[r2].getAttribute('data-model')] || {};
    for (var c2 = 0; c2 < cols.length; c2++) {
      var b2 = cols[c2][0];
      var td = rows[r2].cells[cols[c2][1]];
      var span = td ? td.querySelector('span.cell') : null;
      if (!span || span.classList.contains('absent')) { continue; }
      var v2 = sc2[b2];
      if (typeof v2 !== 'number') { continue; }
      var e2 = mm[b2]; if (!e2) { continue; }
      var t = (e2[1] === e2[0]) ? 0.5 : (v2 - e2[0]) / (e2[1] - e2[0]);
      var isBest = e2[2] >= 2 && v2 === e2[1];
      if (isBest) {
        span.classList.add('best');
        span.style.background = palette.bestBg; span.style.color = palette.bestFg;
        span.setAttribute('title', 'Best on ' + b2);
      } else {
        span.classList.remove('best');
        span.removeAttribute('title');
        var sty = heatStyle(t);
        span.style.background = sty[0]; span.style.color = sty[1];
      }
    }
  }
}

/* ---------- sorting ---------- */

function makeSortable(table) {
  var ths = table.tHead.rows[0].cells;
  for (var h = 0; h < ths.length; h++) {
    (function (th, ci) {
      var type = th.getAttribute('data-type') || 'text';
      th.classList.add('sortable');
      th.setAttribute('aria-sort', 'none');
      var baseTitle = th.getAttribute('title') || '';
      th.title = baseTitle ? (baseTitle + ' — click to sort') : 'Click to sort';
      var dir = null;
      var arrow = document.createElement('span'); arrow.className = 'sort-arrow'; th.appendChild(arrow);
      th.addEventListener('click', function () {
        if (dir === null) { dir = (type === 'text') ? 'asc' : 'desc'; }
        else { dir = (dir === 'asc') ? 'desc' : 'asc'; }
        var tbody = table.tBodies[0];
        var rows = Array.prototype.slice.call(tbody.rows);
        var ABSENT = { '': '1', '\u00b7': '1', '\u2014': '1', '-': '1' };
        function key(row) {
          var td = row.cells[ci]; if (!td) { return { v: 0, abs: true }; }
          if (type === 'num') {
            var raw = (td.getAttribute('data-sort') != null) ? td.getAttribute('data-sort') : td.textContent.trim();
            if (ABSENT[raw]) { return { v: 0, abs: true }; }
            return { v: (parseFloat(raw) || 0), abs: false };
          }
          if (type === 'date') {
            var raw2 = td.getAttribute('data-sort') || '';
            if (ABSENT[raw2]) { return { v: '', abs: true }; }
            return { v: raw2, abs: false };
          }
          var rawT = td.getAttribute('data-sort');
          if (rawT != null && rawT !== '') { return { v: rawT.toLowerCase(), abs: false }; }
          return { v: td.textContent.trim().toLowerCase(), abs: false };
        }
        rows.sort(function (a, b) {
          var ka = key(a), kb = key(b);
          if (ka.abs && kb.abs) { return 0; }
          if (ka.abs) { return 1; }
          if (kb.abs) { return -1; }
          var r;
          if (type === 'num') { r = ka.v - kb.v; }
          else { r = (ka.v < kb.v) ? -1 : (ka.v > kb.v ? 1 : 0); }
          return (dir === 'asc') ? r : -r;
        });
        for (var i = 0; i < rows.length; i++) { tbody.appendChild(rows[i]); }
        for (var o = 0; o < ths.length; o++) {
          var s = ths[o].querySelector('.sort-arrow');
          if (s) { s.textContent = ''; }
          ths[o].setAttribute('aria-sort', 'none');
        }
        arrow.textContent = (dir === 'asc') ? ' \u25b2' : ' \u25bc';
        th.setAttribute('aria-sort', (dir === 'asc') ? 'ascending' : 'descending');
      });
    })(ths[h], h);
  }
}
var tbls = document.querySelectorAll('table.sortable');
for (var t = 0; t < tbls.length; t++) { makeSortable(tbls[t]); }

/* ---------- chart tabs + custom axis pickers ---------- */

function setChartMode(mode) {
  chartMode = mode;
  if (chartTabs) {
    var btns = chartTabs.querySelectorAll('button[data-chart]');
    for (var i = 0; i < btns.length; i++) {
      var on = (btns[i].getAttribute('data-chart') === mode);
      btns[i].classList.toggle('active', on);
      btns[i].setAttribute('aria-selected', on ? 'true' : 'false');
    }
  }
  if (chartCustom) { chartCustom.hidden = !isCustomMode(); }
  buildCharts();
  saveState();
}
if (chartTabs) {
  chartTabs.addEventListener('click', function (e) {
    var b = (e.target && e.target.closest) ? e.target.closest('button[data-chart]') : null;
    if (b) { setChartMode(b.getAttribute('data-chart')); }
  });
}
function onAxisChange() { if (isCustomMode()) { buildCharts(); saveState(); } }
if (chartX) { chartX.addEventListener('change', onAxisChange); }
if (chartY) { chartY.addEventListener('change', onAxisChange); }

var cmpAll = document.getElementById('cmp-all');
if (cmpAll) {
  cmpAll.addEventListener('click', function () {
    showAllCharts = !showAllCharts;
    lastSig = null;
    buildCharts();
  });
}

/* ---------- boot ---------- */

function syncModelChecks() {
  if (!mfList) { return; }
  var cbs = mfList.querySelectorAll('input[type=checkbox]');
  for (var i = 0; i < cbs.length; i++) {
    cbs[i].checked = !!selectedModels[cbs[i].getAttribute('data-mid')];
  }
}

function init() {
  restoreState();
  syncModelChecks();
  syncThemeChrome();
  setHeatView(heatView);
  onFilter();
  updateHeatScroll();
  setChartMode(chartMode);
}
if (document.readyState !== 'loading') { init(); }
else { document.addEventListener('DOMContentLoaded', init); }
