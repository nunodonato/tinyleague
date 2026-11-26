#!/usr/bin/env python3
"""Fetch an HF model card and reduce it to a clean, LLM-friendly benchmark draft.

Writes data/raw/<model_id>.draft.json containing:
  - html_tables:    [[cell, cell, ...], ...]   (every <table>, cells as text)
  - markdown_tables:[[cell, cell, ...], ...]   (markdown |tables|)
  - sections:       [{heading, text}]          (benchmark/eval/results sections, cleaned)
Subagents read the draft, locate the target model column, map canonical benchmark
names + scores, and fill gaps from other sources -> data/raw/<model_id>.json.
"""
import json, os, re, sys, time, argparse
import requests
from bs4 import BeautifulSoup

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from hf_auth import headers as hf_headers  # noqa: E402

BASE = "https://huggingface.co"
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
RAW = os.path.join(ROOT, "data", "raw")

def get_text(u, tries=6):
    for a in range(tries):
        try:
            r = requests.get(u, timeout=30, headers=hf_headers())
            if r.status_code == 200:
                return r.text
            if r.status_code == 429:
                time.sleep(3 * (a + 1)); continue
            if r.status_code >= 500:
                time.sleep(2 * (a + 1)); continue
            return None
        except Exception:
            time.sleep(2)
    return None

def markdown_tables(raw):
    tables, cur = [], []
    for line in raw.splitlines():
        s = line.strip()
        if s.startswith("|") and s.count("|") >= 2:
            cur.append([c.strip() for c in s.strip("|").split("|")])
        else:
            if len(cur) >= 2:
                tables.append(cur)
            cur = []
    if len(cur) >= 2:
        tables.append(cur)
    # drop separator-only rows
    out = []
    for t in tables:
        t2 = [r for r in t if not all(re.fullmatch(r":?-{2,}:?", c or "") for c in r)]
        if len(t2) >= 2:
            out.append(t2)
    return out

BENCH_HEADING = re.compile(r"benchmark|evaluat|result|leaderboard|score|performance|eval\b", re.I)

def sections(soup):
    """Collect text under headings that look like benchmark/eval sections."""
    res = []
    heads = soup.find_all(["h1", "h2", "h3", "h4"])
    for h in heads:
        if not BENCH_HEADING.search(h.get_text(" ", strip=True)):
            continue
        parts = []
        for sib in h.find_next_siblings():
            if sib.name in ("h1", "h2", "h3", "h4"):
                break
            if sib.name == "table":
                continue  # tables captured separately
            txt = sib.get_text(" ", strip=True)
            if txt:
                parts.append(txt)
        if parts:
            res.append({"heading": h.get_text(" ", strip=True), "text": " ".join(parts)[:4000]})
    return res

def extract(model_id):
    name = model_id.split("/")[-1]
    for branch in ("main", "master"):
        raw = get_text(f"{BASE}/{model_id}/raw/{branch}/README.md")
        if raw:
            break
    if not raw:
        return {"model_id": model_id, "error": "README not found"}
    soup = BeautifulSoup(raw, "lxml")
    html_tables = []
    for t in soup.find_all("table"):
        rows = []
        for tr in t.find_all("tr"):
            cells = [c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])]
            if cells:
                rows.append(cells)
        if rows:
            html_tables.append(rows)
    md_tables = markdown_tables(raw)
    return {
        "model_id": model_id,
        "display_name": name,
        "url": f"{BASE}/{model_id}",
        "retrieved_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "html_tables": html_tables[:12],
        "markdown_tables": md_tables[:12],
        "sections": sections(soup)[:20],
        "raw_chars": len(raw),
    }

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("models", nargs="*", help="model_ids; default: all from data/models.json")
    args = ap.parse_args()
    if args.models:
        mids = args.models
    else:
        mids = [m["model_id"] for m in json.load(open(os.path.join(ROOT, "data", "models.json")))["models"]]
    os.makedirs(RAW, exist_ok=True)
    for mid in mids:
        d = extract(mid)
        out = os.path.join(RAW, mid.replace("/", "__") + ".draft.json")
        json.dump(d, open(out, "w"), indent=2, ensure_ascii=False)
        ntab = len(d.get("html_tables", [])) + len(d.get("markdown_tables", []))
        print(f"  {mid}: tables={ntab} sections={len(d.get('sections', []))} -> {os.path.basename(out)}")
        time.sleep(0.6)

if __name__ == "__main__":
    main()
