#!/usr/bin/env python3
"""Estimate each model's decode throughput from its architecture.

Decode is memory-bandwidth bound at batch 1: every generated token streams the
weights that participate in the forward pass plus the KV cache for the context
read so far. Both terms are already in data/models.json (``active_params_b`` and
``kv_cache``), so this is a deterministic estimate -- not a measurement and not a
benchmark. It answers "how fast would this run beside its weights on a known GPU",
which is exactly the trade-off the parameter/KV columns describe.

Formula, BF16 weights, batch 1, one sequence, no tensor parallel::

    bytes_per_token = active_B * 1e9 * 2                 (weights read)
                    + ctx * kv_kib_per_token * 1024     (KV cache read)

    decode_tok_s    = effective_bandwidth / bytes_per_token

``ctx`` is capped at the model's native context (never extrapolated). Two points
are recorded: ``fresh`` (empty context, so only weights are streamed) and
``@128K`` (weights plus the full KV read). Their ratio is the speed retained at
long context. The reference bandwidth is deliberately conservative, and the card
it belongs to is named in every record so the number is auditable rather than a
magic constant.

Usage:
    .venv/bin/python scripts/perf.py            # dry-run, prints a table
    .venv/bin/python scripts/perf.py --apply    # write perf into models.json
"""
import argparse
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
MODELS_PATH = os.path.join(ROOT, "data", "models.json")

REF_CTX = 131072            # 128K, the same reference the KV @128K column uses
WEIGHT_BYTES = 2            # BF16 weights

# One consumer reference card, so the number is reproducible rather than a
# floating constant. RTX 4090: 24 GB, 1008 GB/s HBM3 peak. 50% is a deliberately
# conservative single-stream efficiency at 128K context (attention kernels,
# launch overhead, sampling), not the ~85% a pure copy kernel reaches.
REF_GPU = "NVIDIA RTX 4090 (24 GB)"
PEAK_BW_GBS = 1008.0
ACHIEVED = 0.5
EFFECTIVE_BW_GBS = round(PEAK_BW_GBS * ACHIEVED, 1)


def _num(v):
    return isinstance(v, (int, float)) and v > 0


def estimate(m):
    """Return the perf block for one model, or None when inputs are missing."""
    active = m.get("active_params_b")
    assumed = False
    if not _num(active):
        # Vendors that publish no active count: assume it activates all params.
        # That overstates decode cost for a MoE, so flag it in the record.
        active = m.get("param_count_b")
        assumed = True
    if not _num(active):
        return None

    kv = m.get("kv_cache") or {}
    native = kv.get("native_ctx")
    ctx = min(REF_CTX, native) if _num(native) else REF_CTX

    rate = kv.get("kib_per_token_marginal")
    if not _num(rate):
        gib = kv.get("gib_at_ref_ctx")
        ref_k = kv.get("ref_ctx") or REF_CTX
        rate = (gib * 1024.0 / (ref_k / 1024.0)) if _num(gib) else 0.0

    weight_bytes = active * 1e9 * WEIGHT_BYTES
    kv_bytes = ctx * rate * 1024.0
    bandwidth = EFFECTIVE_BW_GBS * 1e9
    tok_s = bandwidth / (weight_bytes + kv_bytes)
    tok_fresh = bandwidth / weight_bytes          # context is empty, no KV to read

    return {
        "decode_tok_s_fresh": round(tok_fresh, 1),
        "decode_tok_s_at_ref_ctx": round(tok_s, 1),
        "retained_pct": round(100.0 * tok_s / tok_fresh, 1),
        "ref_ctx": int(ctx),
        "active_params_assumed": assumed,
        "weight_bytes_per_param": WEIGHT_BYTES,
        "reference_gpu": REF_GPU,
        "peak_bandwidth_gbs": PEAK_BW_GBS,
        "achieved_fraction": ACHIEVED,
        "effective_bandwidth_gbs": EFFECTIVE_BW_GBS,
        "method": "bandwidth-bound decode estimate",
    }


def main():
    ap = argparse.ArgumentParser(description="Estimate decode throughput from architecture")
    ap.add_argument("--apply", action="store_true", help="write perf into models.json")
    args = ap.parse_args()

    with open(MODELS_PATH, encoding="utf-8") as f:
        doc = json.load(f)

    rows = []
    for m in doc.get("models", []):
        p = estimate(m)
        if p is None:
            continue
        rows.append((p["decode_tok_s_fresh"], p["decode_tok_s_at_ref_ctx"],
                     p["retained_pct"], m.get("display_name") or m["model_id"],
                     m.get("active_params_b") or m.get("param_count_b"),
                     (m.get("kv_cache") or {}).get("kib_per_token_marginal"),
                     p["ref_ctx"], p["active_params_assumed"]))
        if args.apply:
            m["perf"] = p

    rows.sort(key=lambda r: r[0], reverse=True)
    print("est. decode tok/s | %s: %.0f GB/s peak x %.0f%% = %.1f GB/s effective, BF16, batch 1"
          % (REF_GPU, PEAK_BW_GBS, ACHIEVED * 100, EFFECTIVE_BW_GBS))
    print("%8s %8s %7s  %-36s %8s %10s"
          % ("fresh", "@128K", "kept", "model", "active", "KiB/tok"))
    for fresh, ref, kept, n, a, kv, ctx, assumed in rows:
        flag = "  *" if assumed else ""
        print("%8.1f %8.1f %6.0f%%  %-36s %7.1fB %10.2f%s"
              % (fresh, ref, kept, n[:36], a, kv or 0, flag))
    if any(r[5] for r in rows):
        print("\n  * active parameters unknown; assumed all parameters active (overstates cost)")

    if args.apply:
        with open(MODELS_PATH, "w", encoding="utf-8") as f:
            json.dump(doc, f, indent=2, ensure_ascii=False)
            f.write("\n")
        print("\n[applied] wrote perf into %d models" % len(rows))
    else:
        print("\n[dry-run] pass --apply to write perf into models.json")


if __name__ == "__main__":
    main()
