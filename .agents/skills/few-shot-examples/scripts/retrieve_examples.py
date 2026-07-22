# Copyright IBM Corp. 2026 - 2026
# SPDX-License-Identifier: Apache-2.0
#

#!/usr/bin/env python3
"""
Retrieve similar SPARQL examples from the ChromaDB collection.

Given a natural-language question, finds the most similar gold-standard
examples from the train/dev sets. Returns the questions and their gold
SPARQL queries as few-shot context for the agent.

Usage:
    uv run python .agents/skills/few-shot-examples/scripts/retrieve_examples.py \
        --query "Which countries have won a FIFA World Cup?" \
        --top-k 5

    # Filter by pattern:
    uv run python .agents/skills/few-shot-examples/scripts/retrieve_examples.py \
        --query "How far is Alpha Centauri?" \
        --top-k 3 \
        --pattern unit_normalization

    # Filter by multiple patterns (OR):
    uv run python .agents/skills/few-shot-examples/scripts/retrieve_examples.py \
        --query "What is the highest Elo ever?" \
        --top-k 3 \
        --pattern superlative,temporal

Output format (JSON):
    {
        "query": "...",
        "num_results": N,
        "results": [
            {
                "q_id": 130,
                "split": "train",
                "question": "How far away is IRAS 14038-3450 from Earth?",
                "sparql": "SELECT ?obj WHERE { wd:Q80655009 p:P2583/psn:P2583/wikibase:quantityAmount ?obj . }",
                "patterns": ["unit_normalization", "statement_level"],
                "similarity": 0.85
            },
            ...
        ]
    }
"""

import argparse
import json
import os
import sys
from pathlib import Path

import chromadb


# Default path to the examples database
DEFAULT_DB_BASE = str(
    Path(__file__).resolve().parent.parent / "data"
)


def _resolve_db_path(scope: str = "train", db_base: str = DEFAULT_DB_BASE) -> str:
    """Resolve the database path based on scope."""
    if scope == "all":
        return str(Path(db_base) / "examples_db_all")
    else:
        return str(Path(db_base) / "examples_db_train")


def retrieve_examples(
    query: str,
    top_k: int = 5,
    db_path: str = None,
    scope: str = "train",
    pattern_filter: str = None,
) -> dict:
    """
    Retrieve similar examples from the ChromaDB collection.

    Args:
        query: The natural-language question to find similar examples for.
        top_k: Number of results to return.
        db_path: Explicit path to the ChromaDB persistent storage. Overrides scope.
        scope: Which database to use: "train" (train only) or "all" (train+dev).
        pattern_filter: Comma-separated pattern tags to filter by (OR logic).

    Returns:
        Dict with query, num_results, and results list.
    """
    if db_path is None:
        db_path = _resolve_db_path(scope)
    if not Path(db_path).exists():
        return {
            "query": query,
            "num_results": 0,
            "results": [],
            "error": f"Database not found at {db_path}. Run build_examples_db.py first.",
        }

    client = chromadb.PersistentClient(path=db_path)

    try:
        collection = client.get_collection("sparql_examples")
    except Exception as e:
        return {
            "query": query,
            "num_results": 0,
            "results": [],
            "error": f"Collection 'sparql_examples' not found: {e}",
        }

    # Build where filter if pattern specified
    where_filter = None
    if pattern_filter:
        # ChromaDB supports $contains for string matching
        patterns = [p.strip() for p in pattern_filter.split(",")]
        if len(patterns) == 1:
            where_filter = {"patterns": {"$contains": patterns[0]}}
        else:
            # OR logic: any of the patterns
            where_filter = {
                "$or": [{"patterns": {"$contains": p}} for p in patterns]
            }

    # Query the collection
    try:
        results = collection.query(
            query_texts=[query],
            n_results=top_k,
            where=where_filter,
        )
    except Exception as e:
        return {
            "query": query,
            "num_results": 0,
            "results": [],
            "error": f"Query failed: {e}",
        }

    # Format results
    formatted_results = []
    if results and results["ids"] and results["ids"][0]:
        for i, doc_id in enumerate(results["ids"][0]):
            metadata = results["metadatas"][0][i]
            distance = results["distances"][0][i] if results.get("distances") else None

            # Convert distance to similarity (ChromaDB uses L2 distance by default)
            similarity = 1.0 / (1.0 + distance) if distance is not None else None

            formatted_results.append({
                "q_id": metadata.get("q_id"),
                "split": metadata.get("split"),
                "question": results["documents"][0][i],
                "sparql": metadata.get("sparql"),
                "patterns": metadata.get("patterns", "").split(","),
                "num_answers": metadata.get("num_answers"),
                "similarity": round(similarity, 4) if similarity else None,
            })

    return {
        "query": query,
        "num_results": len(formatted_results),
        "results": formatted_results,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Retrieve similar SPARQL examples from the examples database."
    )
    parser.add_argument(
        "--query", "-q",
        required=True,
        help="The natural-language question to find similar examples for.",
    )
    parser.add_argument(
        "--top-k", "-k",
        type=int,
        default=5,
        help="Number of similar examples to retrieve (default: 5).",
    )
    parser.add_argument(
        "--db-path",
        default=None,
        help="Explicit path to ChromaDB storage. Overrides --scope.",
    )
    parser.add_argument(
        "--scope", "-s",
        choices=["train", "all"],
        default="train",
        help="Which examples database to use: 'train' (train only, for dev evaluation) "
             "or 'all' (train+dev, for test evaluation). Default: train.",
    )
    parser.add_argument(
        "--pattern", "-p",
        default=None,
        help="Filter by SPARQL pattern (comma-separated, OR logic). "
             "Options: unit_normalization, statement_level, qualifier, count, "
             "ordering, superlative, boolean, subclass_traversal, "
             "location_hierarchy, exclusion, temporal, relative_time, "
             "inverse_property, union, direct_lookup",
    )

    args = parser.parse_args()

    result = retrieve_examples(
        query=args.query,
        top_k=args.top_k,
        db_path=args.db_path,
        scope=args.scope,
        pattern_filter=args.pattern,
    )

    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
