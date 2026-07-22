---
name: text2sparql
description: End-to-end Text-to-SPARQL skill that orchestrates wikidata-search, graph-exploration, sparql-generation, and sparql-execution to convert a natural-language question into a validated, executable SPARQL query over Wikidata. Use when the user asks a natural-language question and expects a working SPARQL query as output.
compatibility: Requires all dependencies of wikidata-search, graph-exploration, sparql-generation, and sparql-execution skills (Python 3, uv, requests). Requires network access to Wikidata APIs.
---

# Text-to-SPARQL (Orchestrator)

This is the top-level orchestrating skill for the agentic text-to-SPARQL pipeline. It chains together **wikidata-search**, **graph-exploration**, **sparql-generation**, and **sparql-execution** in an iterative workflow to produce a correct, executable SPARQL query over Wikidata.

## When To Use This Skill

Use this skill when:
- The user asks a natural-language question and expects a SPARQL query against Wikidata
- The user provides a `question` that refers to real-world entities, relations, or facts
- You need to produce a SPARQL query that is syntactically valid, executes against the Wikidata Query Service, and returns plausible results

## Inputs

| Parameter | Required | Description |
|-----------|----------|-------------|
| `question` | Yes | The natural-language question to answer |

## Pipeline Overview

```
┌─────────────────────────┐
│  1. Intent Parsing      │  Identify entities, relations, filters, aggregations
└────────┬────────────────┘
         │ parsed intent
         ▼
┌─────────────────────────┐
│  2. Wikidata Search     │  Resolve entity/property names to QIDs/PIDs
└────────┬────────────────┘
         │ candidate IDs
         ▼
┌─────────────────────────┐
│  3. Graph Exploration   │  Inspect graph around seed entities
└────────┬────────────────┘
         │ verified paths, directions, qualifiers
         ▼
┌─────────────────────────┐
│  4. SPARQL Generation   │  Build candidate query from evidence
└────────┬────────────────┘
         │ candidate SPARQL
         ▼
┌─────────────────────────┐
│  5. SPARQL Execution    │  Execute & validate results
└────────┬────────────────┘
         │ result set
         ▼
┌─────────────────────────┐
│  6. Validation &        │  Check results match intent
│     Repair              │  Retry if needed
└─────────────────────────┘
```

If any step fails or produces implausible results, the pipeline loops back with error context to recover.

## Working State

Throughout the pipeline, maintain the following working state:

| Field | Description |
|-------|-------------|
| `original_question` | The user's natural-language question |
| `parsed_intent` | Decomposed intent: entities, relations, filters, aggregations, output fields |
| `candidate_entities` | Search results for entity resolution (with QIDs, labels, descriptions) |
| `candidate_properties` | Search results for property resolution (with PIDs, labels, descriptions) |
| `selected_ids` | Final chosen QIDs and PIDs with confidence notes |
| `discovered_paths` | Graph paths verified through exploration |
| `generated_queries` | History of generated SPARQL queries |
| `execution_errors` | Errors from failed executions |
| `result_samples` | Representative result rows from successful executions |
| `validation_observations` | Notes on result plausibility |

## Detailed Workflow

### Step 1: Intent Parsing

Parse the user's natural-language question to identify:
- **Entities**: Named things (people, places, organizations, works, events)
- **Relations**: How entities connect (occupation, capital of, member of)
- **Filters**: Constraints (dates, types, quantities)
- **Aggregations**: COUNT, MAX, MIN, AVG, GROUP BY
- **Output fields**: What the user wants returned (names, dates, counts)
- **Expected result shape**: Single value, list, or table

Do this as an LLM reasoning step — no tool call needed.

### Step 2: Wikidata Search (or Use Provided Mentions)

**If mentions are provided** (pre-resolved entity/property IDs are given with the question):

The mentions give you QIDs and PIDs as starting points. Your workflow changes:
- **Skip initial search** for entities/properties that already have IDs in the mentions
- **Still search** for any concepts NOT covered by mentions (e.g., intermediate classes, alternative properties)
- **Still search** if a mention seems to point to a concept/movement rather than a classifying type
- Go directly to **Step 3 (Graph Exploration)** to verify the mentions are correct and discover paths

**Mention format:**
```
  - "entity name" | entity=Q12345
  - "property name" | property=P678
  - "relation" | property=P789 | (inverse)
```

**Important caveats about mentions:**
- A mention with `entity=Q_xxx` means that string likely maps to that QID — but verify through exploration
- A mention with `property=P_xxx` suggests the property role — but may not be the exact triple pattern to use
- `(inverse)` means the property should be used in reverse direction (object → subject)
- Mentions may be incomplete — not all relevant entities/properties will be listed
- Mentions may point to a **concept** (Q39162 "open source movement") instead of the **classifying type** (Q1130645 "open-source software") needed for P31 queries

**If NO mentions are provided**, run the wikidata-search script to resolve entity and property names:

```bash
uv run python .agents/skills/wikidata-search/scripts/wikidata_search.py \
  --query "<ENTITY_NAME>" \
  --type item \
  --limit 5
```

```bash
uv run python .agents/skills/wikidata-search/scripts/wikidata_search.py \
  --query "<RELATION_NAME>" \
  --type property \
  --limit 5
```

**Run searches for all identified entities and properties in parallel.**

**Selection rules:**
- Do NOT blindly take the first result. Use descriptions and entity types to select the most plausible candidate.
- If confidence is low, preserve multiple candidates for disambiguation during exploration.
- Cross-check entity descriptions against the question context.
- When searching for properties, try multiple phrasings (e.g., "capital" and "capital city").
- **For generic category types** (companies, organizations, conferences, universities): If your initial query with a single type class returns suspiciously few results (<3), search for additional related type classes. For example, "companies" might need Q783794 (company), Q4830453 (business), Q6881511 (enterprise). Use a `VALUES ?type { ... }` clause to cover relevant types. But if the first type class returns reasonable results, don't expand — more types may over-generate.

**On failure:**
- If zero results: try synonyms, alternative spellings, or broader terms.
- If all candidates seem wrong: try searching for a more specific or more general term.

### Additional Guidance for Mentions

When pre-resolved mentions are provided, apply these additional checks during exploration:

1. **Search for intermediate classes** — If the question combines two concepts (e.g., "NP-complete" + "video games"), search for whether Wikidata has a combined class (e.g., Q21055677 "NP-complete game") before building intersection queries.

2. **Validate mention entities for type queries** — If you plan to use a mentioned entity in `wdt:P31 wd:Q_entity`, verify it's actually used as a type in Wikidata by running a quick count. Concepts and movements (Q39162 "open source") differ from classifying types (Q1130645 "open-source software").

3. **Discover missing properties** — If mentions provide entities without linking properties, explore the graph to find how they connect. Try common linking properties or run `SELECT ?p WHERE { wd:Q_subject ?p wd:Q_object } LIMIT 10`.

4. **Don't over-rely on mentions** — If a mentioned property returns zero results during exploration, search for alternative properties. The mention may indicate the semantic role but not the exact Wikidata property.

### Step 3: Graph Exploration

Use the graph-exploration script to verify the structure around seed entities:

```bash
uv run python .agents/skills/graph-exploration/scripts/graph_explorer.py \
  --entity "<QID>" \
  --mode outgoing \
  --limit 20
```

```bash
uv run python .agents/skills/graph-exploration/scripts/graph_explorer.py \
  --entity "<QID>" \
  --mode incoming \
  --property "<PID>" \
  --limit 10
```

```bash
uv run python .agents/skills/graph-exploration/scripts/graph_explorer.py \
  --entity "<QID>" \
  --mode check-property \
  --property "<PID>"
```

**Exploration goals:**
- Verify that the candidate property actually connects the expected entities
- Determine the correct direction (subject→object or object→subject)
- Check whether direct properties (wdt:) suffice or statement nodes (p:/ps:/pq:) are needed
- Identify required type constraints (instance of / subclass of patterns)
- Find intermediate nodes if a direct path doesn't exist
- **Discover alternative/synonym properties (but prefer the first working one)**: Many relationships can be expressed through multiple properties. When you find one property that works and returns results, **keep it as your primary choice**. Only search for alternatives when the first property returns zero or suspiciously few results. If you do find alternatives, compare their coverage (result count) and prefer the one with broader coverage. Common alternation patterns:
  - Causes: P828 (has cause) | P1478 (has immediate cause) | ^P1542 (inverse of "has effect")
  - Founding/start date: P571 (inception) | P580 (start time)
  - Sport nationality: P1532 (country for sport) is more general than P54 (member of specific team)
  - Holidays observed: P832 (public holiday) — check direction from country to holiday
  - Child organizations: P355 (subsidiary, outgoing from parent) vs P749 (parent organization, incoming from child) — these often differ in coverage; prefer the forward direction from the parent
  
  **Do NOT switch to an alternative property if the first one already returns plausible results.** Switching to a "cleaner" property name may lose valid results.
- **Explore properties of known answer entities**: When you struggle to find the linking property, look at outgoing properties of an entity you know is in the expected answer set. This reveals how the relationship is actually modeled.

**When to explore:**
- Always explore when the relationship between entities is not obvious
- Always explore when you have multiple candidate properties
- Skip exploration only when the pattern is well-known and straightforward (e.g., "instance of", "country")

### Step 4: Retrieve Similar Examples (Conditional)

Retrieve similar gold-standard examples **only when the question involves complex patterns**. Do NOT retrieve examples for simple, straightforward questions where you already have high confidence in the query structure.

**When to retrieve examples:**
- The question involves physical measurements (distance, mass, area, duration, height, speed)
- The question requires temporal qualifiers ("current", "highest ever", "at the time of")
- The question involves complex aggregations (proportions, GROUP BY, nested counts)
- The question involves competition/contest winners with country-level modeling
- Your first query attempt failed and you need pattern guidance for repair

**When NOT to retrieve examples:**
- Simple entity property lookups ("What is the capital of X?", "Who wrote Y?")
- Direct boolean checks ("Is X alive?", "Does X have a president?")
- Straightforward P31/type queries where the pattern is obvious
- Any question where you are already confident about the SPARQL structure

**If retrieval is needed:**

```bash
uv run python .agents/skills/few-shot-examples/scripts/retrieve_examples.py \
  --query "<QUESTION>" \
  --top-k 5
```

This returns similar questions from the evaluation dataset with their correct SPARQL queries. Use these as **structural guidance only** — they show what patterns work (e.g., `psn:` for measurements, `p:/ps:/pq:` for qualifiers) but you must still perform entity search and graph exploration to resolve the correct IDs for the current question.

Pay special attention to:
- Whether similar questions use `psn:` (normalized values) for measurements
- Whether they use `p:/ps:/pq:` (statement level) for qualified data
- The ORDER BY / LIMIT patterns for superlative questions
- The MINUS / FILTER NOT EXISTS patterns for exclusion questions

**Important:** Do NOT skip Steps 2-3 (Search and Graph Exploration) just because you found a similar example. The example shows the pattern; you still need to verify entities, properties, and directions for this specific question.

**Warning:** Do NOT apply complex patterns from retrieved examples to simple questions. If your question is a straightforward lookup and the example shows subclass traversal or qualifiers, ignore the complex pattern and use the simple approach.

### Step 5: SPARQL Generation

Generate a candidate SPARQL query using the sparql-generation skill:

```bash
uv run python .agents/skills/sparql-generation/scripts/sparql_generator.py \
  --question "<QUESTION>" \
  --entities '<JSON_ENTITIES>' \
  --properties '<JSON_PROPERTIES>' \
  --paths '<JSON_PATHS>'
```

Or generate the SPARQL directly as an LLM reasoning step using the verified IDs and paths from exploration.

**Generation rules:**

**Core principles (apply to ALL queries):**
- **Simplicity first**: Start with the simplest query that matches the question. Do not add complexity unless the simple query fails.
- **No extra filters**: Do NOT add MINUS, FILTER, or exclusion clauses beyond what the question explicitly states. If the question says "countries not bordering X", use only `MINUS { X wdt:P47 ?country }`. Do not also exclude dissolved states, the country itself, or other entities not mentioned.
- **Don't switch working properties**: If a property (e.g., P176) already returns plausible results during exploration, use it. Do not switch to a "semantically cleaner" alternative (e.g., P1716) that returns fewer results.

**Specific rules:**
- Use only verified Wikidata IDs (from search + exploration)
- Use correct triple pattern direction (verified in exploration)
- Include `OPTIONAL { ?x rdfs:label ?xLabel FILTER(LANG(?xLabel) = "en") }` for labels (NOTE: `SERVICE wikibase:label` is NOT available on this endpoint — it will cause HTTP 500 errors)
- Use `VALUES` for known entities where appropriate
- Use `OPTIONAL` only for genuinely optional fields
- Use `p:`, `ps:`, `pq:` for qualifier-based queries
- Add `DISTINCT` when JOINs could create duplicates
- Always add a `LIMIT` during exploration/debugging
- Avoid unnecessary Cartesian products
- **For quantity properties** (distance, mass, area, duration, speed, height, etc.): ALWAYS use `p:P.../psn:P.../wikibase:quantityAmount` to get SI-normalized values — NEVER use bare `wdt:P...` for numeric measurements
- **For historical/all-time queries** ("highest ever", "record", "all-time"): Use `p:P.../ps:P...` to access ALL statements including historical ones — `wdt:` only returns the current truthy value
- **For current-state questions** ("Does X currently have Y?", "Who is the current PM?"): Use `p:` + `MINUS { ?stmt pq:P582 ?end }` to exclude ended relationships, or order by `pq:P580` (start time) DESC
- **For "current" multi-valued properties** (current capitals, current members, current official languages): Prefer `wdt:` truthy paths which already reflect Wikidata's rank-based currentness. Do NOT switch to `p:/ps:` with manual `MINUS { pq:P582 }` as this can include false positives that lack explicit end dates.
- **For item-valued properties** (P735 given name, P3150 birthday, P1441 present in work): Return the entity QID, not its label string
- **For location-based queries**: Use `wdt:P131+` (transitive) not bare `wdt:P131`
- **For monetary comparisons**: Filter by `wikibase:quantityUnit` via `psv:` to ensure same currency
- **Do NOT add constraints not in the question**: No plausibility filters, no scope restrictions, no unit constraints unless explicitly asked
- **Return entities, not just counts**: When a question can be answered by listing entities (even if phrased as "how many"), prefer returning the entities themselves. Only use COUNT for explicitly numeric questions where the result set is expected to be large.
- **Match the question's scope precisely**: If the question says "Latin American country", use the exact Wikidata relationship for Latin America (e.g., `P361 Q12585`). Do not broaden to "South American continent" or narrow beyond what was asked.
- **Do NOT use subclass traversal on P921 (main subject)**: Using `wdt:P921/wdt:P279*` massively over-generates by returning items whose topic is any subclass of the target concept. Use direct `wdt:P921 wd:Q_TOPIC` unless you have explicit evidence that traversal is needed.
- **Test multiple type classes only when results are too few**: When the question asks about "companies", "organizations", etc. and your initial query with one type class returns suspiciously few results (<3), THEN search for and test additional type classes. Use a `VALUES ?type { ... }` clause. But if the first type class returns a reasonable number of results, stop there.

### Step 6: SPARQL Execution + Validation

Execute the generated query:

```bash
uv run python .agents/skills/sparql-execution/scripts/sparql_executor.py \
  --sparql "<SPARQL_QUERY>"
```

**For queries expecting large result sets** (e.g., "all people who died in year X", "all countries with property Y"):

```bash
# Write results directly to file — avoids loading thousands of IDs into context
uv run python .agents/skills/sparql-execution/scripts/sparql_executor.py \
  --sparql "<SPARQL_QUERY>" \
  --paginate \
  --extract-ids /path/to/answer_file.json
```

This writes the entity IDs directly to the answer file and returns only a summary (count + sample). Use this when:
- Results are expected to be more than ~50 entities
- The answer is a list of ALL matching entities (not a count or single value)
- You see `"truncated": true` in initial results

**Validation checks after execution:**
1. **Syntax/endpoint errors**: Fix and retry
2. **Empty results**: Re-examine property direction, type constraints, or filter values
3. **Implausibly many results**: Add type constraints or DISTINCT
4. **Duplicate rows**: Add DISTINCT or fix JOIN pattern
5. **Wrong entity types**: Results should match the expected type (e.g., people, cities)
6. **Missing labels**: Add `OPTIONAL { ?x rdfs:label ?xLabel FILTER(LANG(?xLabel) = "en") }` pattern
7. **Timeout**: Simplify query, add LIMIT, reduce complexity
8. **Truncated results** (`"truncated": true`): If the question expects ALL matching entities (not a superlative or sample), re-run with `--paginate --extract-ids <answer_file_path>` to fetch the complete set. Do NOT try to manually paginate or bring large result sets into your context — use `--extract-ids` to write directly to the answer file.

**Handling "How many X?" questions:**
- First check if the entity has a direct count property (P1114, P1538, P1539, P1971) — use that value if available, as it's more authoritative
- If no direct count property, use `SELECT (COUNT(DISTINCT ?x) AS ?count) WHERE { ... }`
- Return the count as a string literal (e.g., `["42"]`), not an entity list

**Handling "current" state questions:**
- "Who IS the X?" (present tense) — `wdt:` truthy value reflects the current best-ranked statement
- If `wdt:` returns multiple values for a position (e.g., P39 head of state, P488 chairperson), the endpoint may have stale data. Verify by using `p:P39/ps:P39` with `MINUS { ?stmt pq:P582 ?end }` to get only statements without an end date
- "Who WAS the X?" (past tense) — use `p:P39/ps:P39` with temporal qualifiers to find the specific time period

**Critical: Trust the endpoint data.**
- Do NOT apply real-world plausibility filters to results (e.g., do NOT add `FILTER(?height < 3)` to remove "unrealistic" values)
- Do NOT override query results with world-knowledge heuristics (e.g., do NOT pick Mount Everest over the top result just because "everyone knows" it's the tallest)
- Do NOT narrow scope after getting valid results (e.g., do NOT switch from sovereign-state subclasses to only `P31 Q6256` after getting a valid answer from the broader query)
- Do NOT expand a working query with extra UNION branches when it already returns a reasonable number of results (>5 for list questions). Adding alternative detection paths (e.g., license-based instead of type-based) may introduce false positives.
- The endpoint data is treated as ground truth. Return whatever the query produces.
- **NEVER use webfetch to call query.wikidata.org directly.** Always use `sparql_executor.py` or `graph_explorer.py` scripts which use the correct configured endpoint. Bypassing them with direct HTTP calls to live Wikidata will produce wrong results.

**Principle of minimal query complexity:**
- Start with the simplest possible query that matches the question's structure.
- Only add complexity (subclass traversal, UNION, alternative properties) when the simple query returns zero or clearly insufficient results.
- If your first query returns plausible results, **stop and return them**. Do not continue "improving" with broader alternatives.

### Step 7: Repair and Retry

When execution fails or results are implausible:

**Common repairs:**
| Problem | Repair |
|---------|--------|
| Wrong property | Go back to search, try alternative PID |
| Wrong direction | Swap subject/object in triple pattern |
| Empty results (type too strict) | Remove or broaden type constraint |
| Empty results (no direct property) | Try statement-level access (p:/ps:) |
| Too many results | Add type constraint, add DISTINCT |
| Missing subclasses | Add `wdt:P31/wdt:P279*` subclass traversal |
| Qualifier needed | Switch from `wdt:` to `p:/ps:/pq:` pattern |
| Timeout | Add LIMIT, simplify, remove subclass traversal depth |
| Wrong numeric value (unit issue) | Switch from `wdt:` to `p:P/psn:P/wikibase:quantityAmount` for SI-normalized values |
| Returns current value, not historical max | Switch from `wdt:` to `p:P/ps:P` to access all statements |
| Returns ended relationships as active | Add `MINUS { ?stmt pq:P582 ?end }` |
| Returns label string instead of QID | Remove label extraction; return the entity variable directly |
| Misses items in sub-locations | Change `wdt:P131 wd:Q` to `wdt:P131+ wd:Q` (transitive) |
| Mixed currencies in comparison | Add `wikibase:quantityUnit wd:Q_CURRENCY` filter via `psv:` |

**Repair rules:**
- Change ONE assumption at a time so the effect is clear
- Maximum 3 retry cycles per query
- If all retries fail, return the best query with explanation
- **On first failure, retrieve similar examples** (if not already done in Step 4): Use `retrieve_examples.py` to see how similar questions were correctly answered. This is the ideal time for few-shot retrieval — when you have a concrete failure to diagnose.
- **Never discard a working query's results based on world knowledge**: If a query executes and returns non-empty, non-error results, that IS the answer. Only repair when there is a genuine failure (syntax error, timeout, truly empty results). Do not "repair" by narrowing scope or adding plausibility filters based on world knowledge.
- **Choosing between competing valid results**: When `wdt:` (truthy) and `p:/ps:` (statement-level) return different result sets, choose based on the question's semantics:
  - "Current" multi-valued properties (capitals, members, languages): prefer `wdt:` truthy results
  - "Total/historical" questions (all spouses ever, all-time records): prefer `p:/ps:` statement-level results
  - Always analyze WHY the two approaches differ before choosing the larger result set

## Error Recovery Strategy

```
Retry budget: 3 attempts per step, 3 full pipeline retries

Cycle 1: Search → Explore → Generate → Execute → Validate
         ↑                                          │
         └──── If implausible, retry with context ──┘

Cycle 2: (Adjusted IDs / alternate properties / different direction)
         ...

Cycle 3: (Broadened search / simplified query / alternative modeling)
```

**Escalation path:**
1. First retry: Fix the specific error (wrong PID, wrong direction, missing type)
2. Second retry: Try alternative properties or modeling approach
3. Third retry: Simplify the query, possibly returning partial results
4. If all retries fail: Return best attempt with clear explanation of what went wrong

## Output

The final output should include:

1. **The SPARQL query** (formatted and ready to execute)
2. **The results** (representative rows or full result set if small)
3. **A brief explanation** of the answer in natural language

Example final output:

```sparql
SELECT ?country WHERE {
  ?country wdt:P31 wd:Q6256 ;
           wdt:P30 wd:Q15 ;
           wdt:P1082 ?population .
  FILTER(?population > 100000000)
}
ORDER BY DESC(?population)
```

Results: [table of African countries with population > 100M]

Answer: The African countries with populations exceeding 100 million are Nigeria (223M) and Ethiopia (126M).

## Full Example Run

**Input**: question = "What are the capitals of countries in South America?"

**Step 1** - Intent Parsing:
- Entities: South America (continent)
- Relations: capital, country, located in continent
- Filters: countries in South America
- Output: country names + capital names

**Step 2** - Wikidata Search:
```bash
uv run python .agents/skills/wikidata-search/scripts/wikidata_search.py \
  --query "South America" --type item --limit 5
# → Q18 (South America, continent)

uv run python .agents/skills/wikidata-search/scripts/wikidata_search.py \
  --query "capital" --type property --limit 5
# → P36 (capital)

uv run python .agents/skills/wikidata-search/scripts/wikidata_search.py \
  --query "continent" --type property --limit 5
# → P30 (continent)
```

**Step 3** - Graph Exploration:
```bash
uv run python .agents/skills/graph-exploration/scripts/graph_explorer.py \
  --entity "Q18" --mode incoming --property "P30" --limit 5
# → Confirms countries use P30 to link to Q18
```

**Step 4** - SPARQL Generation:
```sparql
SELECT ?country ?countryLabel ?capital ?capitalLabel WHERE {
  ?country wdt:P31 wd:Q6256 ;
           wdt:P30 wd:Q18 ;
           wdt:P36 ?capital .
  OPTIONAL { ?country rdfs:label ?countryLabel FILTER(LANG(?countryLabel) = "en") }
  OPTIONAL { ?capital rdfs:label ?capitalLabel FILTER(LANG(?capitalLabel) = "en") }
}
```

**Step 5** - Execution:
```bash
uv run python .agents/skills/sparql-execution/scripts/sparql_executor.py \
  --sparql "SELECT ?country ?countryLabel ?capital ?capitalLabel WHERE { ?country wdt:P31 wd:Q6256 ; wdt:P30 wd:Q18 ; wdt:P36 ?capital . OPTIONAL { ?country rdfs:label ?countryLabel FILTER(LANG(?countryLabel) = 'en') } OPTIONAL { ?capital rdfs:label ?capitalLabel FILTER(LANG(?capitalLabel) = 'en') } }"
```
Result: 12 rows (Argentina/Buenos Aires, Brazil/Brasilia, ...)

**Step 6** - Validation:
- 12 results (reasonable — there are 12 sovereign states in South America)
- All results are countries with capitals
- Labels present

**Final Output**: Query + results + natural language answer.

## Tips for Common Patterns

| Question Pattern | SPARQL Pattern |
|-----------------|----------------|
| "What is the X of Y?" | `wd:Y wdt:PX ?answer` |
| "Which Y have X?" | `?y wdt:P31 wd:TYPE ; wdt:PX ?value . FILTER(...)` |
| "How many X?" | `SELECT (COUNT(?x) AS ?count) WHERE { ... }` |
| "List all X of type T" | `?x wdt:P31 wd:T .` (or `wdt:P31/wdt:P279* wd:T` for subclasses) |
| "X born in place Y" | `?x wdt:P19 wd:Y .` (place of birth) |
| "X that happened after date D" | `?x wdt:Ptime ?date . FILTER(?date > "YYYY-MM-DDT00:00:00Z"^^xsd:dateTime)` — always include T00:00:00Z |
| "Top N by property" | `ORDER BY DESC(?prop) LIMIT N` |
| "X with qualifier Q" | `?x p:PX ?stmt . ?stmt ps:PX ?val ; pq:PQ ?qual .` |
| "X and its subclasses" | `?x wdt:P31/wdt:P279* wd:TYPE .` |
| "Relation between X and Y" | Explore outgoing/incoming to find connecting property |
| "How far/heavy/long/fast is X?" | `wd:X p:P_QUANTITY/psn:P_QUANTITY/wikibase:quantityAmount ?val` |
| "What is the tallest/fastest X?" | `?x p:P/psn:P/wikibase:quantityAmount ?v . ORDER BY DESC(?v) LIMIT 1` |
| "Tallest/highest X in region Y?" | First check if Y has `P610` (highest point) — a direct shortcut. Only use ranked aggregation if P610 doesn't exist. |
| "Highest ever / all-time record" | `?x p:P/ps:P ?v . SELECT MAX(?v)` (accesses all historical statements) |
| "Does X currently have spouse/position?" | `p:P ?stmt . ?stmt ps:P ?val . MINUS { ?stmt pq:P582 ?end }` |
| "Who is the current PM/president?" | `?x p:P39 ?s . ?s ps:P39 wd:POSITION ; pq:P580 ?start . ORDER BY DESC(?start) LIMIT 1` |
| "What is the Nth name/move/item?" | `p:P ?s . ?s pq:P1545 "N" ; ps:P ?val .` |
| "Which X in location Y?" | `?x wdt:P131+ wd:Y .` (transitive containment) |
| "Which X has highest box office in USD?" | `p:P2142 ?s . ?s psv:P2142 [wikibase:quantityAmount ?a; wikibase:quantityUnit wd:Q4917]` |
| "Movies/works featuring character X?" | Try BOTH: `?film wdt:P674 wd:X` (from film) AND `wd:X wdt:P1441 ?film` (from character) |
| "How many floors does X have?" | Sum `wdt:P1101` (above) + `wdt:P1139` (below) for total |
| "X filmed/born/located in country Y" | Compose path to country: `wdt:P915/wdt:P131*/wdt:P17? wd:Y` or `wdt:P19/wdt:P131*/wdt:P17? wd:Y` |
| "X that are NOT Y" / "X outside Z" | Use `MINUS { ... }` clause to exclude matching patterns |
| "X with style/type/food Y" (Y has subkinds) | `wdt:P_PROP/wdt:P279* wd:Y` to catch subclasses of Y |
| "X played for country Y" (sport) | Use `wdt:P1532 wd:Y` (country for sport) not team membership |
| "What parts/items are in X?" | Use outgoing `wd:X wdt:P527 ?part` (has part). Do NOT use incoming `?part wdt:P179 wd:X` (part of series) which may include extras. |
| "X made/produced by company Y" | Use `wdt:P176\|wdt:P127 wd:Y` — include both manufacturer (P176) and owned-by (P127) |
| "Sport teams → country" | Use `?team wdt:P17 ?country` (broader coverage) rather than `wdt:P1532` (country for sport, often incomplete) |
| "How many X are there?" / "How many X has Y?" | Return entity LIST (`SELECT ?x WHERE {...}`), NOT `COUNT(...)`. The evaluation expects entity QIDs. |
| "How many instances of class X?" | Count instances: `SELECT (COUNT(?x) AS ?c) WHERE { ?x wdt:P31 wd:X }` — do NOT read P1114 (quantity) from the class item |

## Troubleshooting

- **Search returns wrong entity**: Try more specific search terms, include disambiguation context (e.g., "Paris, France" not just "Paris").
- **Empty results after execution**: Most common cause is wrong property direction. Use graph exploration to verify.
- **Timeout on Wikidata endpoint**: Add LIMIT, remove subclass traversal (`P279*`), or simplify query.
- **Duplicate results**: Add DISTINCT or check if multiple statement nodes exist for the same fact.
- **Missing labels**: Do NOT use `SERVICE wikibase:label` — it causes HTTP 500 errors on this endpoint. Use `OPTIONAL { ?x rdfs:label ?xLabel FILTER(LANG(?xLabel) = "en") }` instead.
- **Pipeline loops without converging**: After 3 full retries, stop and present best attempt with explanation.
- **Property exists but no direct values**: Switch from `wdt:` to `p:/ps:` (statement-level access).
- **Over-generation (too many results)**: Check if you used subclass traversal (`P279*`) on the topic/subject side of P921. Remove it and use direct matching instead.
- **Missing results for generic categories**: Ensure you tested multiple type classes (company/business/enterprise, conference/conference series) and combined them with VALUES.
