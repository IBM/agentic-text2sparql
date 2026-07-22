# Copyright IBM Corp. 2026 - 2026
# SPDX-License-Identifier: Apache-2.0
#

#!/usr/bin/env python3
"""
QALD F1 Evaluation Script.

Computes Macro QALD F1 by comparing system-generated answers against a ground
truth file. Implements the same per-question F1 logic and macro averaging used
by GERBIL (the official QALD evaluation tool).

Answer matching uses exact string comparison (no normalization). The system is
expected to produce answers in the same format as the ground truth:
  - Wikidata entity IDs: "Q23", "Q453"
  - Wikidata property IDs: "P31", "P279"
  - Literal strings: "95", "2018-11-12T00:00:00Z"
  - Booleans: "True" or "False"

Per-question QALD F1 rules:
  - Gold empty AND system empty  -> P = R = F1 = 1.0
  - Gold empty AND system non-empty -> P = R = F1 = 0.0
  - Gold non-empty AND system empty -> P = R = F1 = 0.0
  - Otherwise: standard set-based P, R, F1

Macro QALD F1 = average of per-question F1 values.

Usage:
    uv run python src/evaluate_qald_f1.py \
        --results-dir outputs/en_dev \
        --ground-truth /path/to/en_no_mentions_dev.json \
        --split en_dev

    # With verbose per-question output:
    uv run python src/evaluate_qald_f1.py \
        --results-dir outputs/en_dev \
        --ground-truth /path/to/en_no_mentions_dev.json \
        --split en_dev \
        --verbose

    # Output results to a JSON file:
    uv run python src/evaluate_qald_f1.py \
        --results-dir outputs/en_dev \
        --ground-truth /path/to/en_no_mentions_dev.json \
        --split en_dev \
        --output evaluation_results.json
"""

import argparse
import json
import sys
from pathlib import Path


def to_answer_string(value) -> str:
    """
    Convert an answer value to its string representation for exact matching.

    The competition expects exact string match. Answers are:
      - Wikidata entity IDs: "Q23", "P31"
      - Literal strings: "95", "2018-11-12T00:00:00Z"
      - Booleans: "True" or "False"

    For JSON booleans in the ground truth (true/false), converts to "True"/"False"
    to match the expected system output format.

    Args:
        value: An answer value from JSON (can be str, bool, int, float).

    Returns:
        The string representation used for exact matching.
    """
    # Handle native JSON booleans -> "True"/"False"
    if isinstance(value, bool):
        return "True" if value else "False"

    # Everything else: convert to string as-is
    return str(value)


def to_answer_set(answers: list) -> set:
    """
    Convert a list of answers into a set of strings for set comparison.

    No normalization is performed — uses exact string matching as required
    by the competition evaluation.

    Args:
        answers: List of answer values.

    Returns:
        Set of answer strings.
    """
    return {to_answer_string(a) for a in answers}


def compute_qald_f1(gold_answers: set, system_answers: set) -> tuple:
    """
    Compute per-question QALD precision, recall, and F1.

    Uses exact string matching between gold and system answer sets.

    Implements the GERBIL empty-set rules:
      - Both empty: P = R = F1 = 1.0
      - Gold empty, system non-empty: P = R = F1 = 0.0
      - Gold non-empty, system empty: P = R = F1 = 0.0
      - Otherwise: standard set-based metrics

    Args:
        gold_answers: Set of gold answer strings.
        system_answers: Set of system answer strings.

    Returns:
        Tuple of (precision, recall, f1).
    """
    tp = len(gold_answers & system_answers)
    fp = len(system_answers - gold_answers)
    fn = len(gold_answers - system_answers)

    if tp == 0:
        if fp == 0 and fn == 0:
            # Both empty
            return (1.0, 1.0, 1.0)
        else:
            # No true positives but either system returned wrong answers
            # or gold has answers that system missed
            return (0.0, 0.0, 0.0)

    precision = tp / (tp + fp)
    recall = tp / (tp + fn)
    f1 = (2 * precision * recall) / (precision + recall)

    return (precision, recall, f1)


def load_ground_truth(ground_truth_path: str) -> dict:
    """
    Load the ground truth file and index answers by question ID.

    Expected format:
        {"questions": [{"id": int, "answers": [...], ...}, ...]}

    Args:
        ground_truth_path: Path to the ground truth JSON file.

    Returns:
        Dict mapping question_id (int) -> list of gold answers.
    """
    with open(ground_truth_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    gold = {}
    questions = data.get("questions", [])
    for q in questions:
        qid = q["id"]
        answers = q.get("answers", [])
        gold[qid] = answers

    return gold


def load_system_answers(results_dir: str, split: str) -> dict:
    """
    Load system answer files from the results directory.

    Looks for files matching the pattern: <split>_<q_id>_answer.json

    Args:
        results_dir: Path to the results directory.
        split: The split name used in file naming.

    Returns:
        Dict mapping question_id (int) -> list of system answers.
    """
    results_path = Path(results_dir)
    system = {}

    # Find all answer files
    pattern = f"{split}_*_answer.json"
    for answer_file in sorted(results_path.glob(pattern)):
        # Extract q_id from filename: <split>_<q_id>_answer.json
        stem = answer_file.stem  # e.g., "en_dev_0_answer"
        # Remove prefix "<split>_" and suffix "_answer"
        prefix = f"{split}_"
        suffix = "_answer"
        if stem.startswith(prefix) and stem.endswith(suffix):
            qid_str = stem[len(prefix):-len(suffix)]
            try:
                qid = int(qid_str)
            except ValueError:
                continue

            try:
                with open(answer_file, "r", encoding="utf-8") as f:
                    answers = json.load(f)
                if not isinstance(answers, list):
                    answers = []
                system[qid] = answers
            except (json.JSONDecodeError, OSError):
                system[qid] = []

    return system


def evaluate(
    results_dir: str,
    ground_truth_path: str,
    split: str,
    verbose: bool = False,
) -> dict:
    """
    Run the full QALD F1 evaluation.

    Args:
        results_dir: Path to the directory containing system answer files.
        ground_truth_path: Path to the ground truth JSON file.
        split: The split name used in output file naming.
        verbose: If True, print per-question details.

    Returns:
        Dict with evaluation results including macro P, R, F1 and per-question details.
    """
    gold = load_ground_truth(ground_truth_path)
    system = load_system_answers(results_dir, split)

    if not system:
        print(f"ERROR: No system answer files found in {results_dir} with split '{split}'")
        return {"macro_precision": 0.0, "macro_recall": 0.0, "macro_f1": 0.0, "num_questions": 0}

    # Evaluate only questions that have both gold and system answers
    evaluated_qids = sorted(set(gold.keys()) & set(system.keys()))

    if not evaluated_qids:
        print("ERROR: No overlap between ground truth question IDs and system answer files.")
        print(f"  Ground truth IDs (sample): {sorted(list(gold.keys()))[:10]}")
        print(f"  System answer IDs (sample): {sorted(list(system.keys()))[:10]}")
        return {"macro_precision": 0.0, "macro_recall": 0.0, "macro_f1": 0.0, "num_questions": 0}

    # Report coverage
    total_gold = len(gold)
    total_system = len(system)
    total_evaluated = len(evaluated_qids)

    print(f"Ground truth questions: {total_gold}")
    print(f"System answer files:    {total_system}")
    print(f"Evaluated (overlap):    {total_evaluated}")

    missing_in_system = set(gold.keys()) - set(system.keys())
    if missing_in_system:
        print(f"Questions in gold but not in system: {len(missing_in_system)}")

    extra_in_system = set(system.keys()) - set(gold.keys())
    if extra_in_system:
        print(f"Questions in system but not in gold: {len(extra_in_system)}")

    print()

    # Compute per-question metrics
    per_question = []
    sum_precision = 0.0
    sum_recall = 0.0
    sum_f1 = 0.0

    for qid in evaluated_qids:
        gold_set = to_answer_set(gold[qid])
        system_set = to_answer_set(system[qid])

        precision, recall, f1 = compute_qald_f1(gold_set, system_set)

        per_question.append({
            "q_id": qid,
            "gold_answers": sorted(gold_set),
            "system_answers": sorted(system_set),
            "precision": precision,
            "recall": recall,
            "f1": f1,
        })

        sum_precision += precision
        sum_recall += recall
        sum_f1 += f1

        if verbose:
            status = "CORRECT" if f1 == 1.0 else ("PARTIAL" if f1 > 0.0 else "WRONG")
            print(f"  q_id={qid:4d}  P={precision:.4f}  R={recall:.4f}  F1={f1:.4f}  [{status}]")
            if verbose and f1 < 1.0:
                print(f"           gold:   {sorted(gold_set)}")
                print(f"           system: {sorted(system_set)}")

    # Macro averages
    n = len(evaluated_qids)
    macro_precision = sum_precision / n
    macro_recall = sum_recall / n
    macro_f1 = sum_f1 / n

    results = {
        "macro_precision": macro_precision,
        "macro_recall": macro_recall,
        "macro_f1": macro_f1,
        "num_questions": n,
        "num_correct": sum(1 for q in per_question if q["f1"] == 1.0),
        "num_partial": sum(1 for q in per_question if 0.0 < q["f1"] < 1.0),
        "num_wrong": sum(1 for q in per_question if q["f1"] == 0.0),
        "per_question": per_question,
    }

    return results


def main():
    parser = argparse.ArgumentParser(
        description="Compute Macro QALD F1 for text-to-SPARQL evaluation.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Basic evaluation:
  uv run python src/evaluate_qald_f1.py \\
      --results-dir outputs/en_dev \\
      --ground-truth /path/to/en_no_mentions_dev.json \\
      --split en_dev

  # Verbose per-question output:
  uv run python src/evaluate_qald_f1.py \\
      --results-dir outputs/en_dev \\
      --ground-truth /path/to/en_no_mentions_dev.json \\
      --split en_dev \\
      --verbose

  # Save results to JSON:
  uv run python src/evaluate_qald_f1.py \\
      --results-dir outputs/en_dev \\
      --ground-truth /path/to/en_no_mentions_dev.json \\
      --split en_dev \\
      --output results.json
        """,
    )
    parser.add_argument(
        "--results-dir", "-r",
        required=True,
        help="Directory containing system answer files (<split>_<q_id>_answer.json).",
    )
    parser.add_argument(
        "--ground-truth", "-g",
        required=True,
        help="Path to the ground truth JSON file.",
    )
    parser.add_argument(
        "--split", "-s",
        required=True,
        help="Split name used in output file naming (e.g., en_dev, dev).",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Print per-question precision, recall, and F1.",
    )
    parser.add_argument(
        "--output", "-o",
        default=None,
        help="Optional path to save full evaluation results as JSON.",
    )

    args = parser.parse_args()

    # Validate inputs
    if not Path(args.results_dir).is_dir():
        print(f"ERROR: Results directory not found: {args.results_dir}")
        sys.exit(1)

    if not Path(args.ground_truth).is_file():
        print(f"ERROR: Ground truth file not found: {args.ground_truth}")
        sys.exit(1)

    # Run evaluation
    results = evaluate(
        results_dir=args.results_dir,
        ground_truth_path=args.ground_truth,
        split=args.split,
        verbose=args.verbose,
    )

    # Print summary
    print("=" * 60)
    print("QALD F1 EVALUATION RESULTS")
    print("=" * 60)
    print(f"  Questions evaluated: {results['num_questions']}")
    print(f"  Correct (F1=1.0):   {results['num_correct']}")
    print(f"  Partial (0<F1<1):   {results['num_partial']}")
    print(f"  Wrong (F1=0.0):     {results['num_wrong']}")
    print("-" * 60)
    print(f"  Macro Precision:    {results['macro_precision']:.4f}")
    print(f"  Macro Recall:       {results['macro_recall']:.4f}")
    print(f"  Macro QALD F1:      {results['macro_f1']:.4f}")
    print("=" * 60)

    # Optionally save full results to JSON
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
        print(f"\nFull results saved to: {args.output}")

    # Exit with status based on whether evaluation succeeded
    if results["num_questions"] == 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
