---
name: wikidata-search
description: Wikidata search skill that resolves entity names and relation phrases to Wikidata item IDs (QIDs) and property IDs (PIDs) using the Wikidata API. Use when you need to find Wikidata identifiers for entities or properties mentioned in a natural-language question.
compatibility: Requires Python 3, uv, requests. Requires network access to the Wikidata API (wikidata.org).
---

# Wikidata Search

Use this skill to resolve entity names and relation phrases to Wikidata identifiers. This is typically the first step after parsing the user's question: converting human-readable names into machine-readable QIDs and PIDs.

## Files

- `scripts/wikidata_search.py`: standalone script for searching the Wikidata API

## When To Use This Skill

Use this skill when:
- You need to resolve an entity name (person, place, organization, concept) to a Wikidata QID
- You need to resolve a relation phrase (occupation, capital, member of) to a Wikidata PID
- You have ambiguous entities and need to see candidate descriptions to disambiguate
- You want to verify that an assumed QID/PID is correct by checking its label and description

## Requirements

Install skill dependencies from the workspace root with `uv sync`.

The script uses the `requests` library for HTTP access to the Wikidata API. No API keys required.

## Environment Variables

None required. The Wikidata API is publicly accessible.

Optional:
- `WIKIDATA_USER_AGENT`: Custom User-Agent string for API requests. Default: `"AgenticText2SPARQL/1.0 (https://github.com/ibm/agentic-text2sparql)"`.

## Safety Rules

- This skill is strictly read-only. It only queries the Wikidata search API.
- Never assume the first search result is correct — always check descriptions and entity types.
- Preserve multiple candidates when confidence is low.
- Rate-limit requests: do not send more than 5 requests per second to the Wikidata API.

## Search Modes

### 1. Entity Search (`item`)

Search for Wikidata items (entities with Q-prefixed IDs):

```bash
uv run python .agents/skills/wikidata-search/scripts/wikidata_search.py \
  --query "Albert Einstein" \
  --type item \
  --limit 5
```

### 2. Property Search (`property`)

Search for Wikidata properties (relations with P-prefixed IDs):

```bash
uv run python .agents/skills/wikidata-search/scripts/wikidata_search.py \
  --query "place of birth" \
  --type property \
  --limit 5
```

### 3. Entity Lookup by ID (`lookup`)

Retrieve details for a known QID or PID:

```bash
uv run python .agents/skills/wikidata-search/scripts/wikidata_search.py \
  --query "Q937" \
  --type lookup
```

### 4. Multi-Search (`batch`)

Search for multiple terms at once (useful for resolving all entities from a question):

```bash
uv run python .agents/skills/wikidata-search/scripts/wikidata_search.py \
  --query "Albert Einstein" "Nobel Prize in Physics" "Germany" \
  --type item \
  --limit 3
```

## Script Usage

### Arguments

Required:
- `--query` / `-q`: One or more search terms
- `--type` / `-t`: Search type (`item`, `property`, `lookup`)

Optional:
- `--limit` / `-l`: Maximum number of results per query (default: 5)
- `--language` / `--lang`: Language for labels and descriptions (default: `en`)
- `--output-file`: Write result JSON to a file instead of stdout

## Return Shape

### Item Search Result

```json
{
  "success": true,
  "query": "Albert Einstein",
  "search_type": "item",
  "result_count": 5,
  "results": [
    {
      "id": "Q937",
      "label": "Albert Einstein",
      "description": "German-born theoretical physicist (1879\u20131955)",
      "aliases": ["Einstein"],
      "url": "https://www.wikidata.org/wiki/Q937",
      "match_type": "label",
      "rank": 1
    },
    {
      "id": "Q1285776",
      "label": "Albert Einstein",
      "description": "Wikimedia disambiguation page",
      "aliases": [],
      "url": "https://www.wikidata.org/wiki/Q1285776",
      "match_type": "label",
      "rank": 2
    }
  ],
  "error": null
}
```

### Property Search Result

```json
{
  "success": true,
  "query": "place of birth",
  "search_type": "property",
  "result_count": 3,
  "results": [
    {
      "id": "P19",
      "label": "place of birth",
      "description": "most specific known birth location of a person, animal or fictional character",
      "aliases": ["birthplace", "born in", "birth city"],
      "datatype": "wikibase-item",
      "url": "https://www.wikidata.org/wiki/Property:P19",
      "match_type": "label",
      "rank": 1
    }
  ],
  "error": null
}
```

### Lookup Result

```json
{
  "success": true,
  "query": "Q937",
  "search_type": "lookup",
  "result_count": 1,
  "results": [
    {
      "id": "Q937",
      "label": "Albert Einstein",
      "description": "German-born theoretical physicist (1879\u20131955)",
      "aliases": ["Einstein", "A. Einstein"],
      "instance_of": ["Q5"],
      "instance_of_labels": ["human"],
      "url": "https://www.wikidata.org/wiki/Q937"
    }
  ],
  "error": null
}
```

## Selection Strategy

When resolving ambiguous entities, use these heuristics:

1. **Check the description**: It should match the expected entity type in the question context.
2. **Check aliases**: They may reveal the common name you're looking for.
3. **Prefer entities over disambiguation pages**: Skip results with "Wikimedia disambiguation page" descriptions.
4. **Use instance_of (P31)**: When available, check that the entity type matches expectations.
5. **Consider the question domain**: "Mercury" in an astronomy question → Q308 (planet), in a chemistry question → Q925 (element).
6. **Preserve multiple candidates**: If the top 2-3 results are plausible, keep them all for verification during graph exploration.

## Integration with text2sparql Pipeline

### Recommended Workflow

1. **Parse the question** to identify entity and relation mentions.
2. **Search for entities** (items):
   ```bash
   uv run python .agents/skills/wikidata-search/scripts/wikidata_search.py \
     --query "South America" --type item --limit 5
   ```
3. **Search for relations** (properties):
   ```bash
   uv run python .agents/skills/wikidata-search/scripts/wikidata_search.py \
     --query "capital" --type property --limit 5
   ```
4. **Disambiguate** using descriptions and the question context.
5. **Pass selected IDs** to the graph-exploration skill for verification.

### Tips

- Search for properties using multiple phrasings: "capital", "capital city", "has capital"
- For inverse relations, try both directions: "part of" vs "has part"
- If searching for a type, try both the type name and "instance of [type]"
- Use lookup mode to verify IDs found in few-shot examples still have the expected meaning

## Troubleshooting

- **Zero results**: Try synonyms, alternative spellings, simpler terms, or different language
- **Wrong entity type in results**: Add context to the search (e.g., "Paris France" instead of "Paris")
- **Property not found**: Wikidata uses specific naming — try the Wikidata property search page patterns
- **API timeout**: Retry after a brief delay; the Wikidata API occasionally has latency spikes
- **Rate limiting**: Space requests at least 200ms apart for batch operations
