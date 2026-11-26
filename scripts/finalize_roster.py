#!/usr/bin/env python3
"""Finalize the curated, verified model roster into data/models.json.

Each model below was hand-verified (official org, non-quant, in 4B-285B range,
released on/after the cutoff, current version). Metadata is fetched live from the
HF API so this script is reproducible and never depends on a churning raw/roster.json.
"""
import json, time, requests, sys, os

BASE = "https://huggingface.co/api/models"
RAW = "https://huggingface.co"
# re-uploader / quant namespaces: a model in one of these orgs is NOT official
NON_OFFICIAL_ORGS = {"unsloth", "mlx-community", "mradermacher", "QuantFactory",
                     "bartowski", "TheDrummer", "Quantius", "city96", "RedHatAI",
                     "QuantLama", "legraphista", "huggingface", "google-research-datasets"}
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
META = json.load(open(os.path.join(ROOT, "data", "meta.json")))

# (model_id, family, must_include, note)
CURATED = [
    ("Qwen/Qwen3.8-27B", "Qwen3.8", False, "Flagship dense model."),
    ("Qwen/Qwen3.8-Flash-Next", "Qwen3.8", False, "Large MoE."),
    ("Qwen/Qwen-AgentWorld-35B-A3B", "Qwen-AgentWorld", False, "Agent-specialized MoE."),
    ("google/gemma-4-12B-it", "gemma-4", False, ""),
    ("deepseek-ai/DeepSeek-V4-Flash-DSpark", "DeepSeek-V4", False, "V4-Flash is the in-range DeepSeek-V4 variant (V4-Pro is 1.6T)."),
    ("poolside/Laguna-S-2.1", "Laguna", False, ""),
    ("poolside/Laguna-XS-2.1", "Laguna", False, "Newer than Laguna-XS.2 (2026-06-20 vs 04-23)."),
    ("LiquidAI/LFM2.5-8B-A1B", "LFM2.5", False, "MoE, A1B active."),
    ("Nanbeige/Nanbeige4.2-3B", "Nanbeige4.2", False, ""),
    ("Kwaipilot/KAT-Coder-V2.5-Dev", "KAT-Coder", False, "Coding model."),
    ("JetBrains/Mellum2-12B-A2.5B-Thinking", "Mellum2", False, "MoE, thinking variant (current)."),
    ("ibm-granite/granite-4.2-30b", "granite-4.2", False, "Current; supersedes granite-4.1."),
    ("ibm-granite/granite-4.2-8b", "granite-4.2", False, "Current; supersedes granite-4.1."),
    ("tencent/Hy-MT2-30B-A3B", "Hy-MT2", False, "Translation MoE."),
    ("meituan-longcat/LongCat-Flash-Lite-Sparse", "LongCat", False, ""),
    ("microsoft/Fara1.5-27B", "Fara", False, ""),
    ("microsoft/Fara1.5-9B", "Fara", False, ""),
    ("microsoft/Mage-VL", "Mage-VL", False, "Vision-language."),
    ("nvidia/Nemotron-3-Nano-Omni-30B-A3B-Reasoning", "Nemotron-3", False, "Omni MoE (reasoning)."),
    ("nvidia/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-BF16", "Nemotron-3.5", False, "Official BF16 (non-quant) weights."),
    ("ornith-ai/Ornith-1.5-9B", "Ornith", True, "REQUIRED family; current v1.5 (1.0 superseded)."),
    ("ornith-ai/Ornith-1.5-35B-A3B", "Ornith", True, "REQUIRED family; current v1.5, MoE A3B."),
    ("inclusionAI/Ling-3.0-tiny", "Ling", True, "REQUIRED family; current v3.0 (2.6 superseded)."),
    ("inclusionAI/Ling-3.0-flash", "Ling", True, "REQUIRED family; current v3.0."),
    ("XHToken/Spark-X2.5-4B", "Spark X", True, "REQUIRED family; current v2.5. (1.7B below 4B floor; -Base is pre-instruct.)"),
    ("tencent/UI-Mate-27B", "UI-Mate", False, ""),
]

def get(u, tries=6):
    for a in range(tries):
        try:
            r = requests.get(u, timeout=25, headers={"User-Agent": "aibench/0.1"})
            if r.status_code == 200:
                return r.json()
            if r.status_code == 429:
                time.sleep(3 * (a + 1)); continue
            if r.status_code >= 500:
                time.sleep(2 * (a + 1)); continue
            return None
        except Exception:
            time.sleep(2)
    return None

def modalities(tags, arch, name):
    t = set(tags or []); n = name.lower()
    mods = ["text"]
    if any("image" in x for x in t) or any(k in n for k in ("vl", "vision", "vlm", "molmo", "mage", "omni")):
        mods.append("vision")
    if any("audio" in x for x in t) or "omni" in n:
        mods.append("audio")
    return mods

def raw_config(cid):
    """Fetch the repo's real config.json (the API `config` field omits nested
    sub-configs like vision_config, so the raw file is the authoritative vision
    signal — see AGENTS.md). Returns {} when absent/unparsable/too large."""
    txt = None
    for branch in ("main", "master"):
        try:
            r = requests.get(f"{RAW}/{cid}/raw/{branch}/config.json", timeout=25,
                             headers={"User-Agent": "aibench/0.1"})
            if r.status_code == 200 and len(r.text) < 2_000_000:
                txt = r.text
                break
        except Exception:
            pass
    if not txt:
        return {}
    try:
        parsed = json.loads(txt)
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def build(cid, family, must_include, note):
    d = get(f"{BASE}/{cid}?full=true")
    if not d:
        print(f"  !! could not fetch {cid}", file=sys.stderr); return None
    cfg = d.get("config") or {}
    card = d.get("cardData") or {}
    tags = d.get("tags") or []
    arch = (cfg.get("architectures") or [None])[0]
    total = (d.get("safetensors") or {}).get("total")
    if not isinstance(total, int) or total <= 0:
        print(f"  !! {cid}: no safetensors total in HF metadata "
              f"(gated/partial upload?) — cannot verify params", file=sys.stderr)
        return None
    b = round(total / 1e9, 1)
    ne = cfg.get("num_experts"); nea = cfg.get("num_experts_per_tok")
    name = cid.split("/")[-1]
    # MoE if config says so, or arch class says Moe, or name uses the -A<n>B active-param
    # convention, or it is a known-MoE flagship whose HF config omits num_experts.
    import re as _re
    arch_moe = any("oe" in str(x).replace("-", "") and "Mo" in str(x) for x in (cfg.get("architectures") or []))
    name_a_b = bool(_re.search(r"-A\d+(?:\.\d+)?B\b", name, _re.I))
    known_moe = {"Qwen3.8-Flash-Next", "DeepSeek-V4-Flash-DSpark"}
    is_moe = bool(ne) or arch_moe or name_a_b or (name in known_moe)
    ctx = cfg.get("max_position_embeddings") or card.get("max_model_len")
    arch_obj = {"type": "moe" if is_moe else "dense"}
    if ne: arch_obj["experts"] = ne
    if nea: arch_obj["active_experts"] = nea
    if ctx: arch_obj["context_length"] = int(ctx)
    arch_obj["modalities"] = modalities(tags, arch, cid)
    # vision support: authoritative signal is a vision tower in the repo's real
    # config.json (the API `config` omits vision_config — verified empirically);
    # API config and the modality name-heuristic are fallbacks.
    file_cfg = raw_config(cid)
    supports_vision = (bool(file_cfg.get("vision_config")) or bool(cfg.get("vision_config"))
                       or ("vision" in arch_obj["modalities"]))
    lic = card.get("license") or next((x.replace("license:", "") for x in tags if str(x).startswith("license:")), None)
    if lic: arch_obj["license"] = lic
    note_field = f"{b:.0f}B total MoE (A{nea}B active)" if (is_moe and nea) else (f"{b:.0f}B total MoE" if is_moe else f"{b:.1f}B dense")
    likes = d.get("likes") or 0
    created = (d.get("createdAt") or "")[:10]
    obj = {
        "model_id": cid,
        "display_name": cid.split("/")[-1],
        "org": cid.split("/")[0],
        "family": family,
        "param_count_b": b,
        "param_count_note": note_field,
        "architecture": arch_obj,
        "supports_vision": supports_vision,
        "official_release_date": created,
        "hf_url": f"https://huggingface.co/{cid}",
        "likes": likes,
        "is_official": cid.split("/")[0] not in NON_OFFICIAL_ORGS,
        "officiality_evidence": f"owned by {cid.split('/')[0]} org; {b:.0f}B safetensors (non-quant); {likes} likes; created {created}",
        "current_version": True,
        "notes": note,
    }
    if must_include:
        obj["must_include_family"] = True
    return obj

def main():
    models, skipped = [], []
    for cid, fam, req, note in CURATED:
        m = build(cid, fam, req, note)
        if m:
            models.append(m); print(f"  + {cid}  {m['param_count_b']}B  {m['architecture']['type']}")
        else:
            skipped.append(cid)
        time.sleep(0.5)
    out = {
        "criteria": {
            "cutoff_date": META["cutoff_date"],
            "min_params_b": META["min_params_b"],
            "max_params_b": META["max_params_b"],
            "max_age_months": META["max_age_months"],
            "min_models": META["min_models"],
            "official_only": True,
            "current_version_only": True,
            "include_families": META["criteria"]["include_families"],
        },
        "models": models,
    }
    path = os.path.join(ROOT, "data", "models.json")
    json.dump(out, open(path, "w"), indent=2, ensure_ascii=False)
    print(f"\nWrote {len(models)} models -> {path}")
    if skipped:
        print("SKIPPED (fetch failed):", skipped, file=sys.stderr)
    # validate
    import jsonschema
    sch = json.load(open(os.path.join(ROOT, "schema", "models.schema.json")))
    jsonschema.validate(out, sch)
    print("schema: ok")

if __name__ == "__main__":
    main()
