---
name: graph-exploration
description: Graph exploration skill that inspects the Wikidata knowledge graph around seed entities using small diagnostic SPARQL queries. Use to verify property directions, discover graph paths, inspect qualifiers, and build evidence for the final query structure.
compatibility: Requires Python 3, uv, requests. Requires network access to the SPARQL endpoint (configurable via WIKIDATA_SPARQL_ENDPOINT env var).
---

# Graph Exploration

Use this skill to explore the Wikidata graph around seed entities and candidate properties. This skill runs small, bounded SPARQL queries to progressively build evidence for the graph pattern required by the final query.

## Files

- `scripts/graph_explorer.py`: standalone script for exploring the Wikidata graph

## When To Use This Skill

Use this skill when:
- You need to verify that a property connects two entities in the expected direction
- You need to discover which properties an entity has
- You need to check whether a direct property (wdt:) or statement node (p:/ps:/pq:) is needed
- You need to find the correct graph path between two entities
- You need to inspect qualifiers on a statement
- You need to verify instance_of / subclass_of patterns for type filtering

## Requirements

Install skill dependencies from the workspace root with `uv sync`.

The script uses the `requests` library to send SPARQL queries to the Wikidata Query Service. No API keys required.

## Environment Variables

None required. The Wikidata SPARQL endpoint is publicly accessible.

Optional:
- `WIKIDATA_SPARQL_ENDPOINT`: Override the SPARQL endpoint URL. Default: `https://wikikgqa.skynet.coypu.org/wikidata`.
- `WIKIDATA_USER_AGENT`: Custom User-Agent string. Default: `"AgenticText2SPARQL/1.0"`.

## Safety Rules

- All queries are read-only (SELECT/ASK only).
- All exploration queries MUST include a LIMIT clause (max 50 results) to avoid overloading the endpoint.
- Never run unbounded subclass traversals without a LIMIT.
- Space requests at least 1 second apart to respect Wikidata rate limits.
- If a query times out, simplify it rather than retrying the same query.

## Exploration Modes

### 1. Outgoing Properties (`outgoing`)

List all properties and sample values going out from an entity:

```bash
uv run python .agents/skills/graph-exploration/scripts/graph_explorer.py \
  --entity "Q937" \
  --mode outgoing \
  --limit 20
```

Returns: properties (PIDs + labels) used as predicates where the entity is the subject, with sample object values.

### 2. Incoming Properties (`incoming`)

List entities that point to the given entity via a specific property (or all properties):

```bash
uv run python .agents/skills/graph-exploration/scripts/graph_explorer.py \
  --entity "Q937" \
  --mode incoming \
  --limit 20
```

```bash
uv run python .agents/skills/graph-exploration/scripts/graph_explorer.py \
  --entity "Q937" \
  --mode incoming \
  --property "P19" \
  --limit 10
```

Returns: entities that have the given entity as an object value (reverse relations).

### 3. Check Property (`check-property`)

Verify whether a specific property connects an entity to anything:

```bash
uv run python .agents/skills/graph-exploration/scripts/graph_explorer.py \
  --entity "Q937" \
  --mode check-property \
  --property "P19"
```

Returns: whether the property exists on the entity, its value(s), and direction confirmation.

### 4. Type Hierarchy (`types`)

Inspect instance_of and subclass_of chains:

```bash
uv run python .agents/skills/graph-exploration/scripts/graph_explorer.py \
  --entity "Q937" \
  --mode types
```

Returns: instance_of values, and for classes, their subclass_of chain.

### 5. Statement Details (`statement`)

Inspect the full statement node including qualifiers:

```bash
uv run python .agents/skills/graph-exploration/scripts/graph_explorer.py \
  --entity "Q937" \
  --mode statement \
  --property "P69"
```

Returns: statement nodes with main values and all qualifiers (start time, end time, etc.).

### 6. Path Discovery (`path`)

Find how two entities are connected:

```bash
uv run python .agents/skills/graph-exploration/scripts/graph_explorer.py \
  --entity "Q937" \
  --mode path \
  --target "Q243"
```

Returns: properties that connect the two entities directly or through one intermediate node.

### 7. Custom Query (`custom`)

Run an arbitrary bounded SPARQL query for exploration:

```bash
uv run python .agents/skills/graph-exploration/scripts/graph_explorer.py \
  --mode custom \
  --sparql "SELECT ?p ?pLabel ?o ?oLabel WHERE { wd:Q937 ?p ?o . OPTIONAL { ?p rdfs:label ?pLabel FILTER(LANG(?pLabel) = 'en') } OPTIONAL { ?o rdfs:label ?oLabel FILTER(LANG(?oLabel) = 'en') } } LIMIT 10"
```

## Script Usage

### Arguments

Required:
- `--mode` / `-m`: Exploration mode (`outgoing`, `incoming`, `check-property`, `types`, `statement`, `path`, `custom`)

Mode-specific:
- `--entity` / `-e`: Wikidata entity ID (e.g., `Q937`) — required for all modes except `custom`
- `--property` / `-p`: Wikidata property ID (e.g., `P19`) — required for `check-property` and `statement` modes
- `--target`: Target entity ID — required for `path` mode
- `--sparql`: SPARQL query string — required for `custom` mode

Optional:
- `--limit` / `-l`: Maximum results (default: 20, max: 50)
- `--output-file`: Write result JSON to a file instead of stdout

## Return Shape

### Outgoing Properties Result

```json
{
  "success": true,
  "entity": "Q937",
  "entity_label": "Albert Einstein",
  "mode": "outgoing",
  "result_count": 20,
  "results": [
    {
      "property": "P19",
      "property_label": "place of birth",
      "value": "Q3012",
      "value_label": "Ulm",
      "value_type": "wikibase-item"
    },
    {
      "property": "P569",
      "property_label": "date of birth",
      "value": "1879-03-14T00:00:00Z",
      "value_label": "14 March 1879",
      "value_type": "time"
    }
  ],
  "error": null
}
```

### Check Property Result

```json
{
  "success": true,
  "entity": "Q937",
  "entity_label": "Albert Einstein",
  "mode": "check-property",
  "property": "P19",
  "property_label": "place of birth",
  "exists": true,
  "direction": "outgoing",
  "values": [
    {
      "value": "Q3012",
      "value_label": "Ulm"
    }
  ],
  "error": null
}
```

### Statement Details Result

```json
{
  "success": true,
  "entity": "Q937",
  "entity_label": "Albert Einstein",
  "mode": "statement",
  "property": "P69",
  "property_label": "educated at",
  "result_count": 3,
  "results": [
    {
      "statement_id": "Q937$some-guid",
      "main_value": "Q11942",
      "main_value_label": "ETH Zurich",
      "qualifiers": [
        {
          "property": "P580",
          "property_label": "start time",
          "value": "1896-01-01T00:00:00Z"
        },
        {
          "property": "P582",
          "property_label": "end time",
          "value": "1900-01-01T00:00:00Z"
        },
        {
          "property": "P512",
          "property_label": "academic degree",
          "value": "Q752297",
          "value_label": "diploma"
        }
      ]
    }
  ],
  "error": null
}
```

## Wikidata Prefixes Reference

| Prefix | URI | Use |
|--------|-----|-----|
| `wd:` | `http://www.wikidata.org/entity/` | Entity references (Q-items, P-properties) |
| `wdt:` | `http://www.wikidata.org/prop/direct/` | Direct truthy statements (most common) |
| `p:` | `http://www.wikidata.org/prop/` | Statement nodes |
| `ps:` | `http://www.wikidata.org/prop/statement/` | Main value on a statement node |
| `pq:` | `http://www.wikidata.org/prop/qualifier/` | Qualifier values on a statement node |
| `wikibase:` | `http://wikiba.se/ontology#` | Wikibase ontology (label service, etc.) |
| `bd:` | `http://www.bigdata.com/rdf#` | BigData extensions (service params) |

### When to use `wdt:` vs `p:/ps:/pq:`

- **Use `wdt:`** (direct) for simple facts: `wd:Q937 wdt:P19 ?birthplace`
- **Use `p:/ps:/pq:`** when you need qualifiers:
  ```sparql
  wd:Q937 p:P69 ?stmt .
  ?stmt ps:P69 ?school ;
        pq:P580 ?startDate .
  ```

## Integration with text2sparql Pipeline

### Recommended Workflow

After wikidata-search has identified candidate IDs:

1. **Verify entity types:**
   ```bash
   uv run python .agents/skills/graph-exploration/scripts/graph_explorer.py \
     --entity "Q937" --mode types
   ```

2. **Check property existence and direction:**
   ```bash
   uv run python .agents/skills/graph-exploration/scripts/graph_explorer.py \
     --entity "Q937" --mode check-property --property "P19"
   ```

3. **Explore outgoing if property is unknown:**
   ```bash
   uv run python .agents/skills/graph-exploration/scripts/graph_explorer.py \
     --entity "Q937" --mode outgoing --limit 30
   ```

4. **Inspect qualifiers if needed:**
   ```bash
   uv run python .agents/skills/graph-exploration/scripts/graph_explorer.py \
     --entity "Q937" --mode statement --property "P69"
   ```

5. **Find path between entities:**
   ```bash
   uv run python .agents/skills/graph-exploration/scripts/graph_explorer.py \
     --entity "Q937" --mode path --target "Q243"
   ```

### Decision Tree

```
Is the relationship between entities clear and well-known?
├── YES → Skip exploration, go directly to SPARQL generation
└── NO → Explore
         ├── Do you know the property?
         │   ├── YES → Use check-property mode
         │   └── NO → Use outgoing mode on subject entity
         ├── Is the direction (subject→object) confirmed?
         │   ├── YES → Proceed to generation
         │   └── NO → Try BOTH directions (outgoing + incoming) to see which has data
         ├── Are qualifiers needed?
         │   ├── YES → Use statement mode to see qualifiers (P580, P582, P1545, etc.)
         │   └── NO → Use wdt: in generation
         ├── Is the property a quantity (distance, mass, area, speed)?
         │   └── YES → Check if psn: (normalized value) is available via statement mode
         └── Does the question ask about "current" state or "all-time" history?
             ├── CURRENT → Need MINUS { pq:P582 ?end } to exclude ended statements
             └── ALL-TIME → Need p:/ps: to access all historical values, not just wdt: truthy
```

### Key Exploration Principles

1. **Always verify property direction**: When a property could go either way (e.g., P674 "characters" vs P1441 "present in work of fiction"), check BOTH the subject's outgoing properties AND the object's outgoing properties. Use the direction that actually returns data.

   **Important**: Many relationships in Wikidata are modeled from both sides. For example, "character in a film" can be expressed as:
   - From the film: `?film wdt:P674 ?character` (film has character)
   - From the character: `?character wdt:P1441 ?film` (character present in work)
   
   Always try both directions and use whichever returns results from the endpoint. If both return results, use the one that gives the most complete answer (more results).

2. **Note the property datatype**: The value type matters for SPARQL generation:
   - `wikibase-item` → return the QID, not a label
   - `quantity` → use `psn:` for normalized SI values
   - `time` → may need date arithmetic or FILTER
   - `string` → direct literal comparison

3. **Check for qualifier structure**: If the question involves ordering ("most recent", "2nd", "current"), use `statement` mode to see what qualifiers exist (P580 start time, P582 end time, P1545 series ordinal, P585 point in time).

4. **Verify membership/containment relationships**: When the question mentions a group/category (e.g., "Latin American countries"), check which specific property links entities to that group. Use `incoming` mode on the group entity to see exactly which items are linked and via which property. Do not approximate with broader relationships (e.g., do not use "continent = South America" when the question says "Latin America").

## Handling Pre-resolved Mentions

When entity/property mentions are provided as input, use these additional exploration strategies:

### Discovering Intermediate Classes

When mentions provide two concepts that should be combined (e.g., "video games" Q7889 + "NP-complete" Q180074), check if Wikidata has a combined class:

```bash
# Check if there's an intermediate class combining both concepts
uv run python .agents/skills/graph-exploration/scripts/graph_explorer.py \
  --entity Q7889 --mode subclasses --limit 50
```

Look for subclasses that incorporate the second concept (e.g., Q21055677 "NP-complete problem in video games"). Using such intermediate classes with `wdt:P31 wd:Q_combined` is often more complete than intersecting two separate constraints.

### Verifying Concept vs. Class Entities

When a mention maps to a broad concept or movement (e.g., "open source" → Q39162), verify whether it's the right entity for a P31/P279 query:

1. Check what `wdt:P31 wd:Q_mentioned` actually returns — if zero results or irrelevant results, the entity may be a concept/movement rather than a classifying type
2. Search for a more specific class: e.g., "open-source software" (Q1130645) instead of "open source" (Q39162)
3. Check the entity's description and P31 to understand its nature

### Discovering Missing Linking Properties

When mentions provide entities but no linking property (e.g., "flags" Q186516 and "pink" Q429220 but no property connecting them):

1. Explore outgoing properties of the subject entity to find which property connects to the object
2. Try common linking properties: P462 (color), P180 (depicts), P527 (has parts), P921 (main subject)
3. Run a diagnostic query: `SELECT ?p WHERE { wd:Q_subject ?p wd:Q_object } LIMIT 10`

## Troubleshooting

- **Timeout on outgoing properties**: Some entities have hundreds of properties. Use --limit and consider filtering by property type.
- **Property exists but shows no values**: The property may use deprecated/non-truthy ranks. Try statement mode.
- **Path discovery returns nothing**: The entities may be connected through more than one intermediate node, or through a different property than expected.
- **Unexpected value types**: Wikidata stores some values as quantity nodes, time nodes, or coordinate nodes rather than simple literals.
- **Too many incoming results**: Add a type constraint or use check-property instead of full incoming scan.
