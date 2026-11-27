#!/usr/bin/env python3
"""Tiny League — static multi-page build.

Writes into out/ — the deployable artifact. Run:

    .venv/bin/python scripts/build_v2.py

Pages: home, models, benchmarks index, one page per benchmark, compare, about.
No model detail pages (deliberately out of scope for this pass).
"""
import datetime
import json
import os
import re
import sys
from xml.sax.saxutils import escape as xml_escape
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import tl_common as gh  # shared helpers, labels, heat ramp, OG card

OUT = os.path.join(ROOT, "out")
SITE = "https://tinyleague.org/"
REPO = "https://github.com/nunodonato/tinyleague"
DISCORD = "https://discord.gg/DQ6E6eJZVJ"
MIN_MODELS = 2
esc = gh.esc

# --------------------------------------------------------------------------
# data

models_doc = gh.load("models.json")
MODELS = models_doc["models"] if isinstance(models_doc, dict) else models_doc
MODELS = sorted(MODELS, key=lambda m: str(m.get("official_release_date") or ""), reverse=True)
BY_ID = {m["model_id"]: m for m in MODELS}

scores_doc = gh.load("scores.json")
SCORES = {}
for rec in scores_doc["models"]:
    d = SCORES.setdefault(rec["model_id"], {})
    for sc in rec["scores"]:
        if isinstance(sc.get("score"), (int, float)):
            # highest value wins if a card reports several (reasoning levels)
            prev = d.get(sc["benchmark"])
            if prev is None or sc["score"] > prev["score"]:
                d[sc["benchmark"]] = sc

COV = Counter(b for d in SCORES.values() for b in d)
MODEL_NUMERIC = {mid: {b: sc["score"] for b, sc in d.items()} for mid, d in SCORES.items()}
try:
    UPDATED_H = gh.load("changelog.json")[0]["date"]
except (OSError, ValueError, IndexError, KeyError, TypeError):
    UPDATED_H = ""
BENCHES = sorted(b for b, n in COV.items() if n >= MIN_MODELS)

# --------------------------------------------------------------------------
# domains: ordered rules, first match wins

RULES = [
    ("Coding", ["swe-", "swe ", "deepswe", "programbench", "nl2repo", "frontiercode",
                "scicode", "codeforces", "livecodebench", "artifactsbench", "sweb",
                "swe atlas", "birdbench", "vision2web"]),
    ("Agentic", ["terminal-bench", "bfcl", "tau", "τ", "tool", "mcp", "osworld",
                 "androidworld", "webarena", "automationbench", "claw", "coworkbench",
                 "enterpriseops", "jobbench", "pagents", "vitabench", "agents' last",
                 "browsecomp", "deepresearch", "widesearch", "deepsearch", "gaia",
                 "graphwalks", "gdpval", "apex", "lifebench", "recreationbench",
                 "skillsbench", "pinchbench", "pagentbench", "profbench", "cve"]),
    ("Math", ["aime", "hmmt", "beyondaime", "imo", "math500", "mgsm", "gaokao", "critpt"]),
    ("Multimodal", ["mmmu", "mathvision", "charxiv", "ocrbench", "omnidoc", "screenspot",
                    "realworldqa", "babyvision", "erqa", "gdp.pdf", "zerobench",
                    "medxpertqa"]),
    ("Long context", ["ruler", "mrcr", "longbench", "aa-lcr"]),
    ("Instruction", ["ifeval", "ifbench", "multi-if", "arena-hard"]),
    ("Knowledge", ["gpqa", "mmlu", "hle", "arc-agi", "bigbench", "supergpqa", "c-eval",
                   "cmmlu", "mmmlu", "aa-omniscience", "aa-briefcase", "multichallenge",
                   "office-qa", "officeqa"]),
]


def domain_of(bench):
    n = bench.lower()
    for dom, keys in RULES:
        if any(k in n for k in keys):
            return dom
    return "Other"


DOMAIN_ORDER = ["Coding", "Agentic", "Math", "Knowledge", "Multimodal",
                "Instruction", "Long context", "Other"]
DOMAIN_OF = {b: domain_of(b) for b in BENCHES}
BY_DOMAIN = defaultdict(list)
for b in BENCHES:
    BY_DOMAIN[DOMAIN_OF[b]].append(b)


def family_of(bench):
    return gh.BENCH_FAMILY.get(bench, bench)


SIBLINGS = defaultdict(list)
for b in BENCHES:
    SIBLINGS[family_of(b)].append(b)


def slug(text):
    # keep Greek benchmark names readable in URLs (τ²-bench -> tau2-bench)
    t = (text.replace("τ", "tau").replace("π", "pi")
             .replace("²", "2").replace("³", "3"))
    s = re.sub(r"[^a-z0-9]+", "-", t.lower()).strip("-")
    return s or "bench"


BENCH_SLUG = {}
_used = set()
for b in BENCHES:
    s = slug(b)
    while s in _used:
        s += "-2"
    _used.add(s)
    BENCH_SLUG[b] = s

# --------------------------------------------------------------------------
# formatting


def num(v):
    if isinstance(v, bool) or v is None:
        return ""
    if isinstance(v, float):
        if abs(v) >= 1000:
            return "{:,}".format(int(round(v)))
        if v == int(v):
            return str(int(v))
        return ("%.2f" % v).rstrip("0").rstrip(".")
    return str(v)


def params(m):
    return "%sB" % gh.fmt(m.get("param_count_b"))


def kv(m):
    v = (m.get("kv_cache") or {}).get("gib_at_ref_ctx")
    return "" if not isinstance(v, (int, float)) else ("%.2f" % v).rstrip("0").rstrip(".") + " GiB"


def speed(m):
    v = (m.get("perf") or {}).get("decode_tok_s_fresh")
    return "" if not isinstance(v, (int, float)) else "%.0f" % v


def active(m):
    txt, _, _ = gh.active_label(m)
    return txt


def ctx(m):
    txt, _ = gh.ctx_label(m)
    return txt


def lic(m):
    return gh.license_label(m)


def mtype(m):
    return ((m.get("architecture") or {}).get("type") or "").lower()


def model_name(m):
    return m.get("display_name") or m["model_id"].split("/")[-1]


def badge_html(m):
    """V / MoE badges, matching the Models table."""
    out = []
    if m.get("supports_vision"):
        out.append('<span class="pill v">V</span>')
    if mtype(m) == "moe":
        out.append('<span class="pill moe">MoE</span>')
    return (" " + " ".join(out)) if out else ""


def best_of(bench):
    rows = [(SCORES[mid][bench]["score"], mid) for mid in SCORES if bench in SCORES[mid]]
    if not rows:
        return None, None
    v, mid = max(rows)
    return v, mid


# --------------------------------------------------------------------------
# chrome

TOKENS = gh.web_asset("tokens.css")
V2CSS = gh.web_asset("v2.css")

# Same ramp as v1: pre-rendered into 21 classes so Python and JS agree on colour.
RAMP_CSS = "".join(
    ".h%d{background:%s;color:%s}" % (i, gh.heat_style(i / 20.0)[0], gh.heat_style(i / 20.0)[1])
    for i in range(21)
)


def heat_class(v, lo, hi):
    if hi <= lo:
        return "h10"
    t = (v - lo) / (hi - lo)
    t = 0.0 if t < 0 else (1.0 if t > 1 else t)
    return "h%d" % int(round(t * 20))


def filter_bar():
    """Params / MoE / vision filter, shared by every page that lists models."""
    return """
<div class="filters" id="filters">
  <span class="flabel">Filter</span>
  <label>min <input id="fmin" type="number" min="0" step="0.5" placeholder="1.5" aria-label="Minimum parameters (B)">B</label>
  <label>max <input id="fmax" type="number" min="0" step="0.5" placeholder="285" aria-label="Maximum parameters (B)">B</label>
  <label><input type="checkbox" id="fmoe"> MoE only</label>
  <label><input type="checkbox" id="fvis"> Vision only</label>
  <button type="button" class="icon-btn" id="freset">Reset</button>
  <span class="count" id="fcount"></span>
</div>"""


NAV_JS = """
(function(){
 var nav=document.getElementById('nav'),mb=document.getElementById('menu');
 if(!nav)return;
 if(mb){mb.addEventListener('click',function(){
   var o=nav.classList.toggle('open');
   mb.setAttribute('aria-expanded',o?'true':'false');});}
 var groups=[].slice.call(document.querySelectorAll('.navgrp'));
 function close(g){var b=g.querySelector('.navbtn');
   g.classList.remove('open');b.setAttribute('aria-expanded','false');}
 function open(g){groups.forEach(function(o){if(o!==g)close(o);});
   g.classList.add('open');g.querySelector('.navbtn').setAttribute('aria-expanded','true');}
 var hover=window.matchMedia&&window.matchMedia('(hover:hover)').matches;
 groups.forEach(function(g){
   var b=g.querySelector('.navbtn'),t=null;
   b.addEventListener('click',function(e){e.stopPropagation();
     if(g.classList.contains('open'))close(g);else open(g);});
   b.addEventListener('keydown',function(e){
     if(e.key==='ArrowDown'){e.preventDefault();open(g);
       var a=g.querySelector('.navmenu a');if(a)a.focus();}});
   if(hover){
     g.addEventListener('pointerenter',function(){clearTimeout(t);open(g);});
     g.addEventListener('pointerleave',function(){clearTimeout(t);
       t=setTimeout(function(){close(g);},170);});
   }
   g.addEventListener('keydown',function(e){if(e.key==='Escape'){close(g);b.focus();}});
 });
 document.addEventListener('click',function(){groups.forEach(close);});
})();
"""

FILTER_JS = """
(function(){
 var el={min:document.getElementById('fmin'),max:document.getElementById('fmax'),
   moe:document.getElementById('fmoe'),vis:document.getElementById('fvis'),
   reset:document.getElementById('freset'),count:document.getElementById('fcount')};
 if(!el.min)return;
 var st={min:'',max:'',moe:false,vis:false};
 try{var s=JSON.parse(localStorage.getItem('tl-filters')||'{}');
     Object.assign(st,s);}catch(e){}
 el.min.value=st.min;el.max.value=st.max;el.moe.checked=!!st.moe;el.vis.checked=!!st.vis;
 function apply(){
   var mn=parseFloat(el.min.value),mx=parseFloat(el.max.value),n=0;
   var rows=document.querySelectorAll('[data-params]');
   for(var i=0;i<rows.length;i++){
     var r=rows[i],p=parseFloat(r.getAttribute('data-params')),ok=true;
     if(!isNaN(mn)&&p<mn)ok=false;
     if(!isNaN(mx)&&p>mx)ok=false;
     if(el.moe.checked&&r.getAttribute('data-moe')!=='1')ok=false;
     if(el.vis.checked&&r.getAttribute('data-vision')!=='1')ok=false;
     r.dataset.f=ok?'1':'0';
     if(ok)n++;
   }
   if(el.count){el.count.style.display=rows.length?'':'none';
     if(rows.length)el.count.textContent=n+' of '+rows.length+' models';}
   window.TL_FILTER={mn:mn,mx:mx,moe:el.moe.checked,vis:el.vis.checked};
   try{localStorage.setItem('tl-filters',JSON.stringify({min:el.min.value,
     max:el.max.value,moe:el.moe.checked,vis:el.vis.checked}));}catch(e){}
   if(window.TL_APPLY)window.TL_APPLY();
   else for(var j=0;j<rows.length;j++){rows[j].style.display=rows[j].dataset.f==='1'?'':'none';}
   document.dispatchEvent(new CustomEvent('tl:filters'));
 }
 ['input','change'].forEach(function(ev){
   [el.min,el.max,el.moe,el.vis].forEach(function(i){i.addEventListener(ev,apply);});});
 el.reset.addEventListener('click',function(){el.min.value='';el.max.value='';
   el.moe.checked=false;el.vis.checked=false;apply();});
 apply();
})();
"""


THEME_JS = """
(function(){try{var m=localStorage.getItem('tl-theme')||'auto';
var dark=m==='dark'||(m==='auto'&&matchMedia('(prefers-color-scheme: dark)').matches);
var r=document.documentElement;r.dataset.theme=dark?'dark':'light';r.dataset.themeMode=m;}catch(e){}})();
"""

TOGGLE_JS = """
(function(){var b=document.getElementById('theme');if(!b)return;
function paint(){var m=document.documentElement.dataset.themeMode||'auto';
b.querySelector('.label').textContent=m[0].toUpperCase()+m.slice(1);}
b.addEventListener('click',function(){
var order=['auto','light','dark'],m=document.documentElement.dataset.themeMode||'auto';
var next=order[(order.indexOf(m)+1)%3];
localStorage.setItem('tl-theme',next);
var dark=next==='dark'||(next==='auto'&&matchMedia('(prefers-color-scheme: dark)').matches);
document.documentElement.dataset.theme=dark?'dark':'light';
document.documentElement.dataset.themeMode=next;paint();});
paint();})();
"""

# A section is ("key", "Label", "page.html") — or a group, where the href is a list
# of sub-views [("key", "Label", "page.html"), ...]. Groups render as a dropdown, so
# adding a view (e.g. a radar chart) is one entry in the list.
NAV = [("home", "Home", "index.html"), ("models", "Models", "models.html"),
       ("scores", "Scores", [("table", "Matrix", "matrix.html"),
                             ("scatter", "Scatter", "scatter.html")]),
       ("bench", "Benchmarks", "benchmarks.html"),
       ("compare", "Compare", "compare.html"), ("about", "About", "about.html")]

CARET = ('<svg class="caret" width="10" height="10" viewBox="0 0 10 10" aria-hidden="true">'
         '<path d="M2 3.5 5 6.5 8 3.5" fill="none" stroke="currentColor" stroke-width="1.6" '
         'stroke-linecap="round" stroke-linejoin="round"/></svg>')


def nav_html(nav, up):
    out = []
    for item in NAV:
        key, label, href = item
        if isinstance(href, list):
            cur = any(k == nav for k, _l, _h in href)
            subs = "".join(
                '<a role="menuitem" href="%s%s"%s>%s</a>'
                % (up, h, ' aria-current="page"' if k == nav else "", esc(l))
                for k, l, h in href
            )
            out.append(
                '<div class="navgrp">'
                '<button class="navbtn%s" type="button" aria-expanded="false" '
                'aria-haspopup="true" aria-controls="navmenu-%s">%s%s</button>'
                '<div class="navmenu" id="navmenu-%s" role="menu">%s</div>'
                '</div>' % (" on" if cur else "", key, esc(label), CARET, key, subs)
            )
        else:
            out.append('<a href="%s%s"%s>%s</a>' % (
                up, href, ' aria-current="page"' if key == nav else "", esc(label)))
    return "".join(out)

GH_MARK = ('<svg width="15" height="15" viewBox="0 0 24 24" aria-hidden="true">'
           '<path fill="currentColor" d="M12 .297c-6.63 0-12 5.373-12 12 0 5.303 3.438 9.8 '
           '8.205 11.385.6.113.82-.258.82-.577 0-.285-.01-1.04-.015-2.04-3.338.724-4.042-1.61'
           '-4.042-1.61C4.422 18.07 3.633 17.7 3.633 17.7c-1.087-.744.084-.729.084-.729 1.205.084 '
           '1.838 1.236 1.838 1.236 1.07 1.835 2.809 1.305 3.495.998.108-.776.417-1.305.76-1.605'
           '-2.665-.3-5.466-1.332-5.466-5.93 0-1.31.465-2.38 1.235-3.22-.135-.303-.54-1.523.105-3.176 '
           '0 0 1.005-.322 3.3 1.23.96-.267 1.98-.399 3-.405 1.02.006 2.04.138 3 .405 '
           '2.28-1.552 3.285-1.23 3.285-1.23.645 1.653.24 2.873.12 3.176.765.84 1.23 1.91 1.23 3.22 '
           '0 4.61-2.805 5.625-5.475 5.92.42.36.81 1.096.81 2.22 0 1.606-.015 2.896-.015 3.286 '
           '0 .315.21.69.825.57C20.565 22.092 24 17.592 24 12.297c0-6.627-5.373-12-12-12"/>'
           '</svg>')

DISCORD_MARK = ('<svg width="15" height="15" viewBox="0 0 24 24" aria-hidden="true">'
                '<path fill="currentColor" d="%s"/></svg>' % gh.DISCORD_LOGO)


def views_html(cur):
    """Segmented switch between the score views (tabs on the pages themselves)."""
    items = [("table", "Matrix", "matrix.html"), ("scatter", "Scatter", "scatter.html")]
    return '<nav class="views" aria-label="Score view">' + "".join(
        '<a href="%s"%s>%s</a>' % (h, ' aria-current="page"' if k == cur else "", l)
        for k, l, h in items) + "</nav>"


def layout(title, body, nav, depth=0, script="", desc="", path="index.html"):
    up = "../" * depth
    canon = SITE if path == "index.html" else SITE + path
    links = nav_html(nav, up)
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)}</title>
<meta name="description" content="{esc(desc or 'Benchmark scores for recent small open-weight models.')}">
<link rel="canonical" href="{canon}">
<link rel="alternate" type="application/rss+xml" title="Tiny League changelog" href="{SITE}feed.xml">
<meta property="og:type" content="website">
<meta property="og:site_name" content="Tiny League">
<meta property="og:title" content="{esc(title)}">
<meta property="og:description" content="{esc(desc or 'Benchmark scores for recent small open-weight models.')}">
<meta property="og:url" content="{canon}">
<meta property="og:image" content="{SITE}og.png">
<meta name="twitter:card" content="summary_large_image">
<script>{THEME_JS}</script>
<style>
{TOKENS}
{V2CSS}
{RAMP_CSS}
</style>
</head>
<body>
<header class="topbar"><div class="inner">
  <a class="brand" href="{up}index.html"><span aria-hidden="true">🏆</span><span>Tiny League</span></a>
  <nav class="nav" id="nav" aria-label="Sections">{links}</nav>
  <div class="actions">
    <a class="icon-btn" href="{REPO}" target="_blank" rel="noopener noreferrer" title="Source on GitHub">{GH_MARK}<span class="label">GitHub</span></a>
    <a class="icon-btn discord" href="{DISCORD}" target="_blank" rel="noopener noreferrer" title="Join the Discord">{DISCORD_MARK}<span class="label">Discord</span></a>
    <a class="icon-btn square rss" href="{SITE}feed.xml" title="Subscribe to the changelog (RSS)" aria-label="Subscribe to the changelog (RSS)">
      <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" aria-hidden="true"><path d="M4 11a9 9 0 0 1 9 9"></path><path d="M4 4a16 16 0 0 1 16 16"></path><circle cx="5" cy="19" r="1.6" fill="currentColor" stroke="none"></circle></svg>
    </a>
    <button class="icon-btn" id="theme" type="button" title="Theme: auto / light / dark">
      <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><circle cx="12" cy="12" r="4"></circle><path d="M12 2v2M12 20v2M2 12h2M20 12h2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M19.1 4.9l-1.4 1.4M6.3 17.7l-1.4 1.4"></path></svg>
      <span class="label">Auto</span>
    </button>
    <button class="icon-btn menu-btn" id="menu" type="button" aria-expanded="false" aria-controls="nav" aria-label="Sections">
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="M4 7h16M4 12h16M4 17h16"></path></svg>
    </button>
  </div>
</div></header>
<main class="wrap">
{body}
</main>
<footer><div class="inner">
  <span>Created and maintained by <a href="https://www.nunodonato.com" target="_blank" rel="noopener">www.nunodonato.com</a></span>
  <span>{len(MODELS)} models · {len(BENCHES)} benchmarks · <a href="{REPO}" target="_blank" rel="noopener">source</a> · <a href="{DISCORD}" target="_blank" rel="noopener">Discord</a> · <a href="{SITE}feed.xml">RSS</a></span>
</div></footer>
<script>{TOGGLE_JS}
{NAV_JS}
{FILTER_JS}
{script}
</script>
</body>
</html>
"""


def write(path, text):
    full = os.path.join(OUT, path)
    os.makedirs(os.path.dirname(full) or OUT, exist_ok=True)
    with open(full, "w", encoding="utf-8") as f:
        f.write(text)
    return len(text)


# --------------------------------------------------------------------------
# pages

def page_home():
    newest = MODELS[:5]
    total_scores = sum(len(d) for d in SCORES.values())
    newest_rows = "".join(
        "<tr>"
        f'<td class="name"><a href="{esc(m.get("hf_url") or "#")}" target="_blank" rel="noopener">{esc(model_name(m))}</a></td>'
        f"<td class=\"num\">{params(m)}</td>"
        f"<td class=\"num\">{active(m)}</td>"
        f"<td class=\"num\">{esc(ctx(m))}</td>"
        f"<td class=\"num\">{esc(kv(m))}</td>"
        f"<td class=\"num\">{esc(m.get('official_release_date') or '')}</td>"
        "</tr>"
        for m in newest
    )
    changes = "".join(
        f'<li><time>{esc(c.get("date"))}</time><span>{esc(c.get("text"))}</span></li>'
        for c in gh.load("changelog.json")[:6]
    )
    body = f"""
<h1>The league table for small open models.</h1>
<p class="lede">Benchmark scores for every recent small open-weight model worth comparing —
read them side by side, see where each one is cheapest to run, and filter down to the ones
that fit your hardware.</p>

<div class="stats">
  <div class="stat"><span class="v">{len(MODELS)}</span><span class="k">models</span></div>
  <div class="stat"><span class="v">{len(BENCHES)}</span><span class="k">benchmarks</span></div>
  <div class="stat"><span class="v">{total_scores}</span><span class="k">data points</span></div>
  <div class="stat"><span class="v">{sum(1 for m in MODELS if m.get('supports_vision'))}</span><span class="k">with vision</span></div>
</div>

<h2>Browse</h2>
<div class="cards">
  <a class="card" href="models.html">
    <span class="kicker">Roster</span>
    <h3>Models</h3>
    <p>Every tracked model with parameters, active size, context, KV cost and decode speed. Sortable.</p>
    <p class="arrow">Open the table →</p>
  </a>
  <a class="card" href="matrix.html">
    <span class="kicker">Scores</span>
    <h3>Matrix</h3>
    <p>Every model against every benchmark at a glance — or plot any two metrics against
    each other in the scatter view.</p>
    <p class="arrow">Open the matrix →</p>
  </a>
  <a class="card" href="benchmarks.html">
    <span class="kicker">Catalogue</span>
    <h3>Benchmarks</h3>
    <p>{len(BENCHES)} benchmarks grouped by domain, each with its own leaderboard and sources.</p>
    <p class="arrow">Browse benchmarks →</p>
  </a>
  <a class="card" href="compare.html">
    <span class="kicker">Compare</span>
    <h3>Side by side</h3>
    <p>Pick up to five models and compare them on the benchmarks they all report.</p>
    <p class="arrow">Start a comparison →</p>
  </a>
</div>

<h2>Newest models</h2>
<div class="tbl-wrap"><table class="tbl">
<thead><tr><th>Model</th><th class="num">Params</th><th class="num">Active</th>
<th class="num">Context</th><th class="num">KV @128K</th><th class="num">Released</th></tr></thead>
<tbody>{newest_rows}</tbody>
</table></div>

<h2 id="changes">Recent changes <a class="feed-link" href="{SITE}feed.xml" title="Subscribe with RSS">RSS</a></h2>
<ul class="changes">{changes}</ul>
"""
    return layout("Tiny League — small models, real benchmarks", body, "home",
                  desc="Benchmark scores for recent small open-weight models.", path="index.html")


def page_models():
    rows = []
    for m in MODELS:
        t = mtype(m)
        badges = ""
        if m.get("supports_vision"):
            badges += '<span class="pill v">V</span> '
        if t == "moe":
            badges += '<span class="pill moe">MoE</span>'
        rows.append(
            f'<tr data-name="{esc(model_name(m).lower())}" data-params="{m.get("param_count_b") or 0}"'
            f' data-moe="{1 if mtype(m) == "moe" else 0}" data-vision="{1 if m.get("supports_vision") else 0}">'
            f'<td class="name"><a href="{esc(m.get("hf_url") or "#")}" target="_blank" rel="noopener">{esc(model_name(m))}</a> {badges}</td>'
            f'<td class="num" data-sort="{m.get("param_count_b") or 0}">{params(m)}</td>'
            f'<td class="num" data-sort="{m.get("active_params_b") or m.get("param_count_b") or 0}">{active(m)}</td>'
            f'<td class="num" data-sort="{(m.get("kv_cache") or {}).get("native_ctx") or 0}">{esc(ctx(m))}</td>'
            f'<td class="num" data-sort="{(m.get("kv_cache") or {}).get("gib_at_ref_ctx") or 0}">{esc(kv(m))}</td>'
            f'<td class="num" data-sort="{(m.get("perf") or {}).get("decode_tok_s_fresh") or 0}">{esc(speed(m))}</td>'
            f'<td>{esc(t)}</td>'
            f'<td>{esc(lic(m))}</td>'
            f'<td data-sort="{esc(m.get("official_release_date") or "")}">{esc(m.get("official_release_date") or "")}</td>'
            "</tr>"
        )
    body = f"""
<h1>Models</h1>
<p class="lede">The roster: recent small open-weight models, official weights only.
<b>Active</b> is what a model uses per token; <b>KV @128K</b> and <b>Decode</b> are derived
from each model's <code>config.json</code>, not measured.</p>
{filter_bar()}
<div class="toolbar">
  <input class="search" id="q" type="search" placeholder="Filter models…" aria-label="Filter models">
</div>
<div class="tbl-wrap"><table class="tbl" id="tbl">
<thead><tr>
  <th>Model</th>
  <th class="num" data-sort>Params</th>
  <th class="num" data-sort>Active</th>
  <th class="num" data-sort>Context</th>
  <th class="num" data-sort>KV @128K</th>
  <th class="num" data-sort>Decode</th>
  <th>Type</th><th>License</th>
  <th data-sort>Released</th>
</tr></thead>
<tbody>{''.join(rows)}</tbody>
</table></div>
"""
    js = """
(function(){
 var tbl=document.getElementById('tbl'),tb=tbl.tBodies[0],q=document.getElementById('q');
 function applyRows(){
   var v=q.value.trim().toLowerCase(),n=0;
   for(var i=0;i<tb.rows.length;i++){
     var r=tb.rows[i];
     var show=r.dataset.f!=='0'&&(!v||r.dataset.name.indexOf(v)>-1);
     r.style.display=show?'':'none'; if(show)n++;
   }
   var c=document.getElementById('fcount');
   if(c)c.textContent=n+' of '+tb.rows.length+' models';
 }
 window.TL_APPLY=applyRows;
 q.addEventListener('input',applyRows);
 applyRows();
 var ths=tbl.tHead.rows[0].cells;
 for(var h=0;h<ths.length;h++){(function(th,ci){
   if(!th.hasAttribute('data-sort'))return;
   var dir=null;
   th.addEventListener('click',function(){
     dir=dir==='asc'?'desc':(dir===null?'desc':'asc');
     for(var j=0;j<ths.length;j++)ths[j].removeAttribute('aria-sort');
     th.setAttribute('aria-sort',dir==='asc'?'ascending':'descending');
     var rows=Array.prototype.slice.call(tb.rows);
     rows.sort(function(a,b){
       var x=a.cells[ci],y=b.cells[ci];
       var xv=x.getAttribute('data-sort'),yv=y.getAttribute('data-sort');
       var xn=parseFloat(xv),yn=parseFloat(yv);
       var num=!isNaN(xn)&&!isNaN(yn)&&xv!==''&&yv!=='';
       var r=num?xn-yn:String(xv).localeCompare(String(yv));
       return dir==='asc'?r:-r;
     });
     rows.forEach(function(r){tb.appendChild(r);});
   });
 })(ths[h],h);}
})();
"""
    return layout("Models — Tiny League", body, "models", script=js,
                  desc="Every tracked small open-weight model, sortable.", path="models.html")


def page_benchmarks():
    blocks = []
    for dom in DOMAIN_ORDER:
        items = BY_DOMAIN.get(dom) or []
        if not items:
            continue
        rows = []
        for b in sorted(items):
            v, mid = best_of(b)
            rows.append(
                f'<tr data-name="{esc(b.lower())}" data-b="{esc(b)}">'
                f'<td class="name"><a href="benchmarks/{BENCH_SLUG[b]}.html">{esc(b)}</a></td>'
                f'<td class="num" data-c>{COV[b]}</td>'
                f'<td class="num best" data-best>{esc(num(v))}</td>'
                f'<td data-leader>{esc(model_name(BY_ID[mid])) if mid else ""}</td>'
                "</tr>"
            )
        blocks.append(
            f'<section class="domain-block" id="dom-{slug(dom)}" data-domain="{esc(dom)}">'
            f'<div class="domain-head"><h2>{esc(dom)}</h2><span class="n">{len(items)} benchmarks</span></div>'
            '<div class="tbl-wrap"><table class="tbl">'
            '<thead><tr><th>Benchmark</th><th class="num">Models</th>'
            '<th class="num">Best</th><th>Leader</th></tr></thead>'
            f'<tbody>{"".join(rows)}</tbody></table></div></section>'
        )
    jump = "".join(
        f'<a class="jump-link" href="#dom-{slug(d)}" data-jump="{esc(d)}">'
        f'{esc(d)} <b>{len(BY_DOMAIN[d])}</b></a>'
        for d in DOMAIN_ORDER if BY_DOMAIN.get(d)
    )
    body = f"""
<h1>Benchmarks</h1>
<p class="lede">{len(BENCHES)} benchmarks reported by at least two tracked models, grouped by
what they measure. Each opens a leaderboard with the models that report it and the source.</p>
<nav class="jump" aria-label="Jump to a category">{jump}</nav>
{filter_bar()}
<div class="toolbar">
  <input class="search" id="q" type="search" placeholder="Filter benchmarks…" aria-label="Filter benchmarks">
  <span class="count" id="count">{len(BENCHES)} benchmarks</span>
</div>
{"".join(blocks)}
"""
    entries = {}
    for b in BENCHES:
        entries[b] = [[mid, SCORES[mid][b]["score"]] for mid in SCORES if b in SCORES[mid]]
    meta = {m["model_id"]: [m.get("param_count_b") or 0,
                            1 if mtype(m) == "moe" else 0,
                            1 if m.get("supports_vision") else 0] for m in MODELS}
    js = """
var BM=%s, MM=%s;
(function(){
 var q=document.getElementById('q'),count=document.getElementById('count');
 function okModel(mid){
   var f=window.TL_FILTER||{},m=MM[mid]||[0,0,0];
   if(f.mn!=null&&!isNaN(f.mn)&&m[0]<f.mn)return false;
   if(f.mx!=null&&!isNaN(f.mx)&&m[0]>f.mx)return false;
   if(f.moe&&m[1]!==1)return false;
   if(f.vis&&m[2]!==1)return false;
   return true;
 }
 function apply(){
   var term=(q.value||'').trim().toLowerCase(),n=0;
   var blocks=document.querySelectorAll('.domain-block');
   for(var i=0;i<blocks.length;i++){
     var rows=blocks[i].querySelectorAll('tbody tr'),shown=0;
     for(var j=0;j<rows.length;j++){
       var tr=rows[j],b=tr.dataset.b;
       var list=(BM[b]||[]).filter(function(p){return okModel(p[0]);});
       var show=list.length>=2&&(!term||tr.dataset.name.indexOf(term)>-1);
       tr.style.display=show?'':'none';
       if(show){
         shown++;n++;
         var best=list.reduce(function(a,p){return p[1]>a[1]?p:a;});
         tr.querySelector('[data-c]').textContent=list.length;
         tr.querySelector('[data-best]').textContent=Math.round(best[1]*100)/100;
         tr.querySelector('[data-leader]').textContent=best[0].split('/').pop();
       }
     }
     blocks[i].style.display=shown?'':'none';
     var lab=blocks[i].querySelector('.n');
     if(lab&&shown)lab.textContent=shown+' benchmarks';
     var chip=document.querySelector('.jump-link[data-jump="'+blocks[i].dataset.domain+'"]');
     if(chip){var cb=chip.querySelector('b');
       if(cb)cb.textContent=shown;
       chip.style.display=shown?'':'none';}
   }
   count.textContent=n+(n===1?' benchmark':' benchmarks');
 }
 window.TL_APPLY=apply;
 q.addEventListener('input',apply);
 apply();
})();
""" % (json.dumps(entries, separators=(",", ":")), json.dumps(meta, separators=(",", ":")))
    return layout("Benchmarks — Tiny League", body, "bench", script=js,
                  desc="Every tracked benchmark grouped by domain.", path="benchmarks.html")


def page_benchmark(bench):
    rows = [(SCORES[mid][bench]["score"], mid) for mid in SCORES if bench in SCORES[mid]]
    rows.sort(key=lambda r: -r[0])
    body_rows = []
    for i, (v, mid) in enumerate(rows, 1):
        m = BY_ID[mid]
        sc = SCORES[mid][bench]
        src = sc.get("source_url")
        src_html = (f'<a href="{esc(src)}" target="_blank" rel="noopener" '
                    f'title="{esc(sc.get("source") or "")}">source</a>') if src else ""
        sub = sc.get("subtask")
        body_rows.append(
            f'<tr data-params="{m.get("param_count_b") or 0}" data-moe="{1 if mtype(m) == "moe" else 0}" data-vision="{1 if m.get("supports_vision") else 0}">'
            f"<td class=\"num\">{i}</td>"
            f'<td class="name"><a href="{esc(m.get("hf_url") or "#")}" target="_blank" rel="noopener">{esc(model_name(m))}</a>'
            + (f' <span class="pill">{esc(sub)}</span>' if sub else "") + "</td>"
            f'<td class="num{" best" if v == rows[0][0] else ""}">{esc(num(v))}</td>'
            f'<td class="num">{params(m)}</td>'
            f'<td class="num">{esc(kv(m))}</td>'
            f'<td class="num">{esc(speed(m))}</td>'
            f'<td class="small">{src_html}</td></tr>'
        )
    fam = family_of(bench)
    sibs = [b for b in SIBLINGS.get(fam, []) if b != bench]
    sib_html = ""
    if sibs:
        sib_html = ('<p class="small muted">Other versions in this family: '
                    + ", ".join(f'<a href="{BENCH_SLUG[s]}.html">{esc(s)}</a>' for s in sibs)
                    + "</p>")
    dom = DOMAIN_OF[bench]
    body = f"""
<div class="crumb"><a href="../index.html">Home</a> / <a href="../benchmarks.html">Benchmarks</a> / {esc(dom)}</div>
<h1>{esc(bench)} <span class="pill domain">{esc(dom)}</span></h1>
<p class="lede">{len(rows)} of {len(MODELS)} tracked models report a score for this benchmark.
Highest reasoning level where a card reports several.</p>
{sib_html}
{filter_bar()}
<div class="tbl-wrap" style="margin-top:14px"><table class="tbl">
<thead><tr><th class="num">#</th><th>Model</th><th class="num">Score</th>
<th class="num">Params</th><th class="num">KV @128K</th><th class="num">Decode</th><th>Source</th></tr></thead>
<tbody>{''.join(body_rows)}</tbody>
</table></div>
<p class="small muted" style="margin-top:14px">Scores are as reported by each model's card or
tech report; missing models are not estimated. Versions are never pooled.</p>
"""
    js = """
window.TL_APPLY=function(){
  var tb=document.querySelector('table.tbl tbody'),n=0;
  for(var i=0;i<tb.rows.length;i++){var r=tb.rows[i];
    var ok=r.dataset.f!=='0';r.style.display=ok?'':'none';
    if(ok){n++;r.cells[0].textContent=n;}}
};
window.TL_APPLY();
"""
    return layout(f"{bench} — Tiny League", body, "bench", depth=1, script=js,
                  desc=f"{bench} scores across small open-weight models.", path=f"benchmarks/{BENCH_SLUG[bench]}.html")


def page_compare():
    payload = {}
    for m in MODELS:
        mid = m["model_id"]
        payload[mid] = {
            "n": model_name(m),
            "p": m.get("param_count_b"),
            "k": (m.get("kv_cache") or {}).get("gib_at_ref_ctx"),
            "d": (m.get("perf") or {}).get("decode_tok_s_fresh"),
            "s": {b: v["score"] for b, v in SCORES.get(mid, {}).items()},
        }
    data = json.dumps(payload, separators=(",", ":"))
    border = {b: DOMAIN_ORDER.index(DOMAIN_OF[b]) for b in BENCHES}
    picker = "".join(
        f'<li data-params="{m.get("param_count_b") or 0}"'
        f' data-moe="{1 if mtype(m) == "moe" else 0}"'
        f' data-vision="{1 if m.get("supports_vision") else 0}">'
        f'<label><input type="checkbox" value="{esc(m["model_id"])}"'
        f'{" checked" if i < 3 else ""}> {esc(model_name(m))}</label></li>'
        for i, m in enumerate(MODELS)
    )
    body = f"""
<h1>Compare models</h1>
<p class="lede">Pick up to five models. The table shows every benchmark reported by at least
two of them, highest score in each row highlighted.</p>
{filter_bar()}
<div class="cmp" style="margin-top:16px">
  <aside class="picker">
    <h3>Models</h3>
    <input class="search" id="q" type="search" placeholder="Filter…" aria-label="Filter models">
    <ul class="plist" id="plist">{picker}</ul>
    <div class="cmp-actions">
      <button class="icon-btn" id="none" type="button">Clear</button>
      <span class="count" id="csel">3 selected</span>
    </div>
  </aside>
  <div id="result"><div class="empty">Select at least two models.</div></div>
</div>
"""
    js = """
var DATA=%s;
var BORDER=%s;
(function(){
 var list=document.getElementById('plist'),res=document.getElementById('result'),
     q=document.getElementById('q'),csel=document.getElementById('csel');
 function selected(){return Array.prototype.filter.call(
   list.querySelectorAll('input'),function(i){return i.checked;}).map(function(i){return i.value;});}
 function render(){
   var sel=selected();
   csel.textContent=sel.length+' selected';
   if(sel.length<2){res.innerHTML='<div class="empty">Select at least two models.</div>';return;}
   var all={};sel.forEach(function(id){Object.keys(DATA[id].s).forEach(function(b){all[b]=1;});});
   var rows=Object.keys(all).filter(function(b){
     return sel.filter(function(id){return b in DATA[id].s;}).length>=2;});
   rows.sort(function(a,b){var da=BORDER[a],db=BORDER[b];
     return da===db?a.localeCompare(b):da-db;});
   var head='<tr><th>Benchmark</th>'+sel.map(function(id){
     return '<th class="num plain">'+DATA[id].n+'</th>';}).join('')+'</tr>';
   var body=rows.map(function(b){
     var vals=sel.map(function(id){return b in DATA[id].s?DATA[id].s[b]:null;});
     var best=Math.max.apply(null,vals.filter(function(v){return v!==null;}));
     return '<tr><td class="name">'+b+'</td>'+vals.map(function(v){
       if(v===null)return '<td class="num muted">—</td>';
       return '<td class="num'+(v===best?' best':'')+'">'+v+'</td>';}).join('')+'</tr>';}).join('');
   res.innerHTML='<div class="tbl-wrap"><table class="tbl"><thead>'+head+'</thead><tbody>'+body+
     '</tbody></table></div><p class="small muted" style="margin-top:12px">'+rows.length+
     ' shared benchmarks · highlighted = best in row</p>';
 }
 list.addEventListener('change',function(e){
   var sel=selected();
   if(sel.length>5){e.target.checked=false;render();
     alert('Compare shows up to five models — uncheck one first.');return;}
   render();});
 document.getElementById('none').addEventListener('click',function(){
   list.querySelectorAll('input').forEach(function(i){i.checked=false;});render();});
 window.TL_APPLY=function(){
   var v=q.value.toLowerCase();
   list.querySelectorAll('li').forEach(function(li){
     var ok=li.dataset.f!=='0'&&(!v||li.textContent.toLowerCase().indexOf(v)>-1);
     li.style.display=ok?'':'none';
     if(!ok){var i=li.querySelector('input');if(i)i.checked=false;}});
   render();
 };
 q.addEventListener('input',window.TL_APPLY);
 window.TL_APPLY();
})();
""" % (data, json.dumps(border))
    return layout("Compare — Tiny League", body, "compare", script=js,
                  desc="Compare small open-weight models side by side.", path="compare.html")


def page_matrix():
    cols = sorted(BENCHES, key=lambda b: (DOMAIN_ORDER.index(DOMAIN_OF[b]), b))
    stats = {}
    for b in cols:
        vals = [SCORES[mid][b]["score"] for mid in SCORES if b in SCORES[mid]]
        stats[b] = (min(vals), max(vals)) if vals else (0, 0)
    head = ['<th class="m">Model</th>']
    for b in cols:
        head.append(
            f'<th data-b="{esc(b)}" data-dom="{esc(DOMAIN_OF[b])}" data-n="{COV[b]}">'
            f'<button type="button" class="thsort">{esc(b)}</button>'
            f'<a class="thopen" href="benchmarks/{BENCH_SLUG[b]}.html" '
            f'title="Open the {esc(b)} leaderboard">&#8599;</a></th>'
        )
    rows = []
    for m in MODELS:
        mid = m["model_id"]
        d = SCORES.get(mid, {})
        cells = [f'<td class="m"><a href="{esc(m.get("hf_url") or "#")}" target="_blank" '
                 f'rel="noopener">{esc(model_name(m))}</a>{badge_html(m)}</td>']
        for b in cols:
            sc = d.get(b)
            if sc is None:
                cells.append('<td class="c empty">·</td>')
            else:
                lo, hi = stats[b]
                v = sc["score"]
                cells.append(f'<td class="c {heat_class(v, lo, hi)}" data-v="{v}">{esc(num(v))}</td>')
        rows.append(
            f'<tr data-params="{m.get("param_count_b") or 0}"'
            f' data-moe="{1 if mtype(m) == "moe" else 0}"'
            f' data-vision="{1 if m.get("supports_vision") else 0}">' + "".join(cells) + "</tr>"
        )
    doms = "".join(f'<option value="{esc(d)}">{esc(d)}</option>'
                   for d in DOMAIN_ORDER if BY_DOMAIN.get(d))
    body = f"""
<h1>Scores</h1>
{views_html("table")}
<p class="lede">Every model against every benchmark. Colour is scaled within each column
across the models currently shown, so a filtered view still reads. Click a column name to
rank the models by it; the ↗ opens that benchmark's leaderboard.</p>
{filter_bar()}
<div class="toolbar mxbar">
  <input class="search" id="mxq" type="search" placeholder="Filter benchmarks…" aria-label="Filter benchmarks">
  <label class="chk"><input type="checkbox" id="mxcore" checked> Core only (5+ models)</label>
  <select id="mxdom" class="select" aria-label="Domain"><option value="">All domains</option>{doms}</select>
  <span class="count" id="mxcount"></span>
</div>
<div class="tbl-wrap mx-wrap"><table class="tbl mx" id="matrix">
<thead><tr>{''.join(head)}</tr></thead>
<tbody>{''.join(rows)}</tbody></table></div>
"""
    js = """
(function(){
 var tbl=document.getElementById('matrix'),ths=tbl.tHead.rows[0].cells,tb=tbl.tBodies[0],
     q=document.getElementById('mxq'),core=document.getElementById('mxcore'),
     dom=document.getElementById('mxdom'),count=document.getElementById('mxcount');
 function rank(v,lo,hi){if(hi<=lo)return 10;var t=(v-lo)/(hi-lo);
   if(t<0)t=0;if(t>1)t=1;return Math.round(t*20);}
 var sortCol=-1,sortDir=-1;
 function sortBy(c){
   if(sortCol===c)sortDir=-sortDir; else {sortCol=c;sortDir=-1;}
   var rows=Array.prototype.slice.call(tb.rows);
   rows.sort(function(a,b){
     var x=a.cells[c],y=b.cells[c];
     var xv=(x&&x.dataset.v!==undefined)?parseFloat(x.dataset.v):null;
     var yv=(y&&y.dataset.v!==undefined)?parseFloat(y.dataset.v):null;
     if(xv===null&&yv===null)return 0;
     if(xv===null)return 1;
     if(yv===null)return -1;
     return (xv-yv)*sortDir;
   });
   rows.forEach(function(r){tb.appendChild(r);});
   for(var i=0;i<ths.length;i++){ths[i].removeAttribute('aria-sort');
     var b0=ths[i].querySelector('.thsort');if(b0)b0.setAttribute('data-arrow','');}
   ths[c].setAttribute('aria-sort',sortDir===-1?'descending':'ascending');
   var b1=ths[c].querySelector('.thsort');
   if(b1)b1.setAttribute('data-arrow',sortDir===-1?' \u2193':' \u2191');
 }
 for(var ci=1;ci<ths.length;ci++){(function(c){
   var btn=ths[c].querySelector('.thsort');
   if(btn)btn.addEventListener('click',function(){sortBy(c);});
 })(ci);}
 function applyAll(){
   var vis=[],r,i,c;
   for(r=0;r<tb.rows.length;r++){var tr=tb.rows[r];
     var show=tr.dataset.f!=='0';tr.style.display=show?'':'none';if(show)vis.push(tr);}
   var term=(q.value||'').trim().toLowerCase(),cs=core.checked,dd=dom.value,shown=0;
   for(c=1;c<ths.length;c++){
     var th=ths[c],name=(th.dataset.b||'').toLowerCase();
     var ok=(!term||name.indexOf(term)>-1)&&(!cs||parseInt(th.dataset.n,10)>=5)
            &&(dd===''||th.dataset.dom===dd);
     var vals=[];
     if(ok){for(i=0;i<vis.length;i++){var td=vis[i].cells[c];
       if(td&&td.dataset.v!==undefined){var v=parseFloat(td.dataset.v);
         if(!isNaN(v))vals.push([td,v]);}}}
     if(ok&&vals.length<2)ok=false;
     th.style.display=ok?'':'none';
     if(ok){var lo=Infinity,hi=-Infinity;
       for(i=0;i<vals.length;i++){if(vals[i][1]<lo)lo=vals[i][1];if(vals[i][1]>hi)hi=vals[i][1];}
       for(i=0;i<vals.length;i++){vals[i][0].className='c h'+rank(vals[i][1],lo,hi);}
       shown++;}
     for(r=0;r<tb.rows.length;r++){var cell=tb.rows[r].cells[c];if(cell)cell.style.display=ok?'':'none';}
   }
   count.textContent=shown+' of '+(ths.length-1)+' benchmarks · '+vis.length+' models';
 }
 window.TL_APPLY=applyAll;
 [q,core,dom].forEach(function(el){
   el.addEventListener('input',applyAll);el.addEventListener('change',applyAll);});
 applyAll();
})();
"""
    return layout("Scores — Tiny League", body, "table", script=js,
                  desc="Every benchmark score in one matrix, filterable by model size.", path="matrix.html")


SCATTER_PRESETS = ["GPQA Diamond", "Terminal-Bench 2.1", "HLE", "IFBench"]
SCATTER_AXES = [("params", "Parameters (B)", True), ("kv", "KV cache @128K (GiB)", True),
                ("f", "Decode fresh (tok/s)", False), ("r", "Decode @128K (tok/s)", False),
                ("t", "Release date", False)]


def scatter_payload():
    models = []
    for m in MODELS:
        mid = m["model_id"]
        kvb = m.get("kv_cache") or {}
        pf = m.get("perf") or {}
        models.append({
            "id": mid,
            "n": model_name(m),
            "u": m.get("hf_url") or "",
            "p": m.get("param_count_b"),
            "kv": kvb.get("gib_at_ref_ctx"),
            "f": pf.get("decode_tok_s_fresh"),
            "r": pf.get("decode_tok_s_at_ref_ctx"),
            "t": m.get("official_release_date"),
            "moe": 1 if mtype(m) == "moe" else 0,
            "v": 1 if m.get("supports_vision") else 0,
            "s": {b: SCORES[mid][b]["score"] for b in SCORES.get(mid, {})},
        })
    axes = [{"k": k, "l": l, "log": lg, "g": "Model"} for k, l, lg in SCATTER_AXES]
    for b in sorted(BENCHES, key=lambda x: (DOMAIN_ORDER.index(DOMAIN_OF[x]), x)):
        axes.append({"k": "bench:" + b, "l": b, "g": "Benchmark"})
    presets = []
    for b in SCATTER_PRESETS:
        if COV.get(b, 0) < 2:
            continue
        presets.append({
            "id": "b-" + BENCH_SLUG[b], "l": b, "x": "params", "y": "bench:" + b,
            "note": "Score on %s against model size. Top-left is the sweet spot: a high score "
                    "on few parameters. Hover a point for its values; click to open the model "
                    "card." % b,
        })
    presets.append({
        "id": "kv", "l": "KV @128K", "x": "params", "y": "kv",
        "note": "KV-cache size against total model size. Bottom-left is the cheap-context "
                "corner: a small model that holds a long context in little VRAM. The shaded "
                "top-left corner is the one to avoid: a big KV cost on a small model.",
    })
    presets.append({
        "id": "speed", "l": "Speed", "x": "params", "y": "r",
        "note": "Estimated single-stream decode speed at 128K context against total model "
                "size (one RTX 4090 at half its 1008 GB/s bandwidth). Top-left is the sweet "
                "spot: high long-context throughput on few parameters. MoE models sit left of "
                "dense peers of the same size because only their active parameters are "
                "streamed.",
    })
    return {"models": models, "axes": axes, "presets": presets}


def axis_select(sel_id, default_key, axes):
    groups = {}
    for a in axes:
        groups.setdefault(a["g"], []).append(a)
    out = []
    for gname in ("Model", "Benchmark"):
        out.append('<optgroup label="%s">' % gname)
        for a in groups.get(gname, []):
            out.append('<option value="%s"%s>%s</option>'
                       % (esc(a["k"]), " selected" if a["k"] == default_key else "",
                          esc(a["l"])))
        out.append("</optgroup>")
    return '<select class="select" id="%s">%s</select>' % (sel_id, "".join(out))


def page_scatter():
    payload = scatter_payload()
    tabs = "".join(
        '<button type="button" role="tab" aria-selected="%s" data-mode="%s">%s</button>'
        % ("true" if i == 0 else "false", esc(p["id"]), esc(p["l"]))
        for i, p in enumerate(payload["presets"])
    ) + ('<button type="button" role="tab" aria-selected="false" data-mode="custom">'
         'Custom</button>')
    default_y = "bench:" + SCATTER_PRESETS[0] if COV.get(SCATTER_PRESETS[0], 0) >= 2 else "kv"
    body = f"""
<h1>Scores</h1>
{views_html("scatter")}
<p class="lede">One metric against another — benchmark scores, parameters, KV-cache cost and
decode speed. The filters apply, so the chart always shows the models in view. Hover a point
for its values; click it to open the model card.</p>
{filter_bar()}
<div class="sc-tabs" role="tablist" aria-label="Chart preset">{tabs}</div>
<div class="sc-custom" id="sc-custom" hidden>
  <label>X axis {axis_select("sc-x", "params", payload["axes"])}</label>
  <label>Y axis {axis_select("sc-y", default_y, payload["axes"])}</label>
</div>
<div class="sc-wrap" id="scwrap"><div class="sc-tip" id="sctip"></div><div id="scbox"></div></div>
<p class="sc-note" id="scnote"></p>
<div class="sc-foot">
  <span class="count" id="sccount"></span>
  <button type="button" id="sc-table-btn" aria-expanded="false" aria-controls="sctable">Show as table</button>
</div>
<div id="sctable" hidden></div>
"""
    js = SCATTER_JS.replace("__SC__", json.dumps(payload, ensure_ascii=False))
    return layout("Scatter — Tiny League", body, "scatter", script=js,
                  desc="Scatter charts of any two metrics: benchmark scores, parameters, "
                       "KV-cache cost and decode speed.", path="scatter.html")


SCATTER_JS = """
(function(){
 var SC=__SC__;
 var wrap=document.getElementById('scwrap'),box=document.getElementById('scbox'),
     tip=document.getElementById('sctip'),note=document.getElementById('scnote'),
     cnt=document.getElementById('sccount'),tbl=document.getElementById('sctable'),
     tblBtn=document.getElementById('sc-table-btn'),
     custom=document.getElementById('sc-custom'),selX=document.getElementById('sc-x'),
     selY=document.getElementById('sc-y'),
     tabs=[].slice.call(document.querySelectorAll('.sc-tabs button'));
 if(!box)return;
 var mode=SC.presets.length?SC.presets[0].id:'custom';
 var pts=[],hot=-1,geo=null,lastW=0;

 function esc(s){return String(s).replace(/[&<>"]/g,function(c){
   return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c];});}
 function isNum(v){return typeof v==='number'&&isFinite(v);}
 function r1(v){return Math.round(v*10)/10;}
 function val(m,k){
   if(k==='params')return isNum(m.p)?m.p:null;
   if(k==='kv')return isNum(m.kv)?m.kv:null;
   if(k==='f')return isNum(m.f)?m.f:null;
   if(k==='r')return isNum(m.r)?m.r:null;
   if(k==='t')return m.t?Date.parse(m.t+'T00:00:00Z'):null;
   if(k.indexOf('bench:')===0){var v=m.s[k.slice(6)];return isNum(v)?v:null;}
   return null;
 }
 function meta(k){
   for(var i=0;i<SC.axes.length;i++){if(SC.axes[i].k===k)return SC.axes[i];}
   return {k:k,l:k};
 }
 function label(k){return meta(k).l||k;}
 function title(k){
   var m=meta(k);
   if(!m.log)return m.l;
   if(m.l.charAt(m.l.length-1)===')')return m.l.slice(0,-1)+', log)';
   return m.l+' (log)';
 }

 function visible(){
   var f=window.TL_FILTER||{},out=[],i,m,
       mn=isNum(f.mn)?f.mn:-Infinity,mx=isNum(f.mx)?f.mx:Infinity;
   for(i=0;i<SC.models.length;i++){
     m=SC.models[i];
     if(!isNum(m.p)||m.p<mn||m.p>mx)continue;
     if(f.moe&&!m.moe)continue;
     if(f.vis&&!m.v)continue;
     out.push(m);
   }
   return out;
 }
 function spec(){
   for(var i=0;i<SC.presets.length;i++){
     var p=SC.presets[i];
     if(p.id===mode)return {x:p.x,y:p.y,note:p.note||'',preset:true};
   }
   return {x:(selX&&selX.value)||'params',y:(selY&&selY.value)||'kv',note:'',preset:false};
 }
 function pad(lo,hi,log){
   if(lo===hi){
     if(log){return [lo/1.4,hi*1.4];}
     var d=Math.abs(lo)*0.08||1;return [lo-d,hi+d];
   }
   if(log){var f=Math.pow(hi/lo,0.05);return [lo/f,hi*f];}
   var p=(hi-lo)*0.06;return [lo-p,hi+p];
 }
 function linTicks(lo,hi){
   var span=hi-lo||1,raw=span/5,mag=Math.pow(10,Math.floor(Math.log10(raw))),
       n=raw/mag,step=(n<=1?1:n<=2?2:n<=2.5?2.5:n<=5?5:10)*mag,
       t=[],v=Math.ceil(lo/step-1e-9)*step;
   while(v<=hi+1e-9){if(v>=lo-1e-9)t.push(v);v+=step;}
   return t;
 }
 function logTicks(lo,hi){
   var t=[],e0=Math.floor(Math.log10(lo)),e1=Math.ceil(Math.log10(hi)),e,j,v,ms=[1,2,5];
   for(e=e0;e<=e1;e++){
     for(j=0;j<3;j++){
       v=ms[j]*Math.pow(10,e);
       if(v>=lo*0.999&&v<=hi*1.001)t.push(v);
     }
   }
   while(t.length>8)t=t.filter(function(_,i){return i%2===0;});
   return t;
 }
 function monthTicks(lo,hi){
   var d=new Date(lo),t=[];
   d=new Date(Date.UTC(d.getUTCFullYear(),d.getUTCMonth(),1));
   while(d.getTime()<lo)d=new Date(Date.UTC(d.getUTCFullYear(),d.getUTCMonth()+1,1));
   while(d.getTime()<=hi){
     t.push(d.getTime());
     d=new Date(Date.UTC(d.getUTCFullYear(),d.getUTCMonth()+1,1));
   }
   while(t.length>7)t=t.filter(function(_,i){return i%2===0;});
   return t;
 }
 function ticks(k,lo,hi,log){
   if(meta(k).date)return monthTicks(lo,hi);
   return log?logTicks(lo,hi):linTicks(lo,hi);
 }
 function fmt(k,v){
   if(meta(k).date){
     var d=new Date(v);return isNaN(d.getTime())?'':d.toISOString().slice(0,10);
   }
   if(Math.abs(v)>=100)return String(Math.round(v));
   return String(r1(v));
 }

 /* Labels are placed after the SVG is in the DOM: it is the only way to get a real
    text width. Each label takes the first free slot around its dot, or is dropped. */
 function placeLabels(svg){
   var narrow=(svg.clientWidth||900)<560;
   var gs=[].slice.call(svg.querySelectorAll('.sc-pt'));
   var cs=gs.map(function(g){
     var c=g.querySelector('circle');
     return {x:+c.getAttribute('cx'),y:+c.getAttribute('cy')};
   });
   var boxes=cs.map(function(p){return {x:p.x-5,y:p.y-5,w:10,h:10};});
   gs.forEach(function(g,i){
     var t=g.querySelector('text');
     if(narrow){t.style.display='none';return;}
     var w=0;
     try{w=t.getComputedTextLength();}catch(e){}
     if(!w)w=52;
     var h=10.5,p=cs[i],
         cands=[[8,-4],[8,-17],[8,9],[-8-w,-4],[-8-w,-17],[-8-w,9],[8,-30],[8,22]];
     for(var k=0;k<cands.length;k++){
       var bx=p.x+cands[k][0],by=p.y+cands[k][1];
       if(bx<geo.L+2||bx+w>geo.L+geo.w-2||by<geo.T+2||by+h>geo.T+geo.h-2)continue;
       var b={x:bx,y:by,w:w,h:h},hit=false;
       for(var j=0;j<boxes.length;j++){
         var o=boxes[j];
         if(b.x<o.x+o.w&&b.x+b.w>o.x&&b.y<o.y+o.h&&b.y+b.h>o.y){hit=true;break;}
       }
       if(!hit){
         boxes.push(b);
         t.setAttribute('x',r1(bx));
         t.setAttribute('y',r1(by+9));
         return;
       }
     }
     t.style.display='none';
   });
 }

 function hideTip(){
   hot=-1;
   if(tip)tip.classList.remove('on');
   var gs=box.querySelectorAll('.sc-pt');
   for(var i=0;i<gs.length;i++)gs[i].classList.remove('hot');
 }

 function render(){
   if(!box)return;
   if(tip)tip.classList.remove('on');
   hot=-1;
   lastW=box.clientWidth||760;
   var sp=spec();
   if(note){
     note.textContent=sp.preset&&sp.note?sp.note:
       'Any two metrics, plotted against each other. Hover a point for its values; click to '+
       'open the model card.';
   }
   var ms=visible(),i;
   pts=[];
   for(i=0;i<ms.length;i++){
     var xv=val(ms[i],sp.x),yv=val(ms[i],sp.y);
     if(xv!==null&&yv!==null)pts.push({m:ms[i],x:xv,y:yv});
   }
   if(cnt)cnt.textContent=pts.length+' of '+ms.length+' models in view have both values';
   if(!pts.length){
     box.innerHTML='<p class="sc-empty">No model in this range reports both <b>'+esc(label(sp.x))+
       '</b> and <b>'+esc(label(sp.y))+'</b>.</p>';
     if(tbl)tbl.innerHTML='';
     return;
   }
   var W=Math.max(300,box.clientWidth||760),
       H=Math.round(Math.min(520,Math.max(300,W*0.58))),
       L=54,R=16,T=16,B=44,
       w=W-L-R,h=H-T-B;
   geo={L:L,T:T,w:w,h:h};
   var xm=meta(sp.x),ym=meta(sp.y),
       xl=Infinity,xh=-Infinity,yl=Infinity,yh=-Infinity;
   for(i=0;i<pts.length;i++){
     if(pts[i].x<xl)xl=pts[i].x;
     if(pts[i].x>xh)xh=pts[i].x;
     if(pts[i].y<yl)yl=pts[i].y;
     if(pts[i].y>yh)yh=pts[i].y;
   }
   var xlog=!!xm.log&&xl>0,ylog=!!ym.log&&yl>0,
       xd=pad(xl,xh,xlog),yd=pad(yl,yh,ylog);
   var lx=Math.log(xd[1]/xd[0])||1,ly=Math.log(yd[1]/yd[0])||1;
   function X(v){return xlog?L+w*(Math.log(v/xd[0])/lx):L+w*(v-xd[0])/(xd[1]-xd[0]);}
   function Y(v){return ylog?T+h-h*(Math.log(v/yd[0])/ly):T+h-h*(v-yd[0])/(yd[1]-yd[0]);}
   var xt=ticks(sp.x,xd[0],xd[1],xlog),yt=ticks(sp.y,yd[0],yd[1],ylog);
   var p=[];
   p.push('<svg viewBox="0 0 '+W+' '+H+'" width="'+W+'" height="'+H+'" role="img" '+
          'aria-labelledby="sc-title sc-desc">');
   p.push('<title id="sc-title">'+esc(label(sp.y))+' vs '+esc(label(sp.x))+'</title>');
   p.push('<desc id="sc-desc">Scatter plot of '+pts.length+' models. '+
          esc(title(sp.y))+' against '+esc(title(sp.x))+'.</desc>');
   /* Params x -> the top-left corner is either the sweet spot (high score, few
      parameters) or the place to avoid (a small model with a big KV cache). */
   var glow=sp.x==='params'?(sp.y==='kv'?'warn':'good'):null;
   if(glow){
     p.push('<defs><radialGradient id="sc-glow" cx="0" cy="0" r="1">'+
            '<stop offset="0" class="g-'+glow+'"/>'+
            '<stop offset="1" class="g-'+glow+' e"/></radialGradient></defs>');
     p.push('<rect x="'+L+'" y="'+T+'" width="'+w+'" height="'+h+
            '" fill="url(#sc-glow)" pointer-events="none"/>');
   }
   var g=[];
   xt.forEach(function(v){var x=r1(X(v));
     g.push('<line x1="'+x+'" y1="'+T+'" x2="'+x+'" y2="'+r1(T+h)+'"/>');});
   yt.forEach(function(v){var y=r1(Y(v));
     g.push('<line x1="'+L+'" y1="'+y+'" x2="'+r1(L+w)+'" y2="'+y+'"/>');});
   p.push('<g class="sc-grid">'+g.join('')+'</g>');
   var t=[];
   xt.forEach(function(v){
     t.push('<text x="'+r1(X(v))+'" y="'+(T+h+17)+'" text-anchor="middle">'+
            esc(fmt(sp.x,v))+'</text>');
   });
   yt.forEach(function(v){
     t.push('<text x="'+(L-8)+'" y="'+r1(Y(v)+4)+'" text-anchor="end">'+
            esc(fmt(sp.y,v))+'</text>');
   });
   p.push('<g class="sc-tick">'+t.join('')+'</g>');
   p.push('<text class="sc-axis-title" x="'+r1(L+w/2)+'" y="'+(H-8)+
          '" text-anchor="middle">'+esc(title(sp.x))+'</text>');
   p.push('<text class="sc-axis-title" transform="translate(14 '+r1(T+h/2)+
          ') rotate(-90)" text-anchor="middle">'+esc(title(sp.y))+'</text>');
   var d=[];
   pts.forEach(function(pt,i){
     pt.px=r1(X(pt.x));
     pt.py=r1(Y(pt.y));
     d.push('<g class="sc-pt" data-i="'+i+'"><circle cx="'+pt.px+'" cy="'+pt.py+
            '" r="5"/><text x="'+pt.px+'" y="'+r1(pt.py-9)+'">'+esc(pt.m.n)+
            '</text></g>');
   });
   p.push('<g class="sc-dots">'+d.join('')+'</g></svg>');
   box.innerHTML=p.join('');
   var svg=box.querySelector('svg');
   placeLabels(svg);
   wire(svg,W,H);
   buildTable(sp);
 }

 function wire(svg,W,H){
   function nearest(e){
     var r=svg.getBoundingClientRect();
     if(!r.width)return -1;
     var k=W/r.width,px=(e.clientX-r.left)*k,py=(e.clientY-r.top)*k,
         best=-1,bd=1e9,i,dx,dy,dd;
     for(i=0;i<pts.length;i++){
       dx=pts[i].px-px;
       dy=pts[i].py-py;
       dd=dx*dx+dy*dy;
       if(dd<bd){bd=dd;best=i;}
     }
     return bd<=196?best:-1;
   }
   function show(i,e){
     hot=i;
     var gs=box.querySelectorAll('.sc-pt');
     for(var j=0;j<gs.length;j++)gs[j].classList.toggle('hot',j===i);
     var pt=pts[i];
     tip.innerHTML='<b>'+esc(pt.m.n)+'</b><br>'+esc(label(specY()))+': '+esc(fmt(specY(),pt.y))+
       '<br>'+esc(label(specX()))+': '+esc(fmt(specX(),pt.x));
     tip.classList.add('on');
     var r=wrap.getBoundingClientRect();
     var tw=tip.offsetWidth||170,th=tip.offsetHeight||46,
         tx=e.clientX-r.left+14,ty=e.clientY-r.top+14;
     if(tx+tw>r.width-6)tx=e.clientX-r.left-tw-14;
     if(ty+th>r.height-6)ty=e.clientY-r.top-th-14;
     tip.style.left=Math.max(4,tx)+'px';
     tip.style.top=Math.max(4,ty)+'px';
   }
   svg.addEventListener('pointermove',function(e){
     var i=nearest(e);
     if(i<0){hideTip();return;}
     show(i,e);
   });
   svg.addEventListener('pointerdown',function(e){
     var i=nearest(e);if(i>=0)show(i,e);
   });
   svg.addEventListener('pointerleave',hideTip);
   svg.addEventListener('click',function(){
     if(hot>=0&&pts[hot]&&pts[hot].m.u)window.open(pts[hot].m.u,'_blank','noopener');
   });
   svg.addEventListener('keydown',function(e){
     if(e.key==='Escape')hideTip();
   });
 }

 function specX(){var s=spec();return s.x;}
 function specY(){var s=spec();return s.y;}

 function buildTable(sp){
   if(!tbl)return;
   var rows=pts.slice().sort(function(a,b){return b.y-a.y;}),h=[];
   h.push('<div class="tbl-wrap" style="margin-top:12px"><table class="tbl"><thead><tr>'+
          '<th>Model</th><th class="num">'+esc(title(sp.y))+'</th>'+
          '<th class="num">'+esc(title(sp.x))+'</th></tr></thead><tbody>');
   rows.forEach(function(pt){
     h.push('<tr><td class="name"><a href="'+esc(pt.m.u)+'" target="_blank" rel="noopener">'+
            esc(pt.m.n)+'</a></td><td class="num">'+esc(fmt(sp.y,pt.y))+
            '</td><td class="num">'+esc(fmt(sp.x,pt.x))+'</td></tr>');
   });
   h.push('</tbody></table></div>');
   tbl.innerHTML=h.join('');
 }

 if(tblBtn&&tbl){
   tblBtn.addEventListener('click',function(){
     var open=tbl.hidden;
     tbl.hidden=!open;
     tblBtn.setAttribute('aria-expanded',open?'true':'false');
     tblBtn.textContent=open?'Hide table':'Show as table';
   });
 }
 tabs.forEach(function(b){
   b.addEventListener('click',function(){
     mode=b.getAttribute('data-mode');
     tabs.forEach(function(o){o.setAttribute('aria-selected',o===b?'true':'false');});
     if(custom)custom.hidden=(mode!=='custom');
     try{if(history.replaceState)history.replaceState(null,'','#'+mode);}catch(e){}
     hideTip();
     render();
   });
 });
 [selX,selY].forEach(function(s){
   if(s)s.addEventListener('change',function(){hideTip();render();});
 });
 /* Deep link: scatter.html#kv opens that preset, so a chart can be shared. */
 (function(){
   var h=(location.hash||'').slice(1),i,found=false;
   if(!h)return;
   for(i=0;i<SC.presets.length;i++){if(SC.presets[i].id===h)found=true;}
   if(h!=='custom'&&!found)return;
   mode=h;
   tabs.forEach(function(b){
     b.setAttribute('aria-selected',b.getAttribute('data-mode')===h?'true':'false');
   });
   if(custom)custom.hidden=(h!=='custom');
 })();
 window.TL_APPLY=render;
 var rt=null;
 window.addEventListener('resize',function(){
   clearTimeout(rt);rt=setTimeout(function(){hideTip();render();},150);
 });
 render();
 /* First paint can measure a pre-layout width (fonts, scrollbar); re-render once
    if the real width differs, so label collisions are judged on the final box. */
 requestAnimationFrame(function(){
   var w=box.clientWidth||760;
   if(Math.abs(w-lastW)>8)render();
 });
})();
"""


def page_about():
    body = f"""
<h1>About &amp; method</h1>
<p class="lede">Tiny League tracks benchmark scores for recent small open-weight models,
so they can be compared without re-reading forty model cards.</p>

<h2>What qualifies</h2>
<ul>
  <li><b>1.5B–285B</b> total parameters.</li>
  <li><b>Released in the last 5 months</b> — the roster only covers current models.</li>
  <li><b>Official weights only:</b> no quantized, finetuned, merged or uncensored re-uploads.</li>
  <li><b>Current version preferred</b>, though closely-timed releases may both appear.</li>
  <li><b>At least 5 benchmarks</b> shared with the rest of the roster.</li>
</ul>

<h2>Where scores come from</h2>
<p>Every score carries a source. Priority: the model's <b>official card or tech report</b>
first, then <b>Artificial Analysis</b> or the vendor blog to fill gaps, then
<b>leaderboards and official X posts</b> to corroborate. Missing is missing — values are
never estimated, and disagreements between sources are logged rather than silently resolved.</p>

<h2>Derived numbers</h2>
<p><b>KV @128K</b> is the cache needed to hold a 128K-token context (BF16, one sequence),
computed from each model's <code>config.json</code> and checked against the released
weights. <b>Decode</b> is an estimated single-stream speed on one RTX 4090 at 50% of its
bandwidth — a model of what the hardware can do, not a measurement.</p>

<h2>Licensing</h2>
<p>Code is MIT; the data is CC BY 4.0 — reuse it with credit. The name and logo are not
licensed, so forks should use their own identity.</p>

"""
    return layout("About — Tiny League", body, "about", desc="Criteria, sources and method.", path="about.html")


# --------------------------------------------------------------------------

def build_feed():
    """RSS 2.0 of the changelog. One item per entry, dated at 00:00 UTC."""
    entries = gh.load("changelog.json")
    items = []
    newest = None
    for e in entries:
        text = (e.get("text") or "").strip()
        # the changelog writes "Sept"; strptime only knows "Sep"
        raw = str(e.get("date") or "").replace("Sept", "Sep")
        try:
            dt = datetime.datetime.strptime(raw, "%d %b %Y")
        except (ValueError, TypeError):
            print("warn: skipping changelog entry with unparseable date: %r" % e.get("date"))
            continue
        if not text:
            continue
        newest = newest or dt
        items.append(
            "  <item>\n"
            "    <title>%s</title>\n"
            "    <link>%s#changes</link>\n"
            '    <guid isPermaLink="false">tinyleague:%s</guid>\n'
            "    <pubDate>%s</pubDate>\n"
            "    <description>%s</description>\n"
            "  </item>\n"
            % (xml_escape(text), SITE, dt.date().isoformat(),
               dt.strftime("%a, %d %b %Y 00:00:00 +0000"), xml_escape(text))
        )
    build = (newest.strftime("%a, %d %b %Y 00:00:00 +0000")
             if newest else datetime.datetime.utcnow().strftime("%a, %d %b %Y %H:%M:%S +0000"))
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">\n'
        "<channel>\n"
        "  <title>Tiny League — changelog</title>\n"
        "  <link>%s</link>\n"
        "  <description>New models, benchmarks and updates: benchmark scores for recent "
        "small open-weight models.</description>\n"
        "  <language>en</language>\n"
        "  <lastBuildDate>%s</lastBuildDate>\n"
        '  <atom:link href="%sfeed.xml" rel="self" type="application/rss+xml"/>\n'
        "  <ttl>1440</ttl>\n" % (SITE, build, SITE)
        + "".join(items)
        + "</channel>\n</rss>\n"
    )


def build_og():
    """Rasterise the social card into a temp file (before out/ is wiped)."""
    import subprocess
    import tempfile
    if os.environ.get("TL_SKIP_OG") == "1":
        return None
    svg = gh.build_og_svg(MODELS, MODEL_NUMERIC, COV, len(MODELS), len(BENCHES), UPDATED_H)
    fd, tmp = tempfile.mkstemp(suffix=".png", prefix="tl-og-")
    os.close(fd)
    try:
        subprocess.run(["rsvg-convert", "-w", "1200", "-h", "630", "-o", tmp],
                       input=svg.encode("utf-8"), check=True)
        return tmp
    except FileNotFoundError:
        print("warn: rsvg-convert not found — no og.png")
    except subprocess.CalledProcessError as exc:
        print("warn: rsvg-convert failed (%s) — no og.png" % exc)
    return None


def main():
    import shutil
    og_tmp = build_og()
    if os.path.isdir(OUT):
        shutil.rmtree(OUT)
    os.makedirs(OUT, exist_ok=True)
    if og_tmp:
        dest = os.path.join(OUT, "og.png")
        shutil.move(og_tmp, dest)
        os.chmod(dest, 0o644)   # mkstemp is 0600; the web server must be able to read it
    written = []
    written.append(("index.html", write("index.html", page_home())))
    written.append(("models.html", write("models.html", page_models())))
    written.append(("benchmarks.html", write("benchmarks.html", page_benchmarks())))
    written.append(("matrix.html", write("matrix.html", page_matrix())))
    written.append(("scatter.html", write("scatter.html", page_scatter())))
    written.append(("compare.html", write("compare.html", page_compare())))
    written.append(("about.html", write("about.html", page_about())))
    n = 0
    for b in BENCHES:
        write("benchmarks/%s.html" % BENCH_SLUG[b], page_benchmark(b))
        n += 1
    print("built into %s" % OUT)
    for name, size in written:
        print("  %-20s %7d bytes" % (name, size))
    # crawler + social artefacts, same set the v1 build ships
    pages = ["index.html", "models.html", "matrix.html", "scatter.html", "benchmarks.html",
             "compare.html", "about.html"]
    pages += ["benchmarks/%s.html" % BENCH_SLUG[b] for b in BENCHES]
    write("feed.xml", build_feed())
    write("robots.txt", "User-agent: *\nAllow: /\n\nSitemap: %ssitemap.xml\n" % SITE)
    lastmod = str(scores_doc.get("generated_at") or "")[:10]
    write("sitemap.xml",
          '<?xml version="1.0" encoding="UTF-8"?>\n'
          '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
          + "".join("<url><loc>%s</loc><lastmod>%s</lastmod></url>\n"
                    % (SITE if u == "index.html" else SITE + u, lastmod)
                    for u in pages)
          + "</urlset>\n")
    write("llms.txt", f"""# Tiny League

> Benchmark scores for {len(MODELS)} recent small open-weight models (1.5B to 285B,
> official weights only, current versions), with {len(BENCHES)} benchmarks, a
> sortable scores matrix and scatter charts, and each model's derived KV-cache cost
> at 128K tokens.

Tiny League is a curated league table of benchmark scores for small open-weight
language models. Scope: 1.5B to 285B total parameters, official developer-org
weights only, current versions only. {len(MODELS)} models and {len(BENCHES)}
benchmarks as of {lastmod}.

## Sections

- {SITE}models.html: one row per model with parameters, active parameters, native
  context, license, release date and derived KV-cache size at 128K tokens.
- {SITE}matrix.html: models x benchmarks heatmap, filterable by parameter size.
- {SITE}scatter.html: scatter charts of any two metrics (benchmark score, parameters,
  KV-cache cost, decode speed), filterable by parameter size.
- {SITE}benchmarks.html: every benchmark grouped by domain, with coverage and leader.
- {SITE}benchmarks/<slug>.html: one leaderboard per benchmark.
- {SITE}compare.html: side-by-side comparison of up to five models.

## Notes

- KV @128K is derived from each model's config.json (BF16, batch 1) and verified
  against the released weights; it is not a benchmark.
- Decode speed is an estimate for one RTX 4090 at 50% of its bandwidth.
- Missing values are absent, never estimated. Versions are never pooled.
""")
    print("  %-20s %7d pages" % ("benchmarks/*", n))
    others = [b for b in BENCHES if DOMAIN_OF[b] == "Other"]
    print("  domains: " + ", ".join("%s %d" % (d, len(BY_DOMAIN.get(d) or []))
                                    for d in DOMAIN_ORDER if BY_DOMAIN.get(d)))
    if others:
        print("  unclassified: " + ", ".join(others))


if __name__ == "__main__":
    main()
