#!/usr/bin/env python3
"""Tiny League v2 — prototype multi-page build.

Writes into out-v2/ (never touches out/, which is what is deployed). Run:

    .venv/bin/python scripts/build_v2.py

Pages: home, models, benchmarks index, one page per benchmark, compare, about.
No model detail pages (deliberately out of scope for this pass).
"""
import json
import os
import re
import sys
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import generate_html as gh  # reuse esc/fmt/license helpers + BENCH_FAMILY

OUT = os.path.join(ROOT, "out-v2")
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
                   "cmmlu", "mmmlu", "aa-omniscience", "aa-briefcase", "multichallenge"]),
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
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
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

STYLE = gh.web_asset("style.css")
TOKENS = "\n".join(re.findall(r":root \{[^}]*\}", STYLE)) + "\n" + \
    re.search(r':root\[data-theme="dark"\] \{[^}]*\}', STYLE).group(0)
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

NAV = [("home", "Home", "index.html"), ("models", "Models", "models.html"),
       ("scores", "Scores", "matrix.html"), ("bench", "Benchmarks", "benchmarks.html"),
       ("compare", "Compare", "compare.html"), ("about", "About", "about.html")]

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


def layout(title, body, nav, depth=0, script="", desc="", path="index.html"):
    up = "../" * depth
    links = "".join(
        '<a href="%s%s"%s>%s</a>' % (up, href, ' aria-current="page"' if key == nav else "", label)
        for key, label, href in NAV
    )
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)}</title>
<meta name="description" content="{esc(desc or 'Benchmark scores for recent small open-weight models.')}">
<link rel="canonical" href="{SITE}{path}">
<meta property="og:type" content="website">
<meta property="og:site_name" content="Tiny League">
<meta property="og:title" content="{esc(title)}">
<meta property="og:description" content="{esc(desc or 'Benchmark scores for recent small open-weight models.')}">
<meta property="og:url" content="{SITE}{path}">
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
  <span>{len(MODELS)} models · {len(BENCHES)} benchmarks · <a href="{REPO}" target="_blank" rel="noopener">source</a> · <a href="{DISCORD}" target="_blank" rel="noopener">Discord</a></span>
</div></footer>
<script>{TOGGLE_JS}
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
    <p>Every model against every benchmark at a glance — the fastest way to see who leads where.</p>
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

<h2>Recent changes</h2>
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
    return layout("Scores — Tiny League", body, "scores", script=js,
                  desc="Every benchmark score in one matrix, filterable by model size.", path="matrix.html")


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

<p class="small muted">Prototype: this v2 layout is being evaluated against the current
single-page build. The heatmap and scatter charts still live on the live site.</p>
"""
    return layout("About — Tiny League", body, "about", desc="Criteria, sources and method.", path="about.html")


# --------------------------------------------------------------------------

def main():
    os.makedirs(OUT, exist_ok=True)
    written = []
    written.append(("index.html", write("index.html", page_home())))
    written.append(("models.html", write("models.html", page_models())))
    written.append(("benchmarks.html", write("benchmarks.html", page_benchmarks())))
    written.append(("matrix.html", write("matrix.html", page_matrix())))
    written.append(("compare.html", write("compare.html", page_compare())))
    written.append(("about.html", write("about.html", page_about())))
    n = 0
    for b in BENCHES:
        write("benchmarks/%s.html" % BENCH_SLUG[b], page_benchmark(b))
        n += 1
    print("v2 built into %s" % OUT)
    for name, size in written:
        print("  %-20s %7d bytes" % (name, size))
    # crawler + social artefacts, same set the v1 build ships
    pages = ["index.html", "models.html", "matrix.html", "benchmarks.html",
             "compare.html", "about.html"]
    pages += ["benchmarks/%s.html" % BENCH_SLUG[b] for b in BENCHES]
    write("robots.txt", "User-agent: *\nAllow: /\n\nSitemap: %ssitemap.xml\n" % SITE)
    lastmod = str(scores_doc.get("generated_at") or "")[:10]
    write("sitemap.xml",
          '<?xml version="1.0" encoding="UTF-8"?>\n'
          '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
          + "".join("<url><loc>%s%s</loc><lastmod>%s</lastmod></url>\n" % (SITE, u, lastmod)
                    for u in pages)
          + "</urlset>\n")
    write("llms.txt", f"""# Tiny League

> Benchmark scores for {len(MODELS)} recent small open-weight models (1.5B to 285B,
> official weights only, current versions), with {len(BENCHES)} benchmarks, a
> sortable scores matrix, and each model's derived KV-cache cost at 128K tokens.

Tiny League is a curated league table of benchmark scores for small open-weight
language models. Scope: 1.5B to 285B total parameters, official developer-org
weights only, current versions only. {len(MODELS)} models and {len(BENCHES)}
benchmarks as of {lastmod}.

## Sections

- {SITE}models.html: one row per model with parameters, active parameters, native
  context, license, release date and derived KV-cache size at 128K tokens.
- {SITE}matrix.html: models x benchmarks heatmap, filterable by parameter size.
- {SITE}benchmarks.html: every benchmark grouped by domain, with coverage and leader.
- {SITE}benchmarks/<slug>.html: one leaderboard per benchmark.
- {SITE}compare.html: side-by-side comparison of up to five models.

## Notes

- KV @128K is derived from each model's config.json (BF16, batch 1) and verified
  against the released weights; it is not a benchmark.
- Decode speed is an estimate for one RTX 4090 at 50% of its bandwidth.
- Missing values are absent, never estimated. Versions are never pooled.
""")
    # reuse the social card built by the v1 pipeline
    src_og = os.path.join(ROOT, "out", "og.png")
    if os.path.exists(src_og):
        import shutil
        shutil.copyfile(src_og, os.path.join(OUT, "og.png"))
    print("  %-20s %7d pages" % ("benchmarks/*", n))
    others = [b for b in BENCHES if DOMAIN_OF[b] == "Other"]
    print("  domains: " + ", ".join("%s %d" % (d, len(BY_DOMAIN.get(d) or []))
                                    for d in DOMAIN_ORDER if BY_DOMAIN.get(d)))
    if others:
        print("  unclassified: " + ", ".join(others))


if __name__ == "__main__":
    main()
