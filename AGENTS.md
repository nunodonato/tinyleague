# Tiny League — agent guide

Knowledge base of **benchmark scores for recent open-weight AI models**, designed to
support comparisons, tables, and charts, and published as a single shareable page.

> **Most common task: "add a new model".** Jump to [Add a new model](#add-a-new-model).
> You are usually given just a name or a Hugging Face URL.

## The build

The site is a **static multi-page build** — no framework, no client router:

```
.venv/bin/python scripts/build_v2.py      # -> out/
```

`out/` is the deployable artifact: `index.html` (home), `models.html`, `matrix.html`
(scores matrix) and `scatter.html` (score charts), `benchmarks.html` + one leaderboard per
benchmark under `benchmarks/`, `compare.html`, `about.html`, plus `robots.txt`,
`sitemap.xml`, `llms.txt`, `og.png`
and `feed.xml` (RSS 2.0, one item per `data/changelog.json` entry — the changelog is the
feed, so keep entries dated and one sentence long).

Caddy serves the directory directly, so deploying is:

```
rsync -a --delete out/ nunodonato.com:~/tinyleague/
```

Shared code is in `scripts/tl_common.py` (labels, heat ramp, social card); the palette is
read from `scripts/web/style.css` and the layout from `scripts/web/v2.css`.

## Criteria (pinned in `data/meta.json`)
- **Params:** 4B–285B inclusive (total parameters).
- **Official weights only:** no GGUF / AWQ / FP8 / GPTQ / bnb / torchao / LoRA /
  finetune / merge / abliterated / uncensored re-uploads. Repo must be the developer org.
- **Age:** released on/after the cutoff (5 months back → currently `2026-04-05`).
- **Current version preferred:** a newer release normally supersedes the older one of
  the same family/size (e.g. `granite-4.1`→`4.2`, `Qwen3.6`→`3.8`), but two
  closely-timed releases may both stay when each is independently comparable.
- **Relevance — ≥ 5 existing benchmarks.** A model must report **at least 5 benchmarks
  that another model in the roster also reports** (`MIN_SHARED_BENCH = 5` in
  `validate.py`, printed as the `[relevance]` block). Below that it adds a row nobody can
  compare, so **warn the user and ask for confirmation before adding it** — state how
  many shared benchmarks it would contribute and which. This is a judgment gate, not a
  hard rule: the user may still want it.
- **≥ 20 models**, and always include the **Ornith**, **Ling** and **Spark X** families.

## Source-of-truth policy (for SCORES)
Priority: **official HF model card / tech report first** → Artificial Analysis /
vendor blog fill gaps → official X posts / leaderboards
corroborate. Rules:
- Every score MUST carry a `source` (keyed in `data/sources.json`) and, where possible,
  a `source_url`.
- **Cross-check AA for every model you add.** After recording the card, fetch
  `https://artificialanalysis.ai/models/<slug>` and add any roster benchmark it publishes
  that the card omits (`source: "artificial-analysis"`, with `source_url`). When both
  report the same benchmark, keep the card as primary and log the disagreement under
  `conflicts`; when AA has no number, say so in `gaps`. AA lags on new releases — its
  newer index evals (AA-Briefcase, AA-Omniscience, Terminal-Bench Science, …) are often
  the only ones available, and very new/small models may have no AA page at all.
- **Never fabricate.** Missing = absent or `null`; put it in `gaps`.
- **Reasoning levels:** for reasoning/thinking models that report a benchmark in
  several reasoning levels (e.g. `no reasoning` / `low` / `high`, or `thinking` vs
  `non-thinking`), ALWAYS take the **highest reasoning level** value. Record the level
  in `subtask`/`notes` (e.g. `subtask: "high reasoning"`).
- **No AA Intelligence Index.** The index was dropped from the dataset: AA no longer
  covers small models well, and newer releases consistently lack it. Do not reintroduce
  it (or a renamed variant of it) as a benchmark column. Individual AA benchmarks
  (`AA-LCR`, `AA-Omniscience`, ...) are still valid gap-fillers.
- If two sources disagree, keep the primary value and log both under `conflicts`
  (do not silently overwrite).
- Benchmark names are **canonical**: reuse the same spelling across models
  (`MMLU-Pro`, `GPQA Diamond`, `SWE-bench Verified`, `IFEval`, `GPQA Diamond`, ...).
  Eval specifics (harness, effort/`w/ HI`, k, context length, tool mode, domain) go in
  `subtask`/`notes`, never in the name.
- **Versioned benchmarks carry the version in the NAME** so non-comparable versions
   become distinct columns: `Terminal-Bench 2.0` / `2.1` / `Hard`, `AIME 2025` /
   `2026`, `HMMT Feb 2025` / `Feb 2026`, `BFCL v3` / `v4`, `LiveCodeBench v6` / `2408-2505`,
   `DeepSWE 1.1`, `MRCR` / `MRCR v2`. When a card does not
   state the version, leave the benchmark unversioned (e.g. `DeepSWE`, `LiveCodeBench`)
   rather than guessing. **Version aliases that name the same release are folded onto one
   column, not split** (e.g. `Terminal-Bench v2` is the same release as `2.0`; a bare
   `v2` is a spelling variant, not a new version). Each versioned name maps to its family
   in `BENCH_FAMILY` (`scripts/tl_common.py`) — add a new multi-version family there so its rare
   versions are not hidden (see the visibility rule below). Spelling-variant / alias synonyms
   of a versioned name are normalized centrally in `scripts/merge.py` → `CANON_BENCH`
   (add new ones there).

## Repository layout
| Path | What it is |
|---|---|
| `data/models.json` | Roster: per-model definition, params, architecture, **vision support** (`supports_vision`), release date, HF link, officiality evidence. |
| `data/scores.json` | Merged per-model scores + `gaps` + `conflicts` (generated; do not hand-edit). |
| `data/sources.json` | Source registry (type, reliability, priority). |
| `data/meta.json` | Criteria: cutoff, param range, required families, min models. |
| `data/changelog.json` | Site changelog (newest first; rendered on the page). **One bullet per day** — fold that day's changes into one short entry. HARD LIMIT: **one sentence, ~15 words max**, naming only what changed (model id(s) + a 3–4 word descriptor, or the feature). NEVER include benchmark numbers, score rundowns, eval settings, rationale, "not tracked by X" notes, or verification details — those live in `scores.json`/`raw/`. e.g. `Added InternScience/Sage-A1.5 (36B MoE, vision).` |
| `data/configs/<org>__<name>.json` | Snapshot of each model's HF `config.json` pinned to a commit SHA (auto, by `kv_cache.py`); the audit trail for the derived KV-cache numbers. |
| `data/raw/<org>__<name>.json` | One researched score record per model (**double underscore**). |
| `data/raw/<org>__<name>.draft.json` | Cleaned table extraction of the card (intermediate, auto). |
| `schema/*.json` | JSON Schemas — enforced by `validate.py`. |
| `out/` | The built site — **this is what is deployed** (see [The build](#the-build)). |
| `out/robots.txt`, `out/llms.txt`, `out/sitemap.xml` | Crawler/agent metadata, emitted by `build_v2.py`. |
| `out/og.png` | 1200×630 social card (Open Graph / Twitter), built from the data at generate time (`build_og_svg` → `rsvg-convert`; skipped with a warning if that tool is missing, keeping the previous PNG). |
| `scripts/web/style.css` | Design tokens (light + dark). Inlined by the build. |
| `scripts/web/v2.css` | v2 layout layer (masthead, tables, matrix, filters, compare). |
| `scripts/build_v2.py`, `scripts/tl_common.py` | The page generator and its shared helpers. |

## Scripts (all run with `.venv/bin/python`, from the repo root)
| Script | Purpose |
|---|---|
| `scripts/add_model.py <id\|name\|url>` | **Add one model** to `models.json` (resolves id, fetches metadata, enforces criteria). Normal path. |
| `scripts/finalize_roster.py` | (Re)build the whole `models.json` from its curated `CURATED` list. Bulk/initial builds only. |
| `scripts/extract_card.py [ids...]` | Fetch + clean model card(s) → `data/raw/*.draft.json`. |
| `scripts/merge.py` | `data/raw/*.json` → `data/scores.json` (canonicalizes benchmark names). |
| `scripts/validate.py` | Schema + criteria + coverage + conflicts. Prints `PASS`/`FAIL`, exit 0/1. |
| `scripts/build_v2.py` | → `out/` — every page, `sitemap.xml`, `llms.txt`, `robots.txt`, `og.png`. Inlines the palette and `scripts/web/v2.css`. |
| `scripts/kv_cache.py [--verify] [--apply] [--jobs N] [--force]` | Derive each model's **KV-cache footprint** from its `config.json` into `models.json` → `kv_cache` (see [KV cache](#kv-cache-derived-not-a-benchmark)). Dry-run prints a table; `--verify` cross-checks per-layer widths against real safetensors tensor shapes; `--refresh` re-fetches configs; unchanged models are reused and fetched in parallel. |
| `scripts/perf.py [--apply]` | Derive each model's **decode speed** into `models.json` → `perf` (see [Decode speed](#decode-speed-derived-not-a-benchmark)). Needs `kv_cache` and `active_params_b`, so run it **after** `kv_cache.py`. Dry-run prints a table. |

## Add a new model
Given a name, HF id, or URL (e.g. `Qwen/Qwen3.9-32B`, `gemma-4`, or a full URL):

1. **Add the model**
   ```
   .venv/bin/python scripts/add_model.py "<name-or-id-or-url>"
   ```
   It resolves the id (searches HF for bare names), fetches live metadata, and enforces
   the criteria. Read its output:
   - `ALREADY PRESENT` → nothing to do.
   - `HARD: ...` (out of range / before cutoff / not official) → **do not** force it in;
     tell the user why it's out of scope. Use `--force` only if the user explicitly wants
     the exception.
   - `warn: confirm this is the CURRENT version` → **verify** there's no newer
     same-family/size release (check the org's repos on HF). If superseded, stop and say so.
    - On success it prints the exact next commands.
    - The vision flag (`supports_vision`, the **V** badge) is set automatically from the
      HF `config.json` (a `vision_config` entry ⇒ vision-capable).

2. **Extract the card**
   ```
   .venv/bin/python scripts/extract_card.py <org/name>
   ```
   Produces `data/raw/<org>__<name>.draft.json`.

3. **Research the scores (you do this — it's judgment, not a script).**
   - Read the draft. In comparison tables **columns = models, rows = benchmarks**; take
     the column whose header matches the target model's display name, per benchmark row.
     Single-cell rows are group headers. `--`/empty = no data (→ `gaps`).
   - If the draft has 0 tables, fetch the raw card: `curl -s https://huggingface.co/<org/name>/raw/main/README.md`
     (scores may be in prose, markdown, or a figure caption).
   - Write `data/raw/<org>__<name>.json` matching `schema/scores.schema.json` (the
     `score_record` form: `{model_id, scores:[{benchmark, subtask?, score, metric?,
     source, source_url?, notes?}], gaps:[...], conflicts:[...], retrieved_at}`).
      Primary source is `huggingface-model-card` + the HF URL. Fill gaps from AA/X **only
      if you can actually read a number**; otherwise list them under `gaps`.
    - Validate it: `.venv/bin/python -c "import json,jsonschema; jsonschema.validate(json.load(open('data/raw/<org>__<name>.json')), json.load(open('schema/scores.schema.json'))); print('ok')"`
    - Cross-check AA before regenerating (see the [source-of-truth
      policy](#source-of-truth-policy-for-scores)): add any roster benchmark AA reports
      that the card omits, log disagreements in `conflicts`, and note in `gaps` where AA
      has nothing (including "no AA model page").

   **Relevance gate — before regenerating.** Count how many of the recorded benchmarks
   already exist in the roster (canonical names, after `merge.py`; `validate.py` prints
   this as `[relevance]`). If the new model shares **fewer than 5**, **stop and ask the
   user**: name the model, say how many shared benchmarks it would add (and list the
   leftovers that would be single-model columns), and get an explicit OK. On "no", follow
   [Remove a model](#remove-a-model). `Qwen-AgentWorld-35B-A3B` (1) and `Laguna-XS-2.1`
   (4) are the current roster's only sub-5 members — accepted on request.

4. **Regenerate**
   ```
   .venv/bin/python scripts/kv_cache.py --verify --apply
   .venv/bin/python scripts/perf.py --apply
   .venv/bin/python scripts/merge.py && .venv/bin/python scripts/validate.py && .venv/bin/python scripts/build_v2.py
   ```
   `kv_cache.py --verify --apply` derives the new model's KV-cache footprint and checks
   it against the repo's real tensor shapes (see [KV cache](#kv-cache-derived-not-a-benchmark)).
   `perf.py --apply` then derives its **decode speed** (see
   [Decode speed](#decode-speed-derived-not-a-benchmark)); it runs *after* `kv_cache.py`
   because it reads the KV rate. Both blocks are **derived, never scraped**: if the card
   states an active-parameter count (e.g. "35B total, 3B active"), set `active_params_b` +
   `active_params_source: "vendor model card"` in `models.json` **before** running
   `perf.py` — without it the speed falls back to "all parameters active" and is flagged.
   `validate.py` FAILs when either derived block is missing, so a skipped step surfaces.
   `validate.py` MUST print `PASS`. If it reports new benchmark-name duplicates, add the
    synonym to `CANON_BENCH` in `merge.py` and re-run.
    **Update `data/changelog.json` first (one bullet per day; one sentence, ~15 words
    max — see the file-layout row), THEN run `build_v2.py`** — the changelog is
    baked into the HTML at generate time, so
    editing it after generating ships a stale changelog (re-run `build_v2.py`
    and re-deploy if you forget).

5. **Ask the user before deploying.** Say it's ready and the link
   (`https://tinyleague.org`), and **ask whether to upload**. Do NOT
   upload without their explicit OK. On "yes", deploy it (maintainers: the private
   `OPS.md` has the commands).

## Remove a model
When a model must be dropped from the roster (out of scope, superseded, retracted, …):
1. Remove its entry from `data/models.json` (filter out its `model_id`).
2. Delete its research files `data/raw/<org>__<name>.json` and
   `data/raw/<org>__<name>.draft.json`.
3. Regenerate exactly as [step 4](#add-a-new-model) — `merge.py` rebuilds `scores.json`
   without the model and `build_v2.py` drops it from the page. `validate.py` must
   still print `PASS` (the roster must keep ≥ 20 models and the required families).
 Then ask before deploying, as usual.

## KV cache (derived, not a benchmark)
Every model's `models.json` entry carries a `kv_cache` block computed by
`scripts/kv_cache.py` — **never scraped or hand-typed**. It answers "how much VRAM does
a long context cost?" and is shown only in the Scores Heatmap, as the **KV @128K**
column (it is not a benchmark, so it does not sit in the Models table).

- **Source:** the model's own `config.json`, fetched at a pinned commit SHA and
  snapshotted under `data/configs/`. The SHA is stored in `kv_cache.config_revision`.
- **Formula (BF16, batch 1, no TP):** per KV-bearing layer, `2 × n_kv_heads × head_dim × 2`
  bytes per token (K + V). MLA layers (DeepSeek, Ling, LongCat) instead store one
  `kv_lora_rank + qk_rope_head_dim` latent per token (no factor 2). Sliding-window
  layers saturate at their window. Linear/KDA/conv/Mamba layers store no growing KV
  (constant recurrent state, **not** included in the number). Compressed attention
  (DeepSeek-V4 CSA/HCA) pools entries by `compress_ratios`, keeping the rolling window
  at full resolution.
- **Cache copies:** the per-layer geometry is multiplied by everything that allocates
  separate KV slots for the same weights — `attention_modules_per_layer` (LongCat's two
  MLA branches) and `cache_copies` (a looped stack such as Nanbeige's `num_loops: 2`
  indexes the cache per pass, `layer_idx + loop_idx * num_hidden_layers`, unless
  `loop_share_kv` is set). Both come from the config, not from the tensors, so `--verify`
  cannot confirm them.
- **Layer structure** comes from `layer_types` / `layers_block_type` where present; else
  `full_attention_interval`, `layer_group_size` (Ling), or all-layers-attention as a
  last resort (recorded in `provenance`).
- **`--verify` is the reliability check:** it reads the safetensors index (complete
  layer→tensor map) and the header of a few shards (real tensor shapes), asserts that
  the layers computed as KV-bearing are exactly the layers that own KV tensors, and that
  each projection's `out_features` equals the computed width. It also counts attention
  branches per layer (LongCat has two MLA branches per layer → 2× the cache). Multimodal
  towers and MTP/speculative heads are excluded by name. A clean run sets
  `verified: true` and `confidence: high`; problems print to stderr and leave
  `verify_notes`. Run it after adding a model; if it reports a mismatch, fix the geometry
  rule in the script rather than editing the number. A plain `--apply` keeps a previous
  verification (same `config_revision`), so it never silently downgrades a checked model —
  but run `--verify --apply` after changing the formula.
- **Runs are incremental and parallel.** A stored block is reused untouched when its
  `config_revision` and `formula_version` still match, and only models needing work are
  fetched (6 at a time, `--jobs N`), so a repeat full-roster run is local and instant and
  after adding a model only that model hits the network. Therefore **bump
  `FORMULA_VERSION` in `kv_cache.py` whenever you change the geometry rules**, or cached
  blocks stay stale; `--force` recomputes everything, and `--verify --force` re-checks
  every model against the weights.
- **Scope:** excludes sparse-attention indexer caches (DeepSeek-V4, LongCat, Qwen3.8-Flash-
  Next), page/block padding, tensor-parallel sharding, and an FP8 KV cache (which halves
  these numbers). The headline column is the total at **128K tokens** so models with
  different native contexts stay comparable — capped at a model's own maximum when that
  is shorter (never extrapolated); the tooltip carries the per-token rate and the cost at
  each model's own maximum context.
- **KV @128K is the first column of the Scores Heatmap**: `kv_cache.gib_at_ref_ctx` in GiB.
  Lower is better. The cell colour uses the heatmap's ramp on a **fixed log scale**
  (≤ 0.5 GiB = deepest blue, ≥ 32 GiB = palest), so the column reads the same way as the
  benchmark columns without depending on the current roster. A 256K column was tried and
  dropped: for most architectures the cache is simply 2× the 128K figure, so it added
  width without adding information. No active-parameter normalisation: the column answers
  "what has to fit in VRAM beside the weights", which is what people plan with.
  `active_params_b` (vendor-stated for MoE, equal to total for dense;
  `models.json` → `active_params_b` + `active_params_source`) is still recorded and
  still appears in the cell tooltip as "GiB per active-B", but it no longer drives the
  column — **never** invent an active count.

## Decode speed (derived, not a benchmark)
Each model's `perf` block answers "how fast will this feel on a known GPU?" — computed by
`scripts/perf.py`, **never scraped or hand-typed**. Decode at batch 1 is memory-bandwidth
bound: every generated token streams the weights that participate plus the KV cache read
so far.

- **Formula (BF16, batch 1, one sequence, no tensor parallel):**
  `bytes_per_token = active_B × 1e9 × 2 + ctx × kv_kib_per_token × 1024`, then
  `tok/s = effective_bandwidth / bytes_per_token`. `ctx` is capped at the model's native
  context (never extrapolated).
- **Two points are recorded:** `decode_tok_s_fresh` (empty context — weights only) and
  `decode_tok_s_at_ref_ctx` (weights + KV read at 128K), plus `retained_pct`, the share of
  fresh speed kept at long context. Shown in the **Models** table as *Decode fresh* /
  *Decode @128K* (with a bar) and in the **Speed** chart preset.
- **Reference card:** one NVIDIA RTX 4090 (1008 GB/s peak) at a deliberately conservative
  **50%** efficiency = 504 GB/s effective; the GPU, peak, efficiency and effective
  bandwidth are all written into each record so the number is auditable rather than a
  magic constant.
- **`active_params_b` is the input that must be right.** Vendor-stated when the card gives
  it (`35B total, 3B active`); equal to total for dense models
  (`active_params_source: "dense: active = total parameters"`). When no active count is
  published the script falls back to "all parameters active", sets
  `active_params_assumed: true`, and the page shows an asterisk — that **overstates cost
  for a MoE**, so it is a fallback, not a substitute. **Never invent an active count.**
- **`perf` is required and checked.** `validate.py` FAILs if a model is missing `perf` or
  `kv_cache`, which is exactly the symptom of forgetting to re-run a derivation script
  after adding a model.

## Local preview
To show the user the page, open `out/index.html` in **their default browser** —
`xdg-open out/index.html` (from the repo root). Do **NOT** use the chrome-devtools
browser tools for this; that opens a headless/managed Chrome instance, not the user's
own browser.

## The site (v2 pages)

Generated by `scripts/build_v2.py`. Key behaviours, so changes stay consistent:

- **Home** — stats, entry cards, newest models, recent changes.
- **Models** — the roster table; sortable on every numeric column, plus a text filter.
- **Scores (matrix)** — models × benchmarks. Colour comes from the shared 21-step ramp
  (`tl_common.heat_style`) and is computed **within each column over the models currently
  shown**, so a filtered view still reads. Click a column name to sort by it; the ↗ opens
  that benchmark's leaderboard. Columns with fewer than 2 visible models are hidden.
- **Scores (scatter)** — `scatter.html`, the second score view: any two metrics on the axes
  (benchmark score, parameters, KV @128K, decode fresh/@128K, release date), with presets
  (four benchmarks + KV + Speed) and a Custom pair of selects. Drawn as inline SVG by
  `SCATTER_JS` (no chart library); it follows the global filters and re-renders on resize,
  logs a corner glow for the params axis (green = sweet spot, red = big KV on a small model),
  and offers "Show as table". A preset is deep-linkable (`scatter.html#kv`).
- **Nav** — sections with several views are groups (`NAV` in `build_v2.py`): "Scores" renders
  as a dropdown (Matrix / Scatter) and the pages carry a matching Matrix|Scatter switch, so a
  new view (e.g. radar) is one entry in `NAV` plus its page function.
- **Benchmarks** — grouped into domains (Coding, Agentic, Math, Knowledge, Multimodal,
  Instruction, Long context) with sticky jump chips whose counts are recomputed under the
  filters, plus one page per benchmark (`benchmarks/<slug>.html`) with its full leaderboard,
  sources and sibling versions.
- **Compare** — up to five models; rows are benchmarks reported by at least two of them,
  best-in-row highlighted.
- **About** — criteria, sources, derived metrics, licensing.

**Filters.** One bar — min/max params, MoE only, Vision only — rendered by `filter_bar()` on
Models, Scores, Benchmarks, every leaderboard and Compare. Rows carry `data-params` /
`data-moe` / `data-vision`; state lives in `localStorage` (`tl-filters`) so it follows you
across pages. Each page sets `window.TL_APPLY` to re-render after a change (renumber ranks,
recolour the matrix, drop empty columns, update counts).

**Theme.** auto → light → dark, stored in `localStorage` (`tl-theme`) and applied before
first paint. This needs a real origin: on `file://` every page is its own origin in Firefox,
so the choice does not persist — preview over `http://`, not by opening the file.

**Domains.** `DOMAIN_OF` in `build_v2.py` maps benchmark names to domains by ordered keyword
rules; add a rule when a new family appears. `BENCH_FAMILY` in `tl_common.py` groups versions
so siblings link to each other, and drives the slug (`τ²-bench` → `tau2-bench`).

**Colour.** `heat_style()` returns background + text per ramp step with a WCAG AA check;
`build_v2` pre-renders 21 `.hN` classes and the page JS recomputes the bucket from the
visible min/max, so Python and JS can never disagree.

## Deployment (not in this repo)

This repository is the **public** project: data, pipeline, dashboard. Deployment,
hosting and traffic stats live in a private ops folder
(`~/Projects/tinyleague-ops/`, with its own `OPS.md`) because they contain the
server host, the Caddy config and the stats auth hash. `out/` is the deployable
artifact — a fork only needs to serve it statically.

## Setup (only if the venv is missing)
```
python3 -m venv .venv && .venv/bin/pip install -q -r requirements.txt
```
Deps: `requests`, `jsonschema`, `beautifulsoup4`, `lxml`.

## Reliability rules (summary)
- Official-only: developer-org repo, real non-quant safetensors, name not a
  quant/finetune/merge. Log evidence in `officiality_evidence`.
- Age: from `official_release_date` (prefer the vendor's stated date over HF
  `createdAt`) vs the cutoff.
- X: official org posts corroborate a score; if `x.com` is unreachable, fall back to
  the vendor blog or a leaderboard rather than guessing.

## Parallelizing (optional)
For adding many models at once, fan out research across **opencode subagents in herdr**
sibling panes (`herdr pane split` + `herdr agent start <name> --kind opencode`), ~5–7
models each, each writing its own `data/raw/<org>__<name>.json`. One builder agent can
write/refresh the scripts. A single agent is fine for a lone model.

## Known quirks
- Some cards are thin (agent-specialized models); their missing standard metrics live in
  `gaps`.
- Opening `out/index.html` via `file://` logs a harmless "unique security origin"
  console warning; it renders fine.
