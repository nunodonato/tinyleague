#!/usr/bin/env python3
"""Derive each model's KV-cache footprint from the architecture in config.json.

KV cache is not a benchmark: it is a deterministic function of the architecture
(number of KV-bearing layers, KV heads, head dim, sliding windows, MLA latents,
linear/recurrent layers). This script reads the model's real `config.json`
(pinned to a commit SHA, snapshotted under data/configs/ for audit) and computes:

  * kib_per_token_marginal - additional cache KiB per extra context token, i.e. the
    slope once sliding windows are full (compressed-attention models add < 1 unit)
  * gib_at_ref_ctx        - total cache (GiB, BF16, batch 1) at a common 128K context,
    capped at the model's native context when that is shorter (never extrapolated)
  * gib_at_native_ctx     - same at the model's own max_position_embeddings

Looped stacks (Nanbeige ``num_loops``) and multi-branch layers (LongCat) each keep
their own KV slots, so the per-layer geometry is multiplied by the number of cache
copies the architecture allocates.

Usage:
    .venv/bin/python scripts/kv_cache.py                 # dry-run, prints a table
    .venv/bin/python scripts/kv_cache.py --apply         # write into models.json
    .venv/bin/python scripts/kv_cache.py --verify        # cross-check vs safetensors
    .venv/bin/python scripts/kv_cache.py --refresh       # re-fetch config.json
    .venv/bin/python scripts/kv_cache.py --force         # recompute even if cached
    .venv/bin/python scripts/kv_cache.py --jobs 6        # parallel model fetches

`--verify` reads the safetensors index (tensor names per layer) and the first
bytes of a few shards (tensor shapes) and asserts that the attention projection
widths match the computed per-layer cache width. Anything it cannot confirm is
reported, never silently accepted: unverified models keep `"verified": false`.

The network is the slow part (config + safetensors index + shard headers), so
models are processed concurrently and an existing `kv_cache` block is reused
untouched when its pinned config revision and `formula_version` still match: a
full-roster run only fetches what actually changed. `--verify` therefore
re-checks only the models whose stored verification is missing or stale; use
`--force` (with `--verify`) to re-check every model from the weights. Bump
FORMULA_VERSION in this file whenever the geometry rules change, or cached
blocks would go stale.
"""
import argparse
import concurrent.futures
import json
import os
import re
import struct
import sys
import threading
import time
from datetime import datetime, timezone

import requests

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
MODELS_PATH = os.path.join(ROOT, "data", "models.json")
CFG_DIR = os.path.join(ROOT, "data", "configs")
RAW = "https://huggingface.co"
API = "https://huggingface.co/api/models"
REF_CTX = 131072          # 128K: the comparable "long context" reference
BYTES = 2                 # BF16 KV cache (default for every engine)
UA = {"User-Agent": "aibench-kvcache/1.0"}

# Bump whenever the geometry rules below change: a stored `kv_cache` block is
# reused verbatim only while this and the pinned config revision both match.
FORMULA_VERSION = 3

# Per-thread pooled sessions: HF redirects `resolve/` to its CDN, and reusing a
# connection skips a TCP + TLS handshake per fetch (the dominant cost of a
# full-roster run). One session per worker thread keeps the pool thread-safe.
_LOCAL = threading.local()


def _session():
    s = getattr(_LOCAL, "session", None)
    if s is None:
        s = requests.Session()
        for prefix in ("https://", "http://"):
            s.mount(prefix, requests.adapters.HTTPAdapter(
                pool_connections=8, pool_maxsize=8))
        _LOCAL.session = s
    return s


sys.path.insert(0, HERE)
from hf_auth import headers as hf_headers  # noqa: E402

# layer kinds that do NOT keep a growing KV cache
STATE_HINTS = ("linear", "delta", "conv", "mamba", "ssm", "recurrent",
               "mlp", "none", "moe", "dense")
WINDOW_HINTS = ("sliding", "window")


def get(url, **kw):
    hdrs = hf_headers(kw.pop("headers", {}) or {}, user_agent=UA["User-Agent"])
    for attempt in range(5):
        try:
            r = _session().get(url, timeout=30, headers=hdrs, **kw)
            if r.status_code in (200, 206):
                return r
            if r.status_code in (429, 500, 502, 503, 504):
                time.sleep(2 * (attempt + 1))
                continue
            return r
        except requests.RequestException:
            time.sleep(2)
    return None


# ---------------------------------------------------------------- config fetch
def fetch_config(cid, refresh=False):
    """Return (config_dict, revision). Uses a local snapshot unless --refresh."""
    os.makedirs(CFG_DIR, exist_ok=True)
    path = os.path.join(CFG_DIR, cid.replace("/", "__") + ".json")
    if os.path.exists(path) and not refresh:
        with open(path, encoding="utf-8") as f:
            snap = json.load(f)
        if snap.get("config"):
            return snap["config"], snap.get("revision")

    r = get("%s/%s?full=true" % (API, cid))
    sha = r.json().get("sha") if r and r.status_code == 200 else None

    cfg = None
    for ref in ([sha] if sha else []) + ["main", "master"]:
        rr = get("%s/%s/raw/%s/config.json" % (RAW, cid, ref))
        if rr is not None and rr.status_code == 200 and len(rr.text) < 4_000_000:
            try:
                cfg = json.loads(rr.text)
                break
            except ValueError:
                pass
    if not isinstance(cfg, dict):
        return None, sha

    with open(path, "w", encoding="utf-8") as f:
        json.dump({"model_id": cid, "revision": sha, "fetched_at":
                   datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                   "source": "%s/%s/raw/%s/config.json" % (RAW, cid, sha or "main"),
                   "config": cfg}, f, indent=2, ensure_ascii=False)
        f.write("\n")
    return cfg, sha


def snapshot_config(cid):
    """(config, revision) from the local snapshot only — never touches the network."""
    path = os.path.join(CFG_DIR, cid.replace("/", "__") + ".json")
    if not os.path.exists(path):
        return None, None
    try:
        with open(path, encoding="utf-8") as f:
            snap = json.load(f)
    except (OSError, ValueError):
        return None, None
    return snap.get("config"), snap.get("revision")


# ------------------------------------------------------------- classification
def text_cfg(cfg):
    """Unwrap composite configs (VLM wrappers, Nemotron) to the language stack."""
    for key in ("text_config", "llm_config", "language_config"):
        sub = cfg.get(key)
        if isinstance(sub, dict) and any(
                k in sub for k in ("num_hidden_layers", "layer_types",
                                   "layers_block_type", "hybrid_override_pattern")):
            return sub
    return cfg


def layer_kinds(c):
    """Return (list_of_kinds, provenance_key). Each item describes one layer."""
    for key in ("layer_types", "layers_block_type", "block_types"):
        v = c.get(key)
        if isinstance(v, list) and v and all(isinstance(x, str) for x in v):
            return list(v), key
    pat = c.get("hybrid_override_pattern")
    if isinstance(pat, str) and pat:
        # Mamba-2 style: M = mamba, * = attention, - / _ = mlp-only
        return ["attention" if ch == "*" else "mamba" if ch in "Mm" else "mlp"
                for ch in pat if ch not in "-_ "], "hybrid_override_pattern"
    pat = c.get("layers_config")
    if isinstance(pat, str) and pat:
        # Olala: V = differential TPA attention, M = Mamba-3 MIMO, - / _ = mlp
        windowed = bool(window_entries(c))
        kinds = []
        for ch in pat:
            if ch in "-_ ":
                continue
            if ch in "Vv*":
                kinds.append("sliding_attention" if windowed else "attention")
            elif ch in "Mm":
                kinds.append("mamba")
            else:
                kinds = None
                break
        if kinds:
            return kinds, "layers_config"
    L = c.get("num_hidden_layers") or c.get("num_layers")
    rda = c.get("rda_config")
    if L and isinstance(rda, dict):
        # Raon (KRAFTON) hybrid stack: `rda_config.mla_layers` lists the
        # full-attention (Gated MLA) layers by 1-based index; every other layer
        # runs Raon Delta Attention, a linear-attention layer with a fixed-size
        # state and no growing KV cache. Confirmed against the weights: exactly
        # those layers own kv_a_proj_with_mqa / kv_b_proj.
        mla = {int(i) - 1 for i in (rda.get("mla_layers") or [])
               if isinstance(i, (int, float))}
        if mla and all(0 <= i < L for i in mla):
            return (["full_attention" if i in mla else "linear_attention"
                     for i in range(L)], "rda_mla_layers")
    local_ids = c.get("local_layer_ids")
    if L and isinstance(local_ids, list) and local_ids and window_entries(c):
        # Inkling-2 style hybrid stack: the config enumerates the sliding-window
        # layers (`local_layer_ids`) and leaves every other layer at full attention.
        local = {int(i) for i in local_ids if isinstance(i, (int, float))}
        return (["sliding_attention" if i in local else "full_attention"
                 for i in range(L)], "local_layer_ids")
    interval = c.get("full_attention_interval") or c.get("global_attention_interval")
    group = c.get("layer_group_size")           # Ling / bailing_hybrid
    if L and interval:
        return (["full_attention" if (i + 1) % interval == 0 else "linear_attention"
                 for i in range(L)], "full_attention_interval")
    if L and group:
        return (["full_attention"
                 if ((i + 1) % group == 0 or i >= L // group * group)
                 else "linear_attention" for i in range(L)], "layer_group_size")
    if L:
        return ["full_attention"] * L, "assumed-all-attention"
    return [], "unknown"


def head_dim(c):
    # `attention_head_size` is the torch-tp-style spelling (Maxwell-MoE series);
    # it must come before the hidden/heads fallback, which is wrong whenever the
    # per-head width is not hidden_size / num_attention_heads.
    return (c.get("head_dim") or c.get("attention_head_size") or c.get("kv_channels")
            or c.get("hidden_size", 0) // max(1, c.get("num_attention_heads", 1)))


def window_entries(c):
    """Rolling-window length for windowed attention, from any of the config spellings."""
    for key in ("sliding_window", "slw_wsize", "sliding_window_size"):
        v = c.get(key)
        if isinstance(v, (int, float)) and v and v > 0:
            return int(v)
    return None


def is_state(kind):
    return any(h in kind.lower() for h in STATE_HINTS)


def is_window(kind):
    return any(h in kind.lower() for h in WINDOW_HINTS)


def kv_reuse(c, total):
    """Layers that read another layer's KV cache instead of allocating their own.

    Aleph-Alpha/Kolibri-1.1 spells this ``kv_source_layers``: one entry per layer
    naming the layer whose cache it attends over, identity meaning "mine". The
    readers are extra sparse-attention layers of the same block, so they add
    compute but no cache slots — only the source layers hold KV for those tokens.
    Returns {reader: source}; empty when the config declares no sharing.
    """
    src = c.get("kv_source_layers")
    if not isinstance(src, list) or not src:
        return {}
    out = {}
    for i, s in enumerate(src[:total]):
        if isinstance(s, (int, float)) and int(s) != i and 0 <= int(s) < total:
            out[i] = int(s)
    return out


def cache_copies(c):
    """How many separate copies of the stack's KV the cache holds.

    Looped stacks (Nanbeige ``num_loops``) re-run the same weights and index the
    cache per pass (``layer_idx + loop_idx * num_hidden_layers``), so every loop
    owns a full set of KV slots. ``loop_share_kv`` opts into reusing the first
    pass's cache instead, which collapses it back to one copy.
    """
    loops = int(c.get("num_loops") or 1)
    if loops > 1 and not c.get("loop_share_kv"):
        return loops
    return 1


def loop_span(*cfgs):
    """(start, end, passes) for a partially looped stack, else None.

    Two spellings are in use: Inkling-2's ``loop_config`` (core_start/core_end/
    num_passes) and SenseNova-Loop's ``loop_settings`` (start/end/counts). The
    latter lives on the root config while the text stack is nested, so callers
    pass both and the first match wins.
    """
    for c in cfgs:
        if not isinstance(c, dict):
            continue
        lc = c.get("loop_config")
        if isinstance(lc, dict):
            passes = int(lc.get("num_passes") or 1)
            if passes > 1:
                return lc.get("core_start"), lc.get("core_end"), passes
        ls = c.get("loop_settings")
        if isinstance(ls, dict):
            counts = ls.get("counts") or []
            passes = int(counts[0]) if counts else int(ls.get("eval_count") or 1)
            if passes > 1:
                return ls.get("start"), ls.get("end"), passes
    return None


def layer_copies(c, idx, loop=None, share_kv=False):
    """Per-layer KV copies for a partially looped stack.

    Inkling-2 loops only its middle block (`loop_config`: `core_start`/`core_end`
    run `num_passes` times with shared weights). Like a full looped stack, each
    pass attends over its own K/V, so the layers inside the block cost
    `num_passes` caches while the outer layers keep one. `loop_share_kv` would
    reuse one pass's cache and collapse this back to 1.
    """
    if share_kv:
        return 1
    if loop is None:
        loop = loop_span(c)
    if loop:
        start, end, passes = loop
        if isinstance(start, int) and isinstance(end, int) and start <= idx < end:
            return passes
    return cache_copies(c)


def layer_geometry(c, kind, idx):
    """Per-layer cache geometry.

    Returns dict with:
      width   bytes stored per cache entry (one entry = one token, or one
              compressed block for CSA/HCA-style attention)
      ratio   tokens per cache entry (1 = one entry per token)
      window  entries kept in a rolling window (None = unbounded)
    """
    ratios = c.get("compress_ratios")
    if c.get("kv_lora_rank"):
        # MLA (DeepSeek-V2/V3, Ling, LongCat): one compressed latent per token,
        # holding the KV content; V is reconstructed, so no factor 2. Hybrid MLA
        # stacks can put a sliding window on some layers (Hy4 flash: sparse MLA +
        # 512-token SWA interleaved), and a windowed layer stores no more than
        # its window — so the window applies here too.
        width = (c["kv_lora_rank"] + (c.get("qk_rope_head_dim") or 0)) * BYTES
        geo = {"width": width, "ratio": 1, "window": None, "pooled": False}
        if is_window(kind) and window_entries(c):
            geo["window"] = window_entries(c)
        return geo
    if isinstance(ratios, list) and idx < len(ratios):
        # DeepSeek-V4 CSA/HCA: single latent per entry (head_dim); remote entries
        # are pooled over `ratio` tokens, plus a rolling sliding window. ratio 0
        # means a pure sliding-window layer (no compressed tail).
        return {"width": head_dim(c) * BYTES, "ratio": max(1, int(ratios[idx] or 1)),
                "window": c.get("sliding_window"), "pooled": bool(ratios[idx])}
    if c.get("global_head_dim") and not is_window(kind):
        # Gemma-4 style: a few global layers use wider heads / fewer KV heads.
        nh = c.get("num_global_key_value_heads") or c.get("num_key_value_heads")
        return {"width": nh * c["global_head_dim"] * 2 * BYTES,
                "ratio": 1, "window": None, "pooled": False}
    n_kv = c.get("num_key_value_heads")
    if not n_kv and c.get("num_signal_heads_diff"):
        # Olala differential attention: only the noise heads own K/V, the signal
        # heads are derived, so `num_key_value_heads` is 0 and the real K/V head
        # count is attention heads minus signal heads.
        n_kv = (c.get("num_attention_heads") or 0) - c["num_signal_heads_diff"]
    n_kv = n_kv or c.get("num_attention_heads") or 1
    geo = {"width": n_kv * head_dim(c) * 2 * BYTES, "ratio": 1, "window": None,
           "pooled": False}
    if is_window(kind) and window_entries(c):
        geo["window"] = window_entries(c)
    return geo


def entries_at(geo, ctx):
    """Cache entries retained at a given context length."""
    if geo["pooled"]:
        # The rolling window keeps recent tokens at full resolution; only the
        # older history is pooled, so the window counts raw and the rest /ratio.
        return (geo["window"] or 0) + ctx // geo["ratio"]
    if geo["window"] is not None:
        return min(ctx, geo["window"]) // geo["ratio"]
    return ctx // geo["ratio"]


def analyse(cfg, mods=None, ctx_override=None):
    c = text_cfg(cfg)
    kinds, provenance = layer_kinds(c)
    if not kinds:
        return None
    total = len(kinds)
    reuse = kv_reuse(c, total)
    layers, kv_layers, windows = [], 0, set()
    for idx, kind in enumerate(kinds):
        if is_state(kind):
            continue
        if idx in reuse:
            continue        # attends over another layer's cache: no slots of its own
        geo = layer_geometry(c, kind, idx)
        # Several attention branches in one layer (LongCat: two MLA branches)
        # each keep their own cache, so scale the per-layer width.
        n = (mods or {}).get(idx, 1)
        geo["width"] *= n
        kv_layers += 1
        if geo["window"] is not None:
            windows.add(geo["window"])
        layers.append((idx, geo))
    ctx = c.get("max_position_embeddings") or c.get("max_seq_len") or 0
    # The vendor's stated context wins over the config: `max_position_embeddings`
    # is often a training-layout artifact (Olala: 100000 in config, 32K on the
    # card), and charging cache beyond the advertised context would overstate it.
    ctx_source = "config.json max_position_embeddings"
    if ctx_override:
        ctx_source = "vendor-stated context"
        ctx = int(ctx_override)
    loop = loop_span(c, cfg)
    share_kv = bool(c.get("loop_share_kv") or cfg.get("loop_share_kv"))
    stacked = [(idx, geo, layer_copies(c, idx, loop, share_kv))
               for idx, geo in layers]
    copies = max((cp for _, _, cp in stacked), default=1)
    looped_layers = sum(1 for _, _, cp in stacked if cp > 1)
    # Never extrapolate past a model's own maximum context: a 125K model would
    # otherwise be charged for 128K of cache it cannot hold.
    ref_ctx = min(REF_CTX, int(ctx)) if ctx else REF_CTX

    def gib(at_ctx):
        if not at_ctx:
            return None
        total_b = sum(geo["width"] * entries_at(geo, int(at_ctx)) * cp
                      for _, geo, cp in stacked)
        return round(total_b / 2 ** 30, 3)

    marginal = sum(geo["width"] / geo["ratio"] * cp for _, geo, cp in stacked
                   if geo["pooled"] or geo["window"] is None)
    confidence = "high" if provenance in ("layer_types", "layers_block_type", "block_types",
                                          "hybrid_override_pattern", "local_layer_ids",
                                          "rda_mla_layers") else "medium"
    if provenance == "assumed-all-attention":
        confidence = "low"
    out = {
        "dtype": "bf16",
        "ref_ctx": int(ref_ctx),
        "gib_at_ref_ctx": gib(ref_ctx),
        "gib_at_native_ctx": gib(ctx),
        "native_ctx": int(ctx) if ctx else None,
        "kib_per_token_marginal": round(marginal / 1024, 2),
        "kv_layers": kv_layers,
        "total_layers": total,
        "cache_copies": copies,
        "attention_modules_per_layer": max(mods.values()) if mods else 1,
        "window": min(windows) if windows else None,
        "method": "formula",
        "formula_version": FORMULA_VERSION,
        "confidence": confidence,
        "provenance": provenance,
        "native_ctx_source": ctx_source,
        "verified": False,
        "config_revision": None,
        "notes": None,
    }
    if looped_layers:
        # only looped stacks carry this, so the field stays absent (not null) elsewhere
        out["looped_layers"] = looped_layers
    if reuse:
        out["shared_kv_layers"] = len(reuse)
    return out


def note_for(c, out):
    """Single source of the per-architecture caveat string (tooltip + audit trail)."""
    c = text_cfg(c)
    bits = []
    reuse = kv_reuse(c, out["total_layers"])
    if out["kv_layers"] >= out["total_layers"]:
        bits.append("all %d layers cache KV" % out["total_layers"])
    elif reuse:
        bits.append("%d of %d layers cache KV" % (out["kv_layers"], out["total_layers"]))
    else:
        bits.append("%d of %d layers cache KV (%d use linear/recurrent state)"
                    % (out["kv_layers"], out["total_layers"],
                       out["total_layers"] - out["kv_layers"]))
    if out.get("cache_copies", 1) > 1:
        looped = out.get("looped_layers")
        if looped and looped < out["kv_layers"]:
            bits.append("%d of %d KV layers run %d passes over the same weights, each "
                        "pass keeping its own KV"
                        % (looped, out["kv_layers"], out["cache_copies"]))
        else:
            bits.append("%d loop passes over the same weights, each keeping its own KV "
                        "(%d cache slots)"
                        % (out["cache_copies"], out["kv_layers"] * out["cache_copies"]))
    mods = out.get("attention_modules_per_layer") or 1
    if mods > 1:
        bits.append("%d attention branches per layer, each keeping its own KV" % mods)
    if reuse:
        bits.append("%d of %d layers re-read the cache of layers %s (kv_source_layers), "
                    "so they allocate no slots of their own"
                    % (len(reuse), out["total_layers"],
                       " / ".join(str(s) for s in sorted(set(reuse.values())))))
    if c.get("kv_lora_rank"):
        bits.append("MLA: latent KV cache (kv_lora_rank + rope), not per-head K/V")
    if c.get("num_signal_heads_diff"):
        bits.append("differential attention: only %d of %d heads keep K/V"
                    % ((c.get("num_attention_heads") or 0) - c["num_signal_heads_diff"],
                       c.get("num_attention_heads") or 0))
    if isinstance(c.get("compress_ratios"), list):
        bits.append("compressed attention (CSA/HCA): cache entries pooled per layer")
    if any(k in c for k in ("index_topk", "indexer_budget")) or c.get("index_n_heads"):
        bits.append("sparse-attention indexer cache not included")
        if not isinstance(c.get("compress_ratios"), list):
            bits.append("sparse selection skips compute only: every token's latent is "
                        "still cached")
    if out["window"]:
        bits.append("sliding window %d" % out["window"])
    if c.get("kv_cache_qat"):
        bits.append("KV-cache QAT: trained to serve a quantised cache, this figure is BF16")
    cfg_ctx = c.get("max_position_embeddings") or c.get("max_seq_len")
    if out.get("native_ctx_source") == "vendor-stated context":
        bits.append("native context %s from the vendor card (config max_position_embeddings "
                    "%s not used)" % (out.get("native_ctx"), cfg_ctx))
    return "; ".join(bits) or None


# ---------------------------------------------------------------- safetensors
MODULE = r"(?:self_attn|global_attn|local_attn|full_attn|attention|attn|mixer|mla)"
# multimodal towers reuse `layers.N.self_attn.*` names — never part of the text KV cache
TOWER = ("vision_tower", "vision_model", "audio_tower", "audio_model", "image_tower",
         "multi_modal", "projector", "connector", ".vision.", ".audio.", ".visual.")


def skip_tensor(name):
    low = name.lower()
    return (low.startswith("mtp.") or ".mtp." in low or "dspark" in low
            # speculative drafters (DFly2 / dspark) reuse the target's KV and keep
            # no cache of their own — their tensor names collide with `layers.N`
            or ".dfly" in low or low.startswith("dfly")
            or any(t in low for t in TOWER))


def marker_regex(c):
    """Regex for the tensor that proves a layer keeps a KV cache.

    Hybrid stacks (Ling, Qwen3.8) also expose k_proj on linear-attention layers,
    so when the config advertises an MLA latent use that projection instead. The
    optional `\\d+.` covers layers with several attention branches (LongCat).
    Fused `q_k_v_proj` (Spark X) carries K and V in a single tensor.
    Low-rank K/V (`wk_dv`, Inkling-2) is matched on the K projection only, so a
    layer is counted once rather than once per K and V tensor.
    """
    if c.get("kv_lora_rank"):
        tensors = r"(?:kv_a_proj_with_mqa)"
    elif isinstance(c.get("compress_ratios"), list):
        tensors = r"(?:wkv)"
    elif c.get("layers_config"):
        # Olala TPA: the low-rank K projection is the per-layer KV marker
        tensors = r"(?:W_A_k)"
    else:
        tensors = r"(?:k_proj|q_k_v_proj|wk_dv)"
    return re.compile(r"layers\.(\d+)\.%s\.(?:\d+\.)?%s\.weight$" % (MODULE, tensors))


def attention_modules(model_id, c, wmap=None, limit=None):
    """{layer_idx: number_of_KV_modules} from the real safetensors index.

    Returns None when the repo layout is unreadable, in which case the
    config-only assumption of one module per layer is kept.
    """
    if wmap is None:
        wmap = _index(model_id)
    if not wmap:
        return None
    if limit is None:
        limit = c.get("num_hidden_layers") or c.get("num_layers")
    rx = marker_regex(c)
    mods = {}
    for name in wmap:
        if skip_tensor(name):
            continue
        if ".compressor." in name.lower() or ".indexer." in name.lower():
            continue                      # shares the parent layer's cache buffer
        m = rx.search(name)
        if not m:
            continue
        i = int(m.group(1))
        if limit is not None and i >= limit:
            continue                      # MTP / next-token head beyond the stack
        mods[i] = mods.get(i, 0) + 1
    return mods or None


_HDR_CACHE = {}


def _read_safetensors_header(url, max_header=64 * 1024 * 1024):
    if url in _HDR_CACHE:
        return _HDR_CACHE[url]
    r = get(url, headers={"Range": "bytes=0-7"})
    if r is None or r.status_code != 206 or len(r.content) < 8:
        return None
    n = struct.unpack("<Q", r.content)[0]
    if n <= 0 or n > max_header:
        return None
    r2 = get(url, headers={"Range": "bytes=8-%d" % (7 + n)})
    if r2 is None or r2.status_code not in (200, 206):
        return None
    try:
        hdr = json.loads(r2.content)
    except ValueError:
        return None
    _HDR_CACHE[url] = hdr
    return hdr


def _index(model_id):
    """weight_map from the safetensors index, or from a single-file header."""
    name = "model.safetensors.index.json"
    r = get("%s/%s/raw/main/%s" % (RAW, model_id, name))
    if r is not None and r.status_code == 200:
        try:
            wm = r.json().get("weight_map") or {}
            if wm:
                return wm
        except ValueError:
            pass            # an LFS pointer: raw/ serves it unresolved, so try resolve/
    r = get("%s/%s/resolve/main/%s" % (RAW, model_id, name))
    if r is not None and r.status_code == 200:
        try:
            return r.json().get("weight_map") or {}
        except ValueError:
            pass
    hdr = _read_safetensors_header(
        "%s/%s/resolve/main/model.safetensors" % (RAW, model_id))
    if hdr:
        return {k: "model.safetensors" for k in hdr if k != "__metadata__"}
    return {}


def verify(model_id, cfg, out, wmap=None, mods=None):
    """Cross-check computed per-layer widths against real tensor shapes.

    Layer *set* and the number of attention branches per layer come from the
    safetensors index (complete, cheap); widths come from the safetensors header
    of the shards holding a few sampled layers.
    """
    c = text_cfg(cfg)
    kinds, _ = layer_kinds(c)
    wmap = wmap if wmap is not None else _index(model_id)
    problems, checked = [], 0
    if not wmap:
        out["verify_notes"] = "no safetensors index in repo"
        return problems

    rx = marker_regex(c)
    names = {}
    for name in wmap:
        if skip_tensor(name):
            continue
        if ".compressor." in name.lower() or ".indexer." in name.lower():
            continue
        m = rx.search(name)
        if m:
            names.setdefault(int(m.group(1)), []).append(name)

    have = sorted(i for i in names if i < len(kinds))
    if not have:
        out["verify_notes"] = "no attention tensors matched the expected layout"
        return problems

    reuse = kv_reuse(c, len(kinds))
    expected = [i for i, k in enumerate(kinds) if not is_state(k) and i not in reuse]
    extra = [i for i in have if i not in expected]
    missing = [i for i in expected if i not in have]
    # A declared reader must hold no KV tensors of its own — that is the whole
    # claim of cache sharing, so confirm it against the weights rather than trusting it.
    readers = [i for i in sorted(reuse) if i in names]
    if readers:
        problems.append("layers declared kv_source reuse but holding their own KV tensors: %s"
                        % readers[:8])
        extra = [i for i in extra if i not in reuse]
    if extra:
        problems.append("tensors show attention on layers classified state-only: %s" % extra[:8])
    if missing:
        problems.append("layers classified KV-bearing without attention tensors: %s" % missing[:8])

    # width check on up to 3 sampled KV layers, using the exact tensor names
    sample = sorted({have[0], have[len(have) // 2], have[-1]})
    for i in sample:
        if i >= len(kinds):
            continue
        shard = wmap[names[i][0]]
        hdr = _read_safetensors_header("%s/%s/resolve/main/%s" % (RAW, model_id, shard))
        if not hdr:
            continue
        geo = layer_geometry(c, kinds[i], i)
        for tname in names[i]:
            meta = hdr.get(tname)
            if not meta or "shape" not in meta:
                continue
            got = meta["shape"][0]           # out_features
            if tname.endswith("q_k_v_proj.weight"):
                # fused Q|K|V: out = n_heads*hd + 2*kv_heads*hd
                want = (c["num_attention_heads"] * head_dim(c)
                        + 2 * (geo["width"] // (2 * BYTES)))
            elif tname.endswith("W_A_k.weight"):
                # Olala TPA low-rank K projection: out = kv_heads * tpa_rank
                want = (geo["width"] // (2 * BYTES * head_dim(c))) * c["tpa_rank"]
            elif c.get("kv_lora_rank") or isinstance(c.get("compress_ratios"), list):
                want = geo["width"] // BYTES          # one latent, no K/V doubling
            else:
                want = geo["width"] // (2 * BYTES)    # K and V stored separately
            checked += 1
            if got != want:
                problems.append("layer %d %s: tensor out=%d, computed=%d"
                                % (i, tname.rsplit(".", 2)[-2], got, want))

    out["verified"] = bool(checked) and not problems
    out["verify_checked"] = checked
    if problems:
        out["verify_notes"] = "; ".join(problems[:4])
    return problems


# -------------------------------------------------------------------- main
def fmt_gib(v):
    return "-" if v is None else ("%.2f" % v)


def cached_ok(m, args):
    """True when the stored block can be reused without touching the network."""
    old = m.get("kv_cache") or {}
    if not old or old.get("formula_version") != FORMULA_VERSION:
        return False
    if args.verify and not old.get("verified"):
        return False
    cfg, sha = snapshot_config(m["model_id"])
    return bool(cfg) and bool(sha) and old.get("config_revision") == sha


def process(m, args):
    """Compute one model's kv_cache block; does network I/O, safe to run in a thread.

    Returns (cid, block_or_None, problems, carried_verification).
    """
    cid = m["model_id"]
    cfg, sha = fetch_config(cid, args.refresh)
    if not cfg:
        return cid, None, ["config.json unavailable"], False
    wmap = _index(cid) if args.verify else None
    mods = attention_modules(cid, text_cfg(cfg), wmap)
    if mods is None and not args.verify:
        mods = attention_modules(cid, text_cfg(cfg))
    out = analyse(cfg, mods, (m.get("architecture") or {}).get("context_length"))
    if not out:
        return cid, None, ["no layer structure in config"], False
    out["config_revision"] = sha
    out["notes"] = note_for(cfg, out)
    carried = False
    if args.verify:
        problems = verify(cid, cfg, out, wmap=wmap, mods=mods)
        if out.get("verified"):
            out["confidence"] = "high"     # confirmed against real weight shapes
        elif (out.get("verify_notes")
              and out.get("verify_notes") != "no safetensors index in repo"):
            out["confidence"] = "low"      # mismatch: geometry rule unproven
        return cid, out, problems, carried
    # Recomputing the formula does not touch the weights, so a previous
    # verification stays valid while the pinned config revision is the same.
    # Without this a plain --apply would silently reset every model to
    # verified=false / low confidence.
    old = m.get("kv_cache") or {}
    if old.get("verified") and old.get("config_revision") == sha:
        out["verified"] = True
        out["verify_checked"] = old.get("verify_checked")
        if isinstance(old.get("verify_notes"), str):
            out["verify_notes"] = old["verify_notes"]
        out["confidence"] = "high"
        carried = True
    return cid, out, [], carried


def main():
    ap = argparse.ArgumentParser(description="Derive KV-cache footprint from config.json")
    ap.add_argument("models", nargs="*", help="model ids (default: whole roster)")
    ap.add_argument("--apply", action="store_true", help="write kv_cache into models.json")
    ap.add_argument("--verify", action="store_true",
                    help="cross-check widths against safetensors headers "
                         "(only models not yet verified at this config revision)")
    ap.add_argument("--refresh", action="store_true", help="re-fetch config.json")
    ap.add_argument("--force", action="store_true",
                    help="recompute models whose cached block is still valid")
    ap.add_argument("--jobs", type=int, default=6, metavar="N",
                    help="models fetched in parallel (default 6; 1 = sequential)")
    args = ap.parse_args()

    doc = json.load(open(MODELS_PATH, encoding="utf-8"))
    roster = doc["models"]
    targets = [m for m in roster if not args.models or m["model_id"] in args.models]
    if not targets:
        print("no matching models"); return 1

    results, failed, carried, reused, todo = {}, [], [], [], []
    for m in targets:
        # An explicit id means "recompute this one"; otherwise reuse the stored
        # block while its pinned config revision and formula version still match,
        # which turns a repeat full-roster run into a purely local operation.
        if not (args.force or args.refresh or args.models) and cached_ok(m, args):
            results[m["model_id"]] = m["kv_cache"]
            reused.append(m["model_id"])
        else:
            todo.append(m)

    workers = max(1, min(args.jobs, len(todo)))
    if todo:
        print("computing %d of %d model(s) with up to %d parallel fetch(es)..."
              % (len(todo), len(targets), workers), file=sys.stderr)
    done = 0
    pool = None
    if workers <= 1:
        jobs = (process(m, args) for m in todo)
    else:
        pool = concurrent.futures.ThreadPoolExecutor(max_workers=workers)
        futures = [pool.submit(process, m, args) for m in todo]

        def _as_completed():
            for f in concurrent.futures.as_completed(futures):
                yield f.result()
        jobs = _as_completed()
    try:
        for cid, out, problems, was_carried in jobs:
            done += 1
            print("  [%d/%d] %s" % (done, len(todo), cid), file=sys.stderr)
            for p in problems:
                print("  VERIFY %s: %s" % (cid, p), file=sys.stderr)
            if out is None:
                failed.append(cid)
                continue
            results[cid] = out
            if was_carried:
                carried.append(cid)
    finally:
        if pool is not None:
            pool.shutdown(wait=True)

    order = sorted(results.items(), key=lambda kv: -(kv[1]["gib_at_ref_ctx"] or 0))
    print("%-52s %6s %5s %11s %11s %10s  %-6s%s"
          % ("model", "GiB@128K", "kv/L", "KiB/tok", "GiB@native", "ctx", "conf", " verified"))
    for cid, o in order:
        print("%-52s %9.2f %3d/%-2d %11.2f %11s %10s  %-6s%s"
              % (cid, o["gib_at_ref_ctx"], o["kv_layers"], o["total_layers"],
                 o["kib_per_token_marginal"], fmt_gib(o["gib_at_native_ctx"]),
                 o["native_ctx"] or "-", o["confidence"],
                 "yes" if o.get("verified") else "no"))

    if not args.apply:
        print("\n[dry-run] pass --apply to write kv_cache into models.json")
        return 1 if failed else 0

    for m in roster:
        cid = m["model_id"]
        if cid in results:
            m["kv_cache"] = results[cid]
    with open(MODELS_PATH, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=2, ensure_ascii=False)
        f.write("\n")
    print("\nwrote kv_cache for %d models into models.json" % len(results))
    if reused:
        print("reused %d unchanged model(s) from models.json (pinned config revision and "
              "formula_version match; pass --force to recompute)" % len(reused))
    if carried:
        print("kept previous safetensors verification for %d model(s) (config revision "
              "unchanged); re-run with --verify to re-check" % len(carried))
    if failed:
        print("FAILED: %s" % ", ".join(failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
