# Copyright IBM Corp. 2026 - 2026
# SPDX-License-Identifier: Apache-2.0
#

#!/usr/bin/env python3
"""
Post-process an OpenCode session log (.session.log JSON) into a human-readable
Markdown trace showing agent reasoning, tool calls with inputs/outputs, and
the final answer.

Can be used standalone:
    uv run python src/format_session_log.py outputs/dev_0_session.log

Or programmatically:
    from format_session_log import format_session_log
    readable = format_session_log("outputs/dev_0_session.log")
"""

import argparse
import json
import sys
import textwrap
from datetime import datetime
from pathlib import Path
from typing import Optional


def _ts_to_str(ts_ms: Optional[int]) -> str:
    """Convert a millisecond timestamp to a readable datetime string."""
    if not ts_ms:
        return "?"
    return datetime.fromtimestamp(ts_ms / 1000).strftime("%H:%M:%S")


def _duration_str(start_ms: Optional[int], end_ms: Optional[int]) -> str:
    """Compute human-readable duration between two timestamps."""
    if not start_ms or not end_ms:
        return ""
    delta_s = (end_ms - start_ms) / 1000
    if delta_s < 1:
        return f"{int(delta_s * 1000)}ms"
    elif delta_s < 60:
        return f"{delta_s:.1f}s"
    else:
        minutes = int(delta_s // 60)
        secs = delta_s % 60
        return f"{minutes}m {secs:.0f}s"


def _indent(text: str, prefix: str = "    ") -> str:
    """Indent every line of text."""
    return textwrap.indent(text, prefix)


def _format_json_compact(obj, max_lines: int = 30) -> str:
    """Format a JSON object compactly, truncating if too long."""
    try:
        if isinstance(obj, str):
            obj = json.loads(obj)
        formatted = json.dumps(obj, indent=2, ensure_ascii=False)
    except (json.JSONDecodeError, TypeError):
        formatted = str(obj)

    lines = formatted.split("\n")
    if len(lines) > max_lines:
        kept = lines[: max_lines - 2]
        kept.append(f"    ... ({len(lines) - max_lines + 2} more lines)")
        kept.append(lines[-1])
        return "\n".join(kept)
    return formatted


def _extract_tool_summary(tool_name: str, state: dict) -> dict:
    """Extract a concise summary of a tool call."""
    input_data = state.get("input", {})
    output_raw = state.get("output", "")
    status = state.get("status", "unknown")
    title = state.get("title", "")
    metadata = state.get("metadata", {})
    time_info = state.get("time", {})

    # For bash tools, extract the command
    command = input_data.get("command", "")
    description = input_data.get("description", title or "")

    # Parse output as JSON if possible
    output_parsed = None
    if output_raw:
        try:
            output_parsed = json.loads(output_raw)
        except (json.JSONDecodeError, TypeError):
            output_parsed = None

    return {
        "tool": tool_name,
        "status": status,
        "description": description,
        "command": command,
        "input": input_data,
        "output_raw": output_raw,
        "output_parsed": output_parsed,
        "exit_code": metadata.get("exit"),
        "duration": _duration_str(time_info.get("start"), time_info.get("end")),
    }


def format_session_log(
    log_path: str,
    max_output_lines: int = 40,
    show_tokens: bool = True,
) -> str:
    """
    Convert an OpenCode session log JSON file into a human-readable Markdown trace.

    Args:
        log_path: Path to the session log JSON file.
        max_output_lines: Maximum lines to show for tool outputs.
        show_tokens: Whether to include token usage info.

    Returns:
        Formatted Markdown string.
    """
    path = Path(log_path)
    data = json.loads(path.read_text(encoding="utf-8"))

    session = data.get("session", {})
    messages = data.get("messages", [])

    # Header
    lines = []
    lines.append(f"# Session Trace: {session.get('title', 'Untitled')}")
    lines.append("")
    lines.append("## Session Metadata")
    lines.append("")
    lines.append(f"- **Session ID:** {session.get('id', '?')}")
    lines.append(f"- **Model:** {session.get('model', {}).get('id', '?')}")
    lines.append(f"- **Provider:** {session.get('model', {}).get('providerID', '?')}")

    time_info = session.get("time", {})
    created = _ts_to_str(time_info.get("created"))
    updated = _ts_to_str(time_info.get("updated"))
    duration = _duration_str(time_info.get("created"), time_info.get("updated"))
    lines.append(f"- **Started:** {created}")
    lines.append(f"- **Ended:** {updated}")
    lines.append(f"- **Duration:** {duration}")

    if show_tokens:
        tokens = session.get("tokens", {})
        lines.append(f"- **Tokens:** input={tokens.get('input', 0):,}, output={tokens.get('output', 0):,}, reasoning={tokens.get('reasoning', 0):,}")
        cache = tokens.get("cache", {})
        if cache.get("read") or cache.get("write"):
            lines.append(f"- **Cache:** read={cache.get('read', 0):,}, write={cache.get('write', 0):,}")

    lines.append("")
    lines.append("---")
    lines.append("")

    # Process messages
    step_num = 0
    for msg in messages:
        info = msg.get("info", {})
        role = info.get("role", "unknown")
        parts = msg.get("parts", [])
        msg_time = info.get("time", {})
        finish_reason = info.get("finish", "")

        if role == "user":
            lines.append("## User Message")
            lines.append("")
            for part in parts:
                if part.get("type") == "text":
                    text = part.get("text", "")
                    # Show the question prominently
                    lines.append(f"> {text.strip()}")
                    lines.append("")
            lines.append("---")
            lines.append("")

        elif role == "assistant":
            step_num += 1
            step_duration = _duration_str(msg_time.get("created"), msg_time.get("completed"))
            lines.append(f"## Step {step_num}" + (f" ({step_duration})" if step_duration else ""))
            lines.append("")

            if show_tokens:
                tokens = info.get("tokens", {})
                if tokens:
                    lines.append(
                        f"*Tokens: in={tokens.get('input', 0):,}, out={tokens.get('output', 0):,}, "
                        f"reasoning={tokens.get('reasoning', 0):,}, "
                        f"cache_read={tokens.get('cache', {}).get('read', 0):,}*"
                    )
                    lines.append("")

            # Process parts
            tool_calls_in_step = []
            for part in parts:
                ptype = part.get("type")

                if ptype == "text":
                    text = part.get("text", "").strip()
                    if text:
                        lines.append("### Agent Reasoning")
                        lines.append("")
                        lines.append(text)
                        lines.append("")

                elif ptype == "tool":
                    tool_name = part.get("tool", "unknown")
                    state = part.get("state", {})
                    summary = _extract_tool_summary(tool_name, state)
                    tool_calls_in_step.append(summary)

                elif ptype == "step-start" or ptype == "step-finish":
                    # Skip structural markers
                    pass

            # Render tool calls
            if tool_calls_in_step:
                lines.append("### Tool Calls")
                lines.append("")

                for i, tc in enumerate(tool_calls_in_step, 1):
                    status_icon = "+" if tc["status"] == "completed" else "x"
                    exit_info = ""
                    if tc["exit_code"] is not None:
                        exit_info = f" (exit={tc['exit_code']})"

                    header = f"#### [{status_icon}] {tc['tool']}"
                    if tc["description"]:
                        header += f": {tc['description']}"
                    if tc["duration"]:
                        header += f" [{tc['duration']}]"
                    header += exit_info
                    lines.append(header)
                    lines.append("")

                    # Show input
                    if tc["tool"] == "bash" and tc["command"]:
                        lines.append("**Command:**")
                        lines.append("```bash")
                        lines.append(tc["command"])
                        lines.append("```")
                        lines.append("")
                    elif tc["tool"] == "skill":
                        skill_name = tc["input"].get("name", "?")
                        lines.append(f"**Skill:** `{skill_name}`")
                        lines.append("")
                    else:
                        # Generic input display
                        if tc["input"]:
                            lines.append("**Input:**")
                            lines.append("```json")
                            lines.append(_format_json_compact(tc["input"], max_lines=15))
                            lines.append("```")
                            lines.append("")

                    # Show output
                    if tc["output_parsed"] is not None:
                        lines.append("**Output:**")
                        lines.append("```json")
                        lines.append(_format_json_compact(tc["output_parsed"], max_lines=max_output_lines))
                        lines.append("```")
                        lines.append("")
                    elif tc["output_raw"]:
                        lines.append("**Output:**")
                        lines.append("```")
                        output_lines = tc["output_raw"].split("\n")
                        if len(output_lines) > max_output_lines:
                            lines.extend(output_lines[: max_output_lines - 2])
                            lines.append(f"... ({len(output_lines) - max_output_lines + 2} more lines)")
                            lines.append(output_lines[-1])
                        else:
                            lines.append(tc["output_raw"])
                        lines.append("```")
                        lines.append("")

            # Finish reason
            if finish_reason == "stop":
                lines.append("*[End of response]*")
                lines.append("")

            lines.append("---")
            lines.append("")

    return "\n".join(lines)


def format_session_log_to_file(
    log_path: str,
    output_path: Optional[str] = None,
    max_output_lines: int = 40,
    show_tokens: bool = True,
) -> str:
    """
    Format a session log and write it to a file.

    Args:
        log_path: Path to the session log JSON file.
        output_path: Output file path. If None, replaces .log with .trace.md.
        max_output_lines: Maximum lines to show for tool outputs.
        show_tokens: Whether to include token usage info.

    Returns:
        The output file path.
    """
    if output_path is None:
        p = Path(log_path)
        output_path = str(p.with_suffix(".trace.md"))

    content = format_session_log(
        log_path,
        max_output_lines=max_output_lines,
        show_tokens=show_tokens,
    )

    Path(output_path).write_text(content, encoding="utf-8")
    return output_path


def main():
    parser = argparse.ArgumentParser(
        description="Convert OpenCode session log to human-readable trace.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Format a single session log:
  uv run python src/format_session_log.py outputs/dev_0_session.log

  # Specify output path:
  uv run python src/format_session_log.py outputs/dev_0_session.log -o trace.md

  # Format all session logs in a directory:
  uv run python src/format_session_log.py outputs/*.log
        """,
    )
    parser.add_argument(
        "logs",
        nargs="+",
        help="One or more session log JSON files to format.",
    )
    parser.add_argument(
        "-o", "--output",
        default=None,
        help="Output file path (only valid for a single input file). "
             "Default: replaces .log suffix with .trace.md",
    )
    parser.add_argument(
        "--max-output-lines",
        type=int,
        default=40,
        help="Maximum lines to show for tool outputs (default: 40).",
    )
    parser.add_argument(
        "--no-tokens",
        action="store_true",
        help="Hide token usage information.",
    )

    args = parser.parse_args()

    if args.output and len(args.logs) > 1:
        print("ERROR: --output can only be used with a single input file.", file=sys.stderr)
        sys.exit(1)

    for log_path in args.logs:
        if not Path(log_path).exists():
            print(f"WARNING: File not found: {log_path}", file=sys.stderr)
            continue

        try:
            out = format_session_log_to_file(
                log_path,
                output_path=args.output,
                max_output_lines=args.max_output_lines,
                show_tokens=not args.no_tokens,
            )
            print(f"  {log_path} -> {out}")
        except json.JSONDecodeError as e:
            print(f"ERROR: Invalid JSON in {log_path}: {e}", file=sys.stderr)
        except Exception as e:
            print(f"ERROR: Failed to process {log_path}: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
