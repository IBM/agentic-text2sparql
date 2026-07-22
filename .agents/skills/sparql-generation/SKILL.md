---
name: sparql-generation
description: SPARQL generation skill that constructs a SPARQL query from resolved Wikidata entities, properties, and graph paths. Use when you have verified Wikidata IDs and need to assemble them into a syntactically correct SPARQL query with proper triple patterns, filters, and aggregations.
compatibility: Requires Python 3, uv. No external API access needed for generation; validation requires requests for optional endpoint check.
---

# SPARQL Generation

Use this skill to generate SPARQL queries from resolved Wikidata entities, properties, and verified graph paths. The skill constructs syntactically correct queries using proper Wikidata modeling patterns.

## Files

- `scripts/sparql_generator.py`: standalone script for generating and validating SPARQL queries
- `references/sparql-1.1-query-features.md`: SPARQL 1.1 language reference for query forms, property paths, aggregation, subqueries, `VALUES`, `BIND`, negation, and solution modifiers
- `references/wikidata-data-model.md`: Wikidata RDF/modeling reference for `wdt:` vs `p:/ps:`, qualifiers, references, ranks, normalized values, datatype handling, and statement/value nodes

## When To Use This Skill

Use this skill when:
- You have resolved entity IDs (QIDs) and property IDs (PIDs) from wikidata-search
- You have verified graph paths from graph-exploration
- You need to assemble a SPARQL query with proper triple patterns
- You want to validate SPARQL syntax before execution
- You need to apply common Wikidata query patterns (subclass traversal, label service, qualifiers)

## Reference Usage

Consult the bundled references whenever the query requires details beyond the core patterns in this file:

- Use `references/sparql-1.1-query-features.md` when deciding which SPARQL construct to use or how to structure it correctly. Typical cases: `OPTIONAL` vs `UNION`, `FILTER NOT EXISTS` vs `MINUS`, property-path syntax, `VALUES`, `BIND`, aggregates with `GROUP BY`/`HAVING`, subqueries, `ORDER BY` with `LIMIT`, and variable-scope questions.
- Use `references/wikidata-data-model.md` when deciding which Wikidata RDF layer to query. Typical cases: choosing `wdt:` vs `p:/ps:`, accessing qualifiers with `pq:`, references with `pr:`, ranks with `wikibase:rank`, normalized quantities via `psn:`/`wikibase:quantityAmount`, datatype-specific handling, and understanding truthy versus full statement semantics.
- Prefer this `SKILL.md` for task-specific generation rules and project-specific guardrails; use the reference documents to resolve syntax/modeling uncertainty, not to replace the workflow here.

## Requirements

Install skill dependencies from the workspace root with `uv sync`.

The script uses `rdflib` for SPARQL parsing/validation (optional) and basic Python for query construction. No API keys required.

## Environment Variables

None required.

## Safety Rules

- Generate only read-only queries (SELECT, ASK, CONSTRUCT, DESCRIBE).
- Always include a LIMIT clause during iterative development (remove only for final verified queries if appropriate).
- Never generate DELETE, INSERT, or UPDATE operations.
- Use verified IDs only — never guess QIDs or PIDs.

## Script Modes

### 1. Validate SPARQL Syntax (`validate`)

Check that a SPARQL query is syntactically valid:

```bash
uv run python .agents/skills/sparql-generation/scripts/sparql_generator.py \
  --mode validate \
  --sparql "SELECT ?x WHERE { ?x wdt:P31 wd:Q5 . } LIMIT 10"
```

### 2. Generate from Template (`generate`)

Generate a SPARQL query from structured inputs:

```bash
uv run python .agents/skills/sparql-generation/scripts/sparql_generator.py \
  --mode generate \
  --question "What is the capital of France?" \
  --entities '{"France": "Q142"}' \
  --properties '{"capital": "P36"}' \
  --pattern "direct-lookup"
```

### 3. Apply Pattern (`pattern`)

Apply a named query pattern with entity/property substitution:

```bash
uv run python .agents/skills/sparql-generation/scripts/sparql_generator.py \
  --mode pattern \
  --pattern "type-filter" \
  --entities '{"type": "Q6256", "constraint_property": "P30", "constraint_value": "Q18"}' \
  --properties '{"output_property": "P36"}'
```

## Script Usage

### Arguments

Required:
- `--mode` / `-m`: Operation mode (`validate`, `generate`, `pattern`)

Mode-specific:
- `--sparql`: SPARQL query string (required for `validate`)
- `--question`: Natural-language question (for `generate` mode context)
- `--entities`: JSON object mapping entity names to QIDs
- `--properties`: JSON object mapping property names to PIDs
- `--paths`: JSON array of verified graph paths from exploration
- `--pattern`: Named pattern to use (`direct-lookup`, `reverse-lookup`, `type-filter`, `aggregation`, `qualifier`, `subclass`, `date-filter`, `top-k`)

Optional:
- `--include-labels`: Include the Wikidata label service (default: true)
- `--limit`: Add a LIMIT clause (default: none for final, 20 for exploration)
- `--output-file`: Write result JSON to a file instead of stdout

## Return Shape

### Validation Result

```json
{
  "success": true,
  "mode": "validate",
  "sparql": "SELECT ?x WHERE { ?x wdt:P31 wd:Q5 . } LIMIT 10",
  "valid": true,
  "errors": [],
  "warnings": ["No label service included — results will show URIs instead of labels"],
  "error": null
}
```

### Generation Result

```json
{
  "success": true,
  "mode": "generate",
  "question": "What is the capital of France?",
  "sparql": "SELECT ?capital ?capitalLabel WHERE {\n  wd:Q142 wdt:P36 ?capital .\n  OPTIONAL { ?capital rdfs:label ?capitalLabel FILTER(LANG(?capitalLabel) = \"en\") }\n}",
  "assumptions": [
    "France = Q142 (country)",
    "capital = P36 (capital property)",
    "Direct property lookup (wdt:) — no qualifiers needed"
  ],
  "pattern_used": "direct-lookup",
  "error": null
}
```

## Query Patterns Reference

### 1. Direct Property Lookup

```sparql
# "What is the X of Y?"
SELECT ?value ?valueLabel WHERE {
  wd:Q_ENTITY wdt:P_PROPERTY ?value .
  OPTIONAL { ?value rdfs:label ?valueLabel FILTER(LANG(?valueLabel) = "en") }
}
```

### 2. Reverse Lookup

```sparql
# "What entities have property X pointing to Y?"
SELECT ?entity ?entityLabel WHERE {
  ?entity wdt:P_PROPERTY wd:Q_TARGET .
  OPTIONAL { ?entity rdfs:label ?entityLabel FILTER(LANG(?entityLabel) = "en") }
}
```

### 3. Type Filter

```sparql
# "Which entities of type T satisfy condition C?"
SELECT ?entity ?entityLabel WHERE {
  ?entity wdt:P31 wd:Q_TYPE ;
          wdt:P_FILTER ?filterValue .
  FILTER(?filterValue > threshold)
  OPTIONAL { ?entity rdfs:label ?entityLabel FILTER(LANG(?entityLabel) = "en") }
}
```

### 4. Subclass Traversal

```sparql
# "All entities that are instances of T or any subclass of T"
SELECT ?entity ?entityLabel WHERE {
  ?entity wdt:P31/wdt:P279* wd:Q_TYPE .
  OPTIONAL { ?entity rdfs:label ?entityLabel FILTER(LANG(?entityLabel) = "en") }
}
```

### 5. Aggregation (COUNT, AVG, etc.)

```sparql
# "How many entities of type T?"
SELECT (COUNT(?entity) AS ?count) WHERE {
  ?entity wdt:P31 wd:Q_TYPE .
}
```

### 6. Top-K / Ordering

```sparql
# "Top N entities by property value"
SELECT ?entity ?entityLabel ?value WHERE {
  ?entity wdt:P31 wd:Q_TYPE ;
          wdt:P_MEASURE ?value .
  OPTIONAL { ?entity rdfs:label ?entityLabel FILTER(LANG(?entityLabel) = "en") }
}
ORDER BY DESC(?value)
LIMIT N
```

### 7. Date Filters

```sparql
# "Entities where date property is after/before a date"
SELECT ?entity ?entityLabel ?date WHERE {
  ?entity wdt:P31 wd:Q_TYPE ;
          wdt:P_DATE ?date .
  FILTER(?date >= "2000-01-01T00:00:00Z"^^xsd:dateTime)
  OPTIONAL { ?entity rdfs:label ?entityLabel FILTER(LANG(?entityLabel) = "en") }
}
```

**Important**: Always use the full ISO 8601 format with time component (`T00:00:00Z`) for `xsd:dateTime` comparisons. Bare date strings (e.g., `"2000-01-01"^^xsd:dateTime`) fail on some endpoints.

### 8. Qualifier Access

```sparql
# "What is the value of property P with qualifier Q?"
SELECT ?value ?valueLabel ?qualifier WHERE {
  wd:Q_ENTITY p:P_PROPERTY ?stmt .
  ?stmt ps:P_PROPERTY ?value ;
        pq:P_QUALIFIER ?qualifier .
  OPTIONAL { ?value rdfs:label ?valueLabel FILTER(LANG(?valueLabel) = "en") }
}
```

### 9. OPTIONAL for Non-Required Fields

```sparql
# "List entities with property X, include Y if available"
SELECT ?entity ?entityLabel ?x ?y WHERE {
  ?entity wdt:P31 wd:Q_TYPE ;
          wdt:P_X ?x .
  OPTIONAL { ?entity wdt:P_Y ?y . }
  OPTIONAL { ?entity rdfs:label ?entityLabel FILTER(LANG(?entityLabel) = "en") }
}
```

### 10. VALUES for Known Entity Sets

```sparql
# "Information about specific entities"
SELECT ?entity ?entityLabel ?value WHERE {
  VALUES ?entity { wd:Q1 wd:Q2 wd:Q3 }
  ?entity wdt:P_PROPERTY ?value .
  OPTIONAL { ?entity rdfs:label ?entityLabel FILTER(LANG(?entityLabel) = "en") }
}
```

## Generation Rules

Before finalizing a query, cross-check any non-trivial syntax against `references/sparql-1.1-query-features.md` and any statement-level or datatype-specific Wikidata modeling against `references/wikidata-data-model.md`.

1. **Use only verified IDs**: Never guess QIDs or PIDs. All IDs must come from wikidata-search or graph-exploration.
2. **Correct triple pattern direction**: Verified in graph exploration. `wd:Q wdt:P ?obj` vs `?subj wdt:P wd:Q`.
3. **Include labels using rdfs:label**: Use `OPTIONAL { ?x rdfs:label ?xLabel FILTER(LANG(?xLabel) = "en") }` for human-readable labels. NOTE: `SERVICE wikibase:label` is NOT available on the custom endpoint — it causes HTTP 500 errors. Always use `rdfs:label` OPTIONAL pattern instead. Omit labels entirely for count/aggregate-only queries.
4. **Use VALUES for known entities from the question**: When the question explicitly names a small set of entities (e.g., "information about France, Germany, and Italy"), use `VALUES ?entity { wd:Q1 wd:Q2 wd:Q3 }`. However, NEVER use VALUES to inject entities discovered from world knowledge that the endpoint didn't return — if a declarative query returns fewer results than expected, those ARE the results.
5. **Use OPTIONAL sparingly**: Only for genuinely optional fields that may not exist on all entities.
6. **Avoid Cartesian products**: Ensure all triple patterns share variables or are properly constrained.
7. **Use DISTINCT when needed**: Especially after JOINs that could produce duplicates.
8. **Bound exploration queries**: Always include LIMIT during iterative development.
9. **Use p:/ps:/pq: for qualifiers**: Switch from wdt: when qualifier access is needed.
10. **Filter placement**: Place FILTERs close to the triple patterns they constrain.
11. **Use normalized values for quantities**: When retrieving numeric quantity values (distance, mass, area, duration, speed, etc.), ALWAYS use the normalized value path `p:P.../psn:P.../wikibase:quantityAmount` instead of `wdt:P...`. This returns SI-normalized values (meters, kg, m², seconds) which are consistent regardless of how the data was entered. See "Quantity Property Patterns" below.
12. **Use full statement model for temporal/historical data**: When the question asks about historical extremes ("highest ever", "all-time record") or needs to count ALL statements including past ones (e.g., "how many spouses total"), use `p:P.../ps:P...` to access all statements. The `wdt:` prefix only returns the single "truthy" (current/best-ranked) value and misses historical data. However, for "current state" questions about **multi-valued properties** (like capitals, members, affiliations), prefer `wdt:` truthy paths which already reflect Wikidata's rank-based currentness semantics. Only switch to statement-level access when you need to explicitly inspect ALL statements (including deprecated/historical ones) or when the truthy path demonstrably misses data that should be there.
13. **Return entity IDs for item-valued properties**: When a Wikidata property has datatype `wikibase-item` (e.g., P735 "given name", P3150 "birthday", P1441 "present in work"), the query must return the entity QID, not a label string. Check the property datatype during graph exploration.
14. **Use transitive P131+ for location containment**: When filtering by geographic location, use `wdt:P131+ wd:Q_location` (transitive) instead of direct `wdt:P131 wd:Q_location`. Items may be in sub-administrative units (suburbs, districts) that are contained within the target location.
15. **Compose property paths for country-level location queries**: When the question asks about items "in country X" but the linking property points to a specific location (city, region), compose the path to reach the country level. Common patterns:
    - Filming location to country: `wdt:P915/wdt:P131*/wdt:P17?`
    - Birthplace to country: `wdt:P19/wdt:P131*/wdt:P17?`
    - General location to continent: `wdt:P276?/wdt:P131*/wdt:P17?/wdt:P30`
    - Instance location to country: `wdt:P131*/wdt:P17`
    - Organization country (multiple paths): `(wdt:P17|wdt:P159/wdt:P17|wdt:P495)` — organizations may have country via direct P17, headquarters location (P159→P17), or country of origin (P495)
    
    The `?` on P17 handles cases where the item already IS a country. Always verify via exploration which intermediate steps are needed.
16. **Only include constraints stated in the question**: Do not add plausibility filters, unit restrictions, or scope constraints that are not explicitly mentioned or directly required by the question. For example:
    - Do not add `FILTER(?height < 3)` or restrict planets to the solar system unless the question says so
    - Do not add `MINUS { ?x wdt:P576 ?dissolved }` (exclude dissolved entities) unless the question says "currently existing"
    - Do not add `FILTER(?x != wd:Q_ENTITY)` self-exclusion unless the question logically requires it (e.g., "not bordering Germany" does NOT exclude Germany itself — Germany doesn't border itself)
    - Do not add extra type constraints that the question didn't mention
17. **Filter by unit for monetary comparisons**: When comparing monetary values (box office, GDP, budget), always filter for a common currency unit using `wikibase:quantityUnit` to ensure like-for-like comparison. Use `psv:` to access the value node with its unit.
18. **Exclude ended relationships for current-state questions**: For questions about current status ("Does X have a wife?", "Who is the current PM?"), add `MINUS { ?stmt pq:P582 ?endDate }` to exclude relationships that have ended.
19. **Sum related sub-properties for total measurements**: When a question asks for a total measurement (e.g., "how many floors", "total length", "overall height") and the entity has complementary sub-properties (e.g., P1101 "floors above ground" + P1139 "floors below ground"), sum them to get the total. Use `BIND(?a + ?b AS ?total)` or arithmetic in SELECT.
20. **Prefer returning entities over counts**: When a question asks "how many X?" or "how many X satisfy Y?", the expected output is almost always the **list of matching entity QIDs**, NOT a numeric count. Use `SELECT ?x WHERE { ... }` to return the entities themselves. Only use `SELECT (COUNT(...) AS ?count)` when the expected answer is clearly a large number (>50) and entities themselves aren't meaningful to list. **Important**: "How many movies has X directed?" → return the list of movie QIDs. "How many countries are there?" → return the list of country QIDs.
21. **SELECT only the answer column**: When the query uses ORDER BY on a value column (e.g., population, date), only SELECT the entity variable, not the ordering column. Including extra columns in SELECT may leak numeric/date values into the final answer. For example, `SELECT ?country WHERE { ... ORDER BY DESC(?pop) }` is correct; `SELECT ?country ?pop WHERE { ... }` would return the population value alongside the entity.
22. **Match the question's scope exactly**: Use exactly the relationships stated in the question. If the question says "Latin American country", map to the specific Wikidata relationship for "Latin America" (e.g., `P361 Q12585`). Do not broaden to "South American continent" or similar approximations. Stick to the most direct relationship matching the question's phrasing.
23. **Consider subclass traversal on property values (conditionally)**: When matching property values against a general class (e.g., architectural style = brutalism, food = pizza, event = theft), the actual value on the entity may be a more specific subclass. Use `wdt:P_PROP/wdt:P279*` to also match subclasses of the target value. This is relevant for properties like:
    - Architectural style (P149): `wdt:P149/wdt:P279* wd:Q_STYLE`
    - Significant event (P793): `ps:P793/wdt:P279* wd:Q_EVENT_TYPE`
    - Last meal (P3902): `wdt:P3902/wdt:P279* wd:Q_FOOD`
    - Taxon parent (P171): use `wdt:P171+` for transitive traversal
    
    **Guardrails — do NOT apply subclass traversal when:**
    - The question is a boolean/ASK query checking for an exact value (e.g., "is there a flag with pink?" → use exact `wdt:P462 wd:Q429220`, not `P279*`)
    - The property is `P106` (occupation) — Wikidata editors assign specific occupations directly; use direct matching first
    - The initial direct query already returns a reasonable number of results (>5 for a list question)
    - The property is `P1412` (languages spoken), `P27` (citizenship), or other simple-valued properties where subclass semantics don't apply
24. **Query through instances, not class items**: When a question asks about members of a class ("paintings of X", "countries where Y are found", "collections with Z"), query through individual instances using `?x wdt:P31/wdt:P279* wd:Q_CLASS`, then access properties on those instances. Do NOT rely on properties of the class item itself (e.g., do not query `wd:Q_CLASS wdt:P17 ?country`), as class-level data is typically incomplete.
25. **Commit to one property direction**: Once exploration verifies the correct property direction, use only that direction. Do NOT hedge by adding a UNION with the inverse property. Example: if P1376 (capital of) is the verified direction, do not UNION with `?x wdt:P36 wd:Q_CITY`. Forward and inverse properties often have different coverage and adding both produces false positives.

### Rules for Mention-Provided Entities

- **Rule: Verify class suitability** — Before using a mention entity in `wdt:P31 wd:Q_entity`, run a quick count. If it returns 0 results, the entity may be a concept/movement rather than a type. Search for the correct classifying entity.

- **Rule: Check for combined/intermediate classes** — When the question combines two concepts (e.g., "NP-complete video games"), prefer using a single intermediate class (`wdt:P31 wd:Q_combined_class`) over intersecting two separate type constraints. Intermediate classes are more complete in Wikidata.

- **Rule: Don't assume mention properties are the linking property** — When a mention has a `property` field, it may indicate the property's role in the question semantics, not necessarily the exact triple pattern to use. Always verify through graph exploration.

## Common Mistakes to Avoid

| Mistake | Fix |
|---------|-----|
| Using `wdt:P31 wd:Q5` for subclasses | Use `wdt:P31/wdt:P279* wd:Q5` for subclass inclusion |
| Using `wdt:P106/wdt:P279*` for occupations | Prefer direct `wdt:P106 wd:Q_OCCUPATION` first — subclass traversal on occupation over-generates. Only add `/wdt:P279*` if the direct query returns < 3 results for a broad category |
| Missing label service | Use `OPTIONAL { ?x rdfs:label ?xLabel FILTER(LANG(?xLabel) = "en") }` (not SERVICE wikibase:label which is unavailable) |
| Wrong property direction | Verify with graph exploration before generating |
| Unbounded `P279*` traversal | Add LIMIT or restrict depth |
| Filtering on labels instead of IDs | Use `wd:QID` not `FILTER(CONTAINS(?label, "..."))` |
| Missing DISTINCT with multiple optional patterns | Add DISTINCT to SELECT |
| Using `FILTER(?x = wd:Q...)` instead of direct triple | Use `wd:Q... wdt:P ?y` directly |
| Qualifying objects in SELECT without GROUP BY | Use aggregate functions or remove from SELECT |
| Using `wdt:` for quantity values | Use `p:P.../psn:P.../wikibase:quantityAmount` for normalized SI values |
| Using `wdt:` for historical maximums | Use `p:P.../ps:P...` to access all historical statements |
| Returning label strings for item-valued properties | Return the entity QID (e.g., `?givenName` as QID, not its label) |
| Using direct `wdt:P131` for location queries | Use `wdt:P131+` (transitive) to include sub-divisions |
| Adding plausibility filters not in the question | Do not add `FILTER(?x < 3)` or restrict to solar system unless asked |
| Comparing monetary values without unit filter | Use `psv:` + `wikibase:quantityUnit` to filter for same currency |
| Using `wdt:P26` for "currently married" | Use `p:P26` + `MINUS { ?stmt pq:P582 ?end }` to exclude ex-spouses |
| Using only P1101 for "total floors" | Sum P1101 (above ground) + P1139 (below ground) for total |
| Returning COUNT when entities are expected | Return entity list; only use COUNT for explicitly numeric questions with large result sets |
| Returning entity list when COUNT is expected | For "How many X?" questions, use `SELECT (COUNT(DISTINCT ?x) AS ?count)`. But first check if the parent entity has a direct quantity property (e.g., P1114, P1538, P1539) that stores the count — if it exists, use it directly as it's more authoritative than counting instances. |
| Using `wdt:` for "current" position when qualifier is needed | For "Who IS the current X?" (present tense), `wdt:` truthy value reflects the best-ranked statement which is usually current. But for positions with multiple holders over time (presidents, chairpersons), verify by checking: if `wdt:P_position` returns multiple values, switch to `p:P39/ps:P39` with `MINUS { ?stmt pq:P582 ?end }` to get only active (non-ended) holders. |
| Broadening scope beyond what the question states | "Latin American" = P361 Q12585; don't expand to "South American continent" |
| Using `wdt:P921/wdt:P279*` (subclass traversal on topic) | This massively over-generates because it returns items whose topic is ANY subclass of the target concept. Prefer direct `wdt:P921 wd:Q_TOPIC` unless there is explicit evidence that topic subclass traversal is needed. Only use `P279*` on the **entity type** side, not the topic/subject side. |
| Hedging with UNION of forward + inverse property | Choose ONE direction after verification. `P1376` and `P36` are NOT interchangeable — one may cover more entities. |
| Using `wdt:P_PROP wd:Q_VALUE` when values may be subclasses | Consider `wdt:P_PROP/wdt:P279* wd:Q_VALUE` for style/event/food properties — but NOT for occupation, language, citizenship, or boolean/ASK queries (see Rule 23 guardrails) |
| Querying properties on the class item directly | Query through instances: `?x wdt:P31/wdt:P279* wd:Q_CLASS . ?x wdt:P_PROP ?value` — not `wd:Q_CLASS wdt:P_PROP ?value` |
| Replacing a declarative query with hardcoded VALUES | Never inject world knowledge as VALUES. If the endpoint returns few results, that IS the answer. |
| Using only one location property for country-level queries | Compose paths: `P915/P131*/P17?` for filming locations, `P19/P131*/P17?` for birthplaces |
| Using `P179` (part of series) for "what parts does X have?" | Use outgoing `wd:X wdt:P527 ?part` (has part) instead — P179 incoming may include unauthorized additions |
| Using only P176 for "made by" questions | Include `P176\|P127` (manufacturer OR owned by) for broader coverage |
| Using COUNT when entities are expected | Return `SELECT ?x WHERE {...}` (entity list), not `SELECT (COUNT(?x) AS ?c)` — evaluation expects QIDs |
| Reading P1114 (quantity) for "how many instances?" | Count instances: `SELECT (COUNT(?x)) WHERE { ?x wdt:P31 wd:Q_CLASS }` — P1114 on the class is often wrong/outdated |
| Using P1532 for team→country mapping | Prefer `wdt:P17` which has broader coverage on sports team entities |
| Returning ALL predecessors for "before X" when person held office multiple times | When X held a position multiple non-consecutive times (e.g., Trump as president twice), "before X" means predecessor of the FIRST term. Use `ORDER BY ?startDate LIMIT 1` on the P39 statements to get only the earliest term, then extract P1365 (replaces) from that statement. |
| Using P31 with a mentioned entity for "brands of X" | Mentions may provide a product class (Q431289 "smartphone model") but brands are not typed as product instances. Instead search for companies (`P31 Q4830453/Q783794`) that manufacture (`P176^` or `P1056`) the product type, or check if Wikidata has a "brand" class for the domain. |
| Using MINUS on all properties for "solely as X" | `MINUS { ?item ?anyProp wd:Q_person . FILTER(?anyProp != wdt:P_role) }` is too aggressive — it removes items where the person appears in metadata properties (P1040 editor, P162 producer). For "solely as director", exclude only competing CREDIT roles: `MINUS { ?film wdt:P58 wd:Q_person }` (screenwriter) and `MINUS { ?film wdt:P162 wd:Q_person }` (producer). Or count roles: `FILTER NOT EXISTS { ?film ?creditRole wd:Q_person . FILTER(?creditRole IN (wdt:P58, wdt:P162, wdt:P1431)) }` |

## Quantity Property Patterns

When a question asks for a numeric measurement (distance, mass, area, duration, speed, height, etc.), **always use the normalized value path**. This ensures consistent SI units regardless of how the data was originally entered.

### Pattern: Retrieve a normalized quantity value

```sparql
# "How far is X from Earth?" / "What is the area of X?" / "How heavy is X?"
SELECT ?value WHERE {
  wd:Q_ENTITY p:P_QUANTITY/psn:P_QUANTITY/wikibase:quantityAmount ?value .
}
```

Examples:
- Distance from Earth (P2583): `p:P2583/psn:P2583/wikibase:quantityAmount` → meters
- Duration (P2047): `p:P2047/psn:P2047/wikibase:quantityAmount` → seconds
- Mass (P2067): `p:P2067/psn:P2067/wikibase:quantityAmount` → kilograms
- Area (P2046): `p:P2046/psn:P2046/wikibase:quantityAmount` → square meters
- Height (P2048): `p:P2048/psn:P2048/wikibase:quantityAmount` → meters
- Speed (P2052): `p:P2052/psn:P2052/wikibase:quantityAmount` → meters per second
- Wheelbase (P3039): `p:P3039/psn:P3039/wikibase:quantityAmount` → meters
- Course length (P3157): `p:P3157/psn:P3157/wikibase:quantityAmount` → meters

### Pattern: Top-K by quantity with normalization

```sparql
# "What is the tallest/fastest/heaviest X?"
SELECT ?entity WHERE {
  ?entity wdt:P31/wdt:P279* wd:Q_TYPE .
  ?entity p:P_QUANTITY/psn:P_QUANTITY/wikibase:quantityAmount ?value .
}
ORDER BY DESC(?value)
LIMIT 1
```

### Pattern: Monetary comparison with unit filter

```sparql
# "Which X has the highest box office (in USD)?"
SELECT ?entity WHERE {
  ?entity wdt:P31/wdt:P279* wd:Q_TYPE .
  ?entity p:P2142 ?stmt .
  ?stmt psv:P2142 ?valueNode .
  ?valueNode wikibase:quantityAmount ?amount ;
             wikibase:quantityUnit wd:Q4917 .  # Q4917 = US dollar
}
ORDER BY DESC(?amount)
LIMIT 1
```

## Temporal and Historical Patterns

### Pattern: Historical maximum (all-time best)

```sparql
# "What is the highest Elo rating ever?" — need ALL statements, not just current
SELECT (MAX(?value) AS ?max) WHERE {
  ?entity p:P1087/ps:P1087 ?value .
}
```

### Pattern: Current position holder (most recent start date)

```sparql
# "Who is the current PM of X?" — use position held with temporal ordering
SELECT ?person WHERE {
  ?person p:P39 ?stmt .
  ?stmt ps:P39 wd:Q_POSITION .
  ?stmt pq:P580 ?startDate .
}
ORDER BY DESC(?startDate)
LIMIT 1
```

### Pattern: Current relationship (exclude ended)

```sparql
# "Does X currently have a spouse?"
ASK WHERE {
  wd:Q_PERSON p:P26 ?stmt .
  ?stmt ps:P26 ?spouse .
  MINUS { ?stmt pq:P582 ?endDate }
}
```

### Pattern: Summing complementary sub-properties

```sparql
# "How many floors does building X have?" (total = above + below ground)
SELECT (?above + ?below AS ?totalFloors) WHERE {
  wd:Q_BUILDING wdt:P1101 ?above ;
                wdt:P1139 ?below .
}
```

Other examples of complementary properties that may need summing:
- P1101 (floors above ground) + P1139 (floors below ground) = total floors
- Multiple distance/length components when asking for "total"

### Pattern: Ordinal qualifier access

```sparql
# "What is the Nth item in sequence X?"
SELECT ?value WHERE {
  wd:Q_ENTITY p:P_PROPERTY ?stmt .
  ?stmt pq:P1545 "N" .   # series ordinal
  ?stmt ps:P_PROPERTY ?value .
}
```

## Integration with text2sparql Pipeline

### Input from Previous Steps

The generation step receives:
- **From wikidata-search**: Resolved QIDs and PIDs with labels
- **From graph-exploration**: Verified paths, directions, qualifier structures

### Output to Next Step

The generated SPARQL is passed to sparql-execution for execution and validation.

## Troubleshooting

- **Syntax errors from validator**: Check bracket matching, semicolons between triple patterns, and proper string escaping.
- **Unsure which SPARQL feature to use**: Check `references/sparql-1.1-query-features.md` before improvising syntax for negation, aggregation, property paths, subqueries, or inline bindings.
- **Unsure which Wikidata prefix/model to use**: Check `references/wikidata-data-model.md` before choosing between `wdt:`, `p:/ps:`, `pq:`, `psv:`, `psn:`, or rank/reference access.
- **Wrong results direction**: Swap subject/object positions and re-run.
- **No results with subclass traversal**: Try without `P279*` first to isolate the issue.
- **Label service not working**: Do NOT use `SERVICE wikibase:label` — it causes HTTP 500 errors on the custom endpoint. Use `OPTIONAL { ?x rdfs:label ?xLabel FILTER(LANG(?xLabel) = "en") }` instead.
- **Timeout during generation**: The generation script itself should be fast; if it's slow, it's likely a validation step querying the endpoint.
