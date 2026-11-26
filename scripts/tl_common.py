"""Shared helpers for the Tiny League build.

Extracted from the retired v1 single-page generator: data loading, formatting,
the per-model label helpers, the heatmap colour ramp and the social card.
Imported by scripts/build_v2.py; nothing in here renders a page.
"""
import html
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
WEB = os.path.join(ROOT, "scripts", "web")

SITE_URL = "https://tinyleague.org/"
GITHUB_REPO = "https://github.com/nunodonato/tinyleague"
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


def model_supports_vision(m):
    """True if the model takes image / visual input. Prefers the explicit
    supports_vision flag, falls back to 'vision' in modalities."""
    sv = m.get("supports_vision")
    if sv is None:
        mods = (m.get("architecture") or {}).get("modalities") or []
        sv = "vision" in mods
    return bool(sv)


def model_is_moe(m):
    """True if the model is a Mixture-of-Experts architecture."""
    atype = ((m.get("architecture") or {}).get("type") or "").lower()
    return atype == "moe"


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
