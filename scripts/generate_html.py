#!/usr/bin/env python
"""Generate a self-contained out/index.html from data/*.json.

Reads data/models.json, data/scores.json, data/sources.json, data/meta.json and
writes ONE static HTML file (no build step). The stylesheet and the front-end
logic live in scripts/web/{style.css,app.js} and are INLINED here, so the output
still has zero external dependencies. Chart.js is inlined from a local copy too.
Robust to null/missing scores and to models with few/zero benchmarks. All
dynamic text is HTML-escaped. Prints the output path + byte size.
"""
import base64
import datetime
import html
import json
import math
import os
import subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
WEB = os.path.join(ROOT, "scripts", "web")
OUT_DIR = os.path.join(ROOT, "out")
OUT_PATH = os.environ.get("TL_OUT") or os.path.join(OUT_DIR, "index.html")
# Chart.js is inlined from this local copy so the output has ZERO external
# dependencies (shareable / embeddable / works offline). If it's missing we
# fall back to the CDN so generation never breaks.
CHART_VENDOR = os.path.join(ROOT, "scripts", "vendor", "chart.umd.min.js")
CHART_CDN = "https://cdn.jsdelivr.net/npm/chart.js"

SITE_URL = "https://tinyleague.org/"

# Community invite. Must be a never-expiring link (Discord's default is 30 days).
DISCORD_INVITE = "https://discord.gg/DQ6E6eJZVJ"
DISCORD_LOGO = (
    "M20.317 4.37a19.79 19.79 0 0 0-4.885-1.515.074.074 0 0 0-.079.037"
    "c-.211.375-.445.865-.608 1.25a18.27 18.27 0 0 0-5.487 0 12.64 12.64 0 0 0-.617-1.25.077.077 0"
    " 0 0-.079-.037A19.736 19.736 0 0 0 3.677 4.37a.07.07 0 0 0-.032.027C.533 9.046-.32 13.58.099 18.058"
    "a.082.082 0 0 0 .031.056 19.9 19.9 0 0 0 5.993 3.03.078.078 0 0 0 .084-.028 14.09 14.09 0 0 0 "
    "1.226-1.994.076.076 0 0 0-.041-.106 13.107 13.107 0 0 1-1.872-.892.077.077 0 0 1-.008-.128 10.2 "
    "10.2 0 0 0 .372-.292.074.074 0 0 1 .078-.01c3.928 1.793 8.18 1.793 12.062 0a.074.074 0 0 1 "
    ".078.01c.12.098.246.198.373.292a.077.077 0 0 1-.006.127 12.299 12.299 0 0 1-1.873.892.077.077 0 "
    "0 0-.041.107c.36.698.772 1.362 1.225 1.993a.076.076 0 0 0 .084.028 19.839 19.839 0 0 0 "
    "6.002-3.03.077.077 0 0 0 .032-.054c.5-5.177-.838-9.674-3.549-13.66a.061.061 0 0 0-.031-.03zM8.02 "
    "15.33c-1.183 0-2.157-1.085-2.157-2.419 0-1.333.956-2.419 2.157-2.419 1.21 0 2.176 1.096 2.157 "
    "2.42 0 1.333-.956 2.418-2.157 2.418zm7.975 0c-1.183 0-2.157-1.085-2.157-2.419 0-1.333.955-2.419 "
    "2.157-2.419 1.21 0 2.176 1.096 2.157 2.42 0 1.333-.946 2.418-2.157 2.418z"
)

# Trophy favicon, inlined as an SVG data URI so the page stays fully self-contained
# (no separate .ico to ship). Browsers render the emoji via the system emoji font.
_FAV_SVG = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
            '<text y="0.9em" font-size="90">🏆</text></svg>')
FAVICON = "data:image/svg+xml;base64," + base64.b64encode(_FAV_SVG.encode("utf-8")).decode("ascii")

# Preset tabs for the single comparison chart: each is plotted against parameters,
# in tab order, with the KV tab and Custom following them.
# A preset is only emitted when the benchmark is reported by >= 2 models.
SCATTER_BENCHES = ["GPQA Diamond", "Terminal-Bench 2.1", "HLE", "IFBench"]

# Caption for a preset tab, shown instead of the generic hover hint. Used where a column
# is not measured the same way across the roster, so the chart needs a health warning.
SCATTER_NOTES = {
    "HLE": "HLE is reported inconsistently across the roster: some models publish the "
           "with-tools score, others the no-tools one, and the two differ by roughly 2x. "
           "Compare points with care.",
}

# A benchmark column is "core" (shown by default in the heatmap) when at least this
# many models report it. Everything else is still there behind "All".
CORE_MIN_MODELS = 5
# Curated headline benchmarks: pinned into the Core view even when their column is
# thinner than CORE_MIN_MODELS (e.g. a new version still short of 5 reporters).
CORE_ALWAYS = ("DeepSWE 1.1", "AutomationBench")
# How many comparison bar charts are drawn before the "show all" control.
DEFAULT_CHARTS = 12

# Methodology-versioned benchmarks carry the version in the benchmark NAME (see
# AGENTS.md) so that non-comparable versions become distinct columns: Terminal-Bench
# 2.0 vs 2.1, AIME 2025 vs 2026, BFCL v3 vs v4, LiveCodeBench v6 vs a date window, etc.
# A versioned column is only HIDDEN if NO version of its family is reported by enough
# models (family-aware visibility, below) — so a rare version of a well-covered family
# (e.g. "Terminal-Bench Hard", 1 model) still shows. Map each versioned name to its
# family; add a new multi-version family here when you introduce one.
BENCH_FAMILY = {
    "Terminal-Bench 2.0": "Terminal-Bench",
    "Terminal-Bench 2.1": "Terminal-Bench",
    "Terminal-Bench 4": "Terminal-Bench",
    "Terminal-Bench Hard": "Terminal-Bench",
    "Terminal-Bench Science 0.1": "Terminal-Bench",
    "VideoMME v2": "VideoMME",
    "BFCL v3": "BFCL",
    "BFCL v4": "BFCL",
    "LiveCodeBench v6": "LiveCodeBench",
    "LiveCodeBench 2408-2505": "LiveCodeBench",
    "LiveCodeBench Pro 25Q2": "LiveCodeBench Pro",
    "AIME 2025": "AIME",
    "AIME 2026": "AIME",
    "HMMT Feb 2025": "HMMT",
    "HMMT Feb 2026": "HMMT",
    "DeepSWE 1.1": "DeepSWE",
    "MRCR v2": "MRCR",
    "SWE-bench Pro v2": "SWE-bench Pro",
    # τ-bench family: τ²-bench (text: retail/airline/telecom) and τ³-bench
    # (knowledge retrieval, banking) are successive releases — keep them adjacent.
    "τ²-bench": "τ-bench",
    "τ³-bench": "τ-bench",
}


def bench_family(b):
    return BENCH_FAMILY.get(b, b)


def esc(x):
    return html.escape("" if x is None else str(x), quote=True)


def load(name):
    with open(os.path.join(DATA, name), "r", encoding="utf-8") as f:
        return json.load(f)


def web_asset(name):
    with open(os.path.join(WEB, name), "r", encoding="utf-8") as f:
        return f.read()


def fmt(v, nd=1):
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    if isinstance(v, float):
        return ("%%.%df" % nd) % v
    return str(v)


def newest_first(models):
    """Roster sorted by official release date, newest first.

    Used for both tables' default row order (a reader opening the page wants the
    latest models up top). Python's sort is stable, so models sharing a release
    date keep their roster order.
    """
    return sorted(models, key=lambda x: x.get("official_release_date") or "",
                  reverse=True)


def model_supports_vision(m):
    """True if the model takes image / visual input. Prefers the explicit
    supports_vision flag, falls back to 'vision' in modalities."""
    sv = m.get("supports_vision")
    if sv is None:
        mods = (m.get("architecture") or {}).get("modalities") or []
        sv = "vision" in mods
    return bool(sv)


def vision_badge(m):
    """Small (V) pill for vision-capable models."""
    if not model_supports_vision(m):
        return ""
    return '<span class="badge b-vision" title="Supports vision / multimodal (image) input">V</span>'


def model_is_moe(m):
    """True if the model is a Mixture-of-Experts architecture."""
    atype = ((m.get("architecture") or {}).get("type") or "").lower()
    return atype == "moe"


def moe_badge(m):
    """Small (MoE) pill for Mixture-of-Experts models."""
    if not model_is_moe(m):
        return ""
    return '<span class="badge b-moe-flag" title="Mixture-of-Experts (MoE) architecture">MoE</span>'


LICENSE_LABELS = {
    "apache-2.0": "Apache 2.0",
    "mit": "MIT",
}


def license_label(m):
    """Human-readable license for the Models table; falls back to the raw value."""
    lic = ((m.get("architecture") or {}).get("license") or "").strip()
    if not lic:
        return ""
    return LICENSE_LABELS.get(lic.lower(), lic)


def ctx_label(m):
    """Native context length, shortened (128K / 262K / 1M)."""
    n = (m.get("kv_cache") or {}).get("native_ctx")
    if not isinstance(n, (int, float)) or n <= 0:
        return "", ""
    if n >= 1_000_000:
        txt = ("%.1f" % (n / 1_000_000)).rstrip("0").rstrip(".") + "M"
    else:
        txt = "%dK" % int(round(n / 1000.0))
    return txt, "%d tokens" % int(n)


def active_label(m):
    """Active parameters for a MoE (vendor-stated); em dash for dense models."""
    if not model_is_moe(m):
        return "&mdash;", "", 0
    a = m.get("active_params_b")
    if not isinstance(a, (int, float)):
        return "&mdash;", "", 0
    return "%sB" % fmt(a), "%s active parameters" % fmt(a), a


# First heatmap column: the KV-cache footprint needed to hold a 128K-token context,
# in GiB, shown as a column of the Models table (it is a hardware cost, not a score).
REF_CTX = 131072          # 128K: the comparable "long context" reference


def kv_model_cell(m):
    """(sort_value, html, tooltip) for the Models table's KV @128K column."""
    kv = m.get("kv_cache") or {}
    gib = kv.get("gib_at_ref_ctx")
    if not isinstance(gib, (int, float)) or gib <= 0:
        return None, "&mdash;", ""
    ref_k = (kv.get("ref_ctx") or REF_CTX) // 1024
    active = m.get("active_params_b")
    bits = ["KV cache at %dK tokens: %.2f GiB (%s, batch 1, no TP)"
            % (ref_k, gib, (kv.get("dtype") or "bf16").upper())]
    rate = kv.get("kib_per_token_marginal")
    if rate is None:
        rate = gib * 1024.0 / ref_k
    bits.append("%.1f KiB per extra token" % rate)
    gnat, nctx = kv.get("gib_at_native_ctx"), kv.get("native_ctx")
    if gnat is not None and nctx:
        bits.append("%.1f GiB at its %s native context"
                    % (gnat, ("%gK" % (nctx / 1024)) if nctx < 1_000_000
                       else ("%gM" % (nctx / 1048576))))
    if isinstance(active, (int, float)) and active > 0:
        bits.append("%.3f GiB per active-B" % (gib / active))
    if kv.get("notes"):
        bits.append(kv["notes"])
    bits.append("derived from config.json" + (", verified against weights"
                                              if kv.get("verified") else ""))
    txt = ("%.1f" % gib) if gib >= 10 else ("%.2f" % gib)
    return gib, txt + " GiB", " · ".join(bits)


def _tok_fmt(tok):
    """Compact token/s text: one decimal below 10, whole numbers above."""
    return ("%.1f" % tok) if tok < 10 else ("%.0f" % tok)


def perf_fresh_cell(m):
    """(sort_value, html, tooltip) for the Models table's fresh-context decode column."""
    p = m.get("perf") or {}
    tok = p.get("decode_tok_s_fresh")
    if not isinstance(tok, (int, float)) or tok <= 0:
        return None, "&mdash;", ""
    bits = ["Estimated decode throughput with an empty context: %.1f tokens/s" % tok]
    bits.append("no KV cache to read, so only the active weights are streamed")
    bits.append("memory-bandwidth bound, BF16 weights, batch 1, one sequence")
    gpu = p.get("reference_gpu")
    if gpu:
        bits.append("reference GPU %s" % gpu)
    active = m.get("active_params_b")
    if isinstance(active, (int, float)) and active > 0:
        bits.append("%sB active weights per token" % fmt(active))
    if p.get("active_params_assumed"):
        bits.append("active parameter count unpublished; assumes all parameters "
                    "active, so this is a lower bound")
    bits.append("estimate, not a measurement")
    return tok, _tok_fmt(tok) + " tok/s", " · ".join(bits)


def perf_ref_cell(m):
    """(sort_value, html, tooltip) for the Models table's Decode @128K column."""
    p = m.get("perf") or {}
    tok = p.get("decode_tok_s_at_ref_ctx")
    if not isinstance(tok, (int, float)) or tok <= 0:
        return None, "&mdash;", ""
    ref_k = (p.get("ref_ctx") or REF_CTX) // 1024
    bits = ["Estimated decode throughput at %dK context: %.1f tokens/s" % (ref_k, tok)]
    bits.append("memory-bandwidth bound, BF16 weights, batch 1, one sequence")
    gpu = p.get("reference_gpu")
    bw = p.get("effective_bandwidth_gbs")
    peak = p.get("peak_bandwidth_gbs")
    frac = p.get("achieved_fraction")
    if gpu:
        line = "reference GPU %s" % gpu
        if isinstance(peak, (int, float)) and isinstance(frac, (int, float)):
            line += ": %.0f GB/s peak x %.0f%%" % (peak, frac * 100)
        if isinstance(bw, (int, float)) and bw > 0:
            line += " = %.0f GB/s effective" % bw
        bits.append(line)
    elif isinstance(bw, (int, float)) and bw > 0:
        bits.append("%.0f GB/s effective bandwidth" % bw)
    active = m.get("active_params_b")
    if isinstance(active, (int, float)) and active > 0:
        bits.append("%sB active weights streamed per token" % fmt(active))
    rate = (m.get("kv_cache") or {}).get("kib_per_token_marginal")
    if isinstance(rate, (int, float)):
        bits.append("%.1f KiB of KV read per token" % rate)
    kept = p.get("retained_pct")
    fresh = p.get("decode_tok_s_fresh")
    if isinstance(kept, (int, float)) and isinstance(fresh, (int, float)):
        bits.append("retains %.0f%% of its %.1f tok/s fresh-context speed"
                    % (kept, fresh))
    if p.get("active_params_assumed"):
        bits.append("active parameter count unpublished; assumes all parameters "
                    "active, so this is a lower bound")
    bits.append("estimate, not a measurement")

    kept_html = ""
    if isinstance(kept, (int, float)):
        kept_html = "<span class=\"sub\">%d%% kept</span>" % int(round(kept))
    return tok, _tok_fmt(tok) + " tok/s" + kept_html, " · ".join(bits)


# --- coverage-heatmap colour scale (per-benchmark, relative: higher = better) ---
HEAT_LOW = (238, 240, 255)   # #eef0ff (pale)  -> weakest in a column
HEAT_HIGH = (45, 49, 166)    # #2d31a6 (deep)  -> strongest in a column
HEAT_BEST_BG = "#fef0c7"     # medal          -> the best model on a benchmark
HEAT_BEST_FG = "#7a2e0e"
HEAT_BEST_LINE = "#fec84b"


def _lerp(a, b, t):
    return a + (b - a) * t


def heat_color(t):
    t = 0.0 if t < 0 else (1.0 if t > 1 else t)
    r = int(round(_lerp(HEAT_LOW[0], HEAT_HIGH[0], t)))
    g = int(round(_lerp(HEAT_LOW[1], HEAT_HIGH[1], t)))
    b = int(round(_lerp(HEAT_LOW[2], HEAT_HIGH[2], t)))
    return "rgb(%d,%d,%d)" % (r, g, b)


def _rel_lum(r, g, b):
    def ch(c):
        c = c / 255.0
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    return 0.2126 * ch(r) + 0.7152 * ch(g) + 0.0722 * ch(b)


INK_LUM = _rel_lum(16, 24, 40)


def _contrast(a, b):
    hi, lo = max(a, b), min(a, b)
    return (hi + 0.05) / (lo + 0.05)


def heat_style(t):
    """(background, text colour) for a heatmap cell at ramp position t.

    Picks white or ink, whichever clears WCAG AA (4.5:1). A middle slice of any
    single-hue ramp clears neither, so those steps are nudged darker until white
    text passes — the cell stays in the ramp, the label stays readable.
    """
    t = 0.0 if t < 0 else (1.0 if t > 1 else t)
    r = _lerp(HEAT_LOW[0], HEAT_HIGH[0], t)
    g = _lerp(HEAT_LOW[1], HEAT_HIGH[1], t)
    b = _lerp(HEAT_LOW[2], HEAT_HIGH[2], t)
    lum = _rel_lum(r, g, b)
    if _contrast(1.0, lum) >= 4.5:
        return "rgb(%d,%d,%d)" % (round(r), round(g), round(b)), "#ffffff"
    if _contrast(INK_LUM, lum) >= 4.5:
        return "rgb(%d,%d,%d)" % (round(r), round(g), round(b)), "#101828"
    k = 1.0
    while k > 0.35:
        k -= 0.02
        if _contrast(1.0, _rel_lum(r * k, g * k, b * k)) >= 4.5:
            break
    return "rgb(%d,%d,%d)" % (round(r * k), round(g * k), round(b * k)), "#ffffff"


def heat_text(t):
    """Text colour for a heatmap cell (kept for callers that only need the colour)."""
    return heat_style(t)[1]



def bench_header_html(b):
    """Header cell for a heatmap column. A versioned benchmark (one that maps to a
    different family) is shown on two lines — family on top, the version emphasized
    below — so sibling versions (Terminal-Bench 2.0 / 2.1 / Hard) stay distinct.
    Non-versioned names keep the single-line (truncated) rendering."""
    fam = BENCH_FAMILY.get(b)
    if fam and b != fam and b.startswith(fam):
        ver = b[len(fam):].strip()
        return ('<span class="bh-fam">%s</span><span class="bh-ver">%s</span>'
                % (esc(fam), esc(ver)))
    return esc(b[:16] + ("…" if len(b) > 16 else ""))


OG_W, OG_H = 1200, 630
# Benchmarks that headline the social card, in order; only those present are drawn.
OG_BENCHES = ["GPQA Diamond", "Terminal-Bench 2.1", "SWE-bench Pro"]


def _x(s):
    return html.escape(str(s), quote=True)


def _truncate(s, n):
    s = str(s)
    return s if len(s) <= n else s[: n - 1] + "…"


def build_og_svg(models, model_numeric, bench_cov, n_models, n_bench, updated_h):
    """A 1200x630 social card built from the data, rendered to out/og.png.

    Hand-authored SVG (rasterised with rsvg-convert) so the build needs no Python
    imaging dependency and the card stays in sync with the roster.
    """
    rows = []
    for b in OG_BENCHES:
        if bench_cov.get(b, 0) < 2:
            continue
        best = None
        for m in models:
            v = model_numeric.get(m["model_id"], {}).get(b)
            if not isinstance(v, (int, float)):
                continue
            if best is None or v > best[0]:
                best = (v, m.get("display_name") or m["model_id"])
        if best:
            rows.append((b, best[1], fmt(best[0])))
    # Fall back to the best-covered benchmarks if the preferred ones are absent.
    if not rows:
        for b in sorted(bench_cov, key=lambda k: -bench_cov[k])[:3]:
            best = None
            for m in models:
                v = model_numeric.get(m["model_id"], {}).get(b)
                if isinstance(v, (int, float)) and (best is None or v > best[0]):
                    best = (v, m.get("display_name") or m["model_id"])
            if best:
                rows.append((_truncate(b, 22), best[1], fmt(best[0])))

    panel_x, panel_y, panel_w = 744, 150, 384
    panel_h = 76 + 74 * max(1, len(rows))
    out = []
    out.append(
        '<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" '
        'viewBox="0 0 %d %d">' % (OG_W, OG_H, OG_W, OG_H))
    out.append(
        '<defs>'
        '<radialGradient id="glow" gradientUnits="userSpaceOnUse" cx="1040" cy="40" r="620">'
        '<stop offset="0" stop-color="#3538cd" stop-opacity=".55"/>'
        '<stop offset=".55" stop-color="#3538cd" stop-opacity=".18"/>'
        '<stop offset="1" stop-color="#3538cd" stop-opacity="0"/>'
        '</radialGradient>'
        '<linearGradient id="gold" x1="0" y1="0" x2="0" y2="1">'
        '<stop offset="0" stop-color="#fec84b"/><stop offset="1" stop-color="#b54708"/>'
        '</linearGradient>'
        '</defs>')
    out.append('<rect width="%d" height="%d" fill="#101828"/>' % (OG_W, OG_H))
    out.append('<rect width="%d" height="%d" fill="url(#glow)"/>' % (OG_W, OG_H))

    # --- trophy mark ---
    out.append('<g transform="translate(96,84)">'
               '<path d="M-15-19h30c0 14-6 21-15 24c-9-3-15-10-15-24z" fill="url(#gold)"/>'
               '<path d="M-15-15c-9 0-10 12 1 13" fill="none" stroke="#fec84b" stroke-width="3"/>'
               '<path d="M15-15c9 0 10 12-1 13" fill="none" stroke="#fec84b" stroke-width="3"/>'
               '<rect x="-3" y="5" width="6" height="8" fill="#fec84b"/>'
               '<rect x="-11" y="13" width="22" height="5" rx="2" fill="#fec84b"/>'
               '</g>')
    out.append('<text x="132" y="96" font-family="Noto Sans" font-size="30" font-weight="bold" '
               'fill="#ffffff" letter-spacing="-.4">Tiny League</text>')

    # --- headline ---
    out.append('<text x="72" y="268" font-family="Noto Sans" font-size="56" font-weight="bold" '
               'fill="#f9fafb" letter-spacing="-1.2">The league table for</text>')
    out.append('<text x="72" y="334" font-family="Noto Sans" font-size="56" font-weight="bold" '
               'fill="#f9fafb" letter-spacing="-1.2">small open models.</text>')
    out.append('<text x="74" y="388" font-family="Noto Sans" font-size="23" fill="#98a2b3">'
               '%d models · %d benchmarks · official weights only</text>'
               % (n_models, n_bench))

    # --- leaderboard panel ---
    out.append('<rect x="%d" y="%d" width="%d" height="%d" rx="20" fill="#ffffff" '
               'fill-opacity=".05" stroke="#ffffff" stroke-opacity=".12"/>'
               % (panel_x, panel_y, panel_w, panel_h))
    out.append('<text x="%d" y="%d" font-family="Noto Sans" font-size="13" font-weight="bold" '
               'fill="#98a2b3" letter-spacing="2.6">LEADERS</text>'
               % (panel_x + 30, panel_y + 44))
    for i, (bench, name, score) in enumerate(rows):
        ry = panel_y + 100 + i * 74
        if i:
            out.append('<line x1="%d" y1="%d" x2="%d" y2="%d" stroke="#ffffff" '
                       'stroke-opacity=".08"/>'
                       % (panel_x + 30, ry - 42, panel_x + panel_w - 30, ry - 42))
        out.append('<text x="%d" y="%d" font-family="Noto Sans" font-size="13.5" fill="#98a2b3">'
                   '%s</text>' % (panel_x + 30, ry - 12, _x(_truncate(bench, 26))))
        out.append('<text x="%d" y="%d" font-family="Noto Sans" font-size="21" font-weight="bold" '
                   'fill="#ffffff">%s</text>'
                   % (panel_x + 30, ry + 20, _x(_truncate(name, 21))))
        out.append('<text x="%d" y="%d" font-family="Noto Sans" font-size="30" font-weight="bold" '
                   'fill="#c7c9ff" text-anchor="end">%s</text>'
                   % (panel_x + panel_w - 30, ry + 18, _x(score)))

    # --- footer ---
    out.append('<text x="72" y="524" font-family="Noto Sans" font-size="20" fill="#667085">'
               'Updated %s · KV cache at 128K tokens</text>' % _x(updated_h))
    out.append('<text x="72" y="566" font-family="Noto Sans" font-size="24" font-weight="bold" '
               'fill="#a5a8ef">tinyleague.org</text>')
    out.append('</svg>')
    return "".join(out)


def human_date(iso):
    try:
        d = datetime.datetime.strptime(str(iso)[:10], "%Y-%m-%d")
    except (ValueError, TypeError):
        return str(iso or "")
    return "%d %s %d" % (d.day, d.strftime("%b"), d.year)


def main():
    models_doc = load("models.json")
    try:
        scores_doc = load("scores.json")
    except Exception:
        scores_doc = {"generated_at": "", "models": []}
    meta = load("meta.json")

    models = models_doc.get("models", [])
    crit = models_doc.get("criteria", {})
    recs = {r.get("model_id"): r for r in scores_doc.get("models", []) if isinstance(r, dict)}

    try:
        with open(CHART_VENDOR, "r", encoding="utf-8") as f:
            chartjs = f.read().strip()
    except Exception:
        chartjs = ""
    chart_tag = ("<script>\n%s\n</script>\n" % chartjs) if chartjs else (
        "<script src=\"%s\"></script>\n" % CHART_CDN)

    cutoff = crit.get("cutoff_date") or meta.get("cutoff_date")
    min_b = crit.get("min_params_b", meta.get("min_params_b"))
    max_b = crit.get("max_params_b", meta.get("max_params_b"))
    generated_at = scores_doc.get("generated_at", "")

    def numeric_by_bench(rec):
        out = {}
        for s in (rec or {}).get("scores", []) or []:
            if not isinstance(s, dict):
                continue
            b = s.get("benchmark")
            v = s.get("score")
            if not b or not isinstance(v, (int, float)):
                continue
            out.setdefault(b, v)
        return out

    model_numeric = {m["model_id"]: numeric_by_bench(recs.get(m["model_id"])) for m in models}

    bench_cov = {}
    for by_b in model_numeric.values():
        for b in by_b:
            bench_cov[b] = bench_cov.get(b, 0) + 1
    bench_order = sorted(bench_cov, key=lambda b: (-bench_cov[b], b))
    # Visibility: a column must be reported by >= 2 models ON THAT EXACT BENCHMARK.
    # Versions are NOT pooled — a rare version (e.g. Terminal-Bench Hard, 1 model) is
    # hidden even when a sibling version is well covered, because its values are not
    # comparable to the sibling's. Column ORDER still uses family totals (below).
    MIN_BENCH_MODELS = 2
    family_total = {}
    for b, n in bench_cov.items():
        fam = bench_family(b)
        family_total[fam] = family_total.get(fam, 0) + n
    vis_set = {b for b in bench_order if bench_cov.get(b, 0) >= MIN_BENCH_MODELS}
    # Order: families by their TOTAL data (most first), and within a family keep the
    # sibling versions adjacent (each by its own coverage). So Terminal-Bench 2.1/2.0/
    # v2/Hard sit side by side, AIME 2025/2026 together, etc.
    fam_members = {}
    for b in vis_set:
        fam_members.setdefault(bench_family(b), []).append(b)
    bench_vis = []
    for fam in sorted(fam_members, key=lambda f: (-family_total[f], f)):
        bench_vis.extend(sorted(fam_members[fam], key=lambda b: (-bench_cov[b], b)))

    # per-benchmark value range for the colour scale (relative, higher=better)
    bench_range = {}
    for b in bench_vis:
        vals = [model_numeric[m["model_id"]].get(b) for m in models]
        vals = [v for v in vals if isinstance(v, (int, float))]
        if vals:
            bench_range[b] = (min(vals), max(vals))

    n_models = len(models)
    n_bench = len(bench_vis)
    n_core = sum(1 for b in bench_vis
                 if bench_cov.get(b, 0) >= CORE_MIN_MODELS or b in CORE_ALWAYS)
    n_points = sum(len(v) for v in model_numeric.values())
    n_vision = sum(1 for m in models if model_supports_vision(m))
    n_moe = sum(1 for m in models if model_is_moe(m))
    n_charts = sum(1 for b in bench_vis if bench_cov.get(b, 0) >= 4)

    cutoff_h = human_date(cutoff)
    updated_h = human_date(generated_at)
    description = (
        "Benchmark scores for %d recent small open-weight models (%sB to %sB, official "
        "weights only, current versions, released since %s): %d benchmarks, a sortable "
        "coverage heatmap, and each model's derived KV-cache cost at 128K tokens."
        % (n_models, fmt(min_b), fmt(max_b), cutoff_h, n_bench)
    )

    og_alt = ("Tiny League — %d small open-weight models ranked on %d benchmarks, "
              "with KV-cache cost at 128K tokens" % (n_models, n_bench))

    jsonld = json.dumps({
        "@context": "https://schema.org",
        "@type": "Dataset",
        "name": "Tiny League — benchmark scores for small open-weight models",
        "description": description,
        "url": SITE_URL,
        "creator": {"@type": "Person", "name": "Nuno Donato", "url": "https://www.nunodonato.com"},
        "dateModified": generated_at,
        "isAccessibleForFree": True,
        "keywords": ["LLM", "benchmarks", "open-weight models", "small language models", "KV cache"],
        "variableMeasured": bench_vis[:20],
    }, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")

    css = web_asset("style.css")
    js = web_asset("app.js")

    # Runs in <head> before the stylesheet so the stored/system theme is on
    # <html> at first paint — no flash of the wrong palette. "auto" has no
    # stored value; explicit light/dark are persisted.
    theme_boot = (
        "(function(){var m='auto';try{m=localStorage.getItem('tl-theme')||'auto';}catch(e){}"
        "if(m!=='light'&&m!=='dark'){m='auto';}"
        "var d=m==='auto'?(window.matchMedia&&window.matchMedia('(prefers-color-scheme: dark)').matches)"
        ":(m==='dark');"
        "var r=document.documentElement;r.setAttribute('data-theme-mode',m);"
        "r.setAttribute('data-theme',d?'dark':'light');})();"
    )

    parts = []
    parts.append(
        "<!doctype html>\n<html lang=\"en\">\n<head>\n<meta charset=\"utf-8\">\n"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
        "<title>Tiny League — benchmark scores for small open-weight models</title>\n"
        "<meta name=\"description\" content=\"%s\">\n"
        "<meta name=\"robots\" content=\"index,follow\">\n"
        "<meta name=\"theme-color\" id=\"theme-color\" content=\"#fcfcfd\">\n"
        "<script>%s</script>\n"
        "<link rel=\"canonical\" href=\"%s\">\n"
        "<meta property=\"og:type\" content=\"website\">\n"
        "<meta property=\"og:site_name\" content=\"Tiny League\">\n"
        "<meta property=\"og:title\" content=\"Tiny League — small models, real benchmarks\">\n"
        "<meta property=\"og:description\" content=\"%s\">\n"
        "<meta property=\"og:url\" content=\"%s\">\n"
        "<meta property=\"og:image\" content=\"%sog.png\">\n"
        "<meta property=\"og:image:type\" content=\"image/png\">\n"
        "<meta property=\"og:image:width\" content=\"1200\">\n"
        "<meta property=\"og:image:height\" content=\"630\">\n"
        "<meta property=\"og:image:alt\" content=\"%s\">\n"
        "<meta name=\"twitter:card\" content=\"summary_large_image\">\n"
        "<meta name=\"twitter:title\" content=\"Tiny League — small models, real benchmarks\">\n"
        "<meta name=\"twitter:description\" content=\"%s\">\n"
        "<meta name=\"twitter:image\" content=\"%sog.png\">\n"
        "<meta name=\"twitter:image:alt\" content=\"%s\">\n"
        % (esc(description), theme_boot, SITE_URL, esc(description), SITE_URL,
           SITE_URL, esc(og_alt), esc(description), SITE_URL, esc(og_alt))
        + ("<link rel=\"icon\" type=\"image/svg+xml\" href=\"%s\">\n" % FAVICON)
        + "<script type=\"application/ld+json\">" + jsonld + "</script>\n"
        + chart_tag
        + "<style>\n" + css + "\n</style>\n</head>\n<body>\n"
    )

    # ---------- sticky masthead ----------
    parts.append(
        "<header class=\"site-head\"><div class=\"head-inner\">\n"
        "<a class=\"brand\" href=\"#top\"><span class=\"mark\">🏆</span><span>Tiny League</span></a>\n"
        "<nav class=\"head-nav\" id=\"head-nav\" aria-label=\"Sections\">"
        "<a href=\"#models\">Models</a>"
        "<a href=\"#heatmap\">Scores</a>"
        "<a href=\"#charts\">Scatter</a>"
        "<a href=\"#compare\">Comparisons</a>"
        "</nav>\n"
        "<div class=\"head-tools\">\n"
        "<a class=\"discord-btn\" href=\"%s\" target=\"_blank\" "
        "rel=\"noopener noreferrer\" title=\"Join the Tiny League Discord\" "
        "aria-label=\"Join the Tiny League Discord (opens in a new tab)\">"
        "<svg width=\"17\" height=\"17\" viewBox=\"0 0 24 24\" aria-hidden=\"true\">"
        "<path fill=\"currentColor\" d=\"%s\"></path></svg>"
        "<span class=\"discord-label\">Discord</span></a>\n"
        "<button type=\"button\" class=\"theme-btn\" id=\"theme-btn\" "
        "aria-label=\"Theme: auto — following your system. Click for light.\" "
        "title=\"Theme: auto — following your system. Click for light.\">\n"
        "<span class=\"ico ico-auto\" aria-hidden=\"true\">"
        "<svg width=\"15\" height=\"15\" viewBox=\"0 0 24 24\">"
        "<circle cx=\"12\" cy=\"12\" r=\"9\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"2\"></circle>"
        "<path d=\"M12 3a9 9 0 0 1 0 18z\" fill=\"currentColor\"></path></svg></span>\n"
        "<span class=\"ico ico-light\" aria-hidden=\"true\">"
        "<svg width=\"15\" height=\"15\" viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"currentColor\" "
        "stroke-width=\"2\" stroke-linecap=\"round\">"
        "<circle cx=\"12\" cy=\"12\" r=\"4\"></circle>"
        "<path d=\"M12 2v2M12 20v2M2 12h2M20 12h2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4"
        "M19.1 4.9l-1.4 1.4M6.3 17.7l-1.4 1.4\"></path></svg></span>\n"
        "<span class=\"ico ico-dark\" aria-hidden=\"true\">"
        "<svg width=\"15\" height=\"15\" viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"currentColor\" "
        "stroke-width=\"2\" stroke-linejoin=\"round\">"
        "<path d=\"M21 12.8A8.5 8.5 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z\"></path></svg></span>\n"
        "<span class=\"theme-label\"><span class=\"t t-auto\">Auto</span>"
        "<span class=\"t t-light\">Light</span><span class=\"t t-dark\">Dark</span></span>\n"
        "</button>\n"
        "<button type=\"button\" class=\"nav-toggle\" id=\"nav-toggle\" aria-expanded=\"false\" "
        "aria-controls=\"head-nav\" aria-label=\"Sections menu\">"
        "<svg width=\"20\" height=\"20\" viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"currentColor\" "
        "stroke-width=\"2\" stroke-linecap=\"round\" aria-hidden=\"true\">"
        "<path d=\"M4 7h16M4 12h16M4 17h16\"></path></svg></button>\n"
        "</div>\n"
        "</div></header>\n<main id=\"top\" class=\"wrap\">\n"
        % (DISCORD_INVITE, DISCORD_LOGO)
    )

    # ---------- hero ----------
    parts.append(
        "<section class=\"hero\">\n"
        "<h1>The league table for small open models.</h1>\n"
        "<p class=\"lede\">Benchmark scores for every recent small open-weight model worth "
        "comparing &mdash; read them side by side, see where each one is cheapest to run, "
        "and filter down to the ones that fit your hardware.</p>\n"
        "<ul class=\"criteria\">\n"
        "<li><b>%sB&ndash;%sB</b> params</li>\n"
        "<li>Official weights only</li>\n"
        "<li>No quantized or finetuned re-uploads</li>\n"
        "</ul>\n"
        "<div class=\"stats\">\n"
        "<div class=\"stat\"><span class=\"v\">%d</span><span class=\"k\">models</span></div>\n"
        "<div class=\"stat\"><span class=\"v\">%d</span><span class=\"k\">benchmarks</span></div>\n"
        "<div class=\"stat\"><span class=\"v\">%d</span><span class=\"k\">data points</span></div>\n"
        "<div class=\"stat\"><span class=\"v\">%d</span><span class=\"k\">with vision</span></div>\n"
        "</div>\n"
        % (fmt(min_b), fmt(max_b), n_models, n_bench, n_points, n_vision)
    )

    # ---------- changelog (collapsed, part of the hero) ----------
    try:
        changelog = load("changelog.json")
    except (OSError, ValueError):
        changelog = []
    if changelog:
        parts.append("<details class=\"changelog\"><summary>Changelog</summary><ul>\n")
        for entry in changelog:
            parts.append(
                "<li><span class=\"cl-date\">%s</span><span>%s</span></li>\n"
                % (esc(entry.get("date")), esc(entry.get("text")))
            )
        parts.append("</ul></details>\n")
    parts.append("</section>\n")

    # ---------- models table ----------
    parts.append(
        "<section id=\"models\">\n"
        "<h2>Models <span class=\"count\">%d</span></h2>\n"
        "<p class=\"sec-note\"><span class=\"sort-hint\">Newest first. Click any header to sort; click again to flip. </span>"
        "<b>Active</b> is the parameters a model uses per token (dense models use all of them); "
        "<b>Context</b> is its native maximum. "
        "<b>KV @128K</b> is the cache needed to hold a 128K-token context (BF16, one sequence) "
        "&mdash; derived from the model's <code>config.json</code> and verified against the "
        "released weights, so it is a hardware cost, not a benchmark. Hover for the per-token "
        "rate. <b>Decode fresh</b> and <b>Decode @128K</b> are estimated single-stream output "
        "speeds on one NVIDIA RTX 4090 at half its 1008 GB/s bandwidth &mdash; before and "
        "after the KV read at 128K, memory-bandwidth bound. The sub-line is the share of "
        "fresh-context speed retained. Both are estimates, not measurements.</p>\n"
        "<div class=\"table-scroll\">"
        "<table class=\"models-tbl sortable\">\n<thead><tr>"
        "<th data-type=\"text\">Model</th>"
        "<th class=\"num\" data-type=\"num\">Params</th>"
        "<th class=\"num\" data-type=\"num\" title=\"Active parameters per token (vendor-stated). Dense models activate all of them.\">Active</th>"
        "<th class=\"num\" data-type=\"num\" title=\"Native maximum context length\">Context</th>"
        "<th class=\"num\" data-type=\"num\" title=\"KV cache needed for a 128K-token context (GiB, BF16, batch 1) — derived from config.json\">KV @128K</th>"
        "<th class=\"num\" data-type=\"num\" title=\"Estimated single-stream decode speed with an empty context (tokens/s) on one NVIDIA RTX 4090 at 50%% of its 1008 GB/s bandwidth — weights only, no KV read\">Decode fresh</th>"
        "<th class=\"num\" data-type=\"num\" title=\"Estimated single-stream decode speed at 128K context (tokens/s) on one NVIDIA RTX 4090 at 50%% of its 1008 GB/s bandwidth — weights plus KV read; the sub-line is the share of fresh-context speed retained\">Decode @128K</th>"
        "<th data-type=\"text\">Type</th>"
        "<th data-type=\"text\">License</th>"
        "<th data-type=\"date\">Released</th>"
        "</tr></thead>\n<tbody>\n"
        % n_models
    )
    for m in newest_first(models):
        mid = m["model_id"]
        arch = m.get("architecture") or {}
        atype = (arch.get("type") or "unknown").lower()
        chip_cls = {"dense": "dense", "moe": "moe", "hybrid": "hybrid"}.get(atype, "")
        pval = fmt(m.get("param_count_b"))
        name = esc(m.get("display_name") or mid)
        vbadge = vision_badge(m)
        dv = "1" if model_supports_vision(m) else "0"
        dm = "1" if model_is_moe(m) else "0"
        lic = esc(license_label(m))
        lic_cls = "lic-other" if lic.lower() in ("other", "", "unknown") else "lic"
        act_txt, act_title, act_val = active_label(m)
        ctx_txt, ctx_title = ctx_label(m)
        kvsort, kvhtml, kvtitle = kv_model_cell(m)
        fsort, fhtml, ftitle = perf_fresh_cell(m)
        psort, phtml, ptitle = perf_ref_cell(m)
        parts.append(
            "<tr data-params=\"%s\" data-model=\"%s\" data-vision=\"%s\" data-moe=\"%s\">"
            "<td class=\"name-cell\" data-sort=\"%s\" data-label=\"Model\">"
            "<a href=\"%s\" target=\"_blank\" rel=\"noopener\" title=\"%s on Hugging Face\">%s</a>%s%s</td>"
            "<td class=\"num\" data-sort=\"%s\" data-label=\"Params\">%sB</td>"
            "<td class=\"num\" data-sort=\"%s\" data-label=\"Active\" title=\"%s\">%s</td>"
            "<td class=\"num\" data-sort=\"%s\" data-label=\"Context\" title=\"%s\">%s</td>"
            "<td class=\"num kv-cell\" data-sort=\"%s\" data-label=\"KV @128K\" title=\"%s\">%s</td>"
            "<td class=\"num perf-cell\" data-sort=\"%s\" data-label=\"Decode fresh\" title=\"%s\">%s</td>"
            "<td class=\"num perf-cell\" data-sort=\"%s\" data-label=\"Decode @128K\" title=\"%s\">%s</td>"
            "<td data-sort=\"%s\" data-label=\"Type\"><span class=\"chip %s\">%s</span></td>"
            "<td data-sort=\"%s\" data-label=\"License\"><span class=\"chip %s\">%s</span></td>"
            "<td data-sort=\"%s\" data-label=\"Released\">%s</td>"
            "</tr>\n"
            % (
                pval, esc(mid), dv, dm,
                name, esc(m.get("hf_url")), esc(mid), name, vbadge, moe_badge(m),
                pval, pval,
                ("" if not act_val else "%g" % act_val), esc(act_title), act_txt,
                ("" if not ctx_txt else "%g" % ((m.get("kv_cache") or {}).get("native_ctx") or 0)),
                esc(ctx_title), ctx_txt,
                ("" if kvsort is None else "%g" % kvsort), esc(kvtitle), kvhtml,
                ("" if fsort is None else "%g" % fsort), esc(ftitle), fhtml,
                ("" if psort is None else "%g" % psort), esc(ptitle), phtml,
                esc(atype), chip_cls, esc(atype),
                lic, lic_cls, lic,
                esc(m.get("official_release_date")), esc(m.get("official_release_date")),
            )
        )
    parts.append("</tbody>\n</table>\n</div>\n</section>\n")

    # ---------- scores heatmap ----------
    parts.append(
        "<section id=\"heatmap\">\n"
        "<h2>Scores heatmap <span class=\"count\">%d benchmarks</span></h2>\n"
        "<details class=\"method\"><summary>How to read this</summary>"
        "<p>Each cell is one model&times;benchmark score. Colour is scaled <em>within</em> a "
        "column (faint &rarr; strong = lower &rarr; higher), so each benchmark is read on its own "
        "scale; the medal cell is the best model on that benchmark. A column is only shown "
        "when at least two models report that exact benchmark &mdash; versions are never "
        "pooled. The <b>Core</b> view keeps the benchmarks with %d+ models, plus a few "
        "curated headline ones; <b>All</b> shows every column. "
        "Click a header to rank models by it.</p>"
        "</details>\n"
        % (n_bench, CORE_MIN_MODELS)
    )
    legend_swatches = "".join(
        "<span class=\"sw\" data-t=\"%s\" style=\"background:%s\"></span>" % (t, heat_color(t))
        for t in (0.0, 0.25, 0.5, 0.75, 1.0))
    parts.append(
        "<div class=\"heat-legend\"><span>lower</span>" + legend_swatches + "<span>higher</span>"
        + "<span class=\"sep\"></span>"
        + "<span class=\"sw\" data-best=\"1\" style=\"background:%s;"
          "box-shadow:inset 0 0 0 1px %s\"></span>"
        % (HEAT_BEST_BG, HEAT_BEST_LINE)
        + "<span>best on benchmark</span>"
        + "<span class=\"sep\"></span>"
        + '<span class="badge b-vision">V</span><span>vision</span>'
        + "<span class=\"sep\"></span>"
        + '<span class="badge b-moe-flag">MoE</span><span>Mixture-of-Experts</span></div>\n'
    )
    if bench_vis:
        parts.append(
            "<div class=\"heat-toolbar\">"
            "<div class=\"seg\" role=\"group\" aria-label=\"Benchmark coverage\">"
            "<button type=\"button\" data-hv=\"core\" aria-pressed=\"true\">Core %d</button>"
            "<button type=\"button\" data-hv=\"all\" aria-pressed=\"false\">All %d</button>"
            "</div>\n"
            "<label for=\"bf-input\">Find</label>"
            "<input type=\"search\" id=\"bf-input\" placeholder=\"benchmark name (swe, mmlu, aa)&#8230;\" "
            "aria-label=\"filter benchmarks\">\n"
            "<button id=\"bf-clear\" type=\"button\" class=\"ghost-btn\">clear</button>\n"
            "<span class=\"note\" id=\"bf-count\"></span>\n"
            "</div>\n"
            % (n_core, n_bench)
        )
        parts.append("<div class=\"heat-outer\">\n"
                     "<p class=\"heat-hint\">Swipe sideways for more benchmarks, "
                     "or tap \u2039 \u203a to page across.</p>\n"
                     "<div class=\"heat\">\n"
                     "<table id=\"heat-table\" class=\"sortable\"><thead><tr>"
                     "<th data-type=\"text\">Model</th>")
        for b in bench_vis:
            parts.append(
                "<th data-type=\"num\" data-bench=\"%s\" title=\"%s — %d models report this\">%s"
                "<span class=\"cov\">%d</span></th>"
                % (esc(b), esc(b), bench_cov.get(b, 0), bench_header_html(b), bench_cov.get(b, 0)))
        parts.append("</tr></thead>\n<tbody>\n")
        for m in newest_first(models):
            by_b = model_numeric.get(m["model_id"], {})
            hname = esc(m.get("display_name") or m["model_id"])
            hvbadge = vision_badge(m) + moe_badge(m)
            hvbadge = ('<span class="nmb">%s</span>' % hvbadge) if hvbadge else ""
            hdv = "1" if model_supports_vision(m) else "0"
            hm = "1" if model_is_moe(m) else "0"
            parts.append(
                "<tr data-params=\"%s\" data-model=\"%s\" data-vision=\"%s\" data-moe=\"%s\">"
                "<td class=\"name\" data-sort=\"%s\"><span class=\"nm\">%s%s</span></td>"
                % (esc(fmt(m.get("param_count_b"))), esc(m["model_id"]), hdv, hm,
                   hname, hname, hvbadge))
            for b in bench_vis:
                v = by_b.get(b)
                if v is None:
                    parts.append("<td><span class=\"cell absent\">&middot;</span></td>")
                else:
                    mn, mx = bench_range.get(b, (v, v))
                    t = 0.5 if mx == mn else (v - mn) / (mx - mn)
                    is_best = bench_cov.get(b, 0) >= 2 and v == mx
                    if is_best:
                        parts.append(
                            "<td data-sort=\"%s\"><span class=\"cell best\" title=\"Best on %s\" "
                            "style=\"background:%s;color:%s\">%s</span></td>"
                            % (esc(fmt(v)), esc(b), HEAT_BEST_BG, HEAT_BEST_FG, esc(fmt(v))))
                    else:
                        cell_bg, cell_fg = heat_style(t)
                        parts.append(
                            "<td data-sort=\"%s\"><span class=\"cell\" "
                            "style=\"background:%s;color:%s\">%s</span></td>"
                            % (esc(fmt(v)), cell_bg, cell_fg, esc(fmt(v))))
            parts.append("</tr>\n")
        parts.append("</tbody>\n</table>\n</div>\n"
                     "<button type=\"button\" class=\"heat-scroll left\" id=\"heat-left\" "
                     "aria-label=\"Scroll left\" hidden>&#8249;</button>\n"
                     "<button type=\"button\" class=\"heat-scroll right\" id=\"heat-right\" "
                     "aria-label=\"Scroll right\" hidden>&#8250;</button>\n"
                     "</div>\n")
    else:
        parts.append("<p class=\"empty\">No scores recorded yet.</p>\n")
    parts.append("</section>\n")

    # ---------- scatter ----------
    scatter_specs = [b for b in SCATTER_BENCHES if bench_cov.get(b, 0) >= 2]
    default_y = ("bench:" + scatter_specs[0]) if scatter_specs else "kvGib"

    attr_axes = [("params", "Parameters (B)"),
                 ("kvGib", "KV cache @128K (GiB)"),
                 ("perfFresh", "Decode fresh (tok/s)"),
                 ("perfRef", "Decode @128K (tok/s)"),
                 ("release", "Release date")]
    bench_axes = [("bench:" + b, b) for b in sorted(bench_vis, key=lambda s: s.lower())]

    def axis_select(sel_id, default_key):
        opts = []
        for group, items in (("Model", attr_axes), ("Benchmark", bench_axes)):
            opts.append("<optgroup label=\"%s\">" % group)
            for k, label in items:
                opts.append("<option value=\"%s\"%s>%s</option>"
                            % (esc(k), " selected" if k == default_key else "", esc(label)))
            opts.append("</optgroup>")
        return "<select id=\"%s\">%s</select>" % (sel_id, "".join(opts))

    presets = [{"id": "preset-%d" % i, "label": b, "x": "params", "y": "bench:" + b,
                "note": SCATTER_NOTES.get(b, "")}
               for i, b in enumerate(scatter_specs)]
    presets.append({
        "id": "preset-kv",
        "label": "KV @128K",
        "x": "params", "y": "kvGib",
        "note": "KV-cache size against total model size (log scale). Bottom-left is the "
                "cheap-context corner: a small model that holds a long context in little VRAM. "
                "The red glow marks the top-left corner to avoid: a high KV cost on a small model."})
    presets.append({
        "id": "preset-decode",
        "label": "Speed",
        "x": "params", "y": "perfRef",
        "note": "Estimated single-stream decode speed at 128K context against total model size "
                "(one RTX 4090 at half its 1008 GB/s bandwidth). Top-left is the sweet spot: "
                "high long-context throughput on few parameters. MoE models sit left of dense "
                "peers of the same size because only their active parameters are streamed."})
    presets.append({"id": "custom", "label": "Custom", "custom": True})

    tabs_html = "".join(
        "<button type=\"button\" class=\"chart-tab%s\" data-chart=\"%s\" role=\"tab\" "
        "aria-selected=\"%s\">%s</button>\n"
        % (" active" if i == 0 else "", esc(p["id"]),
           "true" if i == 0 else "false", esc(p["label"]))
        for i, p in enumerate(presets))

    parts.append(
        "<section id=\"charts\">\n"
        "<h2>Scatter <span class=\"count\">one chart at a time</span></h2>\n"
        "<p class=\"sec-note\">Pick a preset, or <b>Custom</b> to plot any two metrics against "
        "each other. The chart follows the filters, so it always shows the models currently "
        "in view. Hover a point for its values; click to open the model card.</p>\n"
        "<div class=\"chart-tabs\" id=\"chart-tabs\" role=\"tablist\">\n" + tabs_html + "</div>\n"
    )
    parts.append(
        "<div class=\"chart-custom\" id=\"chart-custom\" hidden>\n"
        "<label>X axis %s</label>\n<label>Y axis %s</label>\n</div>\n"
        % (axis_select("chart-x", "params"), axis_select("chart-y", default_y))
    )
    parts.append("<div id=\"chart-pane\"></div>\n</section>\n")

    # ---------- comparisons ----------
    parts.append(
        "<section id=\"compare\">\n"
        "<h2>Comparisons <span class=\"count\">%d benchmark charts</span></h2>\n"
        "<p class=\"sec-note\">A leaderboard per benchmark: the top 10 models reporting it "
        "are drawn when at least four do, within the current filters. Bars are sorted and "
        "labelled, and the leader is filled in solid.</p>\n"
        "<div class=\"cmp-actions\" id=\"cmp-actions\" hidden>"
        "<button type=\"button\" id=\"cmp-all\">Show all %d</button></div>\n"
        "<div id=\"charts-grid\" class=\"charts\"></div>\n</section>\n"
        % (n_charts, n_charts)
    )

    parts.append(
        "<footer>\n"
        "<span>Created and maintained by <a href=\"https://www.nunodonato.com\" "
        "target=\"_blank\" rel=\"noopener\">www.nunodonato.com</a>\n"
        "<span class=\"foot-dot\" aria-hidden=\"true\">&middot;</span>\n"
        "<a class=\"foot-discord\" href=\"%s\" target=\"_blank\" rel=\"noopener noreferrer\">"
        "<svg width=\"13\" height=\"13\" viewBox=\"0 0 24 24\" aria-hidden=\"true\">"
        "<path fill=\"currentColor\" d=\"%s\"></path></svg>Discord</a></span>\n"
        "<span>Updated %s &middot; %d models &middot; %d benchmarks &middot; %d scores</span>\n"
        "</footer>\n"
        % (DISCORD_INVITE, DISCORD_LOGO, esc(updated_h), n_models, n_bench, n_points)
    )

    # ---------- floating param-filter ----------
    params_list = [m.get("param_count_b") for m in models
                   if isinstance(m.get("param_count_b"), (int, float))]
    smin = int(math.floor(min(params_list))) if params_list else (
        int(min_b) if isinstance(min_b, (int, float)) else 0)
    smax = int(math.ceil(max(params_list))) if params_list else int(max_b or 190)

    # ---------- floating controls (share / models / params) ----------
    parts.append(
        "<div class=\"fabs\" id=\"fabs\">\n"
        # Share is revealed by JS only when the current view differs from the default.
        "<button id=\"share-fab\" type=\"button\" class=\"fab fab-share\" hidden "
        "title=\"Copy a link to this view\" aria-label=\"Share — copy a link to this view\">\n"
        "<svg width=\"15\" height=\"15\" viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"currentColor\" "
        "stroke-width=\"2\" stroke-linecap=\"round\" stroke-linejoin=\"round\" aria-hidden=\"true\">"
        "<path d=\"M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71\"></path>"
        "<path d=\"M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71\"></path></svg>\n"
        "<span class=\"fab-text\" id=\"share-label\">Share</span>\n"
        "</button>\n"
        "<span id=\"share-status\" class=\"sr-only\" role=\"status\" aria-live=\"polite\"></span>\n"
        "<button id=\"mf-fab\" type=\"button\" class=\"fab\" aria-expanded=\"false\" "
        "aria-controls=\"mf-panel\" title=\"Select models to compare\">\n"
        "<svg width=\"15\" height=\"15\" viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"currentColor\" "
        "stroke-width=\"2\" stroke-linecap=\"round\" stroke-linejoin=\"round\" aria-hidden=\"true\">"
        "<path d=\"M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2\"></path>"
        "<circle cx=\"9\" cy=\"7\" r=\"4\"></circle>"
        "<line x1=\"17\" y1=\"8\" x2=\"22\" y2=\"8\"></line>"
        "<line x1=\"17\" y1=\"12\" x2=\"22\" y2=\"12\"></line>"
        "<line x1=\"17\" y1=\"16\" x2=\"22\" y2=\"16\"></line></svg>\n"
        "<span class=\"fab-text\">Models <span class=\"fab-badge\" id=\"mf-badge\"></span></span>\n"
        "</button>\n"
        "<button id=\"pf-fab\" type=\"button\" class=\"fab\" aria-expanded=\"false\" "
        "aria-controls=\"pf-panel\" title=\"Filter by parameters\">\n"
        "<svg width=\"15\" height=\"15\" viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"currentColor\" "
        "stroke-width=\"2\" stroke-linecap=\"round\" stroke-linejoin=\"round\" aria-hidden=\"true\">"
        "<polygon points=\"22 3 2 3 10 12.46 10 19 14 21 14 12.46 22 3\"></polygon></svg>\n"
        "<span class=\"fab-text\">Params <span class=\"fab-badge\" id=\"pf-badge\"></span></span>\n"
        "</button>\n"
        "</div>\n"

        "<div id=\"pf-panel\" class=\"panel\" hidden role=\"dialog\" aria-label=\"Filter by parameters\">\n"
        "<div class=\"panel-head\">\n<span class=\"panel-title\">Params (B)</span>\n"
        "<button id=\"pf-close\" type=\"button\" class=\"close\" aria-label=\"Close filter\">&times;</button>\n"
        "</div>\n"
        "<div class=\"range-lbls\"><span id=\"pf-min-lbl\">%d</span><span>&ndash;</span>"
        "<span id=\"pf-max-lbl\">%d</span></div>\n"
        "<input type=\"range\" id=\"pf-min\" min=\"%d\" max=\"%d\" step=\"1\" value=\"%d\" aria-label=\"minimum parameters\">\n"
        "<input type=\"range\" id=\"pf-max\" min=\"%d\" max=\"%d\" step=\"1\" value=\"%d\" aria-label=\"maximum parameters\">\n"
        "<label class=\"check\"><input type=\"checkbox\" id=\"pf-vision\">Only models with vision</label>\n"
        "<label class=\"check\"><input type=\"checkbox\" id=\"pf-moe\">Only MoE models</label>\n"
        "<div class=\"panel-actions\">\n<button id=\"pf-reset\" type=\"button\">reset</button>\n"
        "<span class=\"note\" id=\"pf-count\"></span>\n</div>\n</div>\n"

        "<div id=\"mf-panel\" class=\"panel\" hidden role=\"dialog\" aria-label=\"Select models to compare\">\n"
        "<div class=\"panel-head\">\n<span class=\"panel-title\">Models</span>\n"
        "<button id=\"mf-close\" type=\"button\" class=\"close\" aria-label=\"Close model filter\">&times;</button>\n"
        "</div>\n"
        "<div class=\"mf-actions\">\n"
        "<button id=\"mf-all\" type=\"button\">Select all</button>\n"
        "<button id=\"mf-clear\" type=\"button\">Clear all</button>\n</div>\n"
        "<div id=\"mf-list\" class=\"mf-list\"></div>\n</div>\n"
        % (smin, smax, smin, smax, smin, smin, smax, smax)
    )

    parts.append("</main>\n")

    # ---------- embedded data + JS ----------
    models_js = []
    for m in models:
        mid = m["model_id"]
        by_b = model_numeric.get(mid, {})
        effval = (m.get("kv_cache") or {}).get("gib_at_ref_ctx")
        rel = m.get("official_release_date") or ""
        try:
            rel_ms = int(datetime.datetime.strptime(rel[:10], "%Y-%m-%d")
                         .replace(tzinfo=datetime.timezone.utc).timestamp() * 1000)
        except ValueError:
            rel_ms = None
        models_js.append({
            "id": mid,
            "name": m.get("display_name") or mid,
            "url": m.get("hf_url") or "",
            "params": m.get("param_count_b"),
            "vision": model_supports_vision(m),
            "moe": model_is_moe(m),
            "kvGib": effval,
            "perfFresh": (m.get("perf") or {}).get("decode_tok_s_fresh"),
            "perfRef": (m.get("perf") or {}).get("decode_tok_s_at_ref_ctx"),
            "released": rel_ms,
            "scores": {b: v for b, v in by_b.items() if isinstance(v, (int, float))},
        })

    axes_js = [{"k": k, "label": label, "low": (k == "kvGib")}
               for k, label in attr_axes + bench_axes]
    presets_js = [{"id": p["id"], "label": p["label"], "x": p.get("x"), "y": p.get("y"),
                   "note": p.get("note", ""), "custom": bool(p.get("custom"))}
                  for p in presets]

    # Substitute only at the assignment sites (`= __TOKEN__;`), never bare tokens:
    # app.js names its placeholders in its own header comment, and a plain replace()
    # expanded every data blob into that comment too (~34 KB of duplicated payload).
    subs = (("MODELS", json.dumps(models_js, ensure_ascii=False)),
            ("BENCHES", json.dumps(bench_vis, ensure_ascii=False)),
            ("BENCH_COV", json.dumps(bench_cov, ensure_ascii=False)),
            ("AXES", json.dumps(axes_js, ensure_ascii=False)),
            ("PRESETS", json.dumps(presets_js, ensure_ascii=False)),
            ("CORE_MIN", str(CORE_MIN_MODELS)),
            ("CORE_ALWAYS", json.dumps(list(CORE_ALWAYS), ensure_ascii=False)),
            ("DEFAULT_CHARTS", str(DEFAULT_CHARTS)))
    script_text = js
    for name, value in subs:
        site = "= __%s__;" % name
        if script_text.count(site) != 1:
            raise SystemExit("app.js: expected exactly one '%s' site, found %d"
                             % (site, script_text.count(site)))
        script_text = script_text.replace(site, "= " + value + ";")
    script_text = script_text.replace("</", "<\\/")
    parts.append("<script>\n" + script_text + "\n</script>\n")
    parts.append("</body>\n</html>\n")

    out_html = "".join(parts)

    os.makedirs(os.path.dirname(OUT_PATH) or ".", exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        f.write(out_html)

    # robots.txt + llms.txt live beside the page so crawlers and agents get a
    # machine-readable summary (the deploy copies them along with index.html).
    out_dir = os.path.dirname(OUT_PATH) or "."
    with open(os.path.join(out_dir, "robots.txt"), "w", encoding="utf-8") as f:
        f.write("User-agent: *\nAllow: /\n\nSitemap: %ssitemap.xml\n" % SITE_URL)
    with open(os.path.join(out_dir, "sitemap.xml"), "w", encoding="utf-8") as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n'
                '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
                "<url><loc>%s</loc><lastmod>%s</lastmod></url>\n</urlset>\n"
                % (SITE_URL, esc(generated_at[:10])))
    llms = (
        "# Tiny League\n\n"
        "> %s\n\n"
        "Tiny League is a curated league table of benchmark scores for small open-weight\n"
        "language models. Scope: %sB to %sB total parameters, official developer-org weights\n"
        "only (no GGUF/AWQ/FP8/GPTQ/LoRA/finetunes/merges), current versions only, released on\n"
        "or after %s. %d models and %d benchmark columns as of %s.\n\n"
        "## Sections\n\n"
        "- [Models](%s#models): one row per model with parameters, active parameters, native\n"
        "  context, license, release date and derived KV-cache size at 128K tokens.\n"
        "- [Scores heatmap](%s#heatmap): models x benchmarks, colour-scaled within each column.\n"
        "  Each cell is a score reported by the model's own card or tech report; missing values\n"
        "  are absent, never estimated.\n"
        "- [Scatter](%s#charts): one metric plotted against another.\n"
        "- [Comparisons](%s#compare): a sorted leaderboard per benchmark.\n\n"
        "## Notes\n\n"
        "- KV @128K is derived from each model's config.json (BF16, batch 1, tensor-parallel 1)\n"
        "  and verified against the released weights; it is not a benchmark.\n"
        "- Decode fresh / Decode @128K are estimated single-stream output speeds on one\n"
        "  NVIDIA RTX 4090 at 50%% of its 1008 GB/s bandwidth (memory-bandwidth bound), before\n"
        "  and after the KV read at 128K; the @128K column also shows the share retained.\n"
        "  Both are estimates, not measurements.\n"
        "- Benchmark names carry their version (e.g. Terminal-Bench 2.0 vs 2.1); versions are\n"
        "  never pooled.\n"
        % (description, fmt(min_b), fmt(max_b), cutoff_h, n_models, n_bench, updated_h,
           SITE_URL, SITE_URL, SITE_URL, SITE_URL)
    )
    with open(os.path.join(out_dir, "llms.txt"), "w", encoding="utf-8") as f:
        f.write(llms)

    # Social card. Rasterising needs rsvg-convert; without it the previously built
    # og.png is kept so a missing system tool never breaks the site build.
    og_png = os.path.join(out_dir, "og.png")
    if os.environ.get("TL_SKIP_OG") == "1":
        print("skipped og.png (TL_SKIP_OG=1)")
    else:
        svg = build_og_svg(models, model_numeric, bench_cov, n_models, n_bench, updated_h)
        try:
            subprocess.run(
                ["rsvg-convert", "-w", str(OG_W), "-h", str(OG_H), "-o", og_png],
                input=svg.encode("utf-8"), check=True)
            print("wrote %s (%d bytes)" % (og_png, os.path.getsize(og_png)))
        except FileNotFoundError:
            print("warn: rsvg-convert not found — keeping the existing og.png")
        except subprocess.CalledProcessError as exc:
            print("warn: rsvg-convert failed (%s) — keeping the existing og.png" % exc)

    print("wrote %s (%d bytes)" % (OUT_PATH, os.path.getsize(OUT_PATH)))
    print("wrote robots.txt, sitemap.xml, llms.txt")
    print("models: %d | benchmarks: %d (%d core) | scores: %d | charts: %d"
          % (n_models, n_bench, n_core, n_points, n_charts))


if __name__ == "__main__":
    main()
