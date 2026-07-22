# Copyright IBM Corp. 2026 - 2026
# SPDX-License-Identifier: Apache-2.0
#

#!/usr/bin/env python3
"""
Fill answers and SPARQL queries into the benchmark submission format.

Takes the original benchmark questions file and a results directory,
then populates the 'answers' and 'query.sparql' fields from the
per-question output files.

Usage:
    uv run python src/fill_submission.py \
        --input test-final-format/wikikgqa2026_test_with_mentions_questions.json \
        --results-dir outputs/june-29-en-with-mentions-test-fewshot \
        --split test \
        --output test-final-format/wikikgqa2026_test_with_mentions_submission.json

Input format (benchmark):
    {
        "dataset": {"id": "..."},
        "questions": [
            {
                "id": 4,
                "question": [...],
                "query": {"sparql": "Optional..."},
                "mentions": [...],
                "answers": ["Mandatory..."]
            }, ...
        ]
    }

Results directory structure:
    <results-dir>/
        <split>_<q_id>_answer.json    — JSON array of answer values
        <split>_<q_id>_sparql.json    — {"sparql": "SELECT ..."}
"""

import argparse
import json
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(
        description="Fill answers and SPARQL into benchmark submission format."
    )
    parser.add_argument(
        "--input", "-i",
        required=True,
        help="Path to the benchmark questions JSON file.",
    )
    parser.add_argument(
        "--results-dir", "-r",
        required=True,
        help="Directory containing per-question answer and SPARQL files.",
    )
    parser.add_argument(
        "--split", "-s",
        default="test",
        help="Split prefix used in result filenames (default: test).",
    )
    parser.add_argument(
        "--output", "-o",
        required=True,
        help="Output path for the filled submission JSON.",
    )

    args = parser.parse_args()

    # Load benchmark questions
    with open(args.input, "r", encoding="utf-8") as f:
        data = json.load(f)

    results_dir = Path(args.results_dir)
    split = args.split

    filled = 0
    missing = 0

    for question in data.get("questions", []):
        q_id = question["id"]

        # Load answer
        answer_file = results_dir / f"{split}_{q_id}_answer.json"
        if answer_file.exists():
            try:
                with open(answer_file, "r", encoding="utf-8") as f:
                    answers = json.load(f)
                if isinstance(answers, list):
                    question["answers"] = answers
                else:
                    question["answers"] = [str(answers)]
                filled += 1
            except (json.JSONDecodeError, Exception) as e:
                print(f"WARNING: Could not parse answer for q_id={q_id}: {e}", file=sys.stderr)
                question["answers"] = []
                missing += 1
        else:
            print(f"WARNING: No answer file for q_id={q_id}: {answer_file}", file=sys.stderr)
            question["answers"] = []
            missing += 1

        # Load SPARQL
        sparql_file = results_dir / f"{split}_{q_id}_sparql.json"
        if sparql_file.exists():
            try:
                with open(sparql_file, "r", encoding="utf-8") as f:
                    sparql_data = json.load(f)
                sparql_query = sparql_data.get("sparql", "")
                if sparql_query:
                    question["query"]["sparql"] = sparql_query
            except (json.JSONDecodeError, Exception) as e:
                print(f"WARNING: Could not parse SPARQL for q_id={q_id}: {e}", file=sys.stderr)

    # Write output
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    print(f"Submission file written to: {args.output}")
    print(f"  Questions filled: {filled}/{filled + missing}")
    print(f"  Missing answers: {missing}")


if __name__ == "__main__":
    main()
