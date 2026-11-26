# Tiny League

A knowledge base of **benchmark scores for recent open-weight AI models**, built to
support comparisons, tables, and charts.

**Live:** <https://tinyleague.org> · **Community:** [Discord](https://discord.gg/DQ6E6eJZVJ)
· **Contributing:** [CONTRIBUTING.md](CONTRIBUTING.md)

## Criteria (pinned in `data/meta.json`)
- **Param range:** 1.5B–285B (inclusive), total parameters.
- **Age:** released on/after the cutoff date (5 months back → `2026-04-05`).
- **Official weights only:** no GGUF / AWQ / FP8 / GPTQ / bnb / torchao / LoRA /
  finetune / merge / abliterated / uncensored re-uploads.
- **Current version preferred:** a newer release supersedes an older one of the same
  family/size, though two closely-timed releases can both appear.

## Source-of-truth policy
Every score carries a `source` (keyed into `data/sources.json`) and, where possible,
a `source_url`. Priority:
1. **Official HF model card / tech report** — primary.
2. **Artificial Analysis benchmarks / vendor blog** — fill gaps (no AA Index).
3. **Leaderboards (LMArena, Open LLM Leaderboard) / official X posts** — corroborates.

Rules: never fabricate a number; missing = absent or `null`; when two sources
disagree, keep the primary value and log it under `conflicts` (not silently
overwritten). Benchmark names are canonicalized in `scripts/merge.py` (`CANON_BENCH`)
so the same benchmark is comparable across models; eval specifics live in
`subtask`/`notes`, not the name.

## Data model
| File | Contents |
|---|---|
| `data/models.json` | Roster: per-model definition, params, architecture, **vision support** (`supports_vision`), release date, HF link, officiality evidence. |
| `data/scores.json` | Merged per-model benchmark scores (`{benchmark, subtask?, score, metric?, source, source_url?, notes?}`), plus `gaps` and `conflicts`. |
| `data/sources.json` | Source registry (type, reliability, priority). |
| `data/meta.json` | Run metadata + criteria (cutoff, range, required families). |
| `data/raw/<org>__<name>.draft.json` | Cleaned table extraction of each model card (intermediate). |
| `data/raw/<org>__<name>.json` | Per-model research record (one per model). |
| `out/` | The built site (deployable as-is): home, models, scores matrix, benchmarks + one leaderboard per benchmark, compare, about. |

Schemas in `schema/` are enforced by `scripts/validate.py`.

## Regenerating
```bash
.venv/bin/python scripts/finalize_roster.py   # rebuild data/models.json (roster is curated/verified)
.venv/bin/python scripts/extract_card.py      # re-pull card drafts -> data/raw/*.draft.json
.venv/bin/python scripts/merge.py             # data/raw/*.json -> data/scores.json (canonicalizes names)
.venv/bin/python scripts/validate.py          # schema + range/age/officiality + coverage + conflicts (PASS/FAIL)
.venv/bin/python scripts/build_v2.py          # -> out/ (home, models, matrix, benchmarks/*, compare, about)
```
`extract_card.py` handles HF cards that embed benchmark tables in HTML *or* markdown;
models whose card has no parseable table are read directly from the raw README by the
research step.

## Dashboard
`out/` is a small static site — no framework, no client-side router:

- **Models** — the roster, sortable on every column, with a text filter.
- **Scores** — models × benchmarks matrix; colour is scaled within each column over the
  models currently shown, click a column to sort by it, ↗ opens that benchmark's leaderboard.
- **Benchmarks** — 115 benchmarks grouped by domain with jump chips, each with its own
  leaderboard, source links and sibling versions.
- **Compare** — up to five models side by side, best-in-row highlighted.

One filter bar (min/max params, MoE only, vision only) applies across Models, Scores,
Benchmarks, leaderboards and Compare, and follows you between pages.

## License

Three layers, deliberately different:

| What | License | File |
|---|---|---|
| Source code (`scripts/`, `schema/`, `scripts/web/`) | MIT | [`LICENSE`](LICENSE) |
| Benchmark data (`data/`, `out/`) | CC BY 4.0 | [`LICENSE-DATA`](LICENSE-DATA) |
| Name, logo and wordmark ("Tiny League") | **reserved** | [`NOTICE`](NOTICE) |

The data may be reused and republished, including commercially, as long as
credit is given:

> Benchmark data from Tiny League (https://tinyleague.org), CC BY 4.0.

The name and logo are **not** covered by either license, so forks must use a
different name and identity. That is the usual arrangement for an open dataset
with a curated brand, and it keeps the attribution meaningful.

## Notes / known limitations
- The AA Intelligence Index is not tracked: AA's coverage of small models is poor and
  newer releases lack it entirely. Individual AA benchmarks still fill gaps.
- Some cards are thin by nature (e.g. `Ling-3.0-tiny`, agent-specialized
  `Qwen-AgentWorld-35B-A3B`); these have few benchmarks and their missing standard
  metrics are recorded under `gaps`.
- `validate.py` prints an informational `conflicts` list (e.g. a model card that
  reports a benchmark in two tables); the primary value is kept.
