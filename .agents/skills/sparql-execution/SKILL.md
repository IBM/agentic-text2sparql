---
name: sparql-execution
description: SPARQL execution skill that sends queries to the Wikidata Query Service, captures results, validates them against the user's intent, and performs iterative repair when queries fail or return implausible results. Use when you have a candidate SPARQL query ready to execute.
compatibility: Requires Python 3, uv, requests. Requires network access to the SPARQL endpoint (configurable via WIKIDATA_SPARQL_ENDPOINT env var).
---

# SPARQL Execution

Use this skill to execute SPARQL queries against the Wikidata Query Service, validate the results, and iteratively repair queries that fail or produce implausible results. This is the final execution and validation stage of the text-to-SPARQL pipeline.

## Files

- `scripts/sparql_executor.py`: standalone script for executing SPARQL against the Wikidata endpoint

## When To Use This Skill

Use this skill when:
- You have a candidate SPARQL query ready to execute against Wikidata
- You need to validate that a query runs without errors
- You need to check whether query results match the user's intent
- A previous query failed and you need to diagnose the error
- You want to run a small diagnostic query during graph exploration

## Requirements

Install skill dependencies from the workspace root with `uv sync`.

The script uses the `requests` library for HTTP access to the Wikidata SPARQL endpoint. No API keys required.

## Environment Variables

Optional:
- `WIKIDATA_SPARQL_ENDPOINT`: Override endpoint URL. Default: `https://wikikgqa.skynet.coypu.org/wikidata`.
- `WIKIDATA_USER_AGENT`: Custom User-Agent string. Default: `"AgenticText2SPARQL/1.0"`.

## Safety Rules

- Execute only read-only queries (SELECT, ASK, CONSTRUCT, DESCRIBE).
- Never send DELETE, INSERT, UPDATE, or LOAD operations.
- Always include a timeout to avoid blocking on runaway queries.
- Respect Wikidata rate limits: maximum 1 request per second for sequential queries.
- Add LIMIT to exploratory queries to avoid excessive data transfer.

## Script Usage

### Execute a SPARQL Query

```bash
uv run python .agents/skills/sparql-execution/scripts/sparql_executor.py \
  --sparql "SELECT ?country ?countryLabel WHERE { ?country wdt:P31 wd:Q6256 . OPTIONAL { ?country rdfs:label ?countryLabel FILTER(LANG(?countryLabel) = 'en') } } LIMIT 10"
```

### Execute from a File

```bash
uv run python .agents/skills/sparql-execution/scripts/sparql_executor.py \
  --file query.rq
```

### Execute with Extended Timeout

```bash
uv run python .agents/skills/sparql-execution/scripts/sparql_executor.py \
  --sparql "<QUERY>" \
  --timeout 120
```

### Arguments

Required (one of):
- `--sparql` / `-q`: SPARQL query string
- `--file` / `-f`: Path to a file containing the SPARQL query

Optional:
- `--timeout` / `-t`: Query timeout in seconds (default: 60)
- `--max-rows`: Maximum rows to return (default: 100)
- `--format`: Result format (`json`, `csv`, `tsv`) — default: `json`
- `--output-file`: Write result JSON to a file instead of stdout
- `--endpoint`: Override SPARQL endpoint URL
- `--paginate`: Automatically paginate with LIMIT/OFFSET to fetch all results when query returns more than max-rows

## Handling Large Result Sets

When a query returns more than 100 results (the default `max-rows`), the output will show `"truncated": true` with the total `"row_count"`. To fetch ALL results, use `--paginate`:

```bash
# Fetch all results with automatic pagination
uv run python .agents/skills/sparql-execution/scripts/sparql_executor.py \
  --sparql "SELECT ?person WHERE { ?person wdt:P570 ?date . FILTER(YEAR(?date) = 1973) } ORDER BY ?person" \
  --paginate
```

The `--paginate` flag:
- Automatically adds LIMIT/OFFSET clauses to fetch results in pages of 100
- Adds ORDER BY on the first variable if not already present (needed for stable pagination)
- Continues fetching until all results are retrieved (up to 5000 safety cap)
- Does NOT paginate if the query already has an explicit LIMIT clause

**When to use `--paginate`:**
- Questions expecting a list of ALL matching entities (e.g., "Who died in 1973?", "Which countries border X?")
- Questions where the result count IS the answer (e.g., "How many X?")
- When you see `"truncated": true` in the first result and need the complete set

**When NOT to use `--paginate`:**
- Superlative queries with LIMIT 1 (e.g., "tallest", "oldest")
- Diagnostic/exploration queries where a sample suffices

## Handling Very Large Result Sets (>100 entities)

When a query returns hundreds or thousands of results (e.g., "all people who died in 1973"), do NOT try to bring all IDs into your context. Instead, use `--extract-ids` to write them directly to a file:

```bash
# Write all entity IDs directly to the answer file
uv run python .agents/skills/sparql-execution/scripts/sparql_executor.py \
  --sparql "SELECT ?person WHERE { ?person wdt:P570 ?date . FILTER(YEAR(?date) = 1973) } ORDER BY ?person" \
  --paginate \
  --extract-ids /path/to/answer_file.json
```

This will:
1. Execute the query with pagination (fetching all pages)
2. Extract QIDs/PIDs from Wikidata URIs (e.g., `http://www.wikidata.org/entity/Q42` → `Q42`)
3. Write a deduplicated JSON array directly to the specified file
4. Print only a small summary to stdout (total count + first 10 IDs as sample)

**When to use `--extract-ids`:**
- The query returns more than 100 results
- The answer IS the full list of entities (not a count or single value)
- You see `"truncated": true` with a large `row_count`

**Output to stdout (small, agent-friendly):**
```json
{
  "success": true,
  "extracted_ids_file": "/path/to/answer_file.json",
  "total_ids": 20249,
  "sample": ["Q123", "Q456", "Q789", ...],
  "truncated_in_sample": true
}
```

## Return Shape

### Successful Execution

```json
{
  "success": true,
  "sparql": "SELECT ?country ?countryLabel WHERE { ?country wdt:P31 wd:Q6256 . OPTIONAL { ?country rdfs:label ?countryLabel FILTER(LANG(?countryLabel) = 'en') } } LIMIT 10",
  "results": {
    "variables": ["country", "countryLabel"],
    "rows": [
      {"country": "http://www.wikidata.org/entity/Q142", "countryLabel": "France"},
      {"country": "http://www.wikidata.org/entity/Q183", "countryLabel": "Germany"}
    ],
    "row_count": 10,
    "truncated": false
  },
  "execution_time_ms": 1234,
  "endpoint": "https://wikikgqa.skynet.coypu.org/wikidata",
  "error": null
}
```

### Execution Failure

```json
{
  "success": false,
  "sparql": "SELECT ?x WHERE { ?x wdt:P31 wd:INVALID . }",
  "results": null,
  "execution_time_ms": 89,
  "endpoint": "https://wikikgqa.skynet.coypu.org/wikidata",
  "error": {
    "type": "syntax_error",
    "message": "Bad Request: Lexical error at line 1, column 42",
    "http_status": 400,
    "details": "Encountered: \"INVALID\" (expected: QNAME or IRI)"
  }
}
```

### Timeout

```json
{
  "success": false,
  "sparql": "<complex_query>",
  "results": null,
  "execution_time_ms": 60000,
  "endpoint": "https://wikikgqa.skynet.coypu.org/wikidata",
  "error": {
    "type": "timeout",
    "message": "Query execution exceeded 60 second timeout",
    "http_status": null,
    "details": "Consider simplifying the query, adding LIMIT, or removing unbounded property paths"
  }
}
```

## Error Types and Repairs

### Syntax Errors (HTTP 400)

| Error Pattern | Likely Cause | Repair |
|--------------|--------------|--------|
| "Lexical error" | Invalid character or token | Check for unescaped quotes, invalid prefixes |
| "Expected QNAME or IRI" | Malformed entity reference | Verify QID/PID format (e.g., `wd:Q123` not `wd:Q 123`) |
| "Encountered '}' expected '.' " | Missing period between triple patterns | Add period separator |
| "Unresolved prefix" | Using prefix without declaration | Add PREFIX declaration or use full IRI |

### Endpoint Errors (HTTP 500/503)

| Error Pattern | Likely Cause | Repair |
|--------------|--------------|--------|
| "Query deadline is expired" | Query too complex | Add LIMIT, simplify, remove `P279*` |
| "Service Unavailable" | Wikidata overloaded | Wait 5 seconds and retry (max 3 retries) |
| "Java heap space" | Result set too large | Add LIMIT, add type constraints |

### Semantic Issues (Successful but Wrong Results)

| Symptom | Likely Cause | Repair |
|---------|--------------|--------|
| Empty results | Wrong PID, wrong direction, or overly strict filter | Verify property with exploration, try reversed direction |
| Too many results (thousands) | Missing type constraint | Add `wdt:P31 wd:Q_TYPE` restriction |
| Duplicate rows | Multiple statements per entity | Add DISTINCT |
| Wrong entity types | No type filter | Add instance_of constraint |
| All labels show as QIDs | Missing label pattern | Add `OPTIONAL { ?x rdfs:label ?xLabel FILTER(LANG(?xLabel) = "en") }` (do NOT use SERVICE wikibase:label — it causes 500 errors) |
| Dates look wrong | Wrong precision | Check date format in FILTER |

## Repair Strategy

When a query fails or returns implausible results:

1. **Identify the problem type**: syntax, endpoint, or semantic
2. **Change ONE assumption at a time**: This makes it clear what fixed the issue
3. **Maximum 3 retries per query variant**: If 3 attempts fail, reconsider the approach
4. **Auto-detect truncation**: If results show `"truncated": true` and the question expects a COMPLETE list (not a superlative/sample), immediately re-run with `--paginate --extract-ids <output_file>`. Do NOT attempt to manually construct the full list from your context.
5. **Escalate systematically**:
   - First: Fix the specific error (syntax, wrong PID)
   - Second: Try alternative property or reversed direction
   - Third: Simplify query, use exploration to gather more evidence
   - Fourth: Return best attempt with explanation
5. **Never discard valid results based on world knowledge**: If your query executes successfully and returns non-empty results, do not discard them just because the results seem surprising from a world-knowledge perspective. Only retry when there is a genuine error (syntax, timeout, empty results, or wrong output type). However, when you have **two competing valid result sets** from different query approaches (e.g., truthy `wdt:` vs statement-level `p:/ps:`), choose the one whose semantics best match the question:
   - For "current" multi-valued properties (current capitals, current members): prefer `wdt:` truthy results, which reflect Wikidata's rank-based currentness model.
   - For counting ALL historical statements (total spouses ever, all-time records): prefer statement-level results.
   - When in doubt, analyze WHY the result sets differ before choosing the larger one.

### Typical Repair Sequence

```
Attempt 1: Original query
  → Error: empty results
  
Attempt 2: Reverse property direction
  → Error: still empty
  
Attempt 3: Try alternative property (from search)
  → Success: 12 results
```

## Validation Checks

After successful execution, validate the results:

1. **Non-empty**: Zero results usually means wrong property or direction
2. **Reasonable count**: A "list all countries" query should return ~195, not 5 or 50,000
3. **Correct types**: If asking about people, results should be humans (Q5)
4. **No duplicates**: Same entity shouldn't appear multiple times (unless expected)
5. **Labels present**: Results should have readable labels, not just QIDs
6. **Values in range**: Populations should be positive, dates should be reasonable
7. **Matches intent**: The result columns should answer what was asked
8. **Correct value type**: If the property is item-valued (wikibase-item), results should be QIDs (Q...) not literal strings. If you see a plain string where a QID is expected, the query is extracting a label instead of the entity.
9. **Normalized units for quantities**: If the question asks for a measurement and the result seems too small/large by orders of magnitude, verify whether `psn:` (normalized path) was used instead of `wdt:` (stored unit).
10. **Current vs. historical**: If the question asks about "currently" or "now", verify that ended relationships (those with `pq:P582` end time) are excluded. If it asks about "ever" or "all-time", verify that `p:/ps:` is used to access all statements.

## Critical: Trust the Endpoint Data

The SPARQL endpoint is the **authoritative data source**. Apply these rules strictly:

1. **Do NOT apply real-world plausibility filters**: Never add FILTER clauses that exclude results based on what you believe is "reasonable" from world knowledge. For example:
   - Do NOT add `FILTER(?height < 3)` to exclude "unrealistic" heights
   - Do NOT add `FILTER(?mass > 0)` unless the question explicitly asks for non-zero values
   - Do NOT restrict a query to "Solar System planets" when the question says "planet" generically
   - If the endpoint says an entity has a height of 173m, return that result — do not second-guess data quality

2. **Do NOT override query results with heuristic lookups**: If your SPARQL query returns entity X as the top result, do not discard it in favor of entity Y just because Y is the "well-known" answer from world knowledge. The endpoint may have different data than what you expect.

3. **Do NOT narrow scope after finding valid results**: If your first query returns plausible results, do not re-run with a narrower scope and then discard the earlier findings. Specifically:
   - If a broader query (e.g., using subclass traversal `P31/P279*`) returns an answer, do not re-run with a stricter type check (e.g., just `P31`) and prefer the narrower result
   - If you must try both broad and narrow approaches, prefer the one whose scope best matches the question's wording
   - "Head of state in the world" = all sovereign entities (broad), not just `P31 Q6256` instances (narrow)
   - **Exception — truthy vs statement-level**: When `wdt:` (truthy) and `p:/ps:` (statement-level) return different results, this is NOT a scope issue — it's a semantic difference. For "current" questions (current capitals, current members), prefer `wdt:` because it reflects Wikidata's rank-based filtering. For "total/historical" questions, prefer `p:/ps:`. Analyze the discrepancy before choosing.

4. **Return raw results from the endpoint**: Your job is to faithfully translate the question into SPARQL and return whatever the endpoint gives back. The endpoint data is evaluated as ground truth.

5. **NEVER use webfetch or direct HTTP calls to query.wikidata.org**: Always use the `sparql_executor.py` script to execute SPARQL queries. The script uses the configured endpoint (set via `WIKIDATA_SPARQL_ENDPOINT` env var or defaulting to the evaluation backend). Do NOT bypass it by calling `https://query.wikidata.org/sparql` directly via webfetch — this uses a different data source and will produce incorrect results for evaluation.

## Integration with text2sparql Pipeline

### Recommended Workflow

1. **Execute the generated query:**
   ```bash
   uv run python .agents/skills/sparql-execution/scripts/sparql_executor.py \
     --sparql "<GENERATED_QUERY>"
   ```

2. **On success**: Validate results against the parsed intent
3. **On failure**: Diagnose error type and apply appropriate repair
4. **After repair**: Re-execute and validate again

### Parallel Execution (During Exploration)

When verifying multiple candidates, run diagnostic queries in parallel:

```bash
# Check if P36 works outgoing from Q142
uv run python .agents/skills/sparql-execution/scripts/sparql_executor.py \
  --sparql "SELECT ?v WHERE { wd:Q142 wdt:P36 ?v . } LIMIT 5"

# Check if P36 works incoming to Q142
uv run python .agents/skills/sparql-execution/scripts/sparql_executor.py \
  --sparql "SELECT ?v WHERE { ?v wdt:P36 wd:Q142 . } LIMIT 5"
```

## Troubleshooting

- **Consistent timeouts**: The query is too complex. Remove property paths (`*`, `+`), add LIMIT, reduce OPTIONAL blocks.
- **Rate limiting (HTTP 429)**: You're sending requests too fast. Add at least 1 second delay between requests.
- **Empty results for valid query**: Check if the entity/property combination exists using graph exploration first.
- **Results look correct but incomplete**: Check if LIMIT is too low, or if some entities lack the queried property.
- **SSL/connection errors**: Wikidata endpoint may be temporarily down. Retry after 10 seconds.
