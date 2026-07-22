# Copyright IBM Corp. 2026 - 2026
# SPDX-License-Identifier: Apache-2.0
#

#!/usr/bin/env python3
"""
Batch Text-to-SPARQL runner (with mentions) using OpenCode server.

Takes a JSON file of questions with entity/property mentions
(format: [{"q_id": ..., "question": ..., "mentions": [...]}, ...])
and runs each question through an OpenCode session using the text2sparql skill
pipeline. The mentions provide pre-resolved Wikidata entity IDs (QIDs) and
property IDs (PIDs) that the agent can use as a starting point for graph
exploration, bypassing the initial search step.

Saves per-question outputs:
  - <split>_<q_id>_answer.json        — the answer array (Q/P IDs, literals, booleans)
  - <split>_<q_id>_sparql.json        — the generated SPARQL query
  - <split>_<q_id>_session.log        — the full session export (JSON)
  - <split>_<q_id>_session.trace.md   — human-readable trace of agent interactions

Usage:
    uv run python src/run_text2sparql_with_mentions.py \
        --input data/en_with_mentions_dev_questions.json \
        --split en_dev \
        --output-dir outputs/en_dev_mentions

    # Run a subset of questions:
    uv run python src/run_text2sparql_with_mentions.py \
        --input data/en_with_mentions_dev_questions.json \
        --split en_dev \
        --output-dir outputs/en_dev_mentions \
        --question-ids 0 1 2

    # Run 4 questions in parallel:
    uv run python src/run_text2sparql_with_mentions.py \
        --input data/en_with_mentions_dev_questions.json \
        --split en_dev \
        --output-dir outputs/en_dev_mentions \
        --parallel 4

Requirements:
    - opencode CLI installed (https://opencode.ai/install)
    - requests (pip install requests)
"""

import argparse
import json
import logging
import os
import re
import signal
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional

import requests

# Add parent directory to path so we can find the opencode client utilities
sys.path.insert(0, str(Path(__file__).resolve().parent))

from format_session_log import format_session_log_to_file
from opencode_client import OpencodeClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def load_questions(input_path: str, question_ids: Optional[list] = None) -> list:
    """
    Load questions from the input JSON file.

    Expected format: [{"q_id": ..., "question": ..., "mentions": [...]}, ...]

    Args:
        input_path: Path to the questions JSON file.
        question_ids: Optional list of specific q_ids to run.

    Returns:
        List of question dicts.
    """
    with open(input_path, "r", encoding="utf-8") as f:
        all_questions = json.load(f)

    logger.info(f"Loaded {len(all_questions)} questions from {input_path}")

    # Optionally filter by specific question_ids
    if question_ids is not None:
        id_set = set(question_ids)
        all_questions = [q for q in all_questions if q.get("q_id") in id_set]
        logger.info(f"Filtered to {len(all_questions)} questions by specified question_ids")

    return all_questions


def build_prompt(question: str, mentions: list, examples_scope: str = "none") -> str:
    """
    Build the prompt to send to OpenCode for text-to-SPARQL generation,
    including entity/property mentions as pre-resolved Wikidata IDs.

    Args:
        question: The natural-language question.
        mentions: List of mention dicts, each with "string" and optionally
                  "entity", "property", "inverse", "mention" fields.
        examples_scope: Which examples DB to use: "none", "train", or "all".

    Returns:
        The formatted prompt string.
    """
    # Format mentions into a readable block
    mentions_block = ""
    if mentions:
        mention_lines = []
        for m in mentions:
            parts = [f'"{m["string"]}"']
            if "entity" in m:
                parts.append(f"entity={m['entity']}")
            if "property" in m:
                parts.append(f"property={m['property']}")
            if m.get("inverse"):
                parts.append("(inverse)")
            if m.get("mention") == "implicit":
                parts.append("(implicit)")
            mention_lines.append("  - " + " | ".join(parts))
        mentions_block = (
            "\nPre-resolved Wikidata mentions (use these as starting points for graph exploration):\n"
            + "\n".join(mention_lines)
            + "\n"
        )

    examples_instruction = ""
    if examples_scope in ("train", "all"):
        examples_instruction = (
            f"3. If the question involves complex patterns (measurements, temporal qualifiers, aggregations, or contest/competition winners), "
            f"retrieve similar examples for structural guidance: "
            f'`uv run python .agents/skills/few-shot-examples/scripts/retrieve_examples.py '
            f'--query "{question}" --top-k 5 --scope {examples_scope}` '
            f"— use the returned SPARQL patterns to inform your query structure. "
            f"Skip this step for simple entity lookups where the pattern is obvious.\n"
            f"4. Generate and execute a SPARQL query to answer the question.\n"
        )
    else:
        examples_instruction = (
            f"3. Generate and execute a SPARQL query to answer the question.\n"
        )

    return (
        f'Answer the following question from Wikidata using text2sparql Skill: "{question}"\n'
        f"{mentions_block}\n"
        f"Instructions:\n"
        f"1. These are pre-resolved starting points. You may still search for additional entities/properties if the provided ones seem insufficient or if intermediate classes are needed.\n"
        f"2. Explore the graph to verify property directions and discover any additional paths needed.\n"
        f"{examples_instruction}"
        f"5. Return the final answer as a JSON array of values.\n\n"
        f"IMPORTANT: The final answer MUST be a JSON array containing only:\n"
        f"- Wikidata entity IDs (e.g., \"Q23\", \"Q453\")\n"
        f"- Wikidata property IDs (e.g., \"P31\", \"P279\")\n"
        f"- Literal strings (e.g., \"3\", \"75600000000000000000.0\")\n"
        f"- Boolean values as strings (\"True\" or \"False\")\n\n"
        f"Do NOT return entity labels — only IDs and literals.\n"
        f"The final line of your response must be ONLY the JSON array, e.g.:\n"
        f'["Q23", "Q453"]\n'
    )


def extract_answer_from_response(response_text: str) -> list:
    """
    Extract the answer array from the OpenCode response text.

    Looks for a JSON array in the response, preferring the last one found
    (most likely the final answer).

    Args:
        response_text: The raw text response from OpenCode.

    Returns:
        The extracted answer as a list of strings.
    """
    if not response_text or response_text.startswith("ERROR:"):
        return []

    # Strategy 1: Look for JSON array in a code block
    code_block_pattern = r"```(?:json)?\s*\n?(.*?)```"
    matches = re.findall(code_block_pattern, response_text, re.DOTALL | re.IGNORECASE)
    for match in reversed(matches):
        stripped = match.strip()
        if stripped.startswith("["):
            try:
                parsed = json.loads(stripped)
                if isinstance(parsed, list):
                    return [str(item) for item in parsed]
            except json.JSONDecodeError:
                continue

    # Strategy 2: Find the last line that looks like a JSON array
    lines = response_text.strip().split("\n")
    for line in reversed(lines):
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            try:
                parsed = json.loads(stripped)
                if isinstance(parsed, list):
                    return [str(item) for item in parsed]
            except json.JSONDecodeError:
                continue

    # Strategy 3: Search for any JSON array in the full text
    array_pattern = r'\[(?:[^\[\]]*(?:"[^"]*"[^\[\]]*)*)\]'
    all_arrays = re.findall(array_pattern, response_text)
    for arr_str in reversed(all_arrays):
        try:
            parsed = json.loads(arr_str)
            if isinstance(parsed, list) and len(parsed) > 0:
                return [str(item) for item in parsed]
        except json.JSONDecodeError:
            continue

    # Fallback: return empty list
    return []


def extract_sparql_from_session_log(log_path: Path) -> str:
    """
    Extract the SPARQL query from an exported session log file.

    Looks for the last invocation of the sparql_executor.py script in the
    session's tool calls and extracts the SPARQL query from the --sparql
    argument or from the JSON output.

    Args:
        log_path: Path to the exported session log JSON file.

    Returns:
        The extracted SPARQL query string, or empty string if not found.
    """
    try:
        session_data = json.loads(log_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        logger.warning(f"  Could not read session log for SPARQL extraction: {e}")
        return ""

    messages = session_data.get("messages", [])

    # Collect all sparql_executor tool calls across all messages
    executor_calls = []
    for msg in messages:
        parts = msg.get("parts", [])
        for part in parts:
            if part.get("type") != "tool":
                continue
            state = part.get("state", {})
            input_data = state.get("input", {})
            command = input_data.get("command", "")
            if "sparql_executor.py" in command and "--sparql" in command:
                executor_calls.append((command, state.get("output", "")))

    if not executor_calls:
        return ""

    # Use the last sparql_executor call (the final query)
    last_command, last_output = executor_calls[-1]

    # Strategy 1: Extract SPARQL from the JSON output's "sparql" field
    if last_output:
        try:
            output_data = json.loads(last_output)
            sparql = output_data.get("sparql", "")
            if sparql:
                return sparql
        except json.JSONDecodeError:
            pass

    # Strategy 2: Extract from the --sparql argument in the command
    sparql_match = re.search(r'--sparql\s+"(.*?)"', last_command, re.DOTALL)
    if sparql_match:
        return sparql_match.group(1)

    # Strategy 3: Try single-quoted --sparql argument
    sparql_match = re.search(r"--sparql\s+'(.*?)'", last_command, re.DOTALL)
    if sparql_match:
        return sparql_match.group(1)

    return ""


def _save_session_error_log(
    client: OpencodeClient,
    session_id: Optional[str],
    error_log_file: Path,
    question_id: int,
    error_msg: str,
) -> None:
    """
    Save the session to an error log file. Tries to export the full session
    from the server first; if that fails, writes a JSON fallback with the error details.
    """
    if session_id:
        try:
            client.export_session(session_id, str(error_log_file))
            logger.info(f"  Session saved to {error_log_file}")
            return
        except Exception as export_err:
            logger.warning(f"  Could not export session from server: {export_err}")

    # Fallback: write error details as JSON
    fallback_data = {
        "question_id": question_id,
        "session_id": session_id,
        "error": error_msg,
    }
    try:
        error_log_file.write_text(
            json.dumps(fallback_data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        logger.info(f"  Error log saved to {error_log_file}")
    except Exception as write_err:
        logger.error(f"  Failed to write error log: {write_err}")


class SessionExporter(threading.Thread):
    """
    Background thread that periodically exports active OpenCode sessions
    to partial log files. Supports tracking multiple concurrent sessions.
    """

    def __init__(self, client: OpencodeClient, interval: int = 60):
        super().__init__(daemon=True)
        self._client = client
        self._interval = interval
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        self._sessions: dict[str, Path] = {}

    def add_session(self, session_id: str, output_path: Path) -> None:
        """Register a session for periodic export."""
        with self._lock:
            self._sessions[session_id] = output_path

    def remove_session(self, session_id: str) -> None:
        """Unregister a session (e.g., after it completes)."""
        with self._lock:
            self._sessions.pop(session_id, None)

    def stop(self) -> None:
        """Signal the thread to stop."""
        self._stop_event.set()

    def run(self) -> None:
        """Periodically export all active sessions until stopped."""
        while not self._stop_event.is_set():
            self._stop_event.wait(timeout=self._interval)
            if self._stop_event.is_set():
                break
            self._export_all_snapshots()

    def _export_all_snapshots(self) -> None:
        """Export a snapshot of all active sessions."""
        with self._lock:
            sessions_copy = dict(self._sessions)

        for session_id, output_path in sessions_copy.items():
            try:
                self._client.export_session(session_id, str(output_path))
                logger.debug(f"  [periodic] Session {session_id} snapshot saved to {output_path}")
            except Exception as e:
                logger.debug(f"  [periodic] Could not export session {session_id}: {e}")


def _process_question(
    client: OpencodeClient,
    exporter: SessionExporter,
    question_data: dict,
    split: str,
    out_path: Path,
    index: int,
    total: int,
    examples_scope: str = "none",
) -> dict:
    """
    Process a single question: create session, send prompt, save results.

    Saves:
      - <split>_<q_id>_answer.json   — the answer array
      - <split>_<q_id>_sparql.json   — the SPARQL query
      - <split>_<q_id>_session.log   — the full session export

    Args:
        client: The shared OpencodeClient instance.
        exporter: The shared SessionExporter for periodic snapshots.
        question_data: The question dict with "q_id", "question", and "mentions".
        split: Split name for output file naming.
        out_path: Output directory path.
        index: 1-based index of this question in the batch.
        total: Total number of questions.

    Returns:
        Dict with 'status' ('success', 'failed', 'skipped') and 'q_id'.
    """
    qid = question_data["q_id"]
    question_text = question_data["question"]
    mentions = question_data.get("mentions", [])
    answer_file = out_path / f"{split}_{qid}_answer.json"
    sparql_file = out_path / f"{split}_{qid}_sparql.json"
    log_file = out_path / f"{split}_{qid}_session.log"
    error_log_file = out_path / f"{split}_{qid}_session_error.log"

    logger.info(
        f"[{index}/{total}] Processing q_id={qid}: "
        f"{question_text[:80]}{'...' if len(question_text) > 80 else ''}"
    )

    prompt = build_prompt(question_text, mentions, examples_scope)
    session_id = None

    try:
        # Create a new session for this question
        session_id = client.create_session(title=f"text2sparql-q{qid}")

        # Register with periodic exporter
        partial_log_file = out_path / f"{split}_{qid}_session_partial.log"
        exporter.add_session(session_id, partial_log_file)

        # Send the prompt and wait for response
        response = client.send_message(session_id, prompt)
        response_text = client.extract_final_text(response)

        # Unregister from periodic exporter
        exporter.remove_session(session_id)

        if response_text.startswith("ERROR:"):
            logger.warning(f"  Question {qid} returned an error: {response_text[:100]}")
            _save_session_error_log(client, session_id, error_log_file, qid, response_text)
            result = {"status": "failed", "q_id": qid}
        else:
            # Export session log first (needed for SPARQL extraction)
            client.export_session(session_id, str(log_file))
            logger.info(f"  Saved session log to {log_file}")

            # Generate human-readable trace from the session log
            trace_file = out_path / f"{split}_{qid}_session.trace.md"
            try:
                format_session_log_to_file(str(log_file), str(trace_file))
                logger.info(f"  Saved readable trace to {trace_file}")
            except Exception as trace_err:
                logger.warning(f"  Could not generate trace: {trace_err}")

            # Extract answer from the response text
            answer = extract_answer_from_response(response_text)

            # Extract SPARQL from the exported session log
            sparql = extract_sparql_from_session_log(log_file)

            # Save answer file
            answer_file.write_text(
                json.dumps(answer, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            logger.info(f"  Saved answer ({len(answer)} items) to {answer_file}")

            # Save SPARQL file
            sparql_data = {"sparql": sparql}
            sparql_file.write_text(
                json.dumps(sparql_data, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            logger.info(f"  Saved SPARQL to {sparql_file}")

            result = {"status": "success", "q_id": qid}

        # Clean up partial log
        if partial_log_file.exists():
            partial_log_file.unlink()

        return result

    except KeyboardInterrupt:
        logger.info(f"  Interrupted during q_id={qid}, saving partial session...")
        if session_id:
            exporter.remove_session(session_id)
        _save_session_error_log(client, session_id, error_log_file, qid, "keyboard_interrupt")
        return {"status": "failed", "q_id": qid, "interrupted": True}

    except Exception as e:
        logger.error(f"  Error for q_id={qid}: {e}")
        if session_id:
            exporter.remove_session(session_id)
        _save_session_error_log(client, session_id, error_log_file, qid, str(e))
        return {"status": "failed", "q_id": qid}


def run_batch(
    input_path: str,
    split: str,
    output_dir: str,
    workspace_dir: str,
    config_path: Optional[str] = None,
    question_ids: Optional[list] = None,
    timeout: int = 1500,
    resume: bool = True,
    password: Optional[str] = None,
    parallel: int = 1,
    examples_scope: str = "none",
) -> dict:
    """
    Run batch text-to-SPARQL generation for all questions in the input file.

    Starts a single OpenCode server and processes questions either sequentially
    or in parallel, depending on the `parallel` parameter.

    Args:
        input_path: Path to the questions JSON file.
        split: Split name for output file naming (e.g., "en_dev", "es_train").
        output_dir: Directory to save output files.
        workspace_dir: OpenCode workspace directory.
        config_path: Optional path to opencode.json config.
        question_ids: Optional list of specific q_ids to run.
        timeout: Max seconds to wait per question.
        resume: If True, skip questions that already have output files.
        password: Server password for HTTP Basic Auth.
        parallel: Number of questions to process in parallel (default: 1).

    Returns:
        Summary dict with counts of success/failure/skipped.
    """
    questions = load_questions(input_path, question_ids)
    if not questions:
        logger.error("No questions found in input file")
        return {"total": 0, "success": 0, "failed": 0, "skipped": 0}

    # Create output directory
    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    # Filter out already-completed questions if resuming
    if resume:
        pending_questions = []
        skipped_count = 0
        for q in questions:
            answer_file = out_path / f"{split}_{q['q_id']}_answer.json"
            if answer_file.exists():
                skipped_count += 1
            else:
                pending_questions.append(q)
        if skipped_count:
            logger.info(f"Resuming: skipping {skipped_count} already-completed questions")
    else:
        pending_questions = questions
        skipped_count = 0

    summary = {
        "total": len(questions),
        "success": 0,
        "failed": 0,
        "skipped": skipped_count,
    }

    if not pending_questions:
        logger.info("All questions already completed.")
        return summary

    # Initialize the client (starts one server for all questions)
    client = OpencodeClient(
        workspace_dir=workspace_dir,
        config_path=config_path,
        timeout=timeout,
        password=password,
    )

    # Handle Ctrl+C gracefully
    interrupted = False

    def signal_handler(sig, frame):
        nonlocal interrupted
        if interrupted:
            logger.info("\nForce quitting...")
            sys.exit(1)
        logger.info("\nInterrupted! Waiting for in-flight questions to save sessions...")
        interrupted = True

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Start background thread that periodically exports active sessions
    exporter = SessionExporter(client, interval=60)

    total = len(pending_questions)
    logger.info(f"Processing {total} questions with parallelism={parallel}")

    try:
        client.start_server()
        exporter.start()

        if parallel <= 1:
            # Sequential execution
            for i, question_data in enumerate(pending_questions):
                if interrupted:
                    logger.info("Stopping due to interrupt.")
                    break

                result = _process_question(
                    client, exporter, question_data, split, out_path, i + 1, total,
                    examples_scope=examples_scope,
                )
                summary[result["status"]] += 1

                if result.get("interrupted"):
                    break

                # Small delay between questions
                if not interrupted and i < total - 1:
                    time.sleep(1)
        else:
            # Parallel execution using thread pool
            with ThreadPoolExecutor(max_workers=parallel) as executor:
                futures = {}
                for i, question_data in enumerate(pending_questions):
                    if interrupted:
                        break
                    future = executor.submit(
                        _process_question,
                        client, exporter, question_data, split, out_path,
                        i + 1, total, examples_scope,
                    )
                    futures[future] = question_data["q_id"]

                # Collect results as they complete
                for future in as_completed(futures):
                    if interrupted:
                        for f in futures:
                            f.cancel()
                        break

                    try:
                        result = future.result()
                        summary[result["status"]] += 1
                        if result.get("interrupted"):
                            interrupted = True
                            for f in futures:
                                f.cancel()
                            break
                    except Exception as e:
                        qid = futures[future]
                        logger.error(f"  Unhandled error for q_id={qid}: {e}")
                        summary["failed"] += 1

    finally:
        exporter.stop()
        client.stop_server()

    return summary


def main():
    parser = argparse.ArgumentParser(
        description="Batch Text-to-SPARQL runner (with mentions) using OpenCode server.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run all questions for English dev split (with mentions):
  uv run python src/run_text2sparql_with_mentions.py \\
      --input data/en_with_mentions_dev_questions.json \\
      --split en_dev \\
      --output-dir outputs/en_dev_mentions

  # Run specific questions only:
  uv run python src/run_text2sparql_with_mentions.py \\
      --input data/en_with_mentions_dev_questions.json \\
      --split en_dev \\
      --output-dir outputs/en_dev_mentions \\
      --question-ids 0 1 2

  # Run 4 questions in parallel:
  uv run python src/run_text2sparql_with_mentions.py \\
      --input data/en_with_mentions_dev_questions.json \\
      --split en_dev \\
      --output-dir outputs/en_dev_mentions \\
      --parallel 4

  # Force re-run (no resume):
  uv run python src/run_text2sparql_with_mentions.py \\
      --input data/en_with_mentions_dev_questions.json \\
      --split en_dev \\
      --output-dir outputs/en_dev_mentions \\
      --no-resume
        """,
    )
    parser.add_argument(
        "--input", "-i",
        required=True,
        help="Path to the questions JSON file (format: [{\"q_id\": ..., \"question\": ..., \"mentions\": [...]}, ...]).",
    )
    parser.add_argument(
        "--split", "-s",
        required=True,
        help="Split name for output file naming (e.g., en_dev, en_train, es_test).",
    )
    parser.add_argument(
        "--output-dir", "-o",
        required=True,
        help="Directory to save output files.",
    )
    parser.add_argument(
        "--workspace", "-w",
        default=None,
        help="OpenCode workspace directory (default: current repo root).",
    )
    parser.add_argument(
        "--config", "-c",
        default=None,
        help="Path to an opencode.json config file to use.",
    )
    parser.add_argument(
        "--question-ids", "-q",
        nargs="+",
        type=int,
        default=None,
        help="Specific question IDs to run (space-separated).",
    )
    parser.add_argument(
        "--timeout", "-t",
        type=int,
        default=1500,
        help="Max seconds to wait per question (default: 1500 / 25 min).",
    )
    parser.add_argument(
        "--parallel", "-p",
        type=int,
        default=1,
        help="Number of questions to process in parallel (default: 1 = sequential).",
    )
    parser.add_argument(
        "--no-resume",
        action="store_true",
        help="Do not skip questions that already have output files.",
    )
    parser.add_argument(
        "--password",
        default=None,
        help="Server password for HTTP Basic Auth (default: reads OPENCODE_SERVER_PASSWORD env var).",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable debug logging.",
    )
    parser.add_argument(
        "--examples",
        choices=["none", "train", "all"],
        default="none",
        help="Few-shot examples scope: 'none' (no retrieval), 'train' (train examples only, "
             "for dev evaluation), 'all' (train+dev, for test evaluation). Default: none.",
    )

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # Default workspace is the repository root (where this script lives)
    workspace = args.workspace or str(Path(__file__).resolve().parent.parent)

    summary = run_batch(
        input_path=args.input,
        split=args.split,
        output_dir=args.output_dir,
        workspace_dir=workspace,
        config_path=args.config,
        question_ids=args.question_ids,
        timeout=args.timeout,
        resume=not args.no_resume,
        password=args.password,
        parallel=args.parallel,
        examples_scope=args.examples,
    )

    # Print summary
    print("\n" + "=" * 60)
    print("BATCH TEXT-TO-SPARQL SUMMARY")
    print("=" * 60)
    print(f"  Total questions:  {summary['total']}")
    print(f"  Successful:       {summary['success']}")
    print(f"  Failed:           {summary['failed']}")
    print(f"  Skipped (resume): {summary['skipped']}")
    print("=" * 60)

    # Exit with error code if any failures
    if summary["failed"] > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
