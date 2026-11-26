import json
import os
import re
import time
import datetime
from collections import defaultdict
import requests

BASE = "https://huggingface.co/api"
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
META = json.load(open(os.path.join(ROOT, "data", "meta.json")))

CUTOFF = META["cutoff_date"]
MIN_B = float(META["min_params_b"])
MAX_B = float(META["max_params_b"])
MIN_P = MIN_B * 1e9
MAX_P = MAX_B * 1e9

UA = {"User-Agent": "aibench-discover/0.1 (research; contact: aibench)"}
SESSION = requests.Session()
SESSION.headers.update(UA)

LIKES_PAGES = 20
DOWNLOADS_PAGES = 8
CREATED_PAGES_MAX = 150
PAGE = 100
ORG_LIMIT = 200
MAX_FETCH = 650
KEEP_PT = {"text-generation", "image-text-to-text", "any-to-any"}

REQUIRED = {
    "Ornith": {"org": "ornith-ai", "current": ["Ornith-1.5-9B", "Ornith-1.5-35B-A3B"]},
    "Ling": {"org": "inclusionAI", "current": ["Ling-3.0-tiny", "Ling-3.0-flash"]},
    "Spark X": {"org": "XHToken", "current": ["Spark-X2.5-4B"]},
}

LINEAGE = {
    "Ornith": {
        "ornith-ai/Ornith-1.0-9B": "ornith-ai/Ornith-1.5-9B",
        "ornith-ai/Ornith-1.0-35B": "ornith-ai/Ornith-1.5-35B-A3B",
    },
    "Ling": {
        "inclusionAI/Ling-2.6-flash": "inclusionAI/Ling-3.0-flash",
    },
    "Spark X": {},
}

REAL_DEVELOPER_ORGS = [
    "Qwen", "deepseek-ai", "zai-org", "moonshotai", "google", "meta-llama",
    "mistralai", "nvidia", "xai-org", "openai", "microsoft", "amazon", "apple",
    "ibm-granite", "ibm-research", "allenai", "bigcode", "Salesforce", "tiiuae",
    "bigscience", "LiquidAI", "poolside", "Kwaipilot", "CohereLabs", "deepgrove",
    "JetBrains", "Nanbeige", "upstage", "bosonai", "superwhisper", "OpenMOSS-Team",
    "FlagRelease", "baidu", "SkyworkAI", "StepFun", "01-ai", "meituan",
    "meituan-longcat", "baichuan-inc", "SenseNova", "SenseTime", "THUDM",
    "internlm", "HuggingFaceTB", "tencent", "XiaomiMiMo", "MiniMaxAI", "amd",
    "bytedance", "alibaba", "Stability-AI", "hugging-llm", "ernie-research",
]

BLOCKLIST = {
    "unsloth", "mlx-community", "mradermacher", "QuantFactory", "bartowski",
    "TheDrummer", "Quantius", "leomii12", "city96", "arkai", "RedHatAI",
    "QuantLama", "legraphista", "0xSero", "dealignai", "z-lab", "Youssofal",
    "ProCreations", "Ateron", "EschaLabs", "Mia-AiLab", "LeaderboardModel1",
    "Cactus-Compute", "fastino", "empero-ai", "Chunjiang-Intelligence",
    "badtheorylabs", "Agnuxo", "lordx64", "Akahsizrr", "AliesTaha", "pipecat-ai",
    "IFM", "latam-gpt", "faborbvakkoli", "farbodtavakkoli",
}

EXCL_TOKENS = [
    "gguf", "awq", "fp8", "gptq", "bnb", "nf4", "lora", "finetune", "finetuned",
    "abliterated", "uncensored", "unsloth", "obliterated", "obliteratus", "mythos",
    "mlx", "nvfp4", "bitsandbytes", "mxfp4", "mxfp8", "mxfp", "auto_round",
    "exl3", "exl2", "exl4", "bpw", "ternary", "tern", "qat",
    "w4a16", "w4a8", "w8a8", "w4a4", "-w2", "w2-",
    "da8w8", "da4w8", "da4w4", "torchao",
    "4bit", "8bit", "6bit", "2bit", "int4", "int8", "int3", "int6",
    "q4_", "q5_", "q8_", "q2_", "q3_", "iq2", "iq3", "iq4", "k_m",
    "_distill", "-distill", "distill-", "dpo-", "-dpo",
    "jang", "crack", "paro", "ciru", "spark-optim", "optimized-speed",
]
FT_RE = re.compile(r"(?:^|[-_/])ft[-_]|-ft\b")
Q_RE = re.compile(r"(?:^|[-_])q[0-9]\b|\bq[0-9]_")
BASE_RE = re.compile(r"(?:^|[-_ ])base(?:[-_ ]|$)", re.I)
DTYPE_RE = re.compile(r"[-_ ]?(?:bf16|bf18|fp16)$", re.I)


def is_derived(name):
    n = name.lower()
    if any(t in n for t in EXCL_TOKENS):
        return True
    if FT_RE.search(n):
        return True
    if Q_RE.search(n):
        return True
    return False


def is_base(name):
    return bool(BASE_RE.search(name))


SPECIAL_SUBSTRINGS = [
    "molmo", "stdmoe", "emo_", "contextpilot", "magentic", "privasis", "ising",
    "guardian", "flagos", "moonlight", "fathom", "embodied", "pretrain",
    "midtrain", "harc", "gelab", "riva", "cuda", "cleaner", "translate",
    "motion", "autocomple", "calibration", "puzzle", "twotower", "ui-mate",
    "ui_mate", "scijudge", "scicore", "mathform", "hils", "switch", "labs",
]
SPECIAL_TOKENS = {"sft", "bench", "benchmark", "drive", "routing", "vsm",
                  "emo", "bar"}


def is_specialized(name):
    n = name.lower()
    if any(s in n for s in SPECIAL_SUBSTRINGS):
        return True
    if any(t in SPECIAL_TOKENS for t in re.split(r"[^a-z0-9]+", n)):
        return True
    return False


def strip_dtype(name):
    return DTYPE_RE.sub("", name).rstrip("-_ ")


def get(url, params=None, tries=5):
    for a in range(tries):
        try:
            r = SESSION.get(url, params=params, timeout=40)
        except requests.RequestException:
            time.sleep(2 * (a + 1))
            continue
        if r.status_code == 200:
            return r
        if r.status_code in (429, 500, 502, 503, 504):
            time.sleep(min(60, 2 * (a + 1)))
            continue
        return r
    return None


def next_link(resp):
    link = resp.headers.get("Link")
    if not link:
        return None
    for part in link.split(","):
        if 'rel="next"' in part:
            return part.strip().lstrip("<").split(">")[0]
    return None


def scan_listing(sort, pages, min_created=None):
    params = {"filter": "text-generation", "sort": sort, "direction": "-1", "limit": PAGE}
    cursor = None
    out = []
    for i in range(pages):
        r = get(f"{BASE}/models", params=params) if i == 0 else get(cursor)
        if r is None or r.status_code != 200:
            break
        data = r.json()
        if not isinstance(data, list) or not data:
            break
        stop = False
        for m in data:
            mid = m.get("modelId") if isinstance(m, dict) else None
            if not mid:
                continue
            created = (m.get("createdAt") or "")[:10]
            out.append({
                "id": mid,
                "author": m.get("author") or mid.split("/")[0],
                "likes": m.get("likes") or 0,
                "downloads": m.get("downloads") or 0,
                "createdAt": created,
                "pipeline_tag": m.get("pipeline_tag"),
            })
            if min_created and created < min_created:
                stop = True
        if stop:
            break
        cursor = next_link(r)
        if cursor is None:
            break
        time.sleep(0.1)
    return out


def org_models(org):
    r = get(f"{BASE}/models", params={"author": org, "sort": "createdAt",
                                      "direction": "-1", "limit": ORG_LIMIT})
    if r is None or r.status_code != 200:
        return []
    out = []
    for m in r.json():
        mid = m.get("modelId") if isinstance(m, dict) else None
        if not mid:
            continue
        out.append({
            "id": mid,
            "author": m.get("author") or org,
            "likes": m.get("likes") or 0,
            "downloads": m.get("downloads") or 0,
            "createdAt": (m.get("createdAt") or "")[:10],
            "pipeline_tag": m.get("pipeline_tag"),
        })
    return out


def fetch_full(mid):
    r = get(f"{BASE}/models/{mid}?full=true")
    if r is None or r.status_code != 200:
        return None
    return r.json()


def modalities(pt):
    if pt == "any-to-any":
        return ["text", "vision", "audio"]
    if pt == "image-text-to-text":
        return ["text", "vision"]
    return ["text"]


def arch_info(cfg):
    cfg = cfg or {}
    mt = (cfg.get("model_type") or "").lower()
    arch = (cfg.get("architectures") or [""])[0].lower() if cfg.get("architectures") else ""
    ne = cfg.get("num_experts")
    nep = cfg.get("num_experts_per_tok")
    info = {}
    if "hybrid" in mt or "hybrid" in arch or "sparse" in mt or "linear" in arch:
        atype = "hybrid"
    elif isinstance(ne, int) and ne > 1:
        atype = "moe"
    else:
        atype = "dense"
    info["type"] = atype
    if isinstance(ne, int) and ne > 0:
        info["experts"] = ne
    if isinstance(nep, int) and nep > 0:
        info["active_experts"] = nep
    mpe = cfg.get("max_position_embeddings")
    if isinstance(mpe, int) and mpe > 0:
        info["context_length"] = mpe
    return info


def parse_name(name):
    s = name
    msize = re.search(r"[-_ ]?\d+(?:\.\d+)?[bBmM](?:[-_ ]?A\d+(?:\.\d+)?[bB]?)?$", s)
    size_tag = ""
    core = s
    if msize:
        size_tag = msize.group(0).strip("-_ ")
        core = s[:msize.start()].rstrip("-_ ")
    mver = re.search(r"(\d+\.\d+)$", core)
    version = None
    if mver and core[:mver.start()].strip("-_ "):
        version = tuple(int(x) for x in mver.group(1).split("."))
        core = core[:mver.start()].rstrip("-_ ")
    return core, size_tag, version


def derive_family(org, name):
    for fam, spec in REQUIRED.items():
        if org == spec["org"]:
            return fam
    core, _, _ = parse_name(name)
    for suf in ["thinking", "instruct", "dev", "chat", "pro", "preview", "mini",
                "tiny", "flash", "coder", "code", "assistant", "exp", "ultra",
                "lite", "reason", "reasoning", "vision"]:
        if core.lower().endswith("-" + suf):
            core = core[: -(len(suf) + 1)]
    core = core.strip("-_ ")
    return core or name


def build_candidate(mid, must_include=False, family_override=None, superseded_by=None, note=""):
    d = fetch_full(mid)
    time.sleep(0.08)
    if d is None:
        return None
    org = d.get("author") or mid.split("/", 1)[0]
    name = mid.split("/", 1)[1]
    st = d.get("safetensors") or {}
    total = st.get("total")
    if not isinstance(total, int) or total <= 0:
        return None
    if total < MIN_P or total > MAX_P:
        return None
    created = (d.get("createdAt") or "")[:10]
    if created < CUTOFF:
        return None
    cfg = d.get("config") or {}
    pt = d.get("pipeline_tag")
    if pt is None:
        pt = (d.get("transformersInfo") or {}).get("pipeline_tag")
    if pt not in KEEP_PT:
        return None
    lic = (d.get("cardData") or {}).get("license")
    if isinstance(lic, list):
        lic = lic[0]
    arch = arch_info(cfg)
    arch["modalities"] = modalities(pt)
    if lic:
        arch["license"] = lic
    family = family_override or derive_family(org, name)
    params_b = round(total / 1e9, 1)
    ne = cfg.get("num_experts")
    nep = cfg.get("num_experts_per_tok")
    if isinstance(ne, int) and ne > 1:
        act = int(nep) if isinstance(nep, int) else "?"
        pnote = f"{params_b}B total (A{act}B active) MoE" + (f", {ne} experts" if ne else "")
    else:
        pnote = f"{params_b}B dense"
    ev = (f"HF repo '{mid}' owned by developer org '{org}'; safetensors total={total} "
          f"({params_b}B); no quant/finetune/merge markers in name; license={lic or 'n/a'}")
    cand = {
        "model_id": mid,
        "display_name": name,
        "org": org,
        "family": family,
        "param_count_b": params_b,
        "param_count_note": pnote,
        "architecture": arch,
        "official_release_date": created,
        "hf_url": f"https://huggingface.co/{mid}",
        "likes": d.get("likes") or 0,
        "officiality_evidence": ev,
        "current_version": True,
        "notes": note,
    }
    if must_include:
        cand["must_include_family"] = True
    if superseded_by:
        cand["superseded_by"] = superseded_by
        cand["current_version"] = False
    return cand


def main():
    pool = {}

    for fam, spec in REQUIRED.items():
        for nm in spec["current"]:
            pool[f"{spec['org']}/{nm}"] = {"kind": "required", "fam": fam}
    for fam, line in LINEAGE.items():
        for mid, sup in line.items():
            pool[mid] = {"kind": "lineage", "fam": fam, "sup": sup}

    req_orgs = {spec["org"] for spec in REQUIRED.values()}
    dev_orgs = [o for o in REAL_DEVELOPER_ORGS
                if o not in req_orgs and o not in BLOCKLIST]
    print(f"dev_orgs={len(dev_orgs)} (curated real developer orgs)")

    def eligible(m):
        if m["createdAt"] < CUTOFF:
            return False
        nm = m["id"].split("/", 1)[1]
        if is_derived(nm) or is_base(nm) or is_specialized(nm):
            return False
        if m["pipeline_tag"] is not None and m["pipeline_tag"] not in KEEP_PT:
            return False
        return True

    for org in sorted(dev_orgs):
        for m in org_models(org):
            if not eligible(m):
                continue
            pool.setdefault(m["id"], {"kind": "org", "org": org,
                                      "likes": m["likes"], "downloads": m["downloads"]})

    # Site-wide listing sweeps (catch eligible models from orgs not in the curated
    # list): by likes, by downloads, and newest-created (early-stops at the cutoff).
    # min_created early-stop is only sound for a createdAt-sorted listing (likes/
    # downloads order is not chronological, so an old popular model would abort it).
    for sort_key, pages in (("likes", LIKES_PAGES), ("downloads", DOWNLOADS_PAGES),
                            ("createdAt", CREATED_PAGES_MAX)):
        min_created = CUTOFF if sort_key == "createdAt" else None
        for m in scan_listing(sort_key, pages, min_created=min_created):
            org = m["author"]
            if org in BLOCKLIST or m["id"] in pool:
                continue
            if not eligible(m):
                continue
            pool[m["id"]] = {"kind": "org", "org": org,
                             "likes": m["likes"], "downloads": m["downloads"]}

    print(f"pool={len(pool)}")

    req_ids = [mid for mid, meta in pool.items() if meta["kind"] in ("required", "lineage")]
    org_ids = [mid for mid, meta in pool.items() if meta["kind"] == "org"]
    org_ids.sort(key=lambda m: -pool[m].get("likes", 0))
    fetch_ids = req_ids + org_ids
    if len(fetch_ids) > MAX_FETCH:
        fetch_ids = req_ids + org_ids[:MAX_FETCH - len(req_ids)]
    print(f"fetch_pool={len(fetch_ids)} (required/lineage={len(req_ids)})")

    cands = []
    for mid in fetch_ids:
        meta = pool[mid]
        fam = meta.get("fam")
        must = meta["kind"] in ("required", "lineage")
        sup = meta.get("sup")
        force = fam
        note = ""
        if meta["kind"] == "required":
            note = f"required family '{fam}'"
        elif meta["kind"] == "lineage":
            note = f"required family '{fam}'; older version kept for lineage"
        c = build_candidate(mid, must_include=must, family_override=force,
                            superseded_by=sup, note=note)
        if c:
            cands.append(c)

    cands = dedupe(cands)
    cands = dedupe_variants(cands)
    cands = apply_current_version(cands)

    cands.sort(key=lambda c: (not c.get("must_include_family", False),
                              not c.get("current_version", True),
                              -c.get("likes", 0)))

    roster = {
        "generated_at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "method": (
            "HF models API. For a curated set of real developer orgs, list each org's "
            f"models (sort=createdAt, limit {ORG_LIMIT}) and keep those released >= {CUTOFF} "
            "whose names carry no quantization/finetune/merge markers, are not base "
            "checkpoints, and are text-generation / image-text-to-text / any-to-any "
            "(org-owned by the developer = official weights). Also include required "
            "families Ornith / Ling / Spark X at their current in-range versions plus older "
            "in-range lineage versions. Full metadata per candidate: keep "
            "safetensors.total in [4B,285B] and createdAt>=cutoff. De-dupe, then "
            "current-version rule (newer decimal version of same family+size supersedes). "
            "Candidate pool for orchestrator to finalize to the target model count."
        ),
        "candidates": cands,
    }

    out = os.path.join(ROOT, "data", "raw", "roster.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w") as f:
        json.dump(roster, f, indent=2)

    cur = [c for c in cands if c.get("current_version", True)]
    print(f"wrote {out}: {len(cands)} candidates ({len(cur)} current-version)")
    print("must_include: " + ", ".join(
        c["model_id"] for c in cands if c.get("must_include_family")))
    print("\ncurrent-version in-range:")
    for c in cur:
        tag = "*" if c.get("must_include_family") else " "
        print(f"  {tag} {c['model_id']:48s} {c['param_count_b']:>6}B {c['official_release_date']} fam={c.get('family')}")
    print("\nsuperseded:")
    for c in cands:
        if not c.get("current_version", True):
            print(f"    {c['model_id']:48s} -> {c.get('superseded_by')}")


def dedupe(cands):
    seen = {}
    for c in cands:
        seen.setdefault(c["model_id"], c)
    return list(seen.values())


def dedupe_variants(cands):
    groups = {}
    for c in cands:
        canon = strip_dtype(c["display_name"])
        groups.setdefault((c["org"], canon), []).append(c)
    out = []
    for cs in groups.values():
        cs.sort(key=lambda c: (-c.get("likes", 0), len(c["display_name"])))
        out.append(cs[0])
    return out


def apply_current_version(cands):
    by_org = defaultdict(list)
    for c in cands:
        by_org[c["org"]].append(c)
    for org, cs in by_org.items():
        parsed = [(c, *parse_name(c["display_name"])) for c in cs]
        for c, core_c, size_c, ver_c in parsed:
            if not c.get("current_version", True) or ver_c is None:
                continue
            for d, core_d, size_d, ver_d in parsed:
                if d is c or not d.get("current_version", True) or ver_d is None:
                    continue
                if core_c == core_d and size_c == size_d and ver_d > ver_c:
                    c["current_version"] = False
                    c["superseded_by"] = d["model_id"]
                    c["notes"] = (c.get("notes", "")
                                  + f" [superseded by newer version {d['display_name']}]").strip()
                    break
    return cands


if __name__ == "__main__":
    main()
