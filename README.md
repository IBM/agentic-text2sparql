# ASTER: Agentic Text-to-SPARQL with Task Skills, Autonomous Exploration, and Refinement

ASTER is a general Text2SPARQL approach for converting natural-language questions into executable SPARQL queries over knowledge graphs. It uses a multi-skill pipeline orchestrated by [OpenCode](https://opencode.ai) to search, explore, generate, execute, validate, and refine queries. Wikidata is the primary knowledge graph used in this repository.

## Overview

Given a natural-language question in English, the agent:

1. **Parses intent** - identifies entities, relations, filters, and expected output shape
2. **Searches Wikidata** - resolves entity/property names to QIDs/PIDs
3. **Explores the graph** - verifies property directions and discovers paths
4. **Generates SPARQL** - constructs a query from verified evidence
5. **Executes and validates** - runs the query and checks results for correctness
6. **Repairs if needed** - iteratively fixes queries that fail or return implausible results

## WikiKGQA: Wiki-Based Knowledge Graph Question Answering Challenge

ASTER was evaluated using the [WikiKGQA: Wiki-Based Knowledge Graph Question Answering Challenge](https://wikikgqa.org/), which evaluates systems that answer natural-language questions over Wikidata by generating a single SPARQL query for each question.

The QAWiki-based challenge data includes public training questions, SPARQL queries, and metadata. ASTER was evaluated on the English tracks, which vary across two dimensions:

- **Language**: English
- **Input setting**: question only, or question plus entity/property mention annotations

This gives two English KGQA variants:

- KGQA from the input question alone
- KGQA from the input question together with mention annotations for entities and relations in Wikidata.

The challenge uses Macro QALD F1 on held-out data, computed from the answers returned by each generated query. This repository contains the pipeline, runners, evaluation scripts, and result packaging used for that evaluation, with checked-in outputs focused on the English runs.

### Results

ASTER's performance across the English WikiKGQA evaluation settings is shown below. F1 denotes Macro QALD F1. For the blind test sets, only the macro F1 scores were available; per-question outcome counts were not released. All experiments used the GPT-5.5 model.

| Language | Mentions | Split | Blind | N | Correct | Partial | Wrong | Macro F1 |
|----------|----------|-------|-------|---:|--------:|--------:|------:|---------:|
| English | No mentions | Train | No | 317 | 256 | 27 | 34 | **0.8643** |
| English | No mentions | Dev | No | 100 | 83 | 10 | 7 | **0.8940** |
| English | With mentions | Dev | No | 100 | 86 | 8 | 6 | **0.9042** |
| English | No mentions | Test | Yes | 75 | -- | -- | -- | **0.8074** |
| English | With mentions | Test | Yes | 75 | -- | -- | -- | **0.8755** |

The public leaderboard results are available under the **Test** tab on the following WikiKGQA Challenge 2026 pages in Codabench:

- [EN-WITH-MENTIONS](https://www.codabench.org/competitions/15591/#/results-tab)
- [EN-NO-MENTIONS](https://www.codabench.org/competitions/15592/#/results-tab)

## Project Structure

```
agentic-text2sparql/
├── .agents/
│   └── skills/
│       ├── few-shot-examples/       Reusable SPARQL pattern examples
│       ├── graph-exploration/       Wikidata graph inspection tools
│       ├── sparql-execution/        SPARQL execution and result validation
│       ├── sparql-generation/       SPARQL construction and validation
│       ├── text2sparql/             Top-level pipeline orchestrator
│       └── wikidata-search/          Wikidata entity/property resolution
├── data/
│   ├── en_no_mentions_*_questions.json   English questions without mentions
│   └── en_with_mentions_*_questions.json English questions with mentions
├── outputs/
│   └── demo/
│       ├── README.md                 Description of the demo run and artifacts
│       ├── dev_112_answer.json        Extracted answer array
│       ├── dev_112_session.log       Complete OpenCode session export
│       ├── dev_112_session.trace.md  Human-readable session trace
│       └── dev_112_sparql.json       Extracted SPARQL query
├── src/
│   ├── analyze_session_logs.py            Session log statistics
│   ├── evaluate_qald_f1.py                QALD F1 evaluation
│   ├── fill_submission.py                 Benchmark submission helper
│   ├── format_session_log.py              Session trace formatter
│   ├── generate_agent_execution_report.py Execution report generator
│   ├── opencode_client.py                 OpenCode server client
│   ├── run_text2sparql.py                 Runner without pre-resolved mentions
│   └── run_text2sparql_with_mentions.py   Runner with pre-resolved mentions
├── .github/                            GitHub repository configuration
├── .gitignore                          Git ignore rules
├── .env.example                       Environment variable template
├── CHANGELOG.md                        Project change history
├── CODE_OF_CONDUCT.md                  Community standards
├── CONTRIBUTING.md                     Contribution guidelines
├── LICENSE                             Apache 2.0 license
├── MAINTAINERS.md                      Maintainer information
├── opencode.json                       OpenCode provider/model/permission config
├── pyproject.toml                      Python project metadata and dependencies
├── README.md                           Project documentation
├── .travis.yml                         Travis CI configuration
├── .whitesource                         WhiteSource scanning configuration
```

## Requirements

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) package manager
- [OpenCode CLI](https://opencode.ai/install)
- Network access to Wikidata APIs (wikidata.org, query.wikidata.org)
- `LLM_API_KEY` for the configured LLM provider you use.

## Setup

```bash
# Install dependencies
uv sync
```

Create a `.env` file in the repo root if you want OpenCode runs to load credentials automatically:

```bash
LLM_API_KEY=...
OPENCODE_SERVER_PASSWORD=...   # optional
OPENCODE_SERVER_USERNAME=...   # optional, defaults to opencode
```

Before running OpenCode, correctly configure `opencode.json` to point to your chosen LLM provider and model. The repository includes an IBM LiteLLM configuration as an example, using the default model `ibm-litellm/azure/gpt-5.5`; update it and the corresponding credentials in `.env` when using a different provider. OpenCode supports a wide variety of LLM providers. See the [OpenCode provider documentation](https://opencode.ai/docs/providers) for provider-specific configuration instructions.

## Sample Data

The `data/` directory contains five English question files used as inputs for local runs and benchmark evaluation:

| File | Description |
|------|-------------|
| `en_no_mentions_train_questions.json` | Training questions without pre-resolved entity or property mentions |
| `en_no_mentions_dev_questions.json` | Development questions without pre-resolved entity or property mentions |
| `en_no_mentions_test_questions.json` | Test questions without pre-resolved entity or property mentions |
| `en_with_mentions_dev_questions.json` | Development questions with pre-resolved Wikidata entity and property mentions |
| `en_with_mentions_test_questions.json` | Test questions with pre-resolved Wikidata entity and property mentions |

Each entry contains a natural-language question and a `q_id`. Mentions-aware files also include optional pre-resolved Wikidata entity/property IDs. Ground-truth answer files used for scoring are external to ASTER and can be downloaded from the [WikiKGQA Codabench competition](https://www.codabench.org/competitions/15358/). Pass the downloaded files to `src/evaluate_qald_f1.py` via `--ground-truth`.

## Usage

### Batch Evaluation

Run the agent on a set of questions without mentions:

```bash
# Run on a no-mentions dev set
uv run python src/run_text2sparql.py \
  --input data/en_no_mentions_dev_questions.json \
  --split dev \
  --output-dir outputs/my-run \
  --parallel 4

# Re-run a small subset and disable resume
uv run python src/run_text2sparql.py \
  --input data/en_no_mentions_dev_questions.json \
  --split dev \
  --output-dir outputs/my-run \
  --question-ids 0 1 2 \
  --no-resume

# Enable few-shot retrieval from train examples
uv run python src/run_text2sparql.py \
  --input data/en_no_mentions_dev_questions.json \
  --split dev \
  --output-dir outputs/my-run-fewshot \
  --examples train \
  --parallel 4

# Run the mentions-aware pipeline
uv run python src/run_text2sparql_with_mentions.py \
  --input data/en_with_mentions_dev_questions.json \
  --split dev \
  --output-dir outputs/my-run-with-mentions \
  --parallel 4

# Evaluate results against ground truth
uv run python src/evaluate_qald_f1.py \
  --results-dir outputs/my-run \
  --ground-truth /path/to/en_no_mentions_dev.json \
  --split dev \
  --verbose
```

Both runners support the same core options:

- `--question-ids` to run only selected question IDs
- `--parallel` to process multiple questions concurrently
- `--no-resume` to ignore existing outputs
- `--examples {none,train,all}` to control few-shot retrieval
- `--password` to pass OpenCode server HTTP auth explicitly

### Individual Skill Testing

```bash
# Search for entities
uv run python .agents/skills/wikidata-search/scripts/wikidata_search.py \
  --query "Albert Einstein" --type item --limit 5

# Explore the graph
uv run python .agents/skills/graph-exploration/scripts/graph_explorer.py \
  --entity Q937 --mode outgoing --limit 10

# Execute a SPARQL query
uv run python .agents/skills/sparql-execution/scripts/sparql_executor.py \
  --sparql "SELECT ?item WHERE { ?item wdt:P31 wd:Q6256 . } LIMIT 5"

# Validate SPARQL syntax
uv run python .agents/skills/sparql-generation/scripts/sparql_generator.py \
  --mode validate \
  --sparql "SELECT ?x WHERE { ?x wdt:P31 wd:Q5 . } LIMIT 10"
```

### Session Analysis And Reporting

```bash
# Summarize one log file or an entire results directory as JSON
uv run python src/analyze_session_logs.py \
  outputs/june-29-en-with-mentions-dev

# Emit aggregate-only stats to a JSON file
uv run python src/analyze_session_logs.py \
  outputs/june-29-en-with-mentions-dev \
  --aggregate-only \
  --output outputs/june-29-en-with-mentions-dev/session_stats.json

# Generate a markdown execution report for a run
uv run python src/generate_agent_execution_report.py \
  data/en_with_mentions_dev_questions.json \
  outputs/june-29-en-with-mentions-dev
```

## Evaluation

ASTER is evaluated using the QALD F1 metric (macro-averaged per-question F1):

| Metric | Description |
|--------|-------------|
| Precision | Fraction of system answers that are correct |
| Recall | Fraction of gold answers that the system found |
| F1 | Harmonic mean of precision and recall |
| Macro F1 | Average F1 across all questions |

## Agent Skills

| Skill | Description |
|-------|-------------|
| `text2sparql` | Top-level orchestrator that chains all skills |
| `wikidata-search` | Resolves entity/property names to Wikidata QIDs/PIDs |
| `graph-exploration` | Explores the Wikidata graph to verify paths and directions |
| `sparql-generation` | Generates SPARQL from verified entities and properties |
| `sparql-execution` | Executes queries and validates results |
| `few-shot-examples` | Provides reusable examples of common SPARQL patterns |

## Key Design Principles

1. **Evidence-based**: Never guess QIDs/PIDs. Always search and verify first.
2. **Iterative**: If a query fails, diagnose the problem and repair (max 3 retries).
3. **Minimal complexity**: Start with the simplest query. Only add complexity when needed.
4. **Trust the endpoint**: Return whatever the SPARQL endpoint gives back. Don't override with world knowledge.
5. **No over-filtering**: Only add constraints explicitly stated in the question.

## License

Licensed under the [Apache License, Version 2.0](LICENSE).

## IBM Public Repository Disclosure

All content in this repository including code has been provided by IBM under the associated open source software license and IBM is under no obligation to provide enhancements, updates, or support. IBM developers produced this code as an open source project (not as an IBM product), and IBM makes no assertions as to the level of quality nor security, and will not be maintaining this code going forward.
