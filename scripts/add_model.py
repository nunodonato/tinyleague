#!/usr/bin/env python3
"""Add a single model to data/models.json.

The normal entry point for "add a model". Given a name, HF id, or URL:
    .venv/bin/python scripts/add_model.py "Qwen/Qwen3.9-32B"
    .venv/bin/python scripts/add_model.py "https://huggingface.co/org/model"
    .venv/bin/python scripts/add_model.py "gemma-4-12B"            # resolved via search

It resolves the id, fetches live HF metadata, enforces the criteria from
data/meta.json (4B-285B, released on/after cutoff, official weights), appends the
model to data/models.json and validates it against schema/models.schema.json.

It does NOT research benchmark scores — after it succeeds, run extract_card.py,
do the research step, then merge/validate/generate_html (see AGENTS.md).
"""
import argparse
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from finalize_roster import get, build  # noqa: E402

ROOT = os.path.dirname(HERE)
MODELS_PATH = os.path.join(ROOT, "data", "models.json")
META = json.load(open(os.path.join(ROOT, "data", "meta.json")))
SCHEMA_PATH = os.path.join(ROOT, "schema", "models.schema.json")

BAD_NAME = re.compile(
    r"gguf|awq|fp8|fp4|gptq|bnb|int4|int8|q4_|q5_|q8_|nf4|lora|finetune|merge|"
    r"abliterat|oblit|uncensored|torchao|da8w8|-dpo|unsloth|-base$|-base-|base-30t",
    re.I,
)


def resolve(inp, min_b, max_b):
    """Return (model_id_or_None, [candidate_list_for_disambiguation])."""
    s = inp.strip()
    if s.startswith("http"):
        s = re.sub(r"^https?://", "", s)
        s = re.sub(r"^(huggingface\.co|hf\.co)/", "", s, flags=re.I)
        s = s.split("?", 1)[0].split("#", 1)[0]           # drop query/fragment
        parts = [p for p in s.split("/") if p]
        for cut in ("resolve", "tree", "blob"):           # drop file-path suffixes
            if cut in parts:
                parts = parts[:parts.index(cut)]
        return "/".join(parts[:2]), []                    # keep only org/name
    if "/" in s:
        s = s.split("?", 1)[0].split("#", 1)[0].strip("/")
        parts = [p for p in s.split("/") if p]
        for cut in ("resolve", "tree", "blob"):
            if cut in parts:
                parts = parts[:parts.index(cut)]
        return "/".join(parts[:2]), []
    data = get("%s?search=%s&filter=text-generation&sort=likes&direction=-1&limit=30"
               % (META and "https://huggingface.co/api/models", s)) or []
    cands = []
    for m in data:
        cid = m.get("modelId") or ""
        name = cid.split("/")[-1].lower()
        if BAD_NAME.search(cid):
            continue
        cands.append((cid, m.get("likes") or 0))
    cands.sort(key=lambda x: -x[1])
    return (cands[0][0] if cands else None), [c for c, _ in cands[:5]]


def main():
    ap = argparse.ArgumentParser(description="Add a model to data/models.json")
    ap.add_argument("target", help="HF id, model name, or URL")
    ap.add_argument("--family", default=None, help="override family name")
    ap.add_argument("--note", default="", help="free-form note stored on the model")
    ap.add_argument("--must-include", action="store_true",
                    help="mark as a required family (Ornith/Ling/Spark X)")
    ap.add_argument("--force", action="store_true",
                    help="add even if a hard criterion fails (range/date/official)")
    ap.add_argument("--dry-run", action="store_true",
                    help="resolve + check + print, but do not write models.json")
    args = ap.parse_args()

    min_b = META.get("min_params_b", 4)
    max_b = META.get("max_params_b", 285)
    cutoff = META.get("cutoff_date")

    mid, cands = resolve(args.target, min_b, max_b)
    if not mid:
        print("ERROR: could not resolve %r to a model id." % args.target)
        sys.exit(2)
    if cands and args.target.strip() != mid and "/" not in args.target.strip():
        print("resolved %r -> %s" % (args.target, mid))
        print("  other candidates: %s" % ", ".join(cands))

    family = args.family or mid.split("/")[-1]
    m = build(mid, family, args.must_include, args.note)
    if not m:
        print("ERROR: HF metadata fetch failed for %s (gated/private/typo?)" % mid)
        sys.exit(2)

    _doc = json.load(open(MODELS_PATH))
    param_exemptions = set(
        list(_doc.get("criteria", {}).get("param_exemptions", []))
        + list(META.get("param_exemptions", []))
    )

    problems, warnings = [], []
    if mid not in param_exemptions and not (min_b <= m["param_count_b"] <= max_b):
        problems.append("param count %.1fB outside [%s, %s]B" %
                        (m["param_count_b"], min_b, max_b))
    elif mid in param_exemptions:
        warnings.append("param count %.1fB is below/above the usual range but is in param_exemptions"
                        % m["param_count_b"])
    if m["official_release_date"] < cutoff:
        problems.append("release date %s is before cutoff %s" %
                        (m["official_release_date"], cutoff))
    if BAD_NAME.search(mid):
        problems.append("name looks like a quant/finetune/merge (not official weights)")
    if not m.get("is_official"):
        problems.append("org looks like a re-uploader/quant namespace (not official weights)")
    if (m.get("likes") or 0) < 20:
        warnings.append("low likes (%s) — double-check this is the official repo" % m.get("likes"))
    warnings.append("confirm this is the CURRENT version (no newer same-family/size release)")

    doc = json.load(open(MODELS_PATH))
    existing = [x["model_id"] for x in doc.get("models", [])]
    if mid in existing:
        print("ALREADY PRESENT: %s is already in models.json (no change)." % mid)
        if problems:
            print("  note: %s" % "; ".join(problems))
        sys.exit(0)

    print("candidate: %s  (%.1fB %s, %s, %s likes)" %
          (mid, m["param_count_b"], m["architecture"]["type"],
           m["official_release_date"], m.get("likes")))
    for p in problems:
        print("  HARD: " + p)
    for w in warnings:
        print("  warn: " + w)

    if problems and not args.force:
        print("\nNOT added (hard criterion failed). Re-run with --force to add anyway.")
        sys.exit(1)

    if args.dry_run:
        print("\n[dry-run] would append %s to models.json (total -> %d)." %
              (mid, len(existing) + 1))
        return

    import jsonschema
    doc["models"].append(m)
    jsonschema.validate(doc, json.load(open(SCHEMA_PATH)))
    with open(MODELS_PATH, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=2, ensure_ascii=False)
        f.write("\n")
    print("\nADDED %s -> models.json (%d models total)." % (mid, len(doc["models"])))
    print("NEXT STEPS:")
    print("  1. .venv/bin/python scripts/extract_card.py %s" % mid)
    print("  2. research scores -> data/raw/%s.json  (see AGENTS.md)" % mid.replace("/", "__"))
    print("     - if the card states an active-parameter count (e.g. '35B total, 3B active'),")
    print("       add active_params_b + active_params_source to models.json BEFORE perf.py")
    print("     - relevance gate: if it shares <5 benchmarks with the roster, ASK the user")
    print("       before regenerating (validate.py prints this as [relevance])")
    print("  3. .venv/bin/python scripts/kv_cache.py --verify --apply")
    print("     .venv/bin/python scripts/perf.py --apply")
    print("     .venv/bin/python scripts/merge.py && .venv/bin/python scripts/validate.py "
          "&& .venv/bin/python scripts/generate_html.py")
    print("  4. ASK before publishing `out/` (https://tinyleague.org) — never upload "
          "without an explicit OK.")


if __name__ == "__main__":
    main()
