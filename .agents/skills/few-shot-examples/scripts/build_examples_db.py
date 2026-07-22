# Copyright IBM Corp. 2026 - 2026
# SPDX-License-Identifier: Apache-2.0
#

#!/usr/bin/env python3
"""
Build a ChromaDB collection from gold-standard train/dev examples.

Indexes questions with their gold SPARQL queries and answer patterns
so the agent can retrieve similar examples at runtime.

Usage:
    uv run python .agents/skills/few-shot-examples/scripts/build_examples_db.py \
        --train /path/to/en_no_mentions_train.json \
        --dev /path/to/en_no_mentions_dev.json \
        --output .agents/skills/few-shot-examples/data/examples_db

The database stores:
    - Question text (used for similarity search)
    - Gold SPARQL query
    - Answer list
    - Question ID and split (for reference)
    - SPARQL pattern category (for filtering)
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path

import chromadb


def classify_sparql_pattern(sparql: str) -> list[str]:
    """
    Classify a SPARQL query into pattern categories for metadata filtering.

    Returns a list of pattern tags.
    """
    patterns = []

    # Unit normalization patterns
    if "psn:" in sparql or "psv:" in sparql or "wikibase:quantityAmount" in sparql:
        patterns.append("unit_normalization")
    if "wikibase:quantityUnit" in sparql:
        patterns.append("unit_filter")

    # Statement-level patterns (qualifiers)
    if re.search(r"\bp:", sparql) and re.search(r"\bps:", sparql):
        patterns.append("statement_level")
    if re.search(r"\bpq:", sparql):
        patterns.append("qualifier")

    # Aggregation
    if "COUNT" in sparql.upper():
        patterns.append("count")
    if "ORDER BY" in sparql.upper():
        patterns.append("ordering")
    if "GROUP BY" in sparql.upper():
        patterns.append("group_by")
    if "LIMIT 1" in sparql:
        patterns.append("superlative")

    # Boolean
    if sparql.strip().upper().startswith("ASK"):
        patterns.append("boolean")

    # Property paths
    if "P279*" in sparql or "P279+" in sparql:
        patterns.append("subclass_traversal")
    if "P131*" in sparql or "P131+" in sparql:
        patterns.append("location_hierarchy")
    if "P171+" in sparql or "P171*" in sparql:
        patterns.append("taxon_traversal")

    # MINUS / FILTER NOT EXISTS
    if "MINUS" in sparql.upper():
        patterns.append("exclusion")
    if "FILTER NOT EXISTS" in sparql.upper() or "FILTER(!EXISTS" in sparql.upper():
        patterns.append("exclusion")

    # Temporal
    if "P585" in sparql or "P580" in sparql or "P582" in sparql:
        patterns.append("temporal")
    if "YEAR(" in sparql.upper() or "NOW()" in sparql.upper():
        patterns.append("relative_time")

    # Inverse / bidirectional
    if "^" in sparql and "wdt:" in sparql:
        patterns.append("inverse_property")

    # UNION
    if "UNION" in sparql.upper():
        patterns.append("union")

    # VALUES
    if "VALUES" in sparql.upper():
        patterns.append("values_clause")

    # OPTIONAL
    if "OPTIONAL" in sparql.upper():
        patterns.append("optional")

    # COALESCE / BIND
    if "COALESCE" in sparql.upper():
        patterns.append("coalesce")
    if "BIND(" in sparql.upper():
        patterns.append("bind")

    # Simple direct lookup (no complex patterns)
    if not patterns:
        patterns.append("direct_lookup")

    return patterns


def load_gold_data(filepath: str) -> list[dict]:
    """Load gold-standard questions with SPARQL from a benchmark JSON file."""
    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)

    examples = []
    for q in data.get("questions", []):
        q_id = q.get("id")
        sparql = q.get("sparql", "")
        answers = q.get("answers", [])

        # Extract English question
        question_text = ""
        for lang_entry in q.get("question", []):
            if lang_entry.get("language") == "en":
                question_text = lang_entry.get("string", "")
                break

        if question_text and sparql:
            examples.append({
                "q_id": q_id,
                "question": question_text,
                "sparql": sparql,
                "answers": answers,
            })

    return examples


def build_database(
    train_path: str,
    dev_path: str,
    output_dir: str,
):
    """Build the ChromaDB collection from train and dev examples."""
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    # Load examples
    train_examples = load_gold_data(train_path) if train_path else []
    dev_examples = load_gold_data(dev_path) if dev_path else []

    print(f"Loaded {len(train_examples)} train examples")
    print(f"Loaded {len(dev_examples)} dev examples")

    # Create ChromaDB client with persistent storage
    client = chromadb.PersistentClient(path=str(output_path))

    # Delete existing collection if it exists
    try:
        client.delete_collection("sparql_examples")
    except Exception:
        pass

    collection = client.create_collection(
        name="sparql_examples",
        metadata={"description": "Gold-standard SPARQL examples from Wikidata KGQA benchmark"},
    )

    # Index all examples
    ids = []
    documents = []
    metadatas = []

    for split, examples in [("train", train_examples), ("dev", dev_examples)]:
        for ex in examples:
            doc_id = f"{split}_{ex['q_id']}"
            patterns = classify_sparql_pattern(ex["sparql"])

            ids.append(doc_id)
            documents.append(ex["question"])
            metadatas.append({
                "q_id": ex["q_id"],
                "split": split,
                "sparql": ex["sparql"],
                "answers": json.dumps(ex["answers"]),
                "patterns": ",".join(patterns),
                "num_answers": len(ex["answers"]),
            })

    # Add in batches (ChromaDB has batch limits)
    batch_size = 100
    for i in range(0, len(ids), batch_size):
        batch_end = min(i + batch_size, len(ids))
        collection.add(
            ids=ids[i:batch_end],
            documents=documents[i:batch_end],
            metadatas=metadatas[i:batch_end],
        )

    print(f"\nIndexed {len(ids)} total examples into {output_path}")
    print(f"Collection: sparql_examples")

    # Print pattern distribution
    all_patterns = {}
    for m in metadatas:
        for p in m["patterns"].split(","):
            all_patterns[p] = all_patterns.get(p, 0) + 1

    print("\nPattern distribution:")
    for pattern, count in sorted(all_patterns.items(), key=lambda x: -x[1]):
        print(f"  {pattern}: {count}")


def main():
    parser = argparse.ArgumentParser(
        description="Build ChromaDB collection from gold-standard SPARQL examples."
    )
    parser.add_argument(
        "--train",
        default=None,
        help="Path to train gold-standard JSON file.",
    )
    parser.add_argument(
        "--dev",
        default=None,
        help="Path to dev gold-standard JSON file.",
    )
    parser.add_argument(
        "--output-dir", "-o",
        default=".agents/skills/few-shot-examples/data",
        help="Base output directory. Will create 'examples_db_train' and 'examples_db_all' subdirs.",
    )
    parser.add_argument(
        "--scope",
        choices=["train", "all", "both"],
        default="both",
        help="Which databases to build: 'train' (train only), 'all' (train+dev), 'both' (build both).",
    )

    args = parser.parse_args()

    if not args.train and not args.dev:
        print("ERROR: At least one of --train or --dev must be specified.", file=sys.stderr)
        sys.exit(1)

    base_dir = Path(args.output_dir)

    if args.scope in ("train", "both"):
        if not args.train:
            print("ERROR: --train is required for scope 'train' or 'both'.", file=sys.stderr)
            sys.exit(1)
        print("=" * 60)
        print("Building TRAIN-ONLY database...")
        print("=" * 60)
        build_database(
            train_path=args.train,
            dev_path=None,
            output_dir=str(base_dir / "examples_db_train"),
        )

    if args.scope in ("all", "both"):
        if not args.train:
            print("ERROR: --train is required for scope 'all' or 'both'.", file=sys.stderr)
            sys.exit(1)
        print("\n" + "=" * 60)
        print("Building ALL (train+dev) database...")
        print("=" * 60)
        build_database(
            train_path=args.train,
            dev_path=args.dev,
            output_dir=str(base_dir / "examples_db_all"),
        )

    print("\nDone! Databases available:")
    if args.scope in ("train", "both"):
        print(f"  Train only: {base_dir / 'examples_db_train'}")
    if args.scope in ("all", "both"):
        print(f"  All (train+dev): {base_dir / 'examples_db_all'}")


if __name__ == "__main__":
    main()
