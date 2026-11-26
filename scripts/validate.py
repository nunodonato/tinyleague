#!/usr/bin/env python
"""Validate Tiny League data: schemas + business rules + coverage + conflicts.

Checks
  * schema: models.json (models.schema.json), scores.json (scores.schema.json,
    score_file), every non-draft data/raw/*.json (scores.schema.json, record).
  * business rules per model (from data/meta.json + models.json criteria):
    4 <= param_count_b <= 285; official_release_date on/after cutoff and not in
    the future; is_official == true; current_version == true; model_id must not
    match a quant/finetune/merge pattern.
  * coverage: benchmark x model matrix from data/scores.json.
  * relevance: models sharing fewer than MIN_SHARED_BENCH benchmarks with the rest of
    the roster (informational — gates the add flow, does not fail the build).
  * conflicts: any non-empty conflicts[].

Prints a report and ends with a single "PASS" or "FAIL (n issues)" line.
Exit 0 on PASS, 1 otherwise.
"""
import datetime
import glob
import json
import os
import re
import sys

import jsonschema

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from merge import canon  # noqa: E402  (single source of truth for benchmark names)

ROOT = os.path.dirname(HERE)
DATA = os.path.join(ROOT, "data")
SCHEMA = os.path.join(ROOT, "schema")
RAW = os.path.join(DATA, "raw")

QUANT_RE = re.compile(
    r"gguf|awq|fp8|fp4|gptq|bnb|torchao|da8w8|lora|finetune|merge"
    r"|abliterat|oblit|uncensored",
    re.IGNORECASE,
)

# A model must contribute at least this many benchmarks that another model also reports,
# i.e. land in comparably populated columns. Below it, the add flow asks the user first.
MIN_SHARED_BENCH = 5


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def validate_against(doc, schema, label, issues):
    try:
        jsonschema.validate(doc, schema)
        return True
    except jsonschema.ValidationError as exc:
        issues.append("schema: %s -> %s (at %s)" % (label, exc.message, list(exc.absolute_path)))
        return False
    except jsonschema.SchemaError as exc:
        issues.append("schema: %s -> bad schema: %s" % (label, exc.message))
        return False


def parse_date(s):
    try:
        return datetime.date.fromisoformat(str(s)[:10])
    except Exception:
        return None


def fmt(v):
    if v is None:
        return "."
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v)


def main():
    issues = []
    models_schema = load_json(os.path.join(SCHEMA, "models.schema.json"))
    scores_schema = load_json(os.path.join(SCHEMA, "scores.schema.json"))

    models_path = os.path.join(DATA, "models.json")
    scores_path = os.path.join(DATA, "scores.json")

    models_doc = None
    try:
        models_doc = load_json(models_path)
    except Exception as exc:
        issues.append("cannot read models.json: %s" % exc)

    scores_doc = None
    try:
        scores_doc = load_json(scores_path)
    except Exception as exc:
        issues.append("cannot read scores.json: %s (run scripts/merge.py first)" % exc)

    meta = load_json(os.path.join(DATA, "meta.json"))
    crit = (models_doc or {}).get("criteria", {})
    cutoff = crit.get("cutoff_date") or meta.get("cutoff_date")
    min_b = crit.get("min_params_b", meta.get("min_params_b", 4))
    max_b = crit.get("max_params_b", meta.get("max_params_b", 285))
    param_exemptions = set(
        list(crit.get("param_exemptions", [])) + list(meta.get("param_exemptions", []))
    )
    age_exemptions = set(
        list(crit.get("age_exemptions", [])) + list(meta.get("age_exemptions", []))
    )
    today = datetime.date.today()
    cutoff_date = parse_date(cutoff)

    print("== Tiny League validation ==")

    # --- schema checks ---
    if models_doc is not None:
        validate_against(models_doc, models_schema, "models.json", issues)
    if scores_doc is not None:
        validate_against(scores_doc, scores_schema, "scores.json", issues)

    # changelog.json is display-only; validate it only when present
    changelog_present = False
    changelog_path = os.path.join(DATA, "changelog.json")
    if os.path.exists(changelog_path):
        changelog_present = True
        try:
            changelog_schema = load_json(os.path.join(SCHEMA, "changelog.schema.json"))
            validate_against(load_json(changelog_path), changelog_schema, "changelog.json", issues)
        except Exception as exc:
            issues.append("changelog.json: %s" % exc)

    raw_checked = 0
    for path in sorted(glob.glob(os.path.join(RAW, "*.json"))):
        base = os.path.basename(path)
        if base.endswith(".draft.json") or base == "roster.json":
            continue
        raw_checked += 1
        try:
            doc = load_json(path)
        except Exception as exc:
            issues.append("schema: %s -> JSON parse error %s" % (base, exc))
            continue
        validate_against(doc, scores_schema, base, issues)
        # one entry per canonical benchmark (merge keeps the max and auto-logs a
        # conflict, but the record itself should not carry duplicate columns)
        seen_bench = {}
        for s in (doc.get("scores") or []):
            b = canon(s.get("benchmark")) if isinstance(s, dict) else None
            if not b:
                continue
            seen_bench[b] = seen_bench.get(b, 0) + 1
        dups = sorted(b for b, n in seen_bench.items() if n > 1)
        if dups:
            issues.append("dupes: %s reports duplicate benchmark(s): %s" % (base, ", ".join(dups)))

    # --- business rules per model ---
    models = (models_doc or {}).get("models", [])
    biz_issues = []
    for m in models:
        mid = m.get("model_id", "?")
        pc = m.get("param_count_b")
        if mid not in param_exemptions and (
            not isinstance(pc, (int, float)) or pc < min_b or pc > max_b
        ):
            biz_issues.append("%s: param_count_b=%r outside [%s, %s]" % (mid, pc, min_b, max_b))
        rd = m.get("official_release_date")
        rdate = parse_date(rd)
        if rdate is None:
            biz_issues.append("%s: invalid official_release_date %r" % (mid, rd))
        else:
            if cutoff_date is not None and rdate < cutoff_date and mid not in age_exemptions:
                biz_issues.append("%s: release %s before cutoff %s" % (mid, rd, cutoff))
            if rdate > today:
                biz_issues.append("%s: release %s after today %s" % (mid, rd, today))
        if m.get("is_official") is not True:
            biz_issues.append("%s: is_official is not true" % mid)
        if m.get("current_version") is not True:
            biz_issues.append("%s: current_version is not true" % mid)
        if QUANT_RE.search(mid):
            biz_issues.append("%s: model_id matches quant/finetune/merge pattern" % mid)
    issues.extend("rule: " + b for b in biz_issues)

    # --- derived blocks (scripts/kv_cache.py, scripts/perf.py) ---
    # Both are computed from models.json inputs, never scraped, so a missing block
    # always means a derivation script was not re-run after a model was added.
    derived_issues = []
    for m in models:
        mid = m.get("model_id", "?")
        kv = m.get("kv_cache") or {}
        if not isinstance(kv.get("gib_at_ref_ctx"), (int, float)):
            derived_issues.append("%s: missing kv_cache — run scripts/kv_cache.py --verify --apply" % mid)
        perf = m.get("perf") or {}
        if not isinstance(perf.get("decode_tok_s_fresh"), (int, float)):
            derived_issues.append("%s: missing perf (decode speed) — run scripts/perf.py --apply" % mid)
    issues.extend("derived: " + d for d in derived_issues)

    # --- coverage matrix from scores.json ---
    records = (scores_doc or {}).get("models", [])
    rec_by_id = {r.get("model_id"): r for r in records if isinstance(r, dict)}

    def numeric_scores(rec):
        out = {}
        for s in (rec or {}).get("scores", []) or []:
            if not isinstance(s, dict):
                continue
            b = s.get("benchmark")
            v = s.get("score")
            if not b or not isinstance(v, (int, float)):
                continue
            if b not in out:
                out[b] = v
        return out

    all_numeric = {}  # model_id -> {bench: value}
    for r in records:
        mid = r.get("model_id")
        all_numeric[mid] = numeric_scores(r)

    bench_coverage = {}  # bench -> count of models with a numeric score
    for mid, by_bench in all_numeric.items():
        for b in by_bench:
            bench_coverage[b] = bench_coverage.get(b, 0) + 1

    benches = sorted(bench_coverage, key=lambda b: (-bench_coverage[b], b))

    print("\n[models] %d models in models.json; %d score records in scores.json"
          % (len(models), len(records)))
    print("[schemas] models.json, scores.json, %s%d raw record(s) checked"
          % ("changelog.json, " if changelog_present else "", raw_checked))
    print("[rules] %d violation(s)" % len(biz_issues))
    for b in biz_issues:
        print("   - " + b)
    print("[derived] %d model(s) missing kv_cache/perf" % len(derived_issues))
    for d in derived_issues:
        print("   - " + d)

    print("\n[coverage] %d distinct benchmarks" % len(benches))
    print("  per-benchmark model coverage:")
    for b in benches:
        print("   %2d  %s" % (bench_coverage[b], b))

    # compact matrix over shared benchmarks (>=2 models)
    shared = [b for b in benches if bench_coverage[b] >= 2]
    model_rows = models  # keep roster order
    if shared:
        short = [ (m.get("display_name") or m.get("model_id"))[:30] for m in model_rows ]
        w = 34
        header = " " * w + "".join(("%-14s" % b[:14]) for b in shared)
        print("\n[coverage] matrix (shared benchmarks, >=2 models; value or '.'):")
        print(header)
        for m, row_name in zip(model_rows, short):
            by_bench = all_numeric.get(m.get("model_id"), {})
            cells = "".join(("%-14s" % fmt(by_bench.get(b))) for b in shared)
            print(("%-34s" % (row_name[:33])) + cells)
    else:
        print("\n[coverage] matrix: no benchmark reported by >=2 models yet")

    zero = [m.get("model_id") for m in model_rows if not all_numeric.get(m.get("model_id"))]
    print("\n[coverage] models with 0 numeric scores (%d):" % len(zero))
    for mid in zero:
        print("   - %s" % mid)

    # --- relevance: how many roster benchmarks does each model actually contribute to ---
    # A model that reports fewer than MIN_SHARED_BENCH benchmarks already in the roster
    # adds little comparable information; the add flow must ask the user before keeping it.
    thin = []
    for m in model_rows:
        mid = m.get("model_id")
        shared_hits = [b for b in all_numeric.get(mid, {}) if bench_coverage.get(b, 0) >= 2]
        if len(shared_hits) < MIN_SHARED_BENCH:
            thin.append((mid, len(shared_hits), len(all_numeric.get(mid, {}))))
    print("\n[relevance] models sharing <%d existing benchmarks (%d):"
          % (MIN_SHARED_BENCH, len(thin)))
    if not thin:
        print("   (none)")
    for mid, shared_n, own_n in thin:
        print("   - %s: %d shared of %d reported — below the bar; confirm before adding"
              % (mid, shared_n, own_n))

    # --- conflicts ---
    conflict_count = 0
    print("\n[conflicts]")
    for r in records:
        confs = (r or {}).get("conflicts") or []
        for c in confs:
            conflict_count += 1
            b = c.get("benchmark", "?")
            vals = ", ".join(
                "%s=%s" % (v.get("source"), v.get("score")) for v in (c.get("values") or [])
            )
            print("   - %s / %s: %s | %s" % (
                r.get("model_id"), b, vals, (c.get("resolution") or "").strip()))
    if conflict_count == 0:
        print("   (none)")
    else:
        print("   %d conflict(s) logged (informational; primary value kept, not counted as issues)"
              % conflict_count)

    # --- final line ---
    print()
    if issues:
        print("FAIL (%d issues)" % len(issues))
        for i in issues:
            print("   ! " + i)
        sys.exit(1)
    print("PASS")
    sys.exit(0)


if __name__ == "__main__":
    main()
