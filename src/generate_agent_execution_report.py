# Copyright IBM Corp. 2026 - 2026
# SPDX-License-Identifier: Apache-2.0
#

#!/usr/bin/env python3
"""
Generate a markdown agent execution report for a question set and results directory.

Examples:
    python3 src/generate_agent_execution_report.py \
        data/en_no_mentions_test_questions.json \
        outputs/june-30-en-no-mentions-test-fewshot
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from analyze_session_logs import analyze_session_log, build_aggregate_report


def _safe_int(value: Any) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return int(value)
    return 0


def _fmt_int(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, bool):
        return str(int(value))
    if isinstance(value, (int, float)):
        return f"{int(value):,}"
    return str(value)


def _fmt_float(value: Any, digits: int = 2) -> str:
    if value is None:
        return "-"
    if isinstance(value, (int, float)):
        return f"{float(value):,.{digits}f}"
    return str(value)


def _fmt_ms(value: Any) -> str:
    if value is None:
        return "-"
    if not isinstance(value, (int, float)):
        return str(value)

    total_ms = int(value)
    if total_ms < 1000:
        return f"{total_ms} ms"

    total_seconds = total_ms / 1000
    if total_seconds < 60:
        return f"{total_seconds:.1f} s"

    minutes = int(total_seconds // 60)
    seconds = total_seconds % 60
    return f"{minutes}m {seconds:.0f}s"


def _fmt_percent(numerator: int, denominator: int) -> str:
    if denominator == 0:
        return "-"
    return f"{(numerator / denominator) * 100:.1f}%"


def _truncate(text: str | None, limit: int = 100) -> str:
    if not text:
        return "-"
    compact = " ".join(text.split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 3] + "..."


def _top_items(counter_like: dict[str, int], limit: int = 10) -> list[tuple[str, int]]:
    return sorted(counter_like.items(), key=lambda item: (-item[1], item[0]))[:limit]


def _render_table(headers: list[str], rows: list[list[str]]) -> str:
    if not rows:
        return "_None._"

    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


def _load_questions(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("Question file must be a JSON array.")
    return data


def _infer_split_hint(question_file: Path) -> str | None:
    match = re.search(r"_([A-Za-z0-9]+)_questions$", question_file.stem)
    if match:
        return match.group(1)
    return None


def _matching_logs(results_dir: Path, qid: int, suffix: str, split_hint: str | None) -> list[Path]:
    candidates: list[Path] = []
    seen: set[Path] = set()

    patterns = []
    if split_hint:
        patterns.append(f"{split_hint}_{qid}_{suffix}")
    patterns.append(f"*_{qid}_{suffix}")

    for pattern in patterns:
        for path in sorted(results_dir.glob(pattern)):
            if path not in seen:
                seen.add(path)
                candidates.append(path)

    return candidates


def _select_log(results_dir: Path, qid: int, split_hint: str | None) -> tuple[str, Path | None]:
    finished_matches = _matching_logs(results_dir, qid, "session.log", split_hint)
    partial_matches = _matching_logs(results_dir, qid, "session_partial.log", split_hint)

    if finished_matches:
        return "finished", finished_matches[0]
    if partial_matches:
        return "partial", partial_matches[0]
    return "missing", None


def _summarize_question(question_entry: dict[str, Any], results_dir: Path, split_hint: str | None) -> dict[str, Any]:
    qid = _safe_int(question_entry.get("q_id"))
    question_text = str(question_entry.get("question", "")).strip()
    status, log_path = _select_log(results_dir, qid, split_hint)

    summary: dict[str, Any] = {
        "q_id": qid,
        "question": question_text,
        "status": status,
        "selected_log": str(log_path) if log_path else None,
        "analysis": None,
    }

    if log_path is not None:
        summary["analysis"] = analyze_session_log(log_path)

    return summary


def _rows_overview(question_summaries: list[dict[str, Any]]) -> list[list[str]]:
    total = len(question_summaries)
    finished = sum(1 for item in question_summaries if item["status"] == "finished")
    partial = sum(1 for item in question_summaries if item["status"] == "partial")
    missing = sum(1 for item in question_summaries if item["status"] == "missing")
    present = finished + partial

    return [
        ["Questions in input", _fmt_int(total)],
        ["Finished logs used", _fmt_int(finished)],
        ["Partial logs used", _fmt_int(partial)],
        ["Missing logs", _fmt_int(missing)],
        ["Coverage", _fmt_percent(present, total)],
        ["Finished rate", _fmt_percent(finished, total)],
    ]


def _rows_aggregate_execution(aggregate: dict[str, Any]) -> list[list[str]]:
    return [
        ["LLM rounds", _fmt_int(aggregate["llm_rounds"]["sum"]), _fmt_float(aggregate["llm_rounds"]["mean"]), _fmt_float(aggregate["llm_rounds"]["median"])],
        ["Rounds with tools", _fmt_int(aggregate["rounds_with_tools"]["sum"]), _fmt_float(aggregate["rounds_with_tools"]["mean"]), _fmt_float(aggregate["rounds_with_tools"]["median"])],
        ["Rounds with reasoning text", _fmt_int(aggregate["rounds_with_reasoning_text"]["sum"]), _fmt_float(aggregate["rounds_with_reasoning_text"]["mean"]), _fmt_float(aggregate["rounds_with_reasoning_text"]["median"])],
        ["Tool calls", _fmt_int(aggregate["tool_calls"]["sum"]), _fmt_float(aggregate["tool_calls"]["mean"]), _fmt_float(aggregate["tool_calls"]["median"])],
        ["SPARQL retries", _fmt_int(aggregate["sparql_retry_count"]["sum"]), _fmt_float(aggregate["sparql_retry_count"]["mean"]), _fmt_float(aggregate["sparql_retry_count"]["median"])],
        ["Session duration", _fmt_ms(aggregate["session_duration_ms"]["sum"]), _fmt_ms(aggregate["session_duration_ms"]["mean"]), _fmt_ms(aggregate["session_duration_ms"]["median"])],
    ]


def _rows_aggregate_tokens(aggregate: dict[str, Any]) -> list[list[str]]:
    token_block = aggregate["tokens"]
    rows: list[list[str]] = []
    for key, label in [
        ("input", "Input tokens"),
        ("output", "Output tokens"),
        ("reasoning", "Reasoning tokens"),
        ("cache_read", "Cache read tokens"),
        ("total", "Total token footprint"),
    ]:
        stats = token_block[key]
        rows.append([label, _fmt_int(stats["sum"]), _fmt_float(stats["mean"]), _fmt_float(stats["median"])])
    return rows


def _rows_aggregate_tools(aggregate: dict[str, Any]) -> list[list[str]]:
    total_sessions = max(_safe_int(aggregate.get("sessions")), 1)
    rows: list[list[str]] = []
    for name, count in _top_items(aggregate.get("tool_usage", {}), limit=12):
        rows.append([name, _fmt_int(count), _fmt_float(count / total_sessions)])
    return rows


def _rows_aggregate_skills(aggregate: dict[str, Any]) -> list[list[str]]:
    total_sessions = max(_safe_int(aggregate.get("sessions")), 1)
    rows: list[list[str]] = []
    for name, count in _top_items(aggregate.get("command_skill_usage", {}), limit=12):
        rows.append([name, _fmt_int(count), _fmt_float(count / total_sessions)])
    return rows


def _rows_aggregate_scripts(aggregate: dict[str, Any]) -> list[list[str]]:
    total_sessions = max(_safe_int(aggregate.get("sessions")), 1)
    rows: list[list[str]] = []
    for name, count in _top_items(aggregate.get("scripts", {}), limit=12):
        rows.append([name, _fmt_int(count), _fmt_float(count / total_sessions)])
    return rows


def _rows_sparql(aggregate: dict[str, Any]) -> list[list[str]]:
    domain_stats = aggregate.get("domain_stats", {})
    total_sessions = max(_safe_int(aggregate.get("sessions")), 1)
    return [
        ["Wikidata search calls", _fmt_int(domain_stats.get("wikidata_search_calls")), _fmt_float(_safe_int(domain_stats.get("wikidata_search_calls")) / total_sessions)],
        ["Graph exploration calls", _fmt_int(domain_stats.get("graph_exploration_calls")), _fmt_float(_safe_int(domain_stats.get("graph_exploration_calls")) / total_sessions)],
        ["SPARQL execution calls", _fmt_int(domain_stats.get("sparql_execution_calls")), _fmt_float(_safe_int(domain_stats.get("sparql_execution_calls")) / total_sessions)],
        ["SPARQL successes", _fmt_int(domain_stats.get("sparql_successes")), "-"],
        ["SPARQL failures", _fmt_int(domain_stats.get("sparql_failures")), "-"],
    ]


def _rows_per_question_summary(question_summaries: list[dict[str, Any]]) -> list[list[str]]:
    rows: list[list[str]] = []
    for item in sorted(question_summaries, key=lambda entry: entry["q_id"]):
        analysis = item.get("analysis") or {}
        session = analysis.get("session", {})
        execution = analysis.get("execution_summary", {})
        tokens = analysis.get("tokens", {}).get("session", {})
        final_answer = analysis.get("final_answer", {})
        domain_stats = analysis.get("domain_stats", {}).get("sparql_execution", {})

        rows.append(
            [
                str(item["q_id"]),
                item["status"],
                _fmt_int(analysis.get("llm_rounds")),
                _fmt_int(analysis.get("tool_calls", {}).get("total")),
                _fmt_int(execution.get("sparql_retry_count")),
                _fmt_int(domain_stats.get("calls")),
                _fmt_ms(session.get("duration_ms")),
                _fmt_int(tokens.get("total")),
                _fmt_int(final_answer.get("item_count")),
                _truncate(item["question"], 90),
            ]
        )
    return rows


def _rows_per_question_skills(question_summaries: list[dict[str, Any]]) -> list[list[str]]:
    rows: list[list[str]] = []
    for item in sorted(question_summaries, key=lambda entry: entry["q_id"]):
        analysis = item.get("analysis") or {}
        command_usage = analysis.get("skills", {}).get("command_usage", {})
        rows.append(
            [
                str(item["q_id"]),
                item["status"],
                _fmt_int(command_usage.get("wikidata-search")),
                _fmt_int(command_usage.get("graph-exploration")),
                _fmt_int(command_usage.get("few-shot-examples")),
                _fmt_int(command_usage.get("sparql-execution")),
                _fmt_int(analysis.get("tool_calls", {}).get("total")),
            ]
        )
    return rows


def _rows_partial(question_summaries: list[dict[str, Any]]) -> list[list[str]]:
    rows: list[list[str]] = []
    for item in sorted(question_summaries, key=lambda entry: entry["q_id"]):
        if item["status"] != "partial":
            continue
        analysis = item.get("analysis") or {}
        finish_reasons = analysis.get("finish_reasons", {})
        tool_status = analysis.get("tool_calls", {}).get("by_status", {})
        rows.append(
            [
                str(item["q_id"]),
                _fmt_int(analysis.get("llm_rounds")),
                _fmt_int(analysis.get("tool_calls", {}).get("total")),
                ", ".join(f"{key}:{value}" for key, value in finish_reasons.items()) or "-",
                ", ".join(f"{key}:{value}" for key, value in tool_status.items()) or "-",
                _truncate(item["question"], 90),
            ]
        )
    return rows


def _rows_missing(question_summaries: list[dict[str, Any]]) -> list[list[str]]:
    rows: list[list[str]] = []
    for item in sorted(question_summaries, key=lambda entry: entry["q_id"]):
        if item["status"] != "missing":
            continue
        rows.append([str(item["q_id"]), _truncate(item["question"], 120)])
    return rows


def _rows_heaviest(question_summaries: list[dict[str, Any]], limit: int = 10) -> list[list[str]]:
    present = [item for item in question_summaries if item.get("analysis")]
    present.sort(
        key=lambda item: (
            -_safe_int(item["analysis"].get("tokens", {}).get("session", {}).get("total")),
            item["q_id"],
        )
    )

    rows: list[list[str]] = []
    for item in present[:limit]:
        analysis = item["analysis"]
        rows.append(
            [
                str(item["q_id"]),
                item["status"],
                _fmt_int(analysis.get("tokens", {}).get("session", {}).get("total")),
                _fmt_ms(analysis.get("session", {}).get("duration_ms")),
                _fmt_int(analysis.get("tool_calls", {}).get("total")),
                _truncate(item["question"], 90),
            ]
        )
    return rows


def _render_report(question_file: Path, results_dir: Path, question_summaries: list[dict[str, Any]]) -> str:
    analyzed = [item["analysis"] for item in question_summaries if item.get("analysis")]
    aggregate = build_aggregate_report(analyzed) if analyzed else {
        "sessions": 0,
        "llm_rounds": {"sum": 0, "mean": None, "median": None},
        "rounds_with_tools": {"sum": 0, "mean": None, "median": None},
        "rounds_with_reasoning_text": {"sum": 0, "mean": None, "median": None},
        "tool_calls": {"sum": 0, "mean": None, "median": None},
        "sparql_retry_count": {"sum": 0, "mean": None, "median": None},
        "session_duration_ms": {"sum": 0, "mean": None, "median": None},
        "final_answers": {"json_arrays": 0, "non_json_arrays": 0, "item_count": {"sum": 0, "mean": None, "median": None}},
        "tokens": {
            "input": {"sum": 0, "mean": None, "median": None},
            "output": {"sum": 0, "mean": None, "median": None},
            "reasoning": {"sum": 0, "mean": None, "median": None},
            "cache_read": {"sum": 0, "mean": None, "median": None},
            "total": {"sum": 0, "mean": None, "median": None},
        },
        "tool_usage": {},
        "command_skill_usage": {},
        "scripts": {},
        "domain_stats": {},
    }

    lines = [
        "# Agent Execution Stats",
        "",
        f"Generated: `{datetime.now(tz=timezone.utc).isoformat()}`",
        f"Question file: `{question_file}`",
        f"Results dir: `{results_dir}`",
        "",
        "Finished logs are preferred over partial logs. If a finished log is missing, the report falls back to the partial log. Missing questions are listed explicitly below.",
        "",
        "## Coverage Overview",
        "",
        _render_table(["Metric", "Value"], _rows_overview(question_summaries)),
        "",
        "## Aggregate Execution Totals",
        "",
        _render_table(["Metric", "Total", "Mean / Question", "Median / Question"], _rows_aggregate_execution(aggregate)),
        "",
        "## Aggregate Token Totals",
        "",
        _render_table(["Metric", "Total", "Mean / Question", "Median / Question"], _rows_aggregate_tokens(aggregate)),
        "",
        "## Aggregate Tool Usage",
        "",
        _render_table(["Tool", "Total Calls", "Mean / Question"], _rows_aggregate_tools(aggregate)),
        "",
        "## Aggregate Skill Usage",
        "",
        _render_table(["Skill Family", "Total Calls", "Mean / Question"], _rows_aggregate_skills(aggregate)),
        "",
        "## Aggregate Script Usage",
        "",
        _render_table(["Script", "Total Calls", "Mean / Question"], _rows_aggregate_scripts(aggregate)),
        "",
        "## Aggregate Search And SPARQL Activity",
        "",
        _render_table(["Metric", "Total", "Mean / Question"], _rows_sparql(aggregate)),
        "",
        "## Per Question Execution Summary",
        "",
        _render_table(
            ["QID", "Log", "LLM Rounds", "Tool Calls", "SPARQL Retries", "SPARQL Calls", "Duration", "Total Tokens", "Answer Items", "Question"],
            _rows_per_question_summary(question_summaries),
        ),
        "",
        "## Per Question Skill Breakdown",
        "",
        _render_table(
            ["QID", "Log", "Wikidata Search", "Graph Explore", "Few-shot", "SPARQL Exec", "Total Tools"],
            _rows_per_question_skills(question_summaries),
        ),
        "",
        "## Heaviest Questions",
        "",
        _render_table(["QID", "Log", "Total Tokens", "Duration", "Tool Calls", "Question"], _rows_heaviest(question_summaries)),
        "",
        "## Partial Log Fallbacks",
        "",
        _render_table(["QID", "LLM Rounds", "Tool Calls", "Finish Reasons", "Tool Status", "Question"], _rows_partial(question_summaries)),
        "",
        "## Missing Logs",
        "",
        _render_table(["QID", "Question"], _rows_missing(question_summaries)),
        "",
    ]

    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate markdown agent execution stats for a results directory.")
    parser.add_argument("question_file", help="Path to the question JSON file.")
    parser.add_argument("results_dir", help="Path to the results directory.")
    parser.add_argument(
        "-o",
        "--output",
        default=None,
        help="Optional markdown output path. Defaults to <results_dir>/agent_execution_stats.md",
    )
    args = parser.parse_args()

    question_file = Path(args.question_file).resolve()
    results_dir = Path(args.results_dir).resolve()

    if not question_file.exists():
        raise SystemExit(f"Question file not found: {question_file}")
    if not results_dir.is_dir():
        raise SystemExit(f"Results directory not found: {results_dir}")

    questions = _load_questions(question_file)
    split_hint = _infer_split_hint(question_file)
    question_summaries = [_summarize_question(question_entry, results_dir, split_hint) for question_entry in questions]

    report = _render_report(question_file, results_dir, question_summaries)
    output_path = Path(args.output) if args.output else results_dir / "agent_execution_stats.md"
    output_path.write_text(report + "\n", encoding="utf-8")
    print(output_path)


if __name__ == "__main__":
    main()
