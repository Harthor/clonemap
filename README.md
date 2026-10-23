# clonemap

**Which functions do many independent apps keep rewriting by hand?**

clonemap is a probe, not a product. It clones a few thousand Django and LLM apps from GitHub, extracts every function,
groups functions that do the same thing with *different* code, and compares each group against a control set of ordinary
Python repos. The output is a short list of candidates for human review: places where a library may be missing, or where an
existing one is not being found.

An explorer of the results lives in [`site/`](site/) (a static page; serve the folder or publish it with GitHub Pages).

## The problem

Libraries usually get built when someone asks for them. This project looks for the opposite signal: needs revealed by supply.
If hundreds of unrelated owners write the same helper with their own code, that is evidence of a recurring need, regardless of
whether anybody filed an issue or asked on a forum.

The hard part is telling a real recurring need apart from things every Python program does (argument parsing, logging,
config loading) and from the idiomatic boilerplate a framework asks you to write (Django forms, DRF serializers).

## Method

| # | Stage | Script | What it does |
|---|---|---|---|
| 1 | Select | `s1_select.py` | Candidate pool of 71,362 Python repos pushed in the last two years: an existing GitHub corpus ([gapfinder](https://github.com/Harthor/gapfinder), mostly ≥100 stars) plus the GitHub Search API (≥3 stars). 20,176 were checked one by one with GraphQL: no forks, one repo per owner, 2k–50k lines of Python (estimated from language bytes), no tutorials, boilerplates or paper code, nothing published on PyPI. Domain comes from declared dependencies: `django`, or an LLM SDK (`openai`, `anthropic`, `langchain`, `litellm`, …) in repos created since 2024. |
| 2 | Download | `s2_download.py` | Shallow, sparse clone of `*.py` only, pinned to the commit seen in stage 1. |
| 3 | Parse | `s3_parse.py` | tree-sitter: functions and methods of ≥10 non-blank lines. Excludes tests, migrations, vendored code, generated code (protobuf, OpenAPI clients, Django `manage.py`/`wsgi.py`/`asgi.py`, copied HuggingFace `modeling_*.py`) and files that appear verbatim in ≥5 repos. |
| 4 | Collapse copies | `s4_dedup.py` | MinHash + LSH (Jaccard ≥0.8 on 5-token shingles) merges copy-paste into one variant. The target is *same intent, different code*. |
| 5 | Embed | `s5_embed.py` | `Salesforce/codet5p-110m-embedding` (256-d), locally on Apple MPS, truncated to 256 tokens, cached by content hash. |
| 6 | Cluster | `s6_cluster.py`, `s6b_annotate.py` | BERTopic (UMAP + HDBSCAN), no LLM representation. Each cluster is counted by distinct owners and scored against the control group; framework idioms are flagged from the AST. |
| 7 | Report | `s7_report.py` | Local HTML views by owners and by domain. |
| 8 | Label | `s8_label.py`, `s8b_describe_en.py` | Two models label the top clusters (below); Haiku also writes a plain-English name and one-line description for the explorer. |
| 9 | Summarize | `s9_resumen.py` | Confirmed utilities and whether their repos already declare a library that solves them. |
| 10 | Export | `s10_export_site.py` | `site/data.json` for the explorer, plus the static HTML of its head, headline, numbers and cards. |
| 11 | Preview image | `s11_og_image.py` | `site/og.png` (1200×630) for link previews, rendered with headless Chrome. |

Every stage is a separate, idempotent script that caches its output and reads its parameters from `config.yaml`.
Seed 42 throughout.

### Control group

300 ordinary Python repos, sampled at random from the same corpus with the same "app" filters, verified to have neither
Django nor any LLM SDK in their dependencies. They go through the whole pipeline and are clustered together with the domain
repos. For each cluster, *enrichment* is the share of domain repos that contain it divided by the share of control repos that
do (Laplace-smoothed on both sides, counted by repos, not functions); a one-sided Fisher exact test on the same comparison
gives p, corrected with Benjamini-Hochberg.

Each cluster with ≥8 owners in its main domain lands in one section:

- **Domain-specific**: ≤3 control repos.
- **Enriched, not exclusive**: >3 control repos but ≥5× more common in the domain.
- **Generic**: present in ≥3 % of control repos and <5× enrichment (argparse `main()`, logging setup, YAML config loading end up here).
- **Framework idiom**: ≥60 % of its functions are methods of classes that directly inherit from Django/DRF/Channels base
  classes (`Model`, `ModelForm`, `BaseCommand`, `ModelSerializer`, `APIView`, `ViewSet`, `AsyncWebsocketConsumer`, …), read from the AST.

### Why the control group exists

In the 200-repo pilot, the first domain view ranked clusters by the share of their owners in one domain. LLM apps were 65 % of
all owners, so `main()` with argparse, logging setup and YAML loading looked "LLM-specific": four of them were in the LLM
top 20. Measuring against ordinary Python repos instead of against the mix fixed it; those clusters now sit in the generic
section because they appear in 7–12 % of control repos.

### Labeling

The top 30 domain-specific clusters per domain plus the enriched-not-exclusive ones (65 clusters) were labeled by two models,
each looking at 6 functions from different owners (fixed seed):

- **Jev 1.13** (TypeSafe, `typesafe/jev-1.13` through OpenRouter's System One endpoint) scores four propositions — SDK usage,
  framework idiom, reimplemented utility, other — and returns a probability for each. Its category is the most probable one,
  marked *ambiguous* if it beats the runner-up by less than 0.15.
- **Claude Haiku 5.5** answers the same question as JSON, with a one-line description and up to three PyPI libraries.

A label is **confirmed** when both agree and Jev is not ambiguous: 32 of 65. Each library Haiku proposed was checked against
the PyPI JSON API and scored by Jev ("this library directly solves the need"); 12 of 26 were kept (≥0.7). "Already declared"
is the share of the cluster's repos that list one of those libraries in `requirements*.txt`, `pyproject.toml`, `setup.py`,
`setup.cfg` or `Pipfile`, out of all the cluster's repos (a repo with no declared dependencies counts as not using one).

## Results

Full run: 3,075 repos (1,750 LLM apps, 1,025 Django apps, 300 control), 259,475 Python files, 420,391 functions, 401,857
distinct variants, 6,066 clusters, 2,905 of them with ≥8 owners. By section: 2,107 domain-specific (1,759 LLM, 348 Django),
5 enriched-not-exclusive, 122 generic, 77 framework idioms.

**Headline.** 496 LLM apps (28.3 %) hand-write a parser for JSON embedded in model output — stripping markdown fences,
skipping `<think>` blocks, finding the outermost braces, retrying `json.loads`. Only 4.0 % of control repos do. Jev accepts
`json_repair` as a direct solution; 2 % of those repos declare it.

**Confirmed reimplemented utilities** (Jev and Haiku agree):

| Section | Domain | What the functions do | Owners | Domain vs control | Libraries accepted by Jev | Already declare one |
|---|---|---|---|---|---|---|
| Enriched, not exclusive | LLM | Extract and parse JSON from free text or LLM responses, tolerating markdown fences, `<think>` blocks and surrounding text | 496 | 28.3 % vs 4.0 % (12 repos) | json_repair 0.64.2 | 2 % (12/496) |
| Domain-specific | LLM | Split text into bounded chunks, with overlap or cuts on paragraph, sentence or heading boundaries | 207 | 11.8 % vs 1.0 % (3) | langchain-text-splitters 1.1.3, chonkie 1.7.0, semchunk 4.1.1 | 10 % (21/207) |
| Domain-specific | LLM | Append a message (role and content) to a conversation history, in a database or in memory, sometimes trimming it | 105 | 6.0 % vs 0.3 % (1) | none accepted | — |
| Domain-specific | LLM | Extract and normalize token-usage counters (prompt, completion, input/output, reasoning) from LLM responses | 88 | 5.0 % vs 0.7 % (2) | none accepted | — |
| Domain-specific | Django | Validate uploaded files (size, extension, real type via magic bytes or headers) | 50 | 4.9 % vs 1.0 % (3) | filetype 1.2.0, python-magic 0.4.27, puremagic 2.2.0 | 20 % (10/50) |
| Domain-specific | Django | Build and send password-reset emails with custom logic | 41 | 4.0 % vs 0.7 % (2) | django-allauth 65.20.1, django-rest-passwordreset 1.6.0 | 17 % (7/41) |

Whether any of these is a real gap is a judgment call left to the reader; the explorer shows 5 example functions per cluster
(first lines only, linked to the exact commit on GitHub).

## Limits

- **Small control.** With 300 control repos a cluster can miss the control by chance, and a significance test needs roughly
  30 LLM owners (20 Django owners) before it can say anything. That is why the sections use simple cut-offs and show
  enrichment and q as information.
- **Star bias.** The control comes from a corpus of mostly ≥100-star repos; most domain repos come from the Search API (≥3 stars).
- **Jev's probabilities are independent** and do not sum to 1 (one cluster scored SDK usage 0.85 and reimplemented utility
  0.51), so 19 of 65 labels came out ambiguous.
- **Two models agreeing is not ground truth.** Labels and library suggestions are leads for review.
- **Declared dependencies only.** Transitive ones (e.g. `langchain-text-splitters` via `langchain`) are not counted.
- **Size estimate.** Repo size was estimated from GitHub language bytes; 320 selected repos have fewer than 2k real lines.
- **Embeddings see 256 tokens.** Longer functions are truncated (about half of them); clusters reflect signatures and the first
  part of the body.
- **One snapshot.** GitHub data as of October 2026; search windows end on 2026-10-21.

## Reproducing it

Requirements: macOS or Linux, Python 3.12+, [uv](https://docs.astral.sh/uv/), git, ~5 GB of disk and a GitHub token.
Stage 1 reads the candidate corpus from a local copy of the gapfinder SQLite database (read-only); without it, the pool comes
only from the Search API and the numbers will differ.

```bash
uv sync
scripts/run_full.sh                         # stages 1–7 (incl. 6b) in full mode, in order; skips finished stages
uv run scripts/s8_label.py --mode full      # paid: needs OPENROUTER_API_KEY in .env
uv run scripts/s9_resumen.py --mode full
uv run scripts/s10_export_site.py --mode full
uv run scripts/s11_og_image.py             # needs Google Chrome
```

Each script also accepts `--mode pilot` (200 repos, outputs in `data/pilot/`) and `--force` to redo a finished stage.
`s6b_annotate.py` can be re-run alone to change the domain view without re-clustering.

Tokens are read at runtime from `.env` files (git-ignored) and never written elsewhere. All intermediate data goes to
`data/` (git-ignored): API caches, clones (3.4 GB), parquet outputs and the embedding cache.

## Cost

- **GitHub and PyPI APIs:** free (GitHub token for rate limits).
- **Compute:** local, on an 8 GB M2 MacBook Air. Full run ≈ 5 h: selection 47 min (plus ~1 h of Search API paging, run once
  and cached), embeddings 3 h 44 min at ~27 functions/s, clustering 8 min, everything else minutes.
- **LLM labeling and descriptions:** **$0.106** in total on OpenRouter, measured from the account balance: $0.072 for
  labeling (including a first pass with a routed model that was discarded because the responding model could not be
  verified, and retries of truncated responses) and $0.034 for the plain-English names and descriptions shown in the explorer.

## Third-party code

The examples and links in the explorer point to public repositories owned by third parties, which keep their own licenses.
clonemap does not redistribute their code: it shows only function signatures and short excerpts (at most 5 lines per
function), each linked to the source file at the exact commit. clonemap's own MIT license (see [LICENSE](LICENSE)) covers
this repository's code and does not apply to those excerpts.

## Repository layout

- `scripts/`: one script per stage, plus shared modules (`common.py`, `deps.py`, `domain_stats.py`, `framework.py`).
- `config.yaml`: every parameter.
- `site/`: static explorer (`index.html` + `data.json`).
- `docs/`: working notes from stage 0 and the pilot, in Spanish.
