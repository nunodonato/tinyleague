#!/usr/bin/env python
"""Merge per-model score records (data/raw/*.json) into data/scores.json.

Reads data/models.json (the roster) and every data/raw/*.json that is NOT a
*.draft.json artifact and NOT roster.json. Each raw file is a score_record
{model_id, scores:[...], gaps:[...], conflicts:[...], retrieved_at}.

Writes data/scores.json (score_file form) validated by schema/scores.schema.json:
    {"generated_at": <now>, "models": [one score_record per model]}

Every model in data/models.json is included (empty record if not yet researched)
so coverage can show gaps. Raw files whose model_id is not in models.json are
dropped. Partial / half-written / invalid files are skipped gracefully (research
subagents write concurrently), falling back to an empty record.

Dedupe policy: a record must report each canonical benchmark once. If it doesn't
(several reasoning levels / harnesses under one name), the HIGHEST numeric score
is kept and the disagreement is appended to the record's conflicts automatically.
"""
import glob
import json
import os
import time
import datetime

import jsonschema

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
RAW = os.path.join(DATA, "raw")
SCHEMA = os.path.join(ROOT, "schema", "scores.schema.json")


def now_iso():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


# Conservative canonicalization: unambiguous spelling variants of the SAME
# benchmark are merged (case / punctuation / word-order only). Genuinely
# different benchmarks or versioned/suffixed variants (e.g. OSWorld vs
# OSWorld-Verified, MRCR vs MRCR v2) are intentionally left distinct.
CANON_BENCH = {
    "GPQA": "GPQA Diamond",
    "MATH-Vision": "MathVision",
    "HMMT 2026 Feb": "HMMT Feb 2026",
    "NL2Repo": "NL2Repo-Bench",
    "BIRD": "BirdBench",
    "BIRD-SQL": "BirdBench",
    "IMO-AnswerBench": "IMO AnswerBench",
    "IMOAnswerBench": "IMO AnswerBench",
    "Codeforces": "Codeforces ELO",
    "CVBench2D": "CV-Bench-2D",
    "Claw-Eval": "ClawEval",
    "MMLU-ProX lite (IBM)": "MMLU-ProX lite",
    # --- τ-bench family. Cards spell these many ways (Greek τ or the ASCII
    #     "tau", with the version as a superscript digit, a plain digit, or
    #     "Tau2"/"Tau3"), often with a domain suffix. Normalize the NAME; the
    #     domain/harness always goes in subtask.
    "Tau2": "τ²-bench",
    "Tau²": "τ²-bench",
    "tau2": "τ²-bench",
    "tau²": "τ²-bench",
    "τ2-bench": "τ²-bench",
    "τ²-bench": "τ²-bench",
    "τ-2-bench": "τ²-bench",
    "tau-2-bench": "τ²-bench",
    "tau2-bench": "τ²-bench",
    "τ² bench": "τ²-bench",
    "Tau2-Bench": "τ²-bench",
    "Tau2 (average over 3)": "τ²-bench",
    "τ²-Bench Telecom": "τ²-bench",
    "τ²-Bench Retail": "τ²-bench",
    "τ²-Bench Airline": "τ²-bench",
    "Tau2 Telecom": "τ²-bench",
    "Tau2 Retail": "τ²-bench",
    "Tau2 Airline": "τ²-bench",
    "Tau3-bench": "τ³-bench",
    "Tau3": "τ³-bench",
    "tau3": "τ³-bench",
    "tau³": "τ³-bench",
    "tau3-bench": "τ³-bench",
    "tau³-bench": "τ³-bench",
    "τ3-bench": "τ³-bench",
    "τ³-bench": "τ³-bench",
    "τ³ bench": "τ³-bench",
    "Tau3 Banking": "τ³-bench",
    "Tau3-Banking": "τ³-bench",
    "tau3-Banking": "τ³-bench",
    "tau3-bench Banking": "τ³-bench",
    "Tau3-bench Banking": "τ³-bench",
    "τ³-Bench Banking": "τ³-bench",
    "τ³-Banking": "τ³-bench",
    "τ³-bench (Banking)": "τ³-bench",
    "τ³-bench (AVG)": "τ³-bench",
    "Tau3-bench (Banking)": "τ³-bench",
    "Tau3-bench (AVG)": "τ³-bench",
    "Video MME": "VideoMME",
    # --- versioned benchmark names: fold card spelling variants onto the canonical
    #     versioned column so a single version does not fragment into several columns.
    #     (version goes in the NAME — see AGENTS.md; the version itself is never rewritten)
    "Terminal-Bench v2.1": "Terminal-Bench 2.1",
    "Terminal-Bench v2.0": "Terminal-Bench 2.0",
    "Terminal-Bench v2": "Terminal-Bench 2.0",
    "BFCL-V4": "BFCL v4",
    "BFCLv4": "BFCL v4",
    "BFCL (v4)": "BFCL v4",
    "BFCL-V3": "BFCL v3",
    "BFCLv3": "BFCL v3",
    "BFCL (v3)": "BFCL v3",
    "AIME25": "AIME 2025",
    "AIME26": "AIME 2026",
    "HMMT Feb25": "HMMT Feb 2025",
    "HMMT-Feb26": "HMMT Feb 2026",
    "HMMT-Feb-2026": "HMMT Feb 2026",
    "LiveCodeBench-V6": "LiveCodeBench v6",
    "DeepSWE-1.1": "DeepSWE 1.1",
    "MMMU-Pro": "MMMU Pro",
    "Charxiv Reasoning": "CharXiv",
    "OCRBenchV2": "OCRBench 2",
    "OCRBench_v2": "OCRBench 2",
    "OCRBench v2": "OCRBench 2",
    "Video-MME": "VideoMME",
    "LiveCodeBench-v6": "LiveCodeBench v6",
    "OCR_Reasoning": "OCR-Reasoning",
    "MMlongBench Doc": "MMLongBench-Doc",
    "Video-MME v2": "VideoMME v2",
    "Terminal Bench 4": "Terminal-Bench 4",
    "Terminal-Bench v4": "Terminal-Bench 4",
    "Terminal-Bench 4.0": "Terminal-Bench 4",  # AA spells the same release '4.0'
    "GDPVal-AA-V2": "GDPval-AA-V2",
    "AA-Omniscience-Accuracy": "AA-Omniscience Accuracy",
    "AA-Omniscience-Non-Hallucination": "AA-Omniscience Non-Hallucination",
    "AA-Omniscience Non-Hallucination Rate": "AA-Omniscience Non-Hallucination",
    "DeepResearch-Bench2": "DeepResearch Bench II",
    "DeepResearch-Bench-2": "DeepResearch Bench II",
    "SWE-Bench Pro": "SWE-bench Pro",
    "Scicode": "SciCode",
    "Automation Bench": "AutomationBench",
    # v1.0.6 is the only public AutomationBench release, so the versioned spelling is
    # the same benchmark: fold it onto the bare column (the version stays in subtask).
    "AutomationBench v1.0.6": "AutomationBench",
    "SWE-Atlas-QnA": "SWE Atlas",
    "SWE Atlas - QnA": "SWE Atlas",
    "Tau3-Bench": "τ³-bench",
    # DeepSearchQA (FutureHouse) is spelled with and without the space; one column.
    "DeepSearch QA": "DeepSearchQA",
    "DeepSearch-QA": "DeepSearchQA",
    "DSQA": "DeepSearchQA",
}


def canon(bench):
    return CANON_BENCH.get(bench, bench)


def dedupe_scores(scores):
    """One entry per canonical benchmark. When a record reports the SAME benchmark
    several times (reasoning levels, harnesses, subtasks), keep the entry with the
    HIGHEST numeric score (project policy: highest reasoning level wins); a null
    score only survives when it is the only entry. Numeric disagreements are
    logged as conflicts by conflicts_from_dupes() — never silently dropped."""
    best = {}      # bench -> (has_numeric, position, score, entry)
    order = []     # [(bench_or_None, entry)] in first-seen order
    for s in scores:
        b = s.get("benchmark")
        if not b:
            order.append((None, s))
            continue
        v = s.get("score")
        numeric = isinstance(v, (int, float))
        if b not in best:
            best[b] = (numeric, len(order), v, s)
            order.append((b, s))
        else:
            had_num, pos, old_v, _old_e = best[b]
            if numeric and (not had_num or v > old_v):
                best[b] = (True, pos, v, s)
                order[pos] = (b, s)
    return [s for _b, s in order]


def conflicts_from_dupes(all_scores):
    """Build conflict entries for canonical benchmarks reported with >1 distinct
    numeric score. `all_scores` are the canonicalized score dicts of one model."""
    by_bench = {}
    for s in all_scores:
        b = s.get("benchmark")
        v = s.get("score")
        if b and isinstance(v, (int, float)):
            by_bench.setdefault(b, []).append(s)
    out = []
    for b, entries in by_bench.items():
        distinct = sorted({e["score"] for e in entries}, reverse=True)
        if len(distinct) < 2:
            continue
        kept = distinct[0]
        vals = [{"score": e["score"], "source": e.get("source", "?")} for e in entries]
        subtasks = sorted({e.get("subtask") for e in entries if e.get("subtask")})
        out.append({
            "benchmark": b,
            "values": vals,
            "resolution": ("Duplicate benchmark entries in the record; kept the highest "
                           "value (%s) per the highest-reasoning-level policy. Kept entries: %s."
                           % (kept, "; ".join(subtasks) if subtasks else "see values")),
        })
    return out


def empty_record(model_id, now):
    return {
        "model_id": model_id,
        "scores": [],
        "gaps": [],
        "conflicts": [],
        "retrieved_at": now,
    }


def main():
    models_doc = load_json(os.path.join(DATA, "models.json"))
    models = models_doc.get("models", [])
    model_ids = [m["model_id"] for m in models]
    id_set = set(model_ids)
    schema = load_json(SCHEMA)
    now = now_iso()

    records = {}  # model_id -> (mtime, record)
    dropped = []  # (basename, model_id|None, reason)

    for path in sorted(glob.glob(os.path.join(RAW, "*.json"))):
        base = os.path.basename(path)
        if base.endswith(".draft.json"):
            continue
        if base == "roster.json":
            continue
        try:
            doc = load_json(path)
        except Exception as exc:
            # Research subagents write concurrently: the file may have been caught
            # mid-write. Wait briefly and retry once before giving up.
            time.sleep(1.0)
            try:
                doc = load_json(path)
            except Exception as exc2:
                dropped.append((base, None, "JSON parse error: %s" % exc2))
                continue
        if not isinstance(doc, dict):
            dropped.append((base, None, "top-level not an object"))
            continue
        mid = doc.get("model_id")
        if not mid:
            dropped.append((base, None, "no model_id field"))
            continue
        if mid not in id_set:
            dropped.append((base, mid, "model_id not in models.json"))
            continue
        try:
            jsonschema.validate(doc, schema)
        except jsonschema.ValidationError as exc:
            dropped.append((base, mid, "schema invalid: %s" % exc.message))
            continue
        mtime = os.path.getmtime(path)
        prev = records.get(mid)
        if prev is None or mtime > prev[0]:
            records[mid] = (mtime, doc)

    out_models = []
    for mid in model_ids:
        if mid in records:
            rec = records[mid][1]
            scores = []
            for s in (rec.get("scores", []) or []):
                s = dict(s)
                if s.get("benchmark"):
                    s["benchmark"] = canon(s["benchmark"])
                scores.append(s)
            dupe_conflicts = conflicts_from_dupes(scores)
            scores = dedupe_scores(scores)
            conflicts = list(rec.get("conflicts", []) or [])
            existing = {c.get("benchmark") for c in conflicts}
            conflicts.extend(c for c in dupe_conflicts if c["benchmark"] not in existing)
            out_models.append({
                "model_id": mid,
                "scores": scores,
                "gaps": rec.get("gaps", []) or [],
                "conflicts": conflicts,
                "retrieved_at": rec.get("retrieved_at", now),
            })
        else:
            out_models.append(empty_record(mid, now))

    scores_doc = {"generated_at": now, "models": out_models}
    jsonschema.validate(scores_doc, schema)

    out_path = os.path.join(DATA, "scores.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(scores_doc, f, indent=2, ensure_ascii=False)
        f.write("\n")

    total_scores = sum(len(m["scores"]) for m in out_models)
    with_data = [m for m in out_models if m["scores"]]
    zero = [m["model_id"] for m in out_models if not m["scores"]]

    print("merged models: %d" % len(out_models))
    print("models with scores: %d" % len(with_data))
    print("total scores: %d" % total_scores)
    print("models with 0 scores (%d):" % len(zero))
    for mid in zero:
        print("   - %s" % mid)
    if dropped:
        print("dropped raw files (%d):" % len(dropped))
        for base, mid, reason in dropped:
            print("   - %s (%s): %s" % (base, mid or "-", reason))
    print("wrote %s" % os.path.relpath(out_path, ROOT))


if __name__ == "__main__":
    main()
