# Copyright IBM Corp. 2026 - 2026
# SPDX-License-Identifier: Apache-2.0
#

#!/usr/bin/env python3

"""Standalone SPARQL execution script.

Executes SPARQL queries against the Wikidata Query Service and returns
structured results as JSON.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

# Load .env file from project root
load_dotenv(Path(__file__).resolve().parents[4] / ".env")

try:
    import requests
except ImportError as exc:
    raise SystemExit(
        "Missing dependency 'requests'. Install it with: uv sync"
    ) from exc


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

DEFAULT_ENDPOINT = os.environ.get(
    "WIKIDATA_SPARQL_ENDPOINT",
    "https://backend.wikikgqa.skynet.coypu.org",
)
DEFAULT_TIMEOUT = 60
DEFAULT_MAX_ROWS = 100
DEFAULT_PAGE_SIZE = 100
DEFAULT_USER_AGENT = os.environ.get(
    "WIKIDATA_USER_AGENT",
    "AgenticText2SPARQL/1.0 (https://github.com/ibm/agentic-text2sparql)",
)

# Basic Auth credentials (optional — only used if both username AND password are non-empty)
SPARQL_USERNAME = os.environ.get("WIKIDATA_SPARQL_USERNAME", "")
SPARQL_PASSWORD = os.environ.get("WIKIDATA_SPARQL_PASSWORD", "")
SPARQL_AUTH = (SPARQL_USERNAME, SPARQL_PASSWORD) if SPARQL_USERNAME and SPARQL_PASSWORD else None

# Disallowed operations
WRITE_KEYWORDS = {"INSERT", "DELETE", "LOAD", "CLEAR", "DROP", "CREATE", "ADD", "MOVE", "COPY"}

# Standard Wikidata SPARQL prefixes (needed for endpoints that don't have them built-in)
WIKIDATA_PREFIXES = """\
PREFIX wd: <http://www.wikidata.org/entity/>
PREFIX wdt: <http://www.wikidata.org/prop/direct/>
PREFIX wikibase: <http://wikiba.se/ontology#>
PREFIX p: <http://www.wikidata.org/prop/>
PREFIX ps: <http://www.wikidata.org/prop/statement/>
PREFIX pq: <http://www.wikidata.org/prop/qualifier/>
PREFIX psn: <http://www.wikidata.org/prop/statement/value-normalized/>
PREFIX pqn: <http://www.wikidata.org/prop/qualifier/value-normalized/>
PREFIX pr: <http://www.wikidata.org/prop/reference/>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX bd: <http://www.bigdata.com/rdf#>
PREFIX schema: <http://schema.org/>
PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
"""


# ---------------------------------------------------------------------------
# Utility functions
# ---------------------------------------------------------------------------


def is_read_only(sparql: str) -> bool:
    """Check if the SPARQL query is read-only."""
    # Simple check: look for write keywords at the start of the query
    # Skip any PREFIX declarations first
    upper = sparql.strip().upper()
    # Strip PREFIX lines
    while upper.startswith("PREFIX"):
        newline_idx = upper.find("\n")
        if newline_idx == -1:
            break
        upper = upper[newline_idx + 1:].strip()
    for keyword in WRITE_KEYWORDS:
        if upper.startswith(keyword):
            return False
    return True


def _add_prefixes(sparql: str) -> str:
    """Add standard Wikidata prefixes if not already present."""
    if "PREFIX" in sparql.upper()[:200]:
        return sparql
    return WIKIDATA_PREFIXES + sparql


def classify_error(http_status: int | None, message: str) -> str:
    """Classify the error type from HTTP status and message."""
    if http_status == 400:
        return "syntax_error"
    elif http_status == 403:
        return "forbidden"
    elif http_status == 429:
        return "rate_limited"
    elif http_status == 500:
        return "server_error"
    elif http_status == 503:
        return "service_unavailable"
    elif "timeout" in message.lower() or "deadline" in message.lower():
        return "timeout"
    elif http_status is None:
        return "connection_error"
    else:
        return "unknown_error"


# ---------------------------------------------------------------------------
# SPARQL Execution
# ---------------------------------------------------------------------------


def execute_sparql(
    sparql: str,
    endpoint: str = DEFAULT_ENDPOINT,
    timeout: int = DEFAULT_TIMEOUT,
    max_rows: int = DEFAULT_MAX_ROWS,
    paginate: bool = False,
    page_size: int = DEFAULT_PAGE_SIZE,
) -> dict[str, Any]:
    """Execute a SPARQL query against the Wikidata endpoint.

    Args:
        sparql: The SPARQL query string.
        endpoint: SPARQL endpoint URL.
        timeout: Request timeout in seconds.
        max_rows: Maximum rows to return (per page if not paginating, total cap if paginating).
        paginate: If True, automatically paginate using LIMIT/OFFSET to fetch all results.
        page_size: Number of rows per page when paginating.
        timeout: Request timeout in seconds.
        max_rows: Maximum rows to return.

    Returns:
        dict with success status, results, timing, and any error.
    """
    if not is_read_only(sparql):
        return {
            "success": False,
            "sparql": sparql,
            "results": None,
            "execution_time_ms": 0,
            "endpoint": endpoint,
            "error": {
                "type": "forbidden",
                "message": "Write operations are not allowed. Only SELECT, ASK, CONSTRUCT, and DESCRIBE queries are permitted.",
                "http_status": None,
                "details": None,
            },
        }

    # Add standard prefixes if not already present
    sparql = _add_prefixes(sparql)

    headers = {
        "User-Agent": DEFAULT_USER_AGENT,
        "Accept": "application/sparql-results+json",
    }

    params = {
        "query": sparql,
        "format": "json",
    }

    start_time = time.time()

    try:
        response = requests.get(
            endpoint,
            params=params,
            headers=headers,
            timeout=timeout,
            auth=SPARQL_AUTH,
        )
        execution_time_ms = int((time.time() - start_time) * 1000)

        if response.status_code != 200:
            error_message = response.text[:500] if response.text else f"HTTP {response.status_code}"
            error_type = classify_error(response.status_code, error_message)

            details = None
            if error_type == "timeout":
                details = "Consider simplifying the query, adding LIMIT, or removing unbounded property paths"
            elif error_type == "rate_limited":
                details = "Too many requests. Wait at least 1 second between queries."

            return {
                "success": False,
                "sparql": sparql,
                "results": None,
                "execution_time_ms": execution_time_ms,
                "endpoint": endpoint,
                "error": {
                    "type": error_type,
                    "message": error_message,
                    "http_status": response.status_code,
                    "details": details,
                },
            }

        # Parse results
        data = response.json()
        results = _parse_results(data, max_rows)

        # If paginate is enabled and results are truncated, fetch remaining pages
        if paginate and results.get("truncated") and results.get("type") == "bindings":
            all_rows = list(results["rows"])
            total_fetched = results["row_count"]  # Total from first page (before truncation)

            # Check if query already has LIMIT — if so, don't paginate (user set explicit limit)
            sparql_upper = sparql.upper()
            if "LIMIT" in sparql_upper:
                # User already specified LIMIT, respect it — don't paginate
                pass
            else:
                # Add ORDER BY for stable pagination if not present
                has_order = "ORDER BY" in sparql_upper
                base_query = sparql.rstrip().rstrip(";").rstrip()

                offset = page_size
                max_total = max_rows if max_rows > page_size else 5000  # Safety cap

                while offset < total_fetched and offset < max_total:
                    paged_query = f"{base_query} LIMIT {page_size} OFFSET {offset}"
                    if not has_order:
                        # Add a basic ORDER BY to ensure stable pagination
                        # Use the first variable
                        if results["variables"]:
                            first_var = results["variables"][0]
                            paged_query = f"{base_query} ORDER BY ?{first_var} LIMIT {page_size} OFFSET {offset}"

                    page_params = {"query": paged_query, "format": "json"}
                    try:
                        page_response = requests.get(
                            endpoint, params=page_params, headers=headers,
                            timeout=timeout, auth=SPARQL_AUTH,
                        )
                        if page_response.status_code == 200:
                            page_data = page_response.json()
                            page_bindings = page_data.get("results", {}).get("bindings", [])
                            if not page_bindings:
                                break  # No more results
                            for binding in page_bindings:
                                row = {}
                                for var in results["variables"]:
                                    if var in binding:
                                        row[var] = binding[var].get("value", "")
                                    else:
                                        row[var] = None
                                all_rows.append(row)
                            offset += page_size
                        else:
                            break  # Stop on error
                    except Exception:
                        break  # Stop on any error

                # Update results with all fetched rows
                results["rows"] = all_rows[:max_total]
                results["row_count"] = len(results["rows"])
                results["truncated"] = len(all_rows) > max_total

        return {
            "success": True,
            "sparql": sparql,
            "results": results,
            "execution_time_ms": execution_time_ms,
            "endpoint": endpoint,
            "error": None,
        }

    except requests.exceptions.Timeout:
        execution_time_ms = int((time.time() - start_time) * 1000)
        return {
            "success": False,
            "sparql": sparql,
            "results": None,
            "execution_time_ms": execution_time_ms,
            "endpoint": endpoint,
            "error": {
                "type": "timeout",
                "message": f"Query execution exceeded {timeout} second timeout",
                "http_status": None,
                "details": "Consider simplifying the query, adding LIMIT, or removing unbounded property paths",
            },
        }

    except requests.exceptions.ConnectionError as exc:
        execution_time_ms = int((time.time() - start_time) * 1000)
        return {
            "success": False,
            "sparql": sparql,
            "results": None,
            "execution_time_ms": execution_time_ms,
            "endpoint": endpoint,
            "error": {
                "type": "connection_error",
                "message": f"Connection failed: {exc}",
                "http_status": None,
                "details": "Check network connectivity and endpoint URL",
            },
        }

    except requests.exceptions.RequestException as exc:
        execution_time_ms = int((time.time() - start_time) * 1000)
        return {
            "success": False,
            "sparql": sparql,
            "results": None,
            "execution_time_ms": execution_time_ms,
            "endpoint": endpoint,
            "error": {
                "type": "unknown_error",
                "message": f"Request failed: {exc}",
                "http_status": None,
                "details": None,
            },
        }

    except (json.JSONDecodeError, KeyError, ValueError) as exc:
        execution_time_ms = int((time.time() - start_time) * 1000)
        return {
            "success": False,
            "sparql": sparql,
            "results": None,
            "execution_time_ms": execution_time_ms,
            "endpoint": endpoint,
            "error": {
                "type": "parse_error",
                "message": f"Failed to parse response: {exc}",
                "http_status": 200,
                "details": "The endpoint returned a 200 but the response could not be parsed as SPARQL JSON results",
            },
        }


def _parse_results(data: dict[str, Any], max_rows: int) -> dict[str, Any]:
    """Parse SPARQL JSON results into a structured format.

    Handles both SELECT (results/bindings) and ASK (boolean) result formats.
    """
    # ASK query result
    if "boolean" in data:
        return {
            "type": "boolean",
            "value": data["boolean"],
            "variables": [],
            "rows": [],
            "row_count": 0,
            "truncated": False,
        }

    # SELECT query result
    head = data.get("head", {})
    variables = head.get("vars", [])

    bindings = data.get("results", {}).get("bindings", [])
    total_count = len(bindings)
    truncated = total_count > max_rows

    if truncated:
        bindings = bindings[:max_rows]

    rows = []
    for binding in bindings:
        row = {}
        for var in variables:
            if var in binding:
                cell = binding[var]
                # Extract value, simplifying the representation
                value = cell.get("value", "")
                row[var] = value
            else:
                row[var] = None
        rows.append(row)

    return {
        "type": "bindings",
        "variables": variables,
        "rows": rows,
        "row_count": total_count,
        "truncated": truncated,
    }


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Execute SPARQL queries against the Wikidata Query Service."
    )

    # Query source (one required)
    query_group = parser.add_mutually_exclusive_group(required=True)
    query_group.add_argument(
        "--sparql", "-q",
        help="SPARQL query string.",
    )
    query_group.add_argument(
        "--file", "-f",
        help="Path to a file containing the SPARQL query.",
    )

    # Optional arguments
    parser.add_argument(
        "--timeout", "-t",
        type=int,
        default=DEFAULT_TIMEOUT,
        help=f"Query timeout in seconds (default: {DEFAULT_TIMEOUT}).",
    )
    parser.add_argument(
        "--max-rows",
        type=int,
        default=DEFAULT_MAX_ROWS,
        help=f"Maximum rows to return (default: {DEFAULT_MAX_ROWS}).",
    )
    parser.add_argument(
        "--paginate",
        action="store_true",
        help="Automatically paginate with LIMIT/OFFSET to fetch all results when query returns more than max-rows.",
    )
    parser.add_argument(
        "--endpoint",
        default=DEFAULT_ENDPOINT,
        help=f"SPARQL endpoint URL (default: {DEFAULT_ENDPOINT}).",
    )
    parser.add_argument(
        "--format",
        choices=["json", "csv", "tsv"],
        default="json",
        help="Output format (default: json). Note: csv/tsv only affect the output display.",
    )
    parser.add_argument(
        "--output-file",
        help="Write result JSON to a file instead of stdout.",
    )
    parser.add_argument(
        "--extract-ids",
        help="Extract Wikidata entity IDs from results and write as JSON array to this file. "
             "Useful for large result sets that shouldn't be loaded into agent context. "
             "Extracts QIDs/PIDs from URI values (e.g., 'http://www.wikidata.org/entity/Q42' → 'Q42'), "
             "and includes literal values as-is.",
    )

    return parser.parse_args()


# ---------------------------------------------------------------------------
# Main execution
# ---------------------------------------------------------------------------


def main() -> None:
    args = parse_args()

    # Get the SPARQL query
    if args.sparql:
        sparql = args.sparql
    else:
        query_path = Path(args.file)
        if not query_path.exists():
            result = {
                "success": False,
                "sparql": None,
                "results": None,
                "execution_time_ms": 0,
                "endpoint": args.endpoint,
                "error": {
                    "type": "file_not_found",
                    "message": f"Query file not found: {args.file}",
                    "http_status": None,
                    "details": None,
                },
            }
            print(json.dumps(result, indent=2))
            sys.exit(1)
        sparql = query_path.read_text().strip()

    # Execute the query
    result = execute_sparql(
        sparql=sparql,
        endpoint=args.endpoint,
        timeout=args.timeout,
        max_rows=args.max_rows,
        paginate=args.paginate,
    )

    # Extract IDs to file if requested (for large result sets)
    if args.extract_ids and result["success"] and result["results"]:
        results = result["results"]
        ids = []
        if results.get("type") == "bindings" and results.get("rows"):
            for row in results["rows"]:
                for var in results["variables"]:
                    value = row.get(var)
                    if value is None:
                        continue
                    # Extract QID/PID from Wikidata URI
                    if "wikidata.org/entity/" in value:
                        entity_id = value.split("/")[-1]
                        ids.append(entity_id)
                    elif value.startswith("http://") or value.startswith("https://"):
                        # Other URIs — take last path segment
                        ids.append(value.split("/")[-1])
                    else:
                        # Literal value — include as-is
                        ids.append(value)
        # Deduplicate while preserving order
        seen = set()
        unique_ids = []
        for id_val in ids:
            if id_val not in seen:
                seen.add(id_val)
                unique_ids.append(id_val)
        # Write to file
        Path(args.extract_ids).write_text(
            json.dumps(unique_ids, indent=2, ensure_ascii=False) + "\n"
        )
        # Print summary to stdout (small enough for agent context)
        summary = {
            "success": True,
            "extracted_ids_file": args.extract_ids,
            "total_ids": len(unique_ids),
            "sample": unique_ids[:10],
            "truncated_in_sample": len(unique_ids) > 10,
        }
        print(json.dumps(summary, indent=2, ensure_ascii=False))
        sys.exit(0)

    # Format output
    if args.format in ("csv", "tsv") and result["success"] and result["results"]:
        # For csv/tsv, also include a human-readable table in the output
        results = result["results"]
        if results.get("type") == "bindings" and results.get("rows"):
            separator = "," if args.format == "csv" else "\t"
            lines = [separator.join(results["variables"])]
            for row in results["rows"]:
                values = [str(row.get(v, "")) for v in results["variables"]]
                lines.append(separator.join(values))
            result["formatted_output"] = "\n".join(lines)

    output = json.dumps(result, indent=2, ensure_ascii=False, default=str)

    if args.output_file:
        Path(args.output_file).write_text(output)
    else:
        print(output)

    sys.exit(0 if result["success"] else 1)


if __name__ == "__main__":
    main()
