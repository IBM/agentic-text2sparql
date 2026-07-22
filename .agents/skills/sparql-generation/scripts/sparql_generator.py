# Copyright IBM Corp. 2026 - 2026
# SPDX-License-Identifier: Apache-2.0
#

#!/usr/bin/env python3

"""Standalone SPARQL generation and validation script.

Generates SPARQL queries from resolved Wikidata entities, properties,
and verified graph paths. Also validates SPARQL syntax.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

# Load .env file from project root
load_dotenv(Path(__file__).resolve().parents[4] / ".env")


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

WIKIDATA_PREFIXES = """PREFIX wd: <http://www.wikidata.org/entity/>
PREFIX wdt: <http://www.wikidata.org/prop/direct/>
PREFIX wikibase: <http://wikiba.se/ontology#>
PREFIX p: <http://www.wikidata.org/prop/>
PREFIX ps: <http://www.wikidata.org/prop/statement/>
PREFIX pq: <http://www.wikidata.org/prop/qualifier/>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX bd: <http://www.bigdata.com/rdf#>
PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
PREFIX schema: <http://schema.org/>
"""

DEFAULT_ENDPOINT = os.environ.get(
    "WIKIDATA_SPARQL_ENDPOINT",
    "https://backend.wikikgqa.skynet.coypu.org",
)

LABEL_SERVICE_WDQS = 'SERVICE wikibase:label { bd:serviceParam wikibase:language "[AUTO_LANGUAGE],en". }'


def _is_wdqs_endpoint(endpoint: str) -> bool:
    """Check if the endpoint is the official Wikidata Query Service."""
    return "query.wikidata.org" in endpoint


def _get_label_service(variables: list[str] | None = None) -> str:
    """Return the appropriate label clause for the configured endpoint.

    On the official Wikidata Query Service, uses the built-in SERVICE wikibase:label.
    On other endpoints, uses OPTIONAL rdfs:label with a language filter.
    """
    if _is_wdqs_endpoint(DEFAULT_ENDPOINT):
        return LABEL_SERVICE_WDQS

    if not variables:
        return ""

    # Fallback: fetch labels via OPTIONAL rdfs:label for each variable
    parts = []
    for var in variables:
        var_name = var.lstrip("?")
        parts.append(
            f'OPTIONAL {{ ?{var_name} rdfs:label ?{var_name}Label . FILTER(LANG(?{var_name}Label) = "en") }}'
        )
    return "\n  ".join(parts)


# Keep LABEL_SERVICE as a module-level constant for backward compatibility
LABEL_SERVICE = _get_label_service(["?item"])

# Query patterns
PATTERNS = {
    "direct-lookup": {
        "description": "Direct property lookup: What is the X of Y?",
        "template": """SELECT ?value ?valueLabel WHERE {{
  wd:{entity} wdt:{property} ?value .
  {label_service}
}}""",
        "required_params": ["entity", "property"],
        "label_vars": ["?value"],
    },
    "reverse-lookup": {
        "description": "Reverse lookup: Which entities have Y as their X?",
        "template": """SELECT ?entity ?entityLabel WHERE {{
  ?entity wdt:{property} wd:{target} .
  {label_service}
}}""",
        "required_params": ["property", "target"],
        "label_vars": ["?entity"],
    },
    "type-filter": {
        "description": "Type filter: Which entities of type T satisfy condition?",
        "template": """SELECT ?entity ?entityLabel WHERE {{
  ?entity wdt:P31 wd:{type} ;
          wdt:{filter_property} {filter_value} .
  {label_service}
}}""",
        "required_params": ["type", "filter_property", "filter_value"],
        "label_vars": ["?entity"],
    },
    "subclass": {
        "description": "Subclass traversal: All instances of type T including subclasses",
        "template": """SELECT ?entity ?entityLabel WHERE {{
  ?entity wdt:P31/wdt:P279* wd:{type} .
  {label_service}
}}
LIMIT {limit}""",
        "required_params": ["type"],
        "label_vars": ["?entity"],
    },
    "aggregation": {
        "description": "Aggregation: COUNT/SUM/AVG over matching entities",
        "template": """SELECT ({agg_function}(?entity) AS ?result) WHERE {{
  ?entity wdt:P31 wd:{type} .
  {filter_clause}
}}""",
        "required_params": ["type", "agg_function"],
        "label_vars": [],
    },
    "top-k": {
        "description": "Top-K: Top N entities ordered by a property",
        "template": """SELECT ?entity ?entityLabel ?value WHERE {{
  ?entity wdt:P31 wd:{type} ;
          wdt:{measure_property} ?value .
  {filter_clause}
  {label_service}
}}
ORDER BY {order}(?value)
LIMIT {limit}""",
        "required_params": ["type", "measure_property", "order"],
        "label_vars": ["?entity"],
    },
    "date-filter": {
        "description": "Date filter: Entities with date property before/after a date",
        "template": """SELECT ?entity ?entityLabel ?date WHERE {{
  ?entity wdt:P31 wd:{type} ;
          wdt:{date_property} ?date .
  FILTER(?date {operator} "{date_value}"^^xsd:dateTime)
  {label_service}
}}
ORDER BY ?date""",
        "required_params": ["type", "date_property", "operator", "date_value"],
        "label_vars": ["?entity"],
    },
    "qualifier": {
        "description": "Qualifier access: Property values with their qualifiers",
        "template": """SELECT ?value ?valueLabel ?qualifier ?qualifierLabel WHERE {{
  wd:{entity} p:{property} ?stmt .
  ?stmt ps:{property} ?value .
  OPTIONAL {{ ?stmt pq:{qualifier_property} ?qualifier . }}
  {label_service}
}}""",
        "required_params": ["entity", "property", "qualifier_property"],
        "label_vars": ["?value", "?qualifier"],
    },
}


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def validate_sparql(sparql: str) -> dict[str, Any]:
    """Validate SPARQL query syntax using basic checks.

    Performs structural validation without executing the query.
    """
    errors = []
    warnings = []

    cleaned = sparql.strip()

    # Check for basic structure
    upper = cleaned.upper()
    has_select = "SELECT" in upper
    has_ask = "ASK" in upper
    has_construct = "CONSTRUCT" in upper
    has_describe = "DESCRIBE" in upper

    if not (has_select or has_ask or has_construct or has_describe):
        errors.append("Query must start with SELECT, ASK, CONSTRUCT, or DESCRIBE")

    # Check for balanced braces
    open_braces = cleaned.count("{")
    close_braces = cleaned.count("}")
    if open_braces != close_braces:
        errors.append(f"Unbalanced braces: {open_braces} opening vs {close_braces} closing")

    # Check for balanced parentheses
    open_parens = cleaned.count("(")
    close_parens = cleaned.count(")")
    if open_parens != close_parens:
        errors.append(f"Unbalanced parentheses: {open_parens} opening vs {close_parens} closing")

    # Check for WHERE clause (required for SELECT)
    if has_select and "WHERE" not in upper:
        errors.append("SELECT query is missing WHERE clause")

    # Check for common Wikidata patterns
    if "wdt:" in cleaned or "wd:" in cleaned:
        # Using Wikidata prefixes
        pass
    elif "wikidata.org" not in cleaned and "PREFIX" not in cleaned:
        warnings.append("Query does not use Wikidata prefixes (wd:, wdt:) — ensure correct prefix declarations")

    # Check for label service
    has_label_resolution = (
        "wikibase:label" in cleaned.lower()
        or "rdfs:label" in cleaned
        or "rdfs:label" in cleaned.lower()
    )
    if "Label" in cleaned and not has_label_resolution:
        warnings.append("Query references *Label variables but does not include the Wikidata label service")

    if not has_label_resolution and has_select:
        warnings.append("No label service included — results will show URIs instead of labels")

    # Check for potential Cartesian products (multiple disconnected patterns)
    # Simple heuristic: look for variables that appear only once
    var_pattern = re.findall(r'\?(\w+)', cleaned)
    var_counts = {}
    for v in var_pattern:
        var_counts[v] = var_counts.get(v, 0) + 1

    # Check for common mistakes
    if "P279*" in cleaned and "LIMIT" not in upper:
        warnings.append("Unbounded subclass traversal (P279*) without LIMIT may cause timeout")

    if "OPTIONAL" in upper and cleaned.count("OPTIONAL") > 3:
        warnings.append("Many OPTIONAL clauses may cause performance issues")

    # Validate QID/PID format
    invalid_ids = re.findall(r'wd:([^Q\s{}<>])', cleaned)
    if invalid_ids:
        errors.append(f"Invalid entity reference format (should start with Q): found wd:{invalid_ids[0]}...")

    invalid_props = re.findall(r'wdt:([^P\s{}<>])', cleaned)
    if invalid_props:
        errors.append(f"Invalid property reference format (should start with P): found wdt:{invalid_props[0]}...")

    return {
        "success": True,
        "mode": "validate",
        "sparql": sparql,
        "valid": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
        "error": None,
    }


# ---------------------------------------------------------------------------
# Generation
# ---------------------------------------------------------------------------


def generate_from_template(
    question: str,
    entities: dict[str, str],
    properties: dict[str, str],
    pattern_name: str,
    paths: list[dict] | None = None,
    include_labels: bool = True,
    limit: int | None = None,
) -> dict[str, Any]:
    """Generate a SPARQL query from a named pattern template.

    Args:
        question: The natural-language question (for context/documentation).
        entities: Mapping of entity roles to QIDs.
        properties: Mapping of property roles to PIDs.
        pattern_name: Name of the pattern to use.
        paths: Verified graph paths from exploration.
        include_labels: Whether to include the label service.
        limit: Optional LIMIT clause value.
    """
    if pattern_name not in PATTERNS:
        return {
            "success": False,
            "mode": "generate",
            "question": question,
            "sparql": None,
            "assumptions": [],
            "pattern_used": pattern_name,
            "error": f"Unknown pattern: '{pattern_name}'. Available: {list(PATTERNS.keys())}",
        }

    pattern = PATTERNS[pattern_name]

    # Build substitution dict from entities and properties
    subs = {}
    subs.update(entities)
    subs.update(properties)
    label_vars = pattern.get("label_vars", [])
    subs["label_service"] = _get_label_service(label_vars) if include_labels else ""
    subs["limit"] = str(limit or 20)
    subs["filter_clause"] = ""

    # Fill in defaults
    if "filter_value" not in subs:
        subs["filter_value"] = "?filterValue"
    if "agg_function" not in subs:
        subs["agg_function"] = "COUNT"
    if "order" not in subs:
        subs["order"] = "DESC"
    if "operator" not in subs:
        subs["operator"] = ">="
    if "date_value" not in subs:
        subs["date_value"] = "2000-01-01T00:00:00Z"

    # Try to fill template
    try:
        sparql = pattern["template"].format(**subs)
    except KeyError as exc:
        return {
            "success": False,
            "mode": "generate",
            "question": question,
            "sparql": None,
            "assumptions": [],
            "pattern_used": pattern_name,
            "error": f"Missing required parameter: {exc}",
        }

    # Build assumptions list
    assumptions = []
    for name, qid in entities.items():
        assumptions.append(f"{name} = {qid}")
    for name, pid in properties.items():
        assumptions.append(f"{name} = {pid}")
    assumptions.append(f"Pattern: {pattern['description']}")
    if include_labels:
        assumptions.append("Including Wikidata label service")
    if limit:
        assumptions.append(f"LIMIT {limit}")

    return {
        "success": True,
        "mode": "generate",
        "question": question,
        "sparql": sparql,
        "assumptions": assumptions,
        "pattern_used": pattern_name,
        "error": None,
    }


def apply_pattern(
    pattern_name: str,
    entities: dict[str, str],
    properties: dict[str, str],
    include_labels: bool = True,
    limit: int | None = None,
) -> dict[str, Any]:
    """Apply a named pattern with entity/property substitution."""
    return generate_from_template(
        question="",
        entities=entities,
        properties=properties,
        pattern_name=pattern_name,
        include_labels=include_labels,
        limit=limit,
    )


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate and validate SPARQL queries for Wikidata."
    )

    parser.add_argument(
        "--mode", "-m",
        required=True,
        choices=["validate", "generate", "pattern"],
        help="Operation mode.",
    )
    parser.add_argument(
        "--sparql",
        help="SPARQL query string (for 'validate' mode).",
    )
    parser.add_argument(
        "--question",
        help="Natural-language question (for 'generate' mode context).",
    )
    parser.add_argument(
        "--entities",
        help="JSON object mapping entity names to QIDs.",
    )
    parser.add_argument(
        "--properties",
        help="JSON object mapping property names to PIDs.",
    )
    parser.add_argument(
        "--paths",
        help="JSON array of verified graph paths.",
    )
    parser.add_argument(
        "--pattern",
        help="Named pattern to use for generation.",
    )
    parser.add_argument(
        "--include-labels",
        action="store_true",
        default=True,
        help="Include Wikidata label service (default: true).",
    )
    parser.add_argument(
        "--no-labels",
        action="store_true",
        help="Exclude Wikidata label service.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="Add LIMIT clause to generated query.",
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

    if args.mode == "validate":
        if not args.sparql:
            print(json.dumps({
                "success": False,
                "error": "--sparql is required for 'validate' mode",
            }, indent=2))
            sys.exit(1)
        result = validate_sparql(args.sparql)

    elif args.mode in ("generate", "pattern"):
        # Parse entities and properties from JSON
        entities = {}
        properties = {}
        paths = None

        if args.entities:
            try:
                entities = json.loads(args.entities)
            except json.JSONDecodeError as exc:
                print(json.dumps({
                    "success": False,
                    "error": f"Invalid --entities JSON: {exc}",
                }, indent=2))
                sys.exit(1)

        if args.properties:
            try:
                properties = json.loads(args.properties)
            except json.JSONDecodeError as exc:
                print(json.dumps({
                    "success": False,
                    "error": f"Invalid --properties JSON: {exc}",
                }, indent=2))
                sys.exit(1)

        if args.paths:
            try:
                paths = json.loads(args.paths)
            except json.JSONDecodeError as exc:
                print(json.dumps({
                    "success": False,
                    "error": f"Invalid --paths JSON: {exc}",
                }, indent=2))
                sys.exit(1)

        pattern_name = args.pattern or "direct-lookup"
        include_labels = not args.no_labels

        if args.mode == "generate":
            result = generate_from_template(
                question=args.question or "",
                entities=entities,
                properties=properties,
                pattern_name=pattern_name,
                paths=paths,
                include_labels=include_labels,
                limit=args.limit,
            )
        else:  # pattern
            result = apply_pattern(
                pattern_name=pattern_name,
                entities=entities,
                properties=properties,
                include_labels=include_labels,
                limit=args.limit,
            )
    else:
        result = {"success": False, "error": f"Unknown mode: {args.mode}"}

    output = json.dumps(result, indent=2, ensure_ascii=False)

    if args.output_file:
        from pathlib import Path
        Path(args.output_file).write_text(output)
    else:
        print(output)

    sys.exit(0 if result.get("success", False) else 1)


if __name__ == "__main__":
    main()
