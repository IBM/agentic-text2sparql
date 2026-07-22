# Copyright IBM Corp. 2026 - 2026
# SPDX-License-Identifier: Apache-2.0
#

#!/usr/bin/env python3

"""Standalone Wikidata graph exploration script.

Explores the Wikidata knowledge graph around seed entities using small
diagnostic SPARQL queries to verify property directions, discover paths,
and inspect qualifiers.
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
DEFAULT_LIMIT = 20
MAX_LIMIT = 50
DEFAULT_USER_AGENT = os.environ.get(
    "WIKIDATA_USER_AGENT",
    "AgenticText2SPARQL/1.0 (https://github.com/ibm/agentic-text2sparql)",
)

# Basic Auth credentials (optional)
SPARQL_USERNAME = os.environ.get("WIKIDATA_SPARQL_USERNAME", "")
SPARQL_PASSWORD = os.environ.get("WIKIDATA_SPARQL_PASSWORD", "")
SPARQL_AUTH = (SPARQL_USERNAME, SPARQL_PASSWORD) if SPARQL_USERNAME and SPARQL_PASSWORD else None

# Rate limiting
MIN_REQUEST_INTERVAL = 1.0  # seconds between requests
_last_request_time = 0.0


# ---------------------------------------------------------------------------
# Utility functions
# ---------------------------------------------------------------------------


def _rate_limit() -> None:
    """Enforce rate limiting between SPARQL requests."""
    global _last_request_time
    elapsed = time.time() - _last_request_time
    if elapsed < MIN_REQUEST_INTERVAL:
        time.sleep(MIN_REQUEST_INTERVAL - elapsed)
    _last_request_time = time.time()


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


def _add_prefixes(sparql: str) -> str:
    """Add standard Wikidata prefixes if not already present."""
    if "PREFIX" in sparql.upper()[:200]:
        return sparql
    return WIKIDATA_PREFIXES + sparql


def _execute_sparql(sparql: str, endpoint: str = DEFAULT_ENDPOINT) -> dict[str, Any]:
    """Execute a SPARQL query and return parsed results."""
    _rate_limit()

    # Add standard prefixes if not present
    sparql = _add_prefixes(sparql)

    headers = {
        "User-Agent": DEFAULT_USER_AGENT,
        "Accept": "application/sparql-results+json",
    }
    params = {"query": sparql, "format": "json"}

    try:
        response = requests.get(
            endpoint, params=params, headers=headers, timeout=30, auth=SPARQL_AUTH
        )
        if response.status_code != 200:
            return {"error": f"HTTP {response.status_code}: {response.text[:300]}"}
        return response.json()
    except requests.exceptions.Timeout:
        return {"error": "Query timed out (30s limit)"}
    except requests.exceptions.RequestException as exc:
        return {"error": f"Request failed: {exc}"}
    except json.JSONDecodeError:
        return {"error": "Failed to parse JSON response"}


def _parse_bindings(data: dict[str, Any]) -> list[dict[str, str]]:
    """Parse SPARQL JSON results into a list of dicts."""
    if "error" in data:
        return []
    bindings = data.get("results", {}).get("bindings", [])
    variables = data.get("head", {}).get("vars", [])
    rows = []
    for binding in bindings:
        row = {}
        for var in variables:
            if var in binding:
                row[var] = binding[var].get("value", "")
            else:
                row[var] = None
        rows.append(row)
    return rows


def _is_wdqs_endpoint(endpoint: str) -> bool:
    """Check if the endpoint is the official Wikidata Query Service."""
    return "query.wikidata.org" in endpoint


def _label_clause(variables: list[str], endpoint: str) -> str:
    """Return a SPARQL clause to fetch labels for the given variables.

    On the official Wikidata Query Service, uses the efficient built-in
    SERVICE wikibase:label.  On other endpoints, uses OPTIONAL rdfs:label
    with a language filter.
    """
    if _is_wdqs_endpoint(endpoint):
        return 'SERVICE wikibase:label { bd:serviceParam wikibase:language "en". }'

    # Fallback: fetch labels via OPTIONAL rdfs:label for each variable
    parts = []
    for var in variables:
        var_name = var.lstrip("?")
        parts.append(
            f'OPTIONAL {{ ?{var_name} rdfs:label ?{var_name}Label . FILTER(LANG(?{var_name}Label) = "en") }}'
        )
    return "\n      ".join(parts)


def _get_entity_label(entity_id: str, endpoint: str = DEFAULT_ENDPOINT) -> str:
    """Get the English label for an entity."""
    sparql = f"""
    SELECT ?label WHERE {{
      wd:{entity_id} rdfs:label ?label .
      FILTER(LANG(?label) = "en")
    }} LIMIT 1
    """
    data = _execute_sparql(sparql, endpoint)
    rows = _parse_bindings(data)
    if rows and rows[0].get("label"):
        return rows[0]["label"]
    return entity_id


# ---------------------------------------------------------------------------
# Exploration modes
# ---------------------------------------------------------------------------


def explore_outgoing(
    entity: str, limit: int, endpoint: str
) -> dict[str, Any]:
    """List outgoing properties and sample values from an entity."""
    labels = _label_clause(["?prop", "?value"], endpoint)
    sparql = f"""
    SELECT ?prop ?propLabel ?value ?valueLabel WHERE {{
      wd:{entity} ?p ?value .
      ?prop wikibase:directClaim ?p .
      {labels}
    }}
    LIMIT {limit}
    """
    data = _execute_sparql(sparql, endpoint)

    if "error" in data:
        return {"success": False, "error": data["error"]}

    rows = _parse_bindings(data)
    results = []
    for row in rows:
        prop_uri = row.get("prop", "")
        prop_id = prop_uri.split("/")[-1] if prop_uri else ""
        value_uri = row.get("value", "")
        value_id = value_uri.split("/")[-1] if "entity/" in str(value_uri) else None

        results.append({
            "property": prop_id,
            "property_label": row.get("propLabel", prop_id),
            "value": value_id or value_uri,
            "value_label": row.get("valueLabel", value_id or value_uri),
            "value_type": "wikibase-item" if value_id else "literal",
        })

    entity_label = _get_entity_label(entity, endpoint)

    return {
        "success": True,
        "entity": entity,
        "entity_label": entity_label,
        "mode": "outgoing",
        "result_count": len(results),
        "results": results,
        "error": None,
    }


def explore_incoming(
    entity: str, property_id: str | None, limit: int, endpoint: str
) -> dict[str, Any]:
    """List entities pointing to this entity (incoming relations)."""
    if property_id:
        labels = _label_clause(["?subject"], endpoint)
        sparql = f"""
        SELECT ?subject ?subjectLabel WHERE {{
          ?subject wdt:{property_id} wd:{entity} .
          {labels}
        }}
        LIMIT {limit}
        """
    else:
        labels = _label_clause(["?subject", "?prop"], endpoint)
        sparql = f"""
        SELECT ?subject ?subjectLabel ?prop ?propLabel WHERE {{
          ?subject ?p wd:{entity} .
          ?prop wikibase:directClaim ?p .
          {labels}
        }}
        LIMIT {limit}
        """

    data = _execute_sparql(sparql, endpoint)

    if "error" in data:
        return {"success": False, "error": data["error"]}

    rows = _parse_bindings(data)
    results = []
    for row in rows:
        subject_uri = row.get("subject", "")
        subject_id = subject_uri.split("/")[-1] if "entity/" in str(subject_uri) else subject_uri

        result = {
            "subject": subject_id,
            "subject_label": row.get("subjectLabel", subject_id),
        }
        if not property_id:
            prop_uri = row.get("prop", "")
            result["property"] = prop_uri.split("/")[-1] if prop_uri else ""
            result["property_label"] = row.get("propLabel", "")
        results.append(result)

    entity_label = _get_entity_label(entity, endpoint)

    return {
        "success": True,
        "entity": entity,
        "entity_label": entity_label,
        "mode": "incoming",
        "property_filter": property_id,
        "result_count": len(results),
        "results": results,
        "error": None,
    }


def check_property(
    entity: str, property_id: str, endpoint: str
) -> dict[str, Any]:
    """Check if a property exists on an entity and get its values."""
    # Check outgoing
    labels_out = _label_clause(["?value"], endpoint)
    sparql_out = f"""
    SELECT ?value ?valueLabel WHERE {{
      wd:{entity} wdt:{property_id} ?value .
      {labels_out}
    }}
    LIMIT 10
    """
    data_out = _execute_sparql(sparql_out, endpoint)
    rows_out = _parse_bindings(data_out) if "error" not in data_out else []

    # Check incoming
    labels_in = _label_clause(["?subject"], endpoint)
    sparql_in = f"""
    SELECT ?subject ?subjectLabel WHERE {{
      ?subject wdt:{property_id} wd:{entity} .
      {labels_in}
    }}
    LIMIT 10
    """
    data_in = _execute_sparql(sparql_in, endpoint)
    rows_in = _parse_bindings(data_in) if "error" not in data_in else []

    entity_label = _get_entity_label(entity, endpoint)

    # Get property label
    prop_label = _get_entity_label(property_id, endpoint)

    # Determine direction and existence
    exists_outgoing = len(rows_out) > 0
    exists_incoming = len(rows_in) > 0

    if exists_outgoing:
        direction = "outgoing"
        values = []
        for row in rows_out:
            val_uri = row.get("value", "")
            val_id = val_uri.split("/")[-1] if "entity/" in str(val_uri) else None
            values.append({
                "value": val_id or val_uri,
                "value_label": row.get("valueLabel", val_id or val_uri),
            })
    elif exists_incoming:
        direction = "incoming"
        values = []
        for row in rows_in:
            subj_uri = row.get("subject", "")
            subj_id = subj_uri.split("/")[-1] if "entity/" in str(subj_uri) else subj_uri
            values.append({
                "value": subj_id,
                "value_label": row.get("subjectLabel", subj_id),
            })
    else:
        direction = None
        values = []

    return {
        "success": True,
        "entity": entity,
        "entity_label": entity_label,
        "mode": "check-property",
        "property": property_id,
        "property_label": prop_label,
        "exists": exists_outgoing or exists_incoming,
        "exists_outgoing": exists_outgoing,
        "exists_incoming": exists_incoming,
        "direction": direction,
        "values": values,
        "error": None,
    }


def explore_types(entity: str, endpoint: str) -> dict[str, Any]:
    """Inspect instance_of and subclass_of chains for an entity."""
    labels = _label_clause(["?type", "?superclass"], endpoint)
    sparql = f"""
    SELECT ?type ?typeLabel ?superclass ?superclassLabel WHERE {{
      wd:{entity} wdt:P31 ?type .
      OPTIONAL {{ ?type wdt:P279 ?superclass . }}
      {labels}
    }}
    LIMIT 30
    """
    data = _execute_sparql(sparql, endpoint)

    if "error" in data:
        return {"success": False, "error": data["error"]}

    rows = _parse_bindings(data)
    entity_label = _get_entity_label(entity, endpoint)

    types = []
    seen_types = set()
    for row in rows:
        type_uri = row.get("type", "")
        type_id = type_uri.split("/")[-1] if "entity/" in str(type_uri) else type_uri

        if type_id not in seen_types:
            seen_types.add(type_id)
            type_entry = {
                "type_id": type_id,
                "type_label": row.get("typeLabel", type_id),
                "superclasses": [],
            }
            types.append(type_entry)

        # Add superclass if present
        sc_uri = row.get("superclass")
        if sc_uri:
            sc_id = sc_uri.split("/")[-1] if "entity/" in str(sc_uri) else sc_uri
            # Find the type entry and add superclass
            for t in types:
                if t["type_id"] == type_id:
                    t["superclasses"].append({
                        "id": sc_id,
                        "label": row.get("superclassLabel", sc_id),
                    })
                    break

    return {
        "success": True,
        "entity": entity,
        "entity_label": entity_label,
        "mode": "types",
        "result_count": len(types),
        "results": types,
        "error": None,
    }


def explore_statement(
    entity: str, property_id: str, limit: int, endpoint: str
) -> dict[str, Any]:
    """Inspect statement nodes including qualifiers."""
    if _is_wdqs_endpoint(endpoint):
        labels = _label_clause(["?value", "?qualProp", "?qualValue"], endpoint)
        sparql = f"""
        SELECT ?value ?valueLabel ?qualProp ?qualPropLabel ?qualValue ?qualValueLabel WHERE {{
          wd:{entity} p:{property_id} ?stmt .
          ?stmt ps:{property_id} ?value .
          OPTIONAL {{
            ?stmt ?qualP ?qualValue .
            ?qualProp wikibase:qualifier ?qualP .
          }}
          {labels}
        }}
        LIMIT {limit}
        """
        data = _execute_sparql(sparql, endpoint)

        if "error" in data:
            return {"success": False, "error": data["error"]}

        rows = _parse_bindings(data)
    else:
        # For non-WDQS endpoints, the wikibase:qualifier meta-lookup is too
        # expensive. Instead, get values first, then probe common qualifiers.
        sparql_values = f"""
        SELECT ?value WHERE {{
          wd:{entity} p:{property_id} ?stmt .
          ?stmt ps:{property_id} ?value .
        }}
        LIMIT {limit}
        """
        data_values = _execute_sparql(sparql_values, endpoint)

        if "error" in data_values:
            return {"success": False, "error": data_values["error"]}

        value_rows = _parse_bindings(data_values)
        if not value_rows:
            entity_label = _get_entity_label(entity, endpoint)
            prop_label = _get_entity_label(property_id, endpoint)
            return {
                "success": True,
                "entity": entity,
                "entity_label": entity_label,
                "mode": "statement",
                "property": property_id,
                "property_label": prop_label,
                "result_count": 0,
                "results": [],
                "error": None,
            }

        # Probe common qualifier properties: point in time (P585), start time (P580),
        # end time (P582), of (P642), applies to part (P518)
        common_qualifiers = ["P585", "P580", "P582", "P642", "P518"]
        qual_select = " ".join([f"?qual_{p}" for p in common_qualifiers])
        qual_optionals = "\n          ".join(
            [f"OPTIONAL {{ ?stmt pq:{p} ?qual_{p} . }}" for p in common_qualifiers]
        )
        sparql_with_quals = f"""
        SELECT ?value {qual_select} WHERE {{
          wd:{entity} p:{property_id} ?stmt .
          ?stmt ps:{property_id} ?value .
          {qual_optionals}
        }}
        LIMIT {limit}
        """
        data = _execute_sparql(sparql_with_quals, endpoint)

        if "error" in data:
            # If qualifier probing also fails, return just the values
            rows = [{"value": r.get("value", "")} for r in value_rows]
        else:
            rows = _parse_bindings(data)
            # Transform qualifier columns into qualProp/qualValue format
            transformed_rows = []
            for row in rows:
                base_row = {"value": row.get("value", "")}
                has_qual = False
                for p in common_qualifiers:
                    qual_val = row.get(f"qual_{p}")
                    if qual_val:
                        new_row = dict(base_row)
                        new_row["qualProp"] = f"http://www.wikidata.org/entity/{p}"
                        new_row["qualValue"] = qual_val
                        transformed_rows.append(new_row)
                        has_qual = True
                if not has_qual:
                    transformed_rows.append(base_row)
            rows = transformed_rows

    if "error" in data:
        return {"success": False, "error": data["error"]}

    rows = _parse_bindings(data)
    entity_label = _get_entity_label(entity, endpoint)
    prop_label = _get_entity_label(property_id, endpoint)

    # Group by statement value
    statements = {}
    for row in rows:
        val_uri = row.get("value", "")
        val_id = val_uri.split("/")[-1] if "entity/" in str(val_uri) else val_uri
        val_label = row.get("valueLabel", val_id)

        key = val_id
        if key not in statements:
            statements[key] = {
                "main_value": val_id,
                "main_value_label": val_label,
                "qualifiers": [],
            }

        qual_prop_uri = row.get("qualProp")
        if qual_prop_uri:
            qual_prop_id = qual_prop_uri.split("/")[-1] if qual_prop_uri else ""
            qual_val_uri = row.get("qualValue", "")
            qual_val_id = qual_val_uri.split("/")[-1] if "entity/" in str(qual_val_uri) else qual_val_uri

            statements[key]["qualifiers"].append({
                "property": qual_prop_id,
                "property_label": row.get("qualPropLabel", qual_prop_id),
                "value": qual_val_id,
                "value_label": row.get("qualValueLabel", qual_val_id),
            })

    results = list(statements.values())

    # On non-WDQS endpoints, resolve labels for main values that look like entity IDs
    if not _is_wdqs_endpoint(endpoint):
        for stmt in results:
            val = stmt["main_value"]
            if val and val.startswith("Q") and stmt["main_value_label"] == val:
                stmt["main_value_label"] = _get_entity_label(val, endpoint)

    return {
        "success": True,
        "entity": entity,
        "entity_label": entity_label,
        "mode": "statement",
        "property": property_id,
        "property_label": prop_label,
        "result_count": len(results),
        "results": results,
        "error": None,
    }


def explore_path(
    entity: str, target: str, endpoint: str
) -> dict[str, Any]:
    """Find how two entities are connected (1 or 2 hops)."""
    # Try direct connection (1 hop)
    labels_direct = _label_clause(["?prop"], endpoint)
    sparql_direct = f"""
    SELECT ?prop ?propLabel ?direction WHERE {{
      {{
        wd:{entity} ?p wd:{target} .
        ?prop wikibase:directClaim ?p .
        BIND("outgoing" AS ?direction)
      }} UNION {{
        wd:{target} ?p wd:{entity} .
        ?prop wikibase:directClaim ?p .
        BIND("incoming" AS ?direction)
      }}
      {labels_direct}
    }}
    LIMIT 20
    """
    data_direct = _execute_sparql(sparql_direct, endpoint)
    rows_direct = _parse_bindings(data_direct) if "error" not in data_direct else []

    # Try 2-hop connection
    labels_2hop = _label_clause(["?mid", "?prop1", "?prop2"], endpoint)
    sparql_2hop = f"""
    SELECT ?mid ?midLabel ?prop1 ?prop1Label ?prop2 ?prop2Label WHERE {{
      wd:{entity} ?p1 ?mid .
      ?mid ?p2 wd:{target} .
      ?prop1 wikibase:directClaim ?p1 .
      ?prop2 wikibase:directClaim ?p2 .
      {labels_2hop}
    }}
    LIMIT 10
    """
    data_2hop = _execute_sparql(sparql_2hop, endpoint)
    rows_2hop = _parse_bindings(data_2hop) if "error" not in data_2hop else []

    entity_label = _get_entity_label(entity, endpoint)
    target_label = _get_entity_label(target, endpoint)

    direct_paths = []
    for row in rows_direct:
        prop_uri = row.get("prop", "")
        prop_id = prop_uri.split("/")[-1] if prop_uri else ""
        direct_paths.append({
            "property": prop_id,
            "property_label": row.get("propLabel", prop_id),
            "direction": row.get("direction", ""),
        })

    two_hop_paths = []
    for row in rows_2hop:
        mid_uri = row.get("mid", "")
        mid_id = mid_uri.split("/")[-1] if "entity/" in str(mid_uri) else mid_uri
        prop1_uri = row.get("prop1", "")
        prop1_id = prop1_uri.split("/")[-1] if prop1_uri else ""
        prop2_uri = row.get("prop2", "")
        prop2_id = prop2_uri.split("/")[-1] if prop2_uri else ""

        two_hop_paths.append({
            "intermediate": mid_id,
            "intermediate_label": row.get("midLabel", mid_id),
            "property1": prop1_id,
            "property1_label": row.get("prop1Label", prop1_id),
            "property2": prop2_id,
            "property2_label": row.get("prop2Label", prop2_id),
        })

    return {
        "success": True,
        "entity": entity,
        "entity_label": entity_label,
        "target": target,
        "target_label": target_label,
        "mode": "path",
        "direct_paths": direct_paths,
        "two_hop_paths": two_hop_paths[:5],  # Limit 2-hop results
        "error": None,
    }


def run_custom_query(sparql: str, endpoint: str) -> dict[str, Any]:
    """Run a custom SPARQL query for exploration."""
    data = _execute_sparql(sparql, endpoint)

    if "error" in data:
        return {
            "success": False,
            "mode": "custom",
            "sparql": sparql,
            "results": [],
            "error": data["error"],
        }

    rows = _parse_bindings(data)

    return {
        "success": True,
        "mode": "custom",
        "sparql": sparql,
        "result_count": len(rows),
        "results": rows,
        "error": None,
    }


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Explore the Wikidata knowledge graph around seed entities."
    )

    parser.add_argument(
        "--mode", "-m",
        required=True,
        choices=["outgoing", "incoming", "check-property", "types", "statement", "path", "custom"],
        help="Exploration mode.",
    )
    parser.add_argument(
        "--entity", "-e",
        help="Wikidata entity ID (e.g., Q937). Required for all modes except 'custom'.",
    )
    parser.add_argument(
        "--property", "-p",
        help="Wikidata property ID (e.g., P19). Required for 'check-property' and 'statement' modes.",
    )
    parser.add_argument(
        "--target",
        help="Target entity ID for 'path' mode.",
    )
    parser.add_argument(
        "--sparql",
        help="Custom SPARQL query for 'custom' mode.",
    )
    parser.add_argument(
        "--limit", "-l",
        type=int,
        default=DEFAULT_LIMIT,
        help=f"Maximum results (default: {DEFAULT_LIMIT}, max: {MAX_LIMIT}).",
    )
    parser.add_argument(
        "--endpoint",
        default=DEFAULT_ENDPOINT,
        help=f"SPARQL endpoint URL (default: {DEFAULT_ENDPOINT}).",
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

    # Enforce max limit
    limit = min(args.limit, MAX_LIMIT)

    # Validate required arguments per mode
    if args.mode != "custom" and not args.entity:
        print(json.dumps({
            "success": False,
            "error": f"--entity is required for mode '{args.mode}'",
        }, indent=2))
        sys.exit(1)

    if args.mode in ("check-property", "statement") and not args.property:
        print(json.dumps({
            "success": False,
            "error": f"--property is required for mode '{args.mode}'",
        }, indent=2))
        sys.exit(1)

    if args.mode == "path" and not args.target:
        print(json.dumps({
            "success": False,
            "error": "--target is required for mode 'path'",
        }, indent=2))
        sys.exit(1)

    if args.mode == "custom" and not args.sparql:
        print(json.dumps({
            "success": False,
            "error": "--sparql is required for mode 'custom'",
        }, indent=2))
        sys.exit(1)

    # Dispatch to the appropriate exploration function
    if args.mode == "outgoing":
        result = explore_outgoing(args.entity, limit, args.endpoint)
    elif args.mode == "incoming":
        result = explore_incoming(args.entity, args.property, limit, args.endpoint)
    elif args.mode == "check-property":
        result = check_property(args.entity, args.property, args.endpoint)
    elif args.mode == "types":
        result = explore_types(args.entity, args.endpoint)
    elif args.mode == "statement":
        result = explore_statement(args.entity, args.property, limit, args.endpoint)
    elif args.mode == "path":
        result = explore_path(args.entity, args.target, args.endpoint)
    elif args.mode == "custom":
        result = run_custom_query(args.sparql, args.endpoint)
    else:
        result = {"success": False, "error": f"Unknown mode: {args.mode}"}

    output = json.dumps(result, indent=2, ensure_ascii=False, default=str)

    if args.output_file:
        from pathlib import Path
        Path(args.output_file).write_text(output)
    else:
        print(output)

    sys.exit(0 if result.get("success", False) else 1)


if __name__ == "__main__":
    main()
