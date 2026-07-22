---
name: few-shot-examples
description: Few-shot examples skill that provides reusable examples of common Wikidata SPARQL patterns. Use before generating SPARQL to find relevant examples that demonstrate how similar questions have been answered, covering patterns like direct lookups, reverse relations, subclass traversal, qualifiers, and aggregations.
compatibility: Requires Python 3, uv. No external API access needed (examples are stored locally as JSON).
---

# Few-Shot Examples

Use this skill to retrieve relevant Text-to-SPARQL examples that demonstrate common Wikidata query patterns. The examples are selected based on structural similarity to the current question, helping guide the SPARQL generation step.

## Files

- `examples/patterns.json`: collection of curated examples organized by query pattern
- `scripts/retrieve_examples.py`: retrieves similar gold-standard examples from ChromaDB
- `scripts/build_examples_db.py`: builds the ChromaDB collection (run once during setup)
- `data/examples_db/`: ChromaDB persistent storage with 417 indexed gold examples

## Dynamic Example Retrieval (Recommended)

**Always use this before generating SPARQL.** Retrieves the most similar gold-standard examples from 417 indexed train/dev questions with their correct SPARQL queries.

```bash
# Basic retrieval (top 5 similar examples)
uv run python .agents/skills/few-shot-examples/scripts/retrieve_examples.py \
  --query "How far is Alpha Centauri from Earth?" \
  --top-k 5
```

**Output:** JSON with similar questions and their gold SPARQL, showing correct patterns to follow.

### Key Usage Patterns

```bash
# For measurement/distance questions - look at how psn: is used
uv run python .agents/skills/few-shot-examples/scripts/retrieve_examples.py \
  --query "What is the area of Texas?" --top-k 3

# For superlative questions - look at ORDER BY + LIMIT patterns
uv run python .agents/skills/few-shot-examples/scripts/retrieve_examples.py \
  --query "Which country has the most official languages?" --top-k 3

# For boolean questions - look at ASK patterns
uv run python .agents/skills/few-shot-examples/scripts/retrieve_examples.py \
  --query "Is Turkey located on the Dead Sea?" --top-k 3

# For temporal/current-state questions
uv run python .agents/skills/few-shot-examples/scripts/retrieve_examples.py \
  --query "Does Elon Musk have a wife?" --top-k 3
```

### When to Use Dynamic Retrieval

Use few-shot retrieval **conditionally** — only for complex patterns or after failures. Do NOT retrieve examples for simple questions you can already answer confidently.

**RETRIEVE examples for:**
- Questions involving physical measurements, distances, areas, durations (need `psn:` patterns)
- Superlative questions with complex aggregation ("tallest", "most", requiring ORDER BY + subclass traversal)
- Questions about current state vs. historical ("is X married NOW?", "highest Elo EVER")
- Complex qualifier patterns (ordinals, contest winners, temporal scoping)
- **After a query failure** — this is the best time to retrieve examples for repair guidance

**DO NOT retrieve examples for:**
- Simple entity property lookups ("What is the capital of X?", "Who wrote Y?")
- Direct boolean checks ("Is X alive?", "Does X have a president?")
- Straightforward P31/type queries where the pattern is obvious
- Questions where you already have high confidence in the SPARQL structure

**Why conditional?** Retrieving examples for simple questions can introduce unnecessary complexity — the agent may adopt complex patterns (subclass traversal, qualifiers) from retrieved examples when a simple `wdt:` lookup would be correct.

## When To Use This Skill

Use this skill when:
- You are about to generate SPARQL and want to ground the generation with similar examples
- The question involves complex patterns (qualifiers, subclass traversal, aggregation)
- You need to see how a particular Wikidata modeling pattern is expressed in SPARQL
- A previous generation attempt failed and you want to see correct patterns

## Important: Label Service Not Available

The custom SPARQL endpoint (`wikikgqa.skynet.coypu.org`) does **NOT** support `SERVICE wikibase:label`. Using it will cause HTTP 500 errors. Instead, use:
```sparql
OPTIONAL { ?entity rdfs:label ?entityLabel FILTER(LANG(?entityLabel) = "en") }
```

## Pattern Categories

### 0. Common Pitfall Patterns (Important)

These patterns address frequently incorrect queries:

**"Who was X before Y?" (predecessor with non-consecutive terms):**
```sparql
# WRONG: Gets all predecessors if Y held position multiple times
SELECT ?pred WHERE { wd:Q_PERSON p:P39 ?stmt . ?stmt ps:P39 wd:Q_POSITION . ?stmt pq:P1365 ?pred . }

# CORRECT: Get predecessor of FIRST term only
SELECT ?pred WHERE {
  wd:Q_PERSON p:P39 ?stmt .
  ?stmt ps:P39 wd:Q_POSITION ;
        pq:P1365 ?pred ;
        pq:P580 ?start .
} ORDER BY ?start LIMIT 1
```

**"Which brands of type X are from country Y?" (brands vs products):**
```sparql
# WRONG: Brands are not typed as product instances
SELECT ?brand WHERE { ?brand wdt:P31 wd:Q_PRODUCT_CLASS ; wdt:P495 wd:Q_COUNTRY . }

# CORRECT: Find brands/companies that manufacture products of that type
SELECT ?brand WHERE {
  ?brand wdt:P31/wdt:P279* wd:Q431289 .  # or use the brand/company class
  ?brand wdt:P176?/wdt:P17 wd:Q_COUNTRY .
}
# OR: Search for the correct brand class during exploration
```

**"Films where X is solely the director" (exclusivity constraint):**
```sparql
# WRONG: Removes films where person appears in ANY property (too aggressive)
SELECT ?film WHERE { ?film wdt:P57 wd:Q_PERSON . MINUS { ?film ?p wd:Q_PERSON . FILTER(?p != wdt:P57) } }

# CORRECT: Exclude only competing credit roles (producer, writer)
SELECT ?film WHERE {
  ?film wdt:P31 wd:Q11424 ;
       wdt:P57 wd:Q_PERSON .
  FILTER NOT EXISTS { ?film wdt:P58 wd:Q_PERSON . }   # not screenwriter
  FILTER NOT EXISTS { ?film wdt:P162 wd:Q_PERSON . }  # not producer
}
```

### 0b. Advanced Patterns (For Complex Questions)

**Temporal overlap ("Were X and Y alive at the same time?"):**
```sparql
# Check if two people's lifespans overlap
ASK WHERE {
  wd:Q254 wdt:P569 ?birthA ; wdt:P570 ?deathA .   # Mozart
  wd:Q47365 wdt:P569 ?birthB ; wdt:P570 ?deathB . # Marie Antoinette
  FILTER(?birthA <= ?deathB && ?birthB <= ?deathA)  # Overlap condition
}
```

**Multi-hop familial chains ("great-grandfather of X", "grandfather of spouse of X"):**
```sparql
# Great-grandfather (3 hops via P22 = father)
SELECT ?greatgrandfather WHERE {
  wd:Q_PERSON wdt:P22 ?father .
  ?father wdt:P22 ?grandfather .
  ?grandfather wdt:P22 ?greatgrandfather .
}

# Paternal grandfather of spouse
SELECT ?result WHERE {
  wd:Q_PERSON wdt:P26 ?spouse .
  ?spouse wdt:P22 ?father .
  ?father wdt:P22 ?result .
}
```

**Cross-class string matching ("entities in class A sharing family name with entities in class B"):**
```sparql
# Resistance fighters sharing family name with a painter
SELECT ?fighter ?name WHERE {
  ?fighter wdt:P106 wd:Q1397808 .  # resistance fighter
  ?fighter wdt:P734 ?familyName .
  ?painter wdt:P106 wd:Q1028181 .  # painter
  ?painter wdt:P734 ?familyName .
  ?familyName rdfs:label ?name FILTER(LANG(?name) = "en") .
  FILTER(?fighter != ?painter)
}
```

**GROUP BY on labels with HAVING ("entities with duplicate names"):**
```sparql
# Rivers (tributaries of Rhine) that share the same name
SELECT ?name (COUNT(?river) AS ?count) WHERE {
  ?river wdt:P403 wd:Q584 .  # mouth of river = Rhine
  ?river rdfs:label ?name FILTER(LANG(?name) = "en") .
} GROUP BY ?name HAVING(COUNT(?river) > 1)
```

**Temporal range filtering ("events between year X and year Y"):**
```sparql
# Meteorites impacting Earth between 1950 and 1970
SELECT ?meteorite WHERE {
  ?meteorite wdt:P31/wdt:P279* wd:Q60186 .  # meteorite
  ?meteorite wdt:P585 ?date .                 # point in time (impact)
  FILTER(YEAR(?date) >= 1950 && YEAR(?date) <= 1970)
}
```

### 1. Direct Property Lookup

Questions of the form "What is the X of Y?"

**Example:**
- Question: "What is the capital of France?"
- Search terms: France (item), capital (property)
- Resolved entities: France = Q142
- Resolved properties: capital = P36
- Exploration query:
  ```sparql
  SELECT ?val ?valLabel WHERE {
    wd:Q142 wdt:P36 ?val .
    OPTIONAL { ?val rdfs:label ?valLabel FILTER(LANG(?valLabel) = "en") }
  } LIMIT 5
  ```
- Final SPARQL:
  ```sparql
  SELECT ?capital ?capitalLabel WHERE {
    wd:Q142 wdt:P36 ?capital .
    OPTIONAL { ?capital rdfs:label ?capitalLabel FILTER(LANG(?capitalLabel) = "en") }
  }
  ```
- Expected result shape: Single row with city name
- Common failure mode: Using wrong property (P1376 "capital of" is the reverse direction)

---

### 2. Reverse Relations

Questions where the target entity is the object, not the subject.

**Example:**
- Question: "Which countries have Berlin as their capital?"
- Search terms: Berlin (item), capital (property)
- Resolved entities: Berlin = Q64
- Resolved properties: capital = P36
- Exploration query:
  ```sparql
  SELECT ?country ?countryLabel WHERE {
    ?country wdt:P36 wd:Q64 .
    OPTIONAL { ?country rdfs:label ?countryLabel FILTER(LANG(?countryLabel) = "en") }
  } LIMIT 10
  ```
- Final SPARQL:
  ```sparql
  SELECT ?country ?countryLabel WHERE {
    ?country wdt:P36 wd:Q64 .
    OPTIONAL { ?country rdfs:label ?countryLabel FILTER(LANG(?countryLabel) = "en") }
  }
  ```
- Expected result shape: One or more rows (countries with Berlin as capital)
- Common failure mode: Writing `wd:Q64 wdt:P36 ?country` (wrong direction — P36 goes from country to capital)

---

### 3. Type Filtering (instance of)

Questions that filter entities by type.

**Example:**
- Question: "Which universities are located in Massachusetts?"
- Search terms: university (item for type), Massachusetts (item), located in (property)
- Resolved entities: university = Q3918396, Massachusetts = Q771
- Resolved properties: instance of = P31, located in the administrative territorial entity = P131
- Exploration query:
  ```sparql
  SELECT ?uni ?uniLabel WHERE {
    ?uni wdt:P31 wd:Q3918396 ;
         wdt:P131 wd:Q771 .
    OPTIONAL { ?uni rdfs:label ?uniLabel FILTER(LANG(?uniLabel) = "en") }
  } LIMIT 10
  ```
- Final SPARQL:
  ```sparql
  SELECT ?university ?universityLabel WHERE {
    ?university wdt:P31 wd:Q3918396 ;
               wdt:P131+ wd:Q771 .
    OPTIONAL { ?university rdfs:label ?universityLabel FILTER(LANG(?universityLabel) = "en") }
  }
  ```
- Expected result shape: Multiple rows of universities
- Common failure mode: Using P131 without `+` (transitive) — many universities are in cities within Massachusetts, not directly in Massachusetts

---

### 4. Subclass Traversal

Questions that need to include subclasses of a type.

**Example:**
- Question: "List all types of cancer"
- Search terms: cancer (item), subclass of (property)
- Resolved entities: cancer = Q12078
- Resolved properties: subclass of = P279
- Exploration query:
  ```sparql
  SELECT ?type ?typeLabel WHERE {
    ?type wdt:P279 wd:Q12078 .
    OPTIONAL { ?type rdfs:label ?typeLabel FILTER(LANG(?typeLabel) = "en") }
  } LIMIT 20
  ```
- Final SPARQL:
  ```sparql
  SELECT ?cancer ?cancerLabel ?description WHERE {
    ?cancer wdt:P279 wd:Q12078 .
    OPTIONAL { ?cancer rdfs:label ?cancerLabel FILTER(LANG(?cancerLabel) = "en") }
    OPTIONAL { ?cancer schema:description ?description . FILTER(LANG(?description) = "en") }
  }
  ```
- Expected result shape: Many rows (subtypes of cancer)
- Common failure mode: Using P31 (instance of) instead of P279 (subclass of) — P31 gives specific diagnosed cases, P279 gives types/categories

---

### 5. Date Filters

Questions with temporal constraints.

**Example:**
- Question: "Which Nobel Prize winners in Physics were born after 1950?"
- Search terms: Nobel Prize in Physics (item), date of birth (property), award received (property)
- Resolved entities: Nobel Prize in Physics = Q38104
- Resolved properties: award received = P166, date of birth = P569
- Exploration query:
  ```sparql
  SELECT ?person ?personLabel ?dob WHERE {
    ?person wdt:P166 wd:Q38104 ;
            wdt:P569 ?dob .
    OPTIONAL { ?person rdfs:label ?personLabel FILTER(LANG(?personLabel) = "en") }
  } LIMIT 10
  ```
- Final SPARQL:
  ```sparql
  SELECT ?laureate ?laureateLabel ?birthDate WHERE {
    ?laureate wdt:P166 wd:Q38104 ;
              wdt:P569 ?birthDate .
    FILTER(?birthDate >= "1950-01-01T00:00:00Z"^^xsd:dateTime)
    OPTIONAL { ?laureate rdfs:label ?laureateLabel FILTER(LANG(?laureateLabel) = "en") }
  }
  ORDER BY ?birthDate
  ```
- Expected result shape: Multiple rows of people with birth dates after 1950
- Common failure mode: Using string comparison instead of dateTime typed comparison; or wrong date format

---

### 6. Aggregation and Counting

Questions asking for counts, averages, or other aggregates.

**Example:**
- Question: "How many films has Steven Spielberg directed?"
- Search terms: Steven Spielberg (item), director (property), film (item for type)
- Resolved entities: Steven Spielberg = Q8877, film = Q11424
- Resolved properties: director = P57
- Exploration query:
  ```sparql
  SELECT ?film ?filmLabel WHERE {
    ?film wdt:P57 wd:Q8877 ;
          wdt:P31 wd:Q11424 .
    OPTIONAL { ?film rdfs:label ?filmLabel FILTER(LANG(?filmLabel) = "en") }
  } LIMIT 10
  ```
- Final SPARQL:
  ```sparql
  SELECT (COUNT(DISTINCT ?film) AS ?filmCount) WHERE {
    ?film wdt:P57 wd:Q8877 ;
          wdt:P31 wd:Q11424 .
  }
  ```
- Expected result shape: Single row with a count
- Common failure mode: Missing type constraint (counting all directed works, not just films); missing DISTINCT (counting duplicate statements)

---

### 7. Ordering and Top-K Queries

Questions asking for the most/least/top/bottom items.

**Example:**
- Question: "What are the 5 most populated countries in Europe?"
- Search terms: country (item for type), Europe (item), population (property)
- Resolved entities: country = Q6256, Europe = Q46
- Resolved properties: population = P1082, continent = P30
- Exploration query:
  ```sparql
  SELECT ?country ?countryLabel ?pop WHERE {
    ?country wdt:P31 wd:Q6256 ;
             wdt:P30 wd:Q46 ;
             wdt:P1082 ?pop .
    OPTIONAL { ?country rdfs:label ?countryLabel FILTER(LANG(?countryLabel) = "en") }
  } ORDER BY DESC(?pop) LIMIT 5
  ```
- Final SPARQL:
  ```sparql
  SELECT ?country ?countryLabel ?population WHERE {
    ?country wdt:P31 wd:Q6256 ;
             wdt:P30 wd:Q46 ;
             wdt:P1082 ?population .
    OPTIONAL { ?country rdfs:label ?countryLabel FILTER(LANG(?countryLabel) = "en") }
  }
  ORDER BY DESC(?population)
  LIMIT 5
  ```
- Expected result shape: 5 rows ordered by population descending
- Common failure mode: Wikidata may have multiple population values (different years) — may need to filter for latest or use specific qualifier

---

### 8. Qualifier Retrieval

Questions that require accessing qualifiers on statements.

**Example:**
- Question: "Where did Albert Einstein study and when?"
- Search terms: Albert Einstein (item), educated at (property)
- Resolved entities: Albert Einstein = Q937
- Resolved properties: educated at = P69, start time = P580, end time = P582
- Exploration query:
  ```sparql
  SELECT ?school ?schoolLabel ?start ?end WHERE {
    wd:Q937 p:P69 ?stmt .
    ?stmt ps:P69 ?school .
    OPTIONAL { ?stmt pq:P580 ?start . }
    OPTIONAL { ?stmt pq:P582 ?end . }
    OPTIONAL { ?school rdfs:label ?schoolLabel FILTER(LANG(?schoolLabel) = "en") }
  }
  ```
- Final SPARQL:
  ```sparql
  SELECT ?institution ?institutionLabel ?startDate ?endDate ?degreeLabel WHERE {
    wd:Q937 p:P69 ?stmt .
    ?stmt ps:P69 ?institution .
    OPTIONAL { ?stmt pq:P580 ?startDate . }
    OPTIONAL { ?stmt pq:P582 ?endDate . }
    OPTIONAL { ?stmt pq:P512 ?degree . OPTIONAL { ?degree rdfs:label ?degreeLabel FILTER(LANG(?degreeLabel) = "en") } }
    OPTIONAL { ?institution rdfs:label ?institutionLabel FILTER(LANG(?institutionLabel) = "en") }
  }
  ORDER BY ?startDate
  ```
- Expected result shape: Multiple rows with institutions and optional date qualifiers
- Common failure mode: Using `wdt:P69` (direct) instead of `p:P69/ps:P69` (statement-level) — direct properties don't expose qualifiers

---

## Pattern Selection Guide

Match the user's question structure to the most appropriate pattern:

| Question Structure | Pattern |
|-------------------|---------|
| "What is the X of Y?" | Direct property lookup |
| "Which Y has X as their Z?" | Reverse relation |
| "Which things of type T have property P?" | Type filtering |
| "List all subtypes/kinds of X" | Subclass traversal |
| "Which X happened before/after date D?" | Date filter |
| "How many X?" / "What is the total/average?" | Aggregation |
| "What are the top/most/largest N?" | Top-K ordering |
| "What is X with qualifier Y?" / "When did X happen?" | Qualifier retrieval |
| "How far/heavy/long/fast is X?" | Normalized quantity lookup |
| "What is the highest/fastest/tallest X ever?" | Historical maximum with normalization |
| "Does X currently have Y?" | Current-state boolean (exclude ended) |
| "Who is the current holder of position X?" | Position held with temporal ordering |
| "What is the Nth item in X?" | Ordinal qualifier access |
| "Which X in location Y?" | Transitive location containment |
| "Which X has the highest monetary value?" | Monetary comparison with unit filter |
| "Which works/movies feature character X?" | Bidirectional character-film lookup |
| "How many total floors/units does X have?" | Summing complementary sub-properties |
| "Which X are not Y?" / "X outside of Z?" | MINUS exclusion |
| "Which X in country Y?" (via sub-locations) | Location hierarchy traversal |
| "Which X have style/type/kind Y?" (Y may have subkinds) | Subclass traversal on property values |

For complex questions, combine multiple patterns (e.g., type filter + date filter + ordering).

---

### 9. Normalized Quantity Lookup

Questions asking for physical measurements (distance, mass, area, duration, speed, height).

**Example:**
- Question: "What distance is a marathon?"
- Search terms: marathon (item), distance/length (property)
- Resolved entities: marathon = Q40244
- Resolved properties: course length = P3157
- Exploration query:
  ```sparql
  SELECT ?val WHERE {
    wd:Q40244 p:P3157/psn:P3157/wikibase:quantityAmount ?val .
  } LIMIT 5
  ```
- Final SPARQL:
  ```sparql
  SELECT ?obj WHERE {
    wd:Q40244 p:P3157/psn:P3157/wikibase:quantityAmount ?obj .
  }
  ```
- Expected result shape: Single numeric value in SI units (meters: 42195.0)
- Common failure mode: Using `wdt:P3157` which returns 42.195 (km, stored unit) instead of normalized SI value (meters)

**Example:**
- Question: "How far is Alpha Centauri from Earth?"
- Resolved entities: Alpha Centauri = Q12176
- Resolved properties: distance from Earth = P2583
- Final SPARQL:
  ```sparql
  SELECT ?obj WHERE {
    wd:Q12176 p:P2583/psn:P2583/wikibase:quantityAmount ?obj .
  }
  ```
- Expected result shape: Single numeric value in meters (41249088000000000.0)
- Common failure mode: Using `wdt:P2583` returns 4.36 (light-years) — wrong unit

---

### 10. Historical Maximum (All-Time Best)

Questions asking for the highest/lowest value ever achieved across all historical statements.

**Example:**
- Question: "What is the highest Elo rating a chess player has achieved?"
- Search terms: chess player, Elo rating
- Resolved properties: Elo rating = P1087
- Exploration: Use `statement` mode on a known chess player to see that P1087 has multiple historical values with `pq:P585` (point in time) qualifiers
- Final SPARQL:
  ```sparql
  SELECT (MAX(?obj) AS ?max) WHERE {
    ?sbj p:P1087/ps:P1087 ?obj .
  }
  ```
- Expected result shape: Single maximum value (2882.0)
- Common failure mode: Using `wdt:P1087` only returns the CURRENT truthy Elo value per player, missing historical peaks. Must use `p:P1087/ps:P1087` to access ALL statements.

**Example:**
- Question: "Who held the highest Elo rating in Israel's history?"
- Final SPARQL:
  ```sparql
  SELECT ?sbj WHERE {
    ?sbj p:P1087 ?obj1 .
    ?obj1 ps:P1087 ?obj2 .
    ?sbj wdt:P27 wd:Q801 .
  }
  ORDER BY DESC(?obj2)
  LIMIT 1
  ```
- Common failure mode: Using `wdt:P1087` returns current rating only — a different player may currently be rated highest but not be the all-time record holder.

---

### 11. Current-State Boolean (Exclude Ended Relationships)

Questions asking whether a relationship currently holds.

**Example:**
- Question: "Does Elon Musk have a wife?"
- Search terms: Elon Musk, spouse
- Resolved entities: Elon Musk = Q317521
- Resolved properties: spouse = P26, end time = P582, sex or gender = P21, female = Q6581072
- Exploration: Use `statement` mode on Q317521 for P26 — see that past marriages have `pq:P582` (end time) qualifiers
- Final SPARQL:
  ```sparql
  ASK WHERE {
    wd:Q317521 p:P26|^p:P26 ?obj1 .
    ?obj1 ps:P26 ?obj2 .
    ?obj2 wdt:P21 wd:Q6581072 .
    MINUS { ?obj1 pq:P582 ?obj3 }
  }
  ```
- Expected result: False (all marriages have end dates)
- Common failure mode: Using `ASK { wd:Q317521 wdt:P26 ?x }` returns True because `wdt:` shows ANY spouse statement regardless of whether it ended. Must use `MINUS { pq:P582 ?end }` to exclude ended relationships.

---

### 12. Position Held with Temporal Ordering

Questions about the current holder of a political/organizational position.

**Example:**
- Question: "Who is the prime minister of South Korea?"
- Search terms: prime minister of South Korea, position held
- Resolved entities: Prime Minister of South Korea = Q15407843
- Resolved properties: position held = P39, start time = P580
- Final SPARQL:
  ```sparql
  SELECT ?sbj WHERE {
    ?sbj p:P39 ?obj1 .
    ?obj1 ps:P39 wd:Q15407843 .
    ?obj1 pq:P580 ?obj2
  }
  ORDER BY DESC(?obj2)
  LIMIT 1
  ```
- Expected result shape: Single person QID (the most recent person to start in the role)
- Common failure mode: Using `wdt:P6` (head of government) instead of the specific position. In South Korea, P6 may return the president, not the PM. Always use the specific position entity (Q15407843) with P39.

---

### 13. Ordinal Qualifier Access

Questions that ask for the Nth item in a sequence.

**Example:**
- Question: "What is Donald Trump's middle name?"
- Search terms: Donald Trump, given name
- Resolved entities: Donald Trump = Q22686
- Resolved properties: given name = P735, series ordinal = P1545
- Final SPARQL:
  ```sparql
  SELECT DISTINCT ?obj2 WHERE {
    wd:Q22686 p:P735 ?obj1 .
    ?obj1 pq:P1545 "2" .
    ?obj1 ps:P735 ?obj2 .
  }
  ```
- Expected result shape: Single QID (Q4925477 — the entity for the given name "John")
- Common failure mode: (1) Returning the label "John" instead of the QID Q4925477 — P735 is an item-valued property. (2) Not using ordinal qualifier pq:P1545 to select the 2nd name.

**Example:**
- Question: "What is black's second move in the Catalan Opening?"
- Resolved entities: Catalan Opening = Q1138488
- Resolved properties: chess moves (P5286), series ordinal = P1545
- Final SPARQL:
  ```sparql
  SELECT ?obj3 WHERE {
    wd:Q1138488 p:P5286 ?obj1 .
    ?obj1 pq:P1545 "2" .
    ?obj1 ps:P5286 ?obj2 .
    BIND(STRAFTER(STR(?obj2)," ") AS ?obj3)
  }
  ```
- Note: Chess PGN moves store both white and black moves; STRAFTER extracts black's move after the space.

---

### 14. Transitive Location Containment

Questions about items located within a geographic area (including sub-divisions).

**Example:**
- Question: "Which parks in Perth are State Registered Places?"
- Search terms: Perth, park, State Registered Place, heritage designation
- Resolved entities: Perth = Q3183, park = Q22698, State Registered Place = Q56052054
- Resolved properties: located in (P131), heritage designation (P1435), instance of (P31)
- Final SPARQL:
  ```sparql
  SELECT ?sbj WHERE {
    ?sbj wdt:P31/wdt:P279* wd:Q22698 .
    ?sbj wdt:P131+ wd:Q3183 .
    ?sbj wdt:P1435 wd:Q56052054
  }
  ```
- Expected result shape: One or more park QIDs
- Common failure mode: Using `wdt:P131 wd:Q3183` (direct) instead of `wdt:P131+ wd:Q3183` (transitive). Parks may be in suburbs like "City of Vincent" which is P131→Perth, so the park needs transitive containment to match.

---

### 15. Monetary Comparison with Unit Filter

Questions comparing monetary values across entities that may have different currencies.

**Example:**
- Question: "Which Indian movie has the highest box office?"
- Search terms: Indian, movie, box office
- Resolved entities: film = Q11424, India = Q668, US dollar = Q4917
- Resolved properties: country of origin = P495, box office = P2142
- Final SPARQL:
  ```sparql
  SELECT ?sbj WHERE {
    ?sbj wdt:P31/wdt:P279* wd:Q11424 .
    ?sbj wdt:P495 wd:Q668 .
    ?sbj p:P2142 ?obj1 .
    ?obj1 psv:P2142 ?obj2 .
    ?obj2 wikibase:quantityAmount ?obj3 .
    ?obj2 wikibase:quantityUnit wd:Q4917 .
  }
  ORDER BY DESC(?obj3)
  LIMIT 1
  ```
- Expected result shape: Single film QID
- Common failure mode: Using `wdt:P2142 ?boxOffice` and sorting by raw number — this mixes currencies (INR, USD, EUR) making comparison meaningless. Must filter by `wikibase:quantityUnit` for a specific currency.

---

### 16. Top-K with Normalized Quantities

Questions asking for the tallest/fastest/heaviest entity.

**Example:**
- Question: "Who is the tallest human of all time?"
- Resolved entities: human = Q5
- Resolved properties: height = P2048
- Final SPARQL:
  ```sparql
  SELECT ?sbj WHERE {
    ?sbj wdt:P31 wd:Q5 .
    ?sbj p:P2048/psn:P2048/wikibase:quantityAmount ?obj .
  }
  ORDER BY DESC(?obj)
  LIMIT 1
  ```
- Expected result shape: Single person QID
- Common failure mode: (1) Using `wdt:P2048` which returns values in stored units (some in cm, some in m) making comparison incorrect. (2) Adding plausibility filters like `FILTER(?height < 3)` which incorrectly removes entries stored in centimeters.

**Example (Geographic superlative — use shortcut property):**
- Question: "What is the highest mountain in the Andes?"
- Key insight: Geographic regions often have `P610` (highest point) as a direct shortcut. Always check the region entity for P610 FIRST before attempting a ranked aggregation query.
- Resolved entities: Andes = Q5456
- Resolved properties: highest point = P610
- Final SPARQL:
  ```sparql
  SELECT ?peak WHERE {
    wd:Q5456 wdt:P610 ?peak .
  }
  ```
- Expected result shape: Single entity (Aconcagua)
- Common failure mode: Attempting `?mountain wdt:P4552 wd:Q5456 ; p:P2044/psn:P2044/wikibase:quantityAmount ?h . ORDER BY DESC(?h) LIMIT 1` — this fails because mountains may be tagged under sub-ranges (like "Principal Cordillera") not the top-level range. The P610 shortcut avoids this entirely.

---

### 17. Bidirectional Character-Film Lookup

Questions about works featuring a character (or characters in a work), where the relationship may be modeled from either side.

**Example:**
- Question: "What is the latest movie featuring Harley Quinn?"
- Search terms: Harley Quinn (item), movie/film (type), characters/present in work (properties)
- Resolved entities: Harley Quinn = Q849477, film = Q11424
- Resolved properties: characters = P674, present in work = P1441, publication date = P577
- Exploration: Check BOTH `?film wdt:P674 wd:Q849477` (from film side) AND `wd:Q849477 wdt:P1441 ?film` (from character side) — use whichever direction returns more results
- Final SPARQL (from film side):
  ```sparql
  SELECT ?film WHERE {
    ?film wdt:P31/wdt:P279* wd:Q11424 .
    ?film wdt:P674 wd:Q849477 .
    ?film wdt:P577 ?date .
  }
  ORDER BY DESC(?date)
  LIMIT 1
  ```
- Alternative Final SPARQL (from character side):
  ```sparql
  SELECT ?film WHERE {
    wd:Q849477 wdt:P1441 ?film .
    ?film wdt:P31/wdt:P279* wd:Q11424 .
    ?film wdt:P577 ?date .
  }
  ORDER BY DESC(?date)
  LIMIT 1
  ```
- Expected result shape: Single film QID
- Common failure mode: Only trying one direction (P674 from film) when the data may only be modeled from the other direction (P1441 from character). Always explore both during graph exploration and use the direction that returns data.

---

### 18. Summing Complementary Sub-Properties

Questions asking for a total measurement that is stored across multiple sub-properties.

**Example:**
- Question: "How many floors does the Zifeng Tower have?"
- Search terms: Zifeng Tower (item), floors/storeys (property)
- Resolved entities: Zifeng Tower = Q382121
- Resolved properties: floors above ground = P1101, floors below ground = P1139
- Exploration: Check both P1101 and P1139 on the entity — both exist
- Final SPARQL:
  ```sparql
  SELECT (?above + ?below AS ?totalFloors) WHERE {
    wd:Q382121 wdt:P1101 ?above ;
                wdt:P1139 ?below .
  }
  ```
- Expected result shape: Single numeric value (71.0 = 66 + 5)
- Common failure mode: Only using P1101 (above ground = 66) and missing P1139 (below ground = 5). When the question asks for "total floors" without qualification, always check for both above-ground and below-ground properties.

---

### 19. MINUS Exclusion (Filtering Out Unwanted Categories)

Questions where certain results must be excluded by category or relationship.

**Example:**
- Question: "Which movies based on books by Author X are not editions/translations?"
- Pattern: Find adaptations, then exclude items that are editions of another work
- Final SPARQL:
  ```sparql
  SELECT DISTINCT ?film WHERE {
    ?film wdt:P31/wdt:P279* wd:Q11424 .
    ?film wdt:P144 ?work .
    ?work wdt:P50 wd:Q_AUTHOR .
    MINUS { ?film wdt:P629 ?edition . }
  }
  ```
- Common failure mode: Omitting the MINUS clause, returning editions/translations alongside original adaptations.

**Example:**
- Question: "What extant species are in order X?"
- Pattern: Find species in taxonomy, exclude extinct ones
- Final SPARQL:
  ```sparql
  SELECT ?species WHERE {
    ?species wdt:P171+ wd:Q_ORDER .
    ?species wdt:P105 wd:Q7432 .
    MINUS { ?species (wdt:P31|wdt:P141)/wdt:P279* wd:Q_EXTINCT_CONCEPT . }
  }
  ```
- Common failure mode: Requiring conservation status to exist (`wdt:P141 ?status`) which excludes unannotated species, instead of using MINUS to only remove known-extinct ones.

**Example:**
- Question: "What collections outside of Africa exhibit X?"
- Pattern: Find items, get their collections, exclude collections in Africa
- Final SPARQL:
  ```sparql
  SELECT DISTINCT ?collection WHERE {
    ?item (wdt:P361|wdt:P31)/wdt:P279* wd:Q_COLLECTION_CLASS .
    ?item wdt:P195 ?collection .
    MINUS { ?collection wdt:P131*/wdt:P17?/wdt:P30? wd:Q15 . }
  }
  ```
- Common failure mode: Doing geographic exclusion manually in post-processing rather than encoding it as a MINUS clause in the query.

---

### 20. Location Hierarchy Traversal (Country-Level Queries)

Questions asking about items "in country X" where the items are tagged with sub-locations.

**Example:**
- Question: "Which movies were filmed in Yemen?"
- Search terms: Yemen (item), filmed at (property)
- Resolved entities: Yemen = Q805
- Resolved properties: filming location = P915
- Key insight: Films are tagged with specific cities/regions, not the country directly. Need to traverse up to country level.
- Final SPARQL:
  ```sparql
  SELECT DISTINCT ?film WHERE {
    ?film wdt:P31/wdt:P279* wd:Q11424 .
    ?film wdt:P915/wdt:P131*/wdt:P17? wd:Q805 .
  }
  ```
- Expected result shape: Multiple films
- Common failure mode: Using `?film wdt:P915 wd:Q805` (direct) which only finds films explicitly tagged with "Yemen" as filming location, missing films tagged with Aden, Sana'a, etc.

**Example:**
- Question: "Which football players born in Senegal played for France?"
- Key property paths:
  - Birthplace to country: `wdt:P19/wdt:P131*/wdt:P17?`
  - Country for sport: `wdt:P1532` (more general than team membership P54)
- Final SPARQL:
  ```sparql
  SELECT DISTINCT ?player WHERE {
    ?player wdt:P19/wdt:P131*/wdt:P17? wd:Q1041 .
    ?player wdt:P1532 wd:Q142 .
    ?player wdt:P106 wd:Q937857 .
  }
  ```
- Common failure mode: (1) Using `wdt:P19 wd:Q_COUNTRY` directly instead of traversing the admin hierarchy. (2) Using P54 (member of specific team) instead of P1532 (country for sport) which is more general.

---

### 21. Subclass Traversal on Property Values

Questions where the property value may be a specific subclass of the target concept.

**Example:**
- Question: "Which buildings are in brutalist style?"
- Key insight: Buildings may have a specific substyle (e.g., "New Brutalism") that is a subclass of brutalism (Q47942).
- Final SPARQL:
  ```sparql
  SELECT DISTINCT ?building WHERE {
    ?building wdt:P149/wdt:P279* wd:Q47942 .
  }
  ```
- Common failure mode: Using `?building wdt:P149 wd:Q47942` (exact match only) which misses buildings with substyles. Add `/wdt:P279*` after the property to traverse the subclass hierarchy of the value.

---

## Usage in the Pipeline

Before generating SPARQL, identify the structural pattern of the question and reference the appropriate example. Use the example as a template, substituting the resolved entities and properties from your search and exploration steps.

The examples demonstrate:
- Correct prefix usage (wdt: vs p:/ps:/pq: vs psn:)
- Proper direction of triple patterns
- When to use OPTIONAL vs required patterns
- How to handle type hierarchies
- Label service placement
- Filter syntax for dates and numbers
- Normalized quantity retrieval for measurements
- Temporal qualifier handling for current-state and historical queries
- Item-valued properties (return QIDs not labels)
- Transitive containment for location queries
- Unit filtering for monetary comparisons
- Bidirectional relationship exploration
- Summing complementary sub-properties for totals
- MINUS exclusion for filtering unwanted categories
- Location hierarchy traversal for country-level queries
- Subclass traversal on property values
