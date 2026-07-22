# Copyright IBM Corp. 2026 - 2026
# SPDX-License-Identifier: Apache-2.0
#

#!/usr/bin/env python3

"""Standalone Wikidata search script.

Searches the Wikidata API to resolve entity names and relation phrases
to Wikidata item IDs (QIDs) and property IDs (PIDs).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from typing import Any

try:
    import requests
except ImportError as exc:
    raise SystemExit(
        "Missing dependency 'requests'. Install it with: uv sync"
    ) from exc


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

WIKIDATA_API_URL = "https://www.wikidata.org/w/api.php"
WIKIDATA_ENTITY_URL = "https://www.wikidata.org/wiki/"
DEFAULT_LIMIT = 5
DEFAULT_LANGUAGE = "en"
DEFAULT_USER_AGENT = os.environ.get(
    "WIKIDATA_USER_AGENT",
    "AgenticText2SPARQL/1.0 (https://github.com/ibm/agentic-text2sparql)",
)

# Rate limiting
MIN_REQUEST_INTERVAL = 0.2  # seconds between requests
_last_request_time = 0.0


# ---------------------------------------------------------------------------
# Utility functions
# ---------------------------------------------------------------------------


def _rate_limit() -> None:
    """Enforce rate limiting between API requests."""
    global _last_request_time
    elapsed = time.time() - _last_request_time
    if elapsed < MIN_REQUEST_INTERVAL:
        time.sleep(MIN_REQUEST_INTERVAL - elapsed)
    _last_request_time = time.time()


def _make_request(params: dict[str, Any]) -> dict[str, Any]:
    """Make a rate-limited request to the Wikidata API."""
    _rate_limit()
    headers = {"User-Agent": DEFAULT_USER_AGENT}
    try:
        response = requests.get(
            WIKIDATA_API_URL,
            params=params,
            headers=headers,
            timeout=30,
        )
        response.raise_for_status()
        return response.json()
    except requests.exceptions.Timeout:
        return {"error": "Request timed out after 30 seconds"}
    except requests.exceptions.HTTPError as exc:
        return {"error": f"HTTP error: {exc.response.status_code} {exc.response.reason}"}
    except requests.exceptions.RequestException as exc:
        return {"error": f"Request failed: {exc}"}


# ---------------------------------------------------------------------------
# Search functions
# ---------------------------------------------------------------------------


def search_entities(
    query: str,
    entity_type: str = "item",
    limit: int = DEFAULT_LIMIT,
    language: str = DEFAULT_LANGUAGE,
) -> dict[str, Any]:
    """Search Wikidata for items or properties.

    Args:
        query: Search term.
        entity_type: 'item' for Q-entities, 'property' for P-properties.
        limit: Maximum number of results.
        language: Language for labels and descriptions.

    Returns:
        dict with success status, results list, and any error.
    """
    params = {
        "action": "wbsearchentities",
        "search": query,
        "type": entity_type,
        "limit": limit,
        "language": language,
        "uselang": language,
        "format": "json",
    }

    data = _make_request(params)

    if "error" in data and isinstance(data["error"], str):
        return {
            "success": False,
            "query": query,
            "search_type": entity_type,
            "result_count": 0,
            "results": [],
            "error": data["error"],
        }

    if "error" in data and isinstance(data["error"], dict):
        return {
            "success": False,
            "query": query,
            "search_type": entity_type,
            "result_count": 0,
            "results": [],
            "error": data["error"].get("info", "Unknown API error"),
        }

    search_results = data.get("search", [])
    results = []

    for rank, item in enumerate(search_results, 1):
        result = {
            "id": item.get("id", ""),
            "label": item.get("label", ""),
            "description": item.get("description", ""),
            "aliases": item.get("aliases", []),
            "url": item.get("concepturi", ""),
            "match_type": item.get("match", {}).get("type", ""),
            "rank": rank,
        }
        # Add datatype for properties
        if entity_type == "property" and "datatype" in item:
            result["datatype"] = item["datatype"]
        results.append(result)

    return {
        "success": True,
        "query": query,
        "search_type": entity_type,
        "result_count": len(results),
        "results": results,
        "error": None,
    }


def lookup_entity(
    entity_id: str,
    language: str = DEFAULT_LANGUAGE,
) -> dict[str, Any]:
    """Look up details for a known entity ID.

    Args:
        entity_id: Wikidata ID (e.g., Q937 or P19).
        language: Language for labels and descriptions.

    Returns:
        dict with entity details.
    """
    params = {
        "action": "wbgetentities",
        "ids": entity_id,
        "languages": language,
        "props": "labels|descriptions|aliases|claims",
        "format": "json",
    }

    data = _make_request(params)

    if "error" in data and isinstance(data["error"], str):
        return {
            "success": False,
            "query": entity_id,
            "search_type": "lookup",
            "result_count": 0,
            "results": [],
            "error": data["error"],
        }

    if "error" in data and isinstance(data["error"], dict):
        return {
            "success": False,
            "query": entity_id,
            "search_type": "lookup",
            "result_count": 0,
            "results": [],
            "error": data["error"].get("info", "Unknown API error"),
        }

    entities = data.get("entities", {})
    entity = entities.get(entity_id, {})

    if "missing" in entity:
        return {
            "success": False,
            "query": entity_id,
            "search_type": "lookup",
            "result_count": 0,
            "results": [],
            "error": f"Entity '{entity_id}' not found",
        }

    # Extract label
    labels = entity.get("labels", {})
    label = labels.get(language, {}).get("value", entity_id)

    # Extract description
    descriptions = entity.get("descriptions", {})
    description = descriptions.get(language, {}).get("value", "")

    # Extract aliases
    alias_data = entity.get("aliases", {}).get(language, [])
    aliases = [a.get("value", "") for a in alias_data]

    # Extract instance_of (P31) claims
    claims = entity.get("claims", {})
    instance_of_claims = claims.get("P31", [])
    instance_of = []
    instance_of_labels_list = []

    for claim in instance_of_claims:
        mainsnak = claim.get("mainsnak", {})
        datavalue = mainsnak.get("datavalue", {})
        if datavalue.get("type") == "wikibase-entityid":
            qid = datavalue.get("value", {}).get("id", "")
            if qid:
                instance_of.append(qid)

    # Look up instance_of labels if we have any
    if instance_of:
        label_params = {
            "action": "wbgetentities",
            "ids": "|".join(instance_of[:5]),  # Limit to first 5
            "languages": language,
            "props": "labels",
            "format": "json",
        }
        label_data = _make_request(label_params)
        label_entities = label_data.get("entities", {})
        for qid in instance_of:
            lbl = label_entities.get(qid, {}).get("labels", {}).get(language, {}).get("value", qid)
            instance_of_labels_list.append(lbl)

    # Determine URL
    prefix = "Property:" if entity_id.startswith("P") else ""
    url = f"{WIKIDATA_ENTITY_URL}{prefix}{entity_id}"

    result = {
        "id": entity_id,
        "label": label,
        "description": description,
        "aliases": aliases,
        "instance_of": instance_of,
        "instance_of_labels": instance_of_labels_list,
        "url": url,
    }

    return {
        "success": True,
        "query": entity_id,
        "search_type": "lookup",
        "result_count": 1,
        "results": [result],
        "error": None,
    }


def batch_search(
    queries: list[str],
    entity_type: str = "item",
    limit: int = DEFAULT_LIMIT,
    language: str = DEFAULT_LANGUAGE,
) -> dict[str, Any]:
    """Search for multiple terms, returning results for each.

    Args:
        queries: List of search terms.
        entity_type: 'item' or 'property'.
        limit: Max results per query.
        language: Language for labels.

    Returns:
        dict with combined results.
    """
    all_results = []
    errors = []

    for query in queries:
        result = search_entities(query, entity_type, limit, language)
        if result["success"]:
            all_results.append({
                "query": query,
                "results": result["results"],
                "result_count": result["result_count"],
            })
        else:
            errors.append({
                "query": query,
                "error": result["error"],
            })

    return {
        "success": len(errors) == 0,
        "queries": queries,
        "search_type": entity_type,
        "batch_results": all_results,
        "total_results": sum(r["result_count"] for r in all_results),
        "errors": errors if errors else None,
        "error": errors[0]["error"] if errors else None,
    }


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Search Wikidata for entities and properties."
    )

    parser.add_argument(
        "--query", "-q",
        nargs="+",
        required=True,
        help="One or more search terms.",
    )
    parser.add_argument(
        "--type", "-t",
        choices=["item", "property", "lookup"],
        default="item",
        help="Search type: 'item' (Q-entities), 'property' (P-properties), or 'lookup' (by ID). Default: item.",
    )
    parser.add_argument(
        "--limit", "-l",
        type=int,
        default=DEFAULT_LIMIT,
        help=f"Maximum results per query (default: {DEFAULT_LIMIT}).",
    )
    parser.add_argument(
        "--language", "--lang",
        default=DEFAULT_LANGUAGE,
        help=f"Language for labels and descriptions (default: {DEFAULT_LANGUAGE}).",
    )
    parser.add_argument(
        "--output-file",
        help="Write result JSON to a file instead of stdout.",
    )

    return parser.parse_args()


# ---------------------------------------------------------------------------
# Main execution
# ---------------------------------------------------------------------------


def main() -> None:
    args = parse_args()

    queries = args.query
    search_type = args.type

    if search_type == "lookup":
        # Lookup mode: treat each query as an entity ID
        if len(queries) == 1:
            result = lookup_entity(queries[0], args.language)
        else:
            # Batch lookup
            all_results = []
            for qid in queries:
                r = lookup_entity(qid, args.language)
                if r["success"]:
                    all_results.extend(r["results"])
            result = {
                "success": True,
                "query": queries,
                "search_type": "lookup",
                "result_count": len(all_results),
                "results": all_results,
                "error": None,
            }
    elif len(queries) == 1:
        # Single search
        result = search_entities(queries[0], search_type, args.limit, args.language)
    else:
        # Batch search
        result = batch_search(queries, search_type, args.limit, args.language)

    output = json.dumps(result, indent=2, ensure_ascii=False)

    if args.output_file:
        from pathlib import Path
        Path(args.output_file).write_text(output)
    else:
        print(output)

    sys.exit(0 if result["success"] else 1)


if __name__ == "__main__":
    main()
