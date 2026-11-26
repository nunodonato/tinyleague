# Contributing to Tiny League

Tiny League is a league table of benchmark scores for recent **small
open-weight models**, published as a single self-contained page at
<https://tinyleague.org>. Everything on the site is generated from the JSON in
`data/` by the scripts in `scripts/`.

Thanks for helping. This file is the short version; the long version — the
per-model research workflow, edge cases and the reasoning behind every rule —
lives in [`AGENTS.md`](AGENTS.md).

## Ways to contribute

1. **Add a model.** The most useful contribution, and the most mechanical.
2. **Correct a score.** Model cards get re-uploaded and vendors post updated
   numbers; a wrong cell is worse than a missing one.
3. **Report a missing benchmark.** If a model's card reports a benchmark the
   page doesn't show, that's a bug.
4. **Improve the dashboard.** The page is plain HTML/CSS/JS in `scripts/web/`
   (no framework, no build step beyond inlining).

## Ground rules

These are not style preferences — they decide what gets merged.

- **Official weights only.** No GGUF / AWQ / FP8 / GPTQ / bnb / torchao / LoRA /
  finetune / merge / abliterated / uncensored re-uploads. The repo must be the
  developer's own org, with real non-quantized safetensors.
- **Current versions preferred.** A newer release normally supersedes the older one
  of the same family and size; closely-timed releases may both be accepted.
- **Never fabricate a number.** Missing is missing. If a value cannot be read
  from a source, it is absent or `null` and noted under `gaps` — never
  estimated, interpolated or copied from a sibling model.
- **Reasoning levels:** when a model reports a benchmark at several reasoning
  levels, take the **highest** and record the level in `subtask`/`notes`.
- **Benchmark names are canonical**, and versions live in the name
  (`Terminal-Bench 2.1`, `AIME 2025`, `HMMT Feb 2026`). Eval specifics belong
  in `notes`, never in the name. Versions are never pooled.
- **Every score has a source**, keyed in `data/sources.json`, with a
  `source_url` where one exists.

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

All commands below run from the repository root.

## Adding a model

Given a name, a Hugging Face id (`Org/Model-9B`) or a full HF URL:

```bash
# 1. resolve it, fetch live metadata, check the criteria
.venv/bin/python scripts/add_model.py "Org/Model-9B"

# 2. pull and clean the model card into data/raw/Org__Model-9B.draft.json
.venv/bin/python scripts/extract_card.py Org/Model-9B
```

3. **Research the scores by hand.** Read the draft (comparison tables: columns
   are models, rows are benchmarks — take the column matching this model). If
   the draft has no tables, read the raw card:
   `curl -s https://huggingface.co/Org/Model-9B/raw/main/README.md`. Then write
   `data/raw/Org__Model-9B.json` in the shape of
   `schema/scores.schema.json` — `{model_id, scores: [...], gaps: [...],
   conflicts: [...], retrieved_at}`. If you can, cross-check
   `https://artificialanalysis.ai/models/<slug>` and add any roster benchmark
   the card omits (with its `source` and `source_url`).

4. **Regenerate and validate.**

```bash
.venv/bin/python scripts/kv_cache.py --verify --apply   # derive KV cache from config.json
.venv/bin/python scripts/perf.py --apply                # derive decode speed (after kv_cache)
.venv/bin/python scripts/merge.py                       # raw/*.json -> scores.json
.venv/bin/python scripts/validate.py                    # must print PASS
.venv/bin/python scripts/generate_html.py               # -> out/index.html + sitemap/llms/robots/og.png
```

`validate.py` is the gate: if it prints `FAIL`, the PR is not ready. Two of its
checks catch the most common mistakes — a model that shares fewer than 5
benchmarks with the rest of the roster (it adds a column nobody can compare),
and a missing `kv_cache`/`perf` block (a derivation script was skipped).

**Relevance check.** If `validate.py` reports fewer than 5 shared benchmarks,
say so in the PR description and let a maintainer decide — a model with one
comparable benchmark may still be worth tracking, but it is a judgment call,
not a bug.

## Correcting a score

Change the value in `data/raw/<org>__<name>.json` (not `data/scores.json` — it
is generated), keep the `source`/`source_url` pointing at where the number
comes from, note the reason in `notes`, then re-run `merge.py`,
`validate.py` and `generate_html.py`. If two sources disagree, keep the card's
value as primary and record both under `conflicts`.

## Pull request checklist

- [ ] `validate.py` prints `PASS`
- [ ] `out/` regenerated (`git status` shows the rebuilt files)
- [ ] one model (or one logical change) per PR
- [ ] scores are sourced, and nothing is estimated
- [ ] if you changed the build, the page still works from `file://`

Small, single-purpose PRs get reviewed fast. Large ones tend to sit.

## Licensing of contributions

By opening a PR you agree your contribution is licensed under the same terms as
the project: **code under MIT**, **data under CC BY 4.0**. There is no CLA.

## Help

- Discord: <https://discord.gg/DQ6E6eJZVJ>
- Bugs and requests: GitHub issues (templates are provided)

The project is maintained by one person in their spare time, so issues may sit
for a while. Pull requests that already pass `validate.py` jump the queue.
