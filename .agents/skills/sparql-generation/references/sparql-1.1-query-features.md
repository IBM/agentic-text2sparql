# SPARQL 1.1 Query Features — Concise Agent Reference

This reference summarizes the main features of the **SPARQL 1.1 Query Language** for agents that generate, inspect, or repair SPARQL queries.

Source: W3C Recommendation, *SPARQL 1.1 Query Language*  
https://www.w3.org/TR/sparql11-query/

---

## 1. Quick Feature Selection Guide
| Requirement | SPARQL feature |
|---|---|
| Match RDF facts | Triple/basic graph patterns |
| Require multiple facts | Patterns in the same group |
| Optional attribute | `OPTIONAL` |
| Alternative structures | `UNION` |
| Exclude matching resources | `NOT EXISTS` or `MINUS` |
| Multi-hop traversal | Property paths |
| Compute a value | `BIND` or `SELECT` expression |
| Supply candidate constants | `VALUES` |
| Count or summarize | Aggregates + `GROUP BY` |
| Filter aggregate results | `HAVING` |
| Query nested intermediate results | Subquery |
| Query named graphs | `GRAPH` |
| Select the active dataset | `FROM`, `FROM NAMED` |
| Query another endpoint | `SERVICE` |
| Remove duplicates | `DISTINCT` |
| Rank results | `ORDER BY` |
| Return a result window | `LIMIT`, `OFFSET` |
| Test existence | `ASK`, `EXISTS`, `NOT EXISTS` |
| Generate RDF | `CONSTRUCT` |


---

## 2. Basic Query Structure

```sparql
PREFIX ex: <http://example.org/>

SELECT ?item ?label
WHERE {
  ?item ex:label ?label .
}
```

- `PREFIX` declares namespace abbreviations.
- Variables begin with `?` or `$`.
- A triple pattern has subject, predicate, and object positions.
- Multiple triple patterns in the same group form a conjunction (join).
- `a` is shorthand for `rdf:type`.
- `;` repeats the subject; `,` repeats the subject and predicate.

```sparql
?person a ex:Person ;
        ex:name ?name ;
        ex:knows ?friend1, ?friend2 .
```

---

## 3. Query Forms

### `SELECT`

Returns variable bindings.

```sparql
SELECT DISTINCT ?person ?name
WHERE {
  ?person a ex:Person ;
          ex:name ?name .
}
```

### `ASK`

Returns `true` or `false`.

```sparql
ASK {
  ex:Alice ex:knows ex:Bob .
}
```

### `CONSTRUCT`

Creates an RDF graph from query results.

```sparql
CONSTRUCT {
  ?person ex:displayName ?name .
}
WHERE {
  ?person ex:name ?name .
}
```

### `DESCRIBE`

Returns an implementation-defined RDF description of resources.

```sparql
DESCRIBE ex:Alice
```

Use `CONSTRUCT` instead when predictable output is required.

---

## 4. Graph Pattern Composition

### Required patterns

All patterns in a basic graph pattern must match.

```sparql
?person ex:name ?name ;
        ex:birthDate ?date .
```

### `OPTIONAL`

Keeps a solution even when the optional pattern does not match.

```sparql
?person ex:name ?name .
OPTIONAL {
  ?person ex:email ?email .
}
```

A variable introduced only inside `OPTIONAL` may remain unbound.

### `UNION`

Matches any of several alternatives.

```sparql
{
  ?item a ex:Book .
}
UNION
{
  ?item a ex:Article .
}
```

### Nested groups

Braces control grouping and scope.

```sparql
{
  ?item a ex:Book .
  OPTIONAL { ?item ex:isbn ?isbn . }
}
```

---

## 5. Filtering and Negation

### `FILTER`

Restricts solutions using an expression.

```sparql
FILTER(?price > 100)
FILTER(LANG(?label) = "en")
FILTER(CONTAINS(LCASE(STR(?label)), "graph"))
```

Common operators:

```text
=  !=  <  <=  >  >=
+  -  *  /
&&  ||  !
IN (...)  NOT IN (...)
```

### `FILTER EXISTS`

Keeps solutions for which a pattern exists.

```sparql
FILTER EXISTS {
  ?person ex:email ?email .
}
```

### `FILTER NOT EXISTS`

Keeps solutions for which a pattern does not exist.

```sparql
FILTER NOT EXISTS {
  ?person ex:email ?email .
}
```

### `MINUS`

Removes compatible solutions matched by another graph pattern.

```sparql
?person a ex:Person .
MINUS {
  ?person ex:status ex:Inactive .
}
```

`NOT EXISTS` is correlated with the current solution. `MINUS` compares solution mappings and behaves differently when variables are not shared.

---

## 6. Property Paths

Property paths match routes through an RDF graph.

| Syntax | Meaning |
|---|---|
| `ex:p/ex:q` | Sequence |
| `ex:p|ex:q` | Alternative |
| `^ex:p` | Inverse direction |
| `ex:p?` | Zero or one occurrence |
| `ex:p*` | Zero or more occurrences |
| `ex:p+` | One or more occurrences |
| `!ex:p` | Any predicate except `ex:p` |
| `!(ex:p|ex:q)` | Any predicate except listed alternatives |

```sparql
SELECT ?ancestor
WHERE {
  ex:Alice ex:parent+ ?ancestor .
}
```

```sparql
SELECT ?related
WHERE {
  ex:Alice (ex:parent|ex:spouse)+ ?related .
}
```

Property paths return endpoint bindings, not the intermediate path or path length.

---

## 7. Assignment and Inline Data

### `BIND`

Assigns the result of an expression to a new variable.

```sparql
BIND(CONCAT(?first, " ", ?last) AS ?fullName)
```

A variable cannot be rebound in the same group.

### `VALUES`

Provides inline bindings and can restrict candidate values.

```sparql
VALUES ?country {
  ex:France
  ex:Germany
  ex:Italy
}
```

Multiple variables:

```sparql
VALUES (?country ?code) {
  (ex:France  "FR")
  (ex:Germany "DE")
}
```

Use `UNDEF` for an unbound value.

---

## 8. Aggregation

Supported aggregates include:

- `COUNT`
- `SUM`
- `AVG`
- `MIN`
- `MAX`
- `SAMPLE`
- `GROUP_CONCAT`

```sparql
SELECT ?country (COUNT(?city) AS ?cityCount)
WHERE {
  ?city ex:country ?country .
}
GROUP BY ?country
```

### `HAVING`

Filters groups after aggregation.

```sparql
SELECT ?country (COUNT(?city) AS ?count)
WHERE {
  ?city ex:country ?country .
}
GROUP BY ?country
HAVING(COUNT(?city) > 10)
```

Distinct aggregate values:

```sparql
COUNT(DISTINCT ?city)
```

String aggregation:

```sparql
GROUP_CONCAT(DISTINCT ?label; separator=", ")
```

Every projected non-aggregate variable must normally appear in `GROUP BY`.

---

## 9. Subqueries

A nested `SELECT` can calculate, group, rank, or limit intermediate results.

```sparql
SELECT ?country ?count
WHERE {
  {
    SELECT ?country (COUNT(?city) AS ?count)
    WHERE {
      ?city ex:country ?country .
    }
    GROUP BY ?country
  }
  FILTER(?count > 10)
}
```

Only variables projected by the subquery are visible outside it.

---

## 10. RDF Datasets and Named Graphs

### Dataset clauses

```sparql
SELECT ?s ?p ?o
FROM <http://example.org/default>
FROM NAMED <http://example.org/graph1>
WHERE {
  ?s ?p ?o .
}
```

- `FROM` contributes to the query's default graph.
- `FROM NAMED` makes a named graph available to `GRAPH`.
- Dataset clauses define the query dataset; they do not merely add filters.

### `GRAPH`

Queries a named graph.

```sparql
GRAPH <http://example.org/graph1> {
  ?s ?p ?o .
}
```

Query graph names dynamically:

```sparql
GRAPH ?graph {
  ?s ex:name ?name .
}
```

---

## 11. Federated Query

`SERVICE` sends a graph pattern to a remote SPARQL endpoint.

```sparql
SERVICE <https://query.example.org/sparql> {
  ?item ex:identifier ?id .
}
```

Use `SERVICE SILENT` to suppress a service failure and continue with no matches from that service.

```sparql
SERVICE SILENT <https://query.example.org/sparql> {
  ?item ex:identifier ?id .
}
```

Federated queries may be slow, rate-limited, unavailable, or unsupported by an endpoint.

---

## 12. Solution Modifiers

### Projection

```sparql
SELECT ?person (?birthYear + 1 AS ?nextYear)
```

### Duplicate handling

```sparql
SELECT DISTINCT ?person
```

`REDUCED` permits, but does not guarantee, duplicate elimination.

### Ordering

```sparql
ORDER BY ASC(?name) DESC(?score)
```

### Pagination

```sparql
LIMIT 100
OFFSET 200
```

Use `ORDER BY` with `LIMIT` or `OFFSET` when deterministic paging matters.

---

## 13. Common Built-in Functions

### Variable and term checks

```text
BOUND(?v)
isIRI(?v)
isBlank(?v)
isLiteral(?v)
isNumeric(?v)
sameTerm(?a, ?b)
```

### RDF term access and construction

```text
STR(?term)
LANG(?literal)
DATATYPE(?literal)
IRI(?string)
BNODE()
STRDT(?string, datatypeIRI)
STRLANG(?string, languageTag)
UUID()
STRUUID()
```

### Conditional and error handling

```text
IF(condition, thenValue, elseValue)
COALESCE(expr1, expr2, ...)
```

### String functions

```text
STRLEN
SUBSTR
UCASE
LCASE
STRSTARTS
STRENDS
CONTAINS
STRBEFORE
STRAFTER
CONCAT
REGEX
REPLACE
ENCODE_FOR_URI
LANGMATCHES
```

Example:

```sparql
FILTER(REGEX(STR(?label), "^graph", "i"))
```

### Numeric functions

```text
ABS
ROUND
CEIL
FLOOR
RAND
```

### Date and time functions

```text
NOW
YEAR
MONTH
DAY
HOURS
MINUTES
SECONDS
TIMEZONE
TZ
```

### Hash functions

```text
MD5
SHA1
SHA256
SHA384
SHA512
```

---

## 14. Literals and RDF Terms

Examples:

```sparql
"hello"
"hello"@en
"42"^^xsd:integer
42
3.14
true
```

Important distinctions:

- `"cat"` and `"cat"@en` are different RDF terms.
- `=` compares values where possible.
- `sameTerm()` tests exact RDF-term identity.
- Language-tagged literals should usually be filtered with `LANG` or `LANGMATCHES`.
- Numeric and date comparisons require compatible datatypes.

---

## 15. Variable Scope

- Variables projected by a subquery are visible outside the subquery.
- Variables not projected by a subquery remain local.
- Variables introduced in `OPTIONAL` may be unbound.
- Variables used only inside `EXISTS` or `NOT EXISTS` are local to that pattern unless correlated with outer variables.
- A `BIND` target variable must not already be in scope in the same group.
- `SELECT *` exposes variables in scope but may make generated queries less predictable.

---

## 16. Agent-Oriented Query Construction Checklist

1. Declare all required prefixes.
2. Choose the correct query form: `SELECT`, `ASK`, `CONSTRUCT`, or `DESCRIBE`.
3. Identify seed entities, target variables, and connecting predicates.
4. Use required triple patterns for mandatory constraints.
5. Use `OPTIONAL` only for genuinely optional information.
6. Use `UNION` for alternative graph structures.
7. Use property paths for multi-hop or variable-length traversal.
8. Apply `FILTER` after the variables it references are introduced.
9. Use `VALUES` to constrain known candidate entities or constants.
10. Use `GROUP BY` and aggregates only after confirming the intended grouping.
11. Use `HAVING` for aggregate constraints and `FILTER` for row-level constraints.
12. Add `DISTINCT` only when duplicate solutions are not meaningful.
13. Add `ORDER BY` before using `LIMIT` for top-k or deterministic pagination.
14. Validate endpoint support for `SERVICE`, functions, and dataset behavior.
15. Execute and inspect results; repair empty, duplicated, or unexpectedly broad results.

---

## 17. Frequent Query-Generation Errors

- Using a label string where an entity IRI is required.
- Reversing the subject and object of a predicate.
- Assuming a predicate is symmetric.
- Making a mandatory pattern that should be `OPTIONAL`.
- Placing a `FILTER` outside the scope of its variables.
- Confusing `FILTER NOT EXISTS` with `MINUS`.
- Omitting `GROUP BY` variables in aggregate queries.
- Using `LIMIT` without `ORDER BY` for top-k questions.
- Expecting property paths to expose intermediate nodes.
- Assuming `DESCRIBE` has portable, deterministic semantics.
- Comparing language-tagged and untagged strings as identical RDF terms.
- Assuming all endpoints implement extensions or identical inference behavior.

---
---

## Scope Note

This file summarizes the **SPARQL 1.1 Query Language**. SPARQL 1.1 Update operations such as `INSERT`, `DELETE`, `LOAD`, `CLEAR`, and `DROP` are defined in a separate W3C recommendation and are intentionally excluded.