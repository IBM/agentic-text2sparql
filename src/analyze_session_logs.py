# Copyright IBM Corp. 2026 - 2026
# SPDX-License-Identifier: Apache-2.0
#

#!/usr/bin/env python3
"""
Analyze OpenCode session logs and emit JSON statistics.

Examples:
    uv run python src/analyze_session_logs.py outputs/june-30-en-no-mentions-test-fewshot/test_100_session.log
    uv run python src/analyze_session_logs.py outputs/june-30-en-no-mentions-test-fewshot
    uv run python src/analyze_session_logs.py outputs/**/test_*_session.log -o outputs/report.json
"""

from __future__ import annotations

import argparse
import glob
import json
import shlex
import statistics
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _safe_int(value: Any) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return int(value)
    return 0


def _ms_duration(start_ms: Any, end_ms: Any) -> int | None:
    if start_ms is None or end_ms is None:
        return None
    return int(end_ms) - int(start_ms)


def _iso_from_ms(ts_ms: Any) -> str | None:
    if ts_ms is None:
        return None
    return datetime.fromtimestamp(int(ts_ms) / 1000, tz=timezone.utc).isoformat()


def _safe_json_loads(raw: Any) -> Any:
    if not isinstance(raw, str):
        return None
    raw = raw.strip()
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def _counter_to_dict(counter: Counter[str]) -> dict[str, int]:
    return {key: counter[key] for key in sorted(counter)}


def _numeric_summary(values: list[int]) -> dict[str, float | int | None]:
    if not values:
        return {
            "count": 0,
            "min": None,
            "max": None,
            "mean": None,
            "median": None,
            "sum": 0,
        }

    return {
        "count": len(values),
        "min": min(values),
        "max": max(values),
        "mean": round(statistics.fmean(values), 2),
        "median": statistics.median(values),
        "sum": sum(values),
    }


def _extract_script_info(command: str) -> dict[str, Any]:
    info: dict[str, Any] = {
        "executable": None,
        "script_path": None,
        "script_name": None,
        "category": None,
        "skill_name": None,
        "skill_script": None,
    }

    if not command:
        return info

    try:
        tokens = shlex.split(command)
    except ValueError:
        tokens = command.split()

    if not tokens:
        return info

    info["executable"] = tokens[0]

    script_token = next((token for token in tokens if token.endswith(".py")), None)
    if not script_token:
        info["category"] = "shell-command"
        return info

    normalized = script_token
    if normalized.startswith("./"):
        normalized = normalized[2:]

    info["script_path"] = normalized
    info["script_name"] = Path(normalized).name

    skill_prefix = ".agents/skills/"
    scripts_segment = "/scripts/"
    if normalized.startswith(skill_prefix) and scripts_segment in normalized:
        remainder = normalized[len(skill_prefix):]
        skill_name, script_name = remainder.split(scripts_segment, 1)
        info["category"] = "skill-script"
        info["skill_name"] = skill_name
        info["skill_script"] = f"{skill_name}/{script_name}"
    elif normalized.startswith("src/"):
        info["category"] = "src-script"
    else:
        info["category"] = "python-script"

    return info


def _detect_sparql_query_type(sparql: str) -> str | None:
    if not sparql:
        return None

    compact = sparql.lstrip().upper()
    prefixes = (
        "PREFIX ",
        "BASE ",
    )
    while compact.startswith(prefixes):
        newline = compact.find("\n")
        if newline == -1:
            return None
        compact = compact[newline + 1 :].lstrip()

    for query_type in ("SELECT", "ASK", "CONSTRUCT", "DESCRIBE"):
        if compact.startswith(query_type):
            return query_type.lower()
    return None


def _extract_question_text(messages: list[dict[str, Any]]) -> str | None:
    for message in messages:
        if message.get("info", {}).get("role") != "user":
            continue
        texts = [part.get("text", "") for part in message.get("parts", []) if part.get("type") == "text"]
        question = "\n".join(text.strip() for text in texts if text.strip()).strip()
        if question:
            return question
    return None


def _extract_final_response_text(messages: list[dict[str, Any]]) -> str | None:
    assistant_messages = [message for message in messages if message.get("info", {}).get("role") == "assistant"]
    if not assistant_messages:
        return None

    parts = assistant_messages[-1].get("parts", [])
    texts = [part.get("text", "") for part in parts if part.get("type") == "text"]
    response = "\n".join(text.strip() for text in texts if text.strip()).strip()
    return response or None


def _derive_question_id(path: Path, session_title: Any) -> str | None:
    stem = path.stem
    if stem.endswith("_session_partial"):
        return stem[: -len("_session_partial")]
    if stem.endswith("_session"):
        return stem[: -len("_session")]
    if isinstance(session_title, str) and "-q" in session_title:
        return session_title.rsplit("-q", 1)[-1]
    return None


def analyze_session_log(log_path: str | Path) -> dict[str, Any]:
    path = Path(log_path)
    data = json.loads(path.read_text(encoding="utf-8"))

    session = data.get("session", {})
    messages = data.get("messages", [])

    message_counts: Counter[str] = Counter()
    finish_reasons: Counter[str] = Counter()
    part_counts: Counter[str] = Counter()
    tool_counts: Counter[str] = Counter()
    tool_status_counts: Counter[str] = Counter()
    skill_usage: Counter[str] = Counter()
    bash_categories: Counter[str] = Counter()
    script_paths: Counter[str] = Counter()
    script_names: Counter[str] = Counter()
    command_skill_usage: Counter[str] = Counter()
    skill_scripts: Counter[str] = Counter()
    executables: Counter[str] = Counter()
    patch_files: Counter[str] = Counter()

    assistant_input_tokens: list[int] = []
    assistant_output_tokens: list[int] = []
    assistant_reasoning_tokens: list[int] = []
    assistant_cache_read_tokens: list[int] = []
    assistant_cache_write_tokens: list[int] = []
    assistant_total_tokens: list[int] = []
    assistant_durations_ms: list[int] = []
    tool_durations_ms: list[int] = []
    tool_round_indices: set[int] = set()

    sparql_stats = {
        "queries": 0,
        "successes": 0,
        "failures": 0,
        "query_types": Counter(),
        "rows_returned": [],
        "execution_time_ms": [],
    }
    wikidata_search_result_counts: list[int] = []
    graph_exploration_result_counts: list[int] = []

    assistant_rounds: list[dict[str, Any]] = []
    reasoning_rounds = 0
    rounds_with_tools = 0

    for message_index, message in enumerate(messages, start=1):
        info = message.get("info", {})
        role = info.get("role", "unknown")
        message_counts[role] += 1

        if role != "assistant":
            for part in message.get("parts", []):
                if part.get("type") == "patch":
                    for patched_file in part.get("files", []):
                        patch_files[patched_file] += 1
            continue

        finish = info.get("finish") or "unknown"
        finish_reasons[finish] += 1

        time_info = info.get("time", {})
        duration_ms = _ms_duration(time_info.get("created"), time_info.get("completed"))
        if duration_ms is not None:
            assistant_durations_ms.append(duration_ms)

        tokens = info.get("tokens", {})
        assistant_input_tokens.append(_safe_int(tokens.get("input")))
        assistant_output_tokens.append(_safe_int(tokens.get("output")))
        assistant_reasoning_tokens.append(_safe_int(tokens.get("reasoning")))
        assistant_cache_read_tokens.append(_safe_int(tokens.get("cache", {}).get("read")))
        assistant_cache_write_tokens.append(_safe_int(tokens.get("cache", {}).get("write")))
        assistant_total_tokens.append(_safe_int(tokens.get("total")))

        round_part_counts: Counter[str] = Counter()
        round_tool_counts: Counter[str] = Counter()
        round_script_names: Counter[str] = Counter()
        round_skill_scripts: Counter[str] = Counter()
        round_texts: list[str] = []
        round_tool_calls = 0

        for part in message.get("parts", []):
            part_type = part.get("type", "unknown")
            part_counts[part_type] += 1
            round_part_counts[part_type] += 1

            if part_type == "text":
                text = part.get("text", "").strip()
                if text:
                    round_texts.append(text)

            if part_type == "patch":
                for patched_file in part.get("files", []):
                    patch_files[patched_file] += 1

            if part_type != "tool":
                continue

            round_tool_calls += 1
            tool_round_indices.add(len(assistant_rounds) + 1)

            tool_name = part.get("tool", "unknown")
            round_tool_counts[tool_name] += 1
            tool_counts[tool_name] += 1

            state = part.get("state", {})
            status = state.get("status") or "unknown"
            tool_status_counts[status] += 1

            tool_duration_ms = _ms_duration(state.get("time", {}).get("start"), state.get("time", {}).get("end"))
            if tool_duration_ms is not None:
                tool_durations_ms.append(tool_duration_ms)

            input_data = state.get("input", {}) if isinstance(state.get("input"), dict) else {}
            output_data = _safe_json_loads(state.get("output"))

            if tool_name == "skill":
                skill_name = input_data.get("name") or state.get("metadata", {}).get("name")
                if skill_name:
                    skill_usage[str(skill_name)] += 1

            if tool_name != "bash":
                continue

            command = str(input_data.get("command", ""))
            script_info = _extract_script_info(command)

            if script_info["category"]:
                bash_categories[str(script_info["category"])] += 1
            if script_info["executable"]:
                executables[str(script_info["executable"])] += 1
            if script_info["script_path"]:
                script_paths[str(script_info["script_path"])] += 1
            if script_info["script_name"]:
                script_name = str(script_info["script_name"])
                script_names[script_name] += 1
                round_script_names[script_name] += 1
            if script_info["skill_name"]:
                command_skill_usage[str(script_info["skill_name"])] += 1
            if script_info["skill_script"]:
                skill_script = str(script_info["skill_script"])
                skill_scripts[skill_script] += 1
                round_skill_scripts[skill_script] += 1

            script_name = script_info.get("script_name")
            if not isinstance(output_data, dict) or not script_name:
                continue

            if script_name == "wikidata_search.py":
                wikidata_search_result_counts.append(_safe_int(output_data.get("result_count")))

            if script_name == "graph_explorer.py":
                graph_exploration_result_counts.append(_safe_int(output_data.get("result_count")))

            if script_name == "sparql_executor.py":
                sparql_stats["queries"] += 1
                if output_data.get("success"):
                    sparql_stats["successes"] += 1
                else:
                    sparql_stats["failures"] += 1

                query_type = _detect_sparql_query_type(str(output_data.get("sparql", "")))
                if query_type:
                    sparql_stats["query_types"][query_type] += 1

                execution_time_ms = output_data.get("execution_time_ms")
                if isinstance(execution_time_ms, (int, float)):
                    sparql_stats["execution_time_ms"].append(int(execution_time_ms))

                results = output_data.get("results", {})
                if isinstance(results, dict):
                    row_count = results.get("row_count")
                    if isinstance(row_count, (int, float)):
                        sparql_stats["rows_returned"].append(int(row_count))

        assistant_rounds.append(
            {
                "round_index": len(assistant_rounds) + 1,
                "message_index": message_index,
                "finish_reason": finish,
                "duration_ms": duration_ms,
                "tool_calls": round_tool_calls,
                "tool_counts": _counter_to_dict(round_tool_counts),
                "part_counts": _counter_to_dict(round_part_counts),
                "script_names": _counter_to_dict(round_script_names),
                "skill_scripts": _counter_to_dict(round_skill_scripts),
                "input_tokens": _safe_int(tokens.get("input")),
                "output_tokens": _safe_int(tokens.get("output")),
                "reasoning_tokens": _safe_int(tokens.get("reasoning")),
                "cache_read_tokens": _safe_int(tokens.get("cache", {}).get("read")),
                "cache_write_tokens": _safe_int(tokens.get("cache", {}).get("write")),
                "total_tokens": _safe_int(tokens.get("total")),
                "text_preview": round_texts[0][:200] if round_texts else None,
            }
        )

        if round_texts:
            reasoning_rounds += 1
        if round_tool_calls:
            rounds_with_tools += 1

    session_time = session.get("time", {})
    session_tokens = session.get("tokens", {})
    final_response_text = _extract_final_response_text(messages)
    final_response_json = _safe_json_loads(final_response_text)
    final_answer_is_array = isinstance(final_response_json, list)
    final_answer_items = len(final_response_json) if final_answer_is_array else None
    total_tool_calls = sum(tool_counts.values())
    llm_rounds = message_counts.get("assistant", 0)
    sparql_calls = script_names.get("sparql_executor.py", 0)

    return {
        "file": {
            "path": str(path),
            "name": path.name,
            "stem": path.stem,
            "size_bytes": path.stat().st_size,
            "is_partial": path.name.endswith("_session_partial.log"),
            "question_id": _derive_question_id(path, session.get("title")),
        },
        "session": {
            "id": session.get("id"),
            "title": session.get("title"),
            "agent": session.get("agent"),
            "version": session.get("version"),
            "model": session.get("model", {}).get("id"),
            "provider": session.get("model", {}).get("providerID"),
            "created_at": _iso_from_ms(session_time.get("created")),
            "updated_at": _iso_from_ms(session_time.get("updated")),
            "duration_ms": _ms_duration(session_time.get("created"), session_time.get("updated")),
            "cost": session.get("cost"),
        },
        "question": _extract_question_text(messages),
        "final_response_text": final_response_text,
        "final_response_json": final_response_json,
        "final_answer": {
            "is_json": final_response_json is not None,
            "is_json_array": final_answer_is_array,
            "item_count": final_answer_items,
        },
        "message_counts": _counter_to_dict(message_counts),
        "llm_rounds": llm_rounds,
        "tool_call_rounds": len(tool_round_indices),
        "finish_reasons": _counter_to_dict(finish_reasons),
        "part_counts": _counter_to_dict(part_counts),
        "execution_summary": {
            "rounds_with_reasoning_text": reasoning_rounds,
            "rounds_with_tools": rounds_with_tools,
            "avg_tool_calls_per_llm_round": round(total_tool_calls / llm_rounds, 2) if llm_rounds else 0,
            "avg_tool_calls_per_tool_round": round(total_tool_calls / rounds_with_tools, 2) if rounds_with_tools else 0,
            "sparql_retry_count": max(sparql_calls - 1, 0),
        },
        "tool_calls": {
            "total": total_tool_calls,
            "completed": tool_status_counts.get("completed", 0),
            "failed": sum(count for status, count in tool_status_counts.items() if status != "completed"),
            "by_tool": _counter_to_dict(tool_counts),
            "by_status": _counter_to_dict(tool_status_counts),
        },
        "skills": {
            "loaded": _counter_to_dict(skill_usage),
            "loaded_total": sum(skill_usage.values()),
            "loaded_unique": len(skill_usage),
            "command_usage": _counter_to_dict(command_skill_usage),
            "command_usage_total": sum(command_skill_usage.values()),
            "skill_scripts": _counter_to_dict(skill_scripts),
        },
        "commands": {
            "bash_calls": tool_counts.get("bash", 0),
            "categories": _counter_to_dict(bash_categories),
            "executables": _counter_to_dict(executables),
            "script_paths": _counter_to_dict(script_paths),
            "scripts": _counter_to_dict(script_names),
        },
        "tokens": {
            "session": {
                "input": _safe_int(session_tokens.get("input")),
                "output": _safe_int(session_tokens.get("output")),
                "reasoning": _safe_int(session_tokens.get("reasoning")),
                "cache_read": _safe_int(session_tokens.get("cache", {}).get("read")),
                "cache_write": _safe_int(session_tokens.get("cache", {}).get("write")),
                "total": (
                    _safe_int(session_tokens.get("input"))
                    + _safe_int(session_tokens.get("output"))
                    + _safe_int(session_tokens.get("reasoning"))
                    + _safe_int(session_tokens.get("cache", {}).get("read"))
                    + _safe_int(session_tokens.get("cache", {}).get("write"))
                ),
            },
            "assistant_round_sums": {
                "input": sum(assistant_input_tokens),
                "output": sum(assistant_output_tokens),
                "reasoning": sum(assistant_reasoning_tokens),
                "cache_read": sum(assistant_cache_read_tokens),
                "cache_write": sum(assistant_cache_write_tokens),
                "total": sum(assistant_total_tokens),
            },
        },
        "durations_ms": {
            "assistant_rounds": _numeric_summary(assistant_durations_ms),
            "tool_calls": _numeric_summary(tool_durations_ms),
        },
        "patches": {
            "unique_files": len(patch_files),
            "files_touched": _counter_to_dict(patch_files),
        },
        "domain_stats": {
            "wikidata_search": {
                "calls": script_names.get("wikidata_search.py", 0),
                "result_counts": _numeric_summary(wikidata_search_result_counts),
            },
            "graph_exploration": {
                "calls": script_names.get("graph_explorer.py", 0),
                "result_counts": _numeric_summary(graph_exploration_result_counts),
            },
            "sparql_execution": {
                "calls": script_names.get("sparql_executor.py", 0),
                "successes": sparql_stats["successes"],
                "failures": sparql_stats["failures"],
                "query_types": _counter_to_dict(sparql_stats["query_types"]),
                "rows_returned": _numeric_summary(sparql_stats["rows_returned"]),
                "execution_time_ms": _numeric_summary(sparql_stats["execution_time_ms"]),
            },
        },
        "assistant_rounds": assistant_rounds,
    }


def _collect_counter(summaries: list[dict[str, Any]], path: tuple[str, ...]) -> Counter[str]:
    counter: Counter[str] = Counter()
    for summary in summaries:
        node: Any = summary
        for key in path:
            if not isinstance(node, dict):
                node = None
                break
            node = node.get(key)
        if isinstance(node, dict):
            counter.update({str(key): _safe_int(value) for key, value in node.items()})
    return counter


def _collect_int(summaries: list[dict[str, Any]], path: tuple[str, ...]) -> list[int]:
    values: list[int] = []
    for summary in summaries:
        node: Any = summary
        for key in path:
            if not isinstance(node, dict):
                node = None
                break
            node = node.get(key)
        if isinstance(node, (int, float)):
            values.append(int(node))
    return values


def build_aggregate_report(summaries: list[dict[str, Any]]) -> dict[str, Any]:
    llm_rounds = _collect_int(summaries, ("llm_rounds",))
    tool_calls_total = _collect_int(summaries, ("tool_calls", "total"))
    session_duration_ms = _collect_int(summaries, ("session", "duration_ms"))
    reasoning_rounds = _collect_int(summaries, ("execution_summary", "rounds_with_reasoning_text"))
    rounds_with_tools = _collect_int(summaries, ("execution_summary", "rounds_with_tools"))
    sparql_retry_count = _collect_int(summaries, ("execution_summary", "sparql_retry_count"))
    final_answer_item_counts = _collect_int(summaries, ("final_answer", "item_count"))
    final_json_arrays = sum(
        1 for summary in summaries if summary.get("final_answer", {}).get("is_json_array")
    )

    session_tokens_input = _collect_int(summaries, ("tokens", "session", "input"))
    session_tokens_output = _collect_int(summaries, ("tokens", "session", "output"))
    session_tokens_reasoning = _collect_int(summaries, ("tokens", "session", "reasoning"))
    session_tokens_cache_read = _collect_int(summaries, ("tokens", "session", "cache_read"))
    session_tokens_cache_write = _collect_int(summaries, ("tokens", "session", "cache_write"))
    session_tokens_total = _collect_int(summaries, ("tokens", "session", "total"))

    return {
        "sessions": len(summaries),
        "llm_rounds": _numeric_summary(llm_rounds),
        "rounds_with_reasoning_text": _numeric_summary(reasoning_rounds),
        "rounds_with_tools": _numeric_summary(rounds_with_tools),
        "tool_calls": _numeric_summary(tool_calls_total),
        "sparql_retry_count": _numeric_summary(sparql_retry_count),
        "session_duration_ms": _numeric_summary(session_duration_ms),
        "final_answers": {
            "json_arrays": final_json_arrays,
            "non_json_arrays": len(summaries) - final_json_arrays,
            "item_count": _numeric_summary(final_answer_item_counts),
        },
        "tokens": {
            "input": _numeric_summary(session_tokens_input),
            "output": _numeric_summary(session_tokens_output),
            "reasoning": _numeric_summary(session_tokens_reasoning),
            "cache_read": _numeric_summary(session_tokens_cache_read),
            "cache_write": _numeric_summary(session_tokens_cache_write),
            "total": _numeric_summary(session_tokens_total),
        },
        "message_counts": _counter_to_dict(_collect_counter(summaries, ("message_counts",))),
        "finish_reasons": _counter_to_dict(_collect_counter(summaries, ("finish_reasons",))),
        "part_counts": _counter_to_dict(_collect_counter(summaries, ("part_counts",))),
        "tool_usage": _counter_to_dict(_collect_counter(summaries, ("tool_calls", "by_tool"))),
        "tool_status": _counter_to_dict(_collect_counter(summaries, ("tool_calls", "by_status"))),
        "loaded_skills": _counter_to_dict(_collect_counter(summaries, ("skills", "loaded"))),
        "command_skill_usage": _counter_to_dict(_collect_counter(summaries, ("skills", "command_usage"))),
        "skill_scripts": _counter_to_dict(_collect_counter(summaries, ("skills", "skill_scripts"))),
        "scripts": _counter_to_dict(_collect_counter(summaries, ("commands", "scripts"))),
        "script_paths": _counter_to_dict(_collect_counter(summaries, ("commands", "script_paths"))),
        "bash_categories": _counter_to_dict(_collect_counter(summaries, ("commands", "categories"))),
        "executables": _counter_to_dict(_collect_counter(summaries, ("commands", "executables"))),
        "domain_stats": {
            "wikidata_search_calls": sum(_collect_int(summaries, ("domain_stats", "wikidata_search", "calls"))),
            "graph_exploration_calls": sum(_collect_int(summaries, ("domain_stats", "graph_exploration", "calls"))),
            "sparql_execution_calls": sum(_collect_int(summaries, ("domain_stats", "sparql_execution", "calls"))),
            "sparql_successes": sum(_collect_int(summaries, ("domain_stats", "sparql_execution", "successes"))),
            "sparql_failures": sum(_collect_int(summaries, ("domain_stats", "sparql_execution", "failures"))),
            "sparql_query_types": _counter_to_dict(
                _collect_counter(summaries, ("domain_stats", "sparql_execution", "query_types"))
            ),
        },
        "patches": {
            "unique_files": len(_collect_counter(summaries, ("patches", "files_touched"))),
            "files_touched": _counter_to_dict(_collect_counter(summaries, ("patches", "files_touched"))),
        },
    }


def discover_log_paths(inputs: list[str]) -> list[Path]:
    paths: list[Path] = []
    seen: set[Path] = set()

    for raw in inputs:
        matches: list[Path] = []

        if glob.has_magic(raw):
            matches = [Path(match) for match in glob.glob(raw, recursive=True)]
        else:
            candidate = Path(raw).expanduser()
            if candidate.is_dir():
                matches = sorted(candidate.rglob("*_session.log"))
            elif candidate.exists():
                matches = [candidate]
            else:
                raise FileNotFoundError(raw)

        for match in sorted(matches):
            resolved = match.resolve()
            if resolved.is_file() and resolved not in seen:
                seen.add(resolved)
                paths.append(resolved)

    return sorted(paths)


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze OpenCode session logs and emit JSON statistics.")
    parser.add_argument("inputs", nargs="+", help="Session log file(s), directory path(s), or glob pattern(s).")
    parser.add_argument("-o", "--output", help="Write JSON output to this file instead of stdout.")
    parser.add_argument(
        "--aggregate-only",
        action="store_true",
        help="Emit only aggregate statistics, omitting the per-log entries.",
    )
    args = parser.parse_args()

    try:
        log_paths = discover_log_paths(args.inputs)
    except FileNotFoundError as exc:
        print(f"ERROR: Input not found: {exc}", file=sys.stderr)
        sys.exit(1)

    if not log_paths:
        print("ERROR: No session logs found.", file=sys.stderr)
        sys.exit(1)

    summaries = [analyze_session_log(path) for path in log_paths]
    report: dict[str, Any] = {
        "generated_at": datetime.now(tz=timezone.utc).isoformat(),
        "input_count": len(args.inputs),
        "log_count": len(summaries),
        "aggregate": build_aggregate_report(summaries),
    }
    if not args.aggregate_only:
        report["logs"] = summaries

    output_text = json.dumps(report, indent=2, ensure_ascii=False)

    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(output_text + "\n", encoding="utf-8")
    else:
        print(output_text)


if __name__ == "__main__":
    main()
