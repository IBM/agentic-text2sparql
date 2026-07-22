# Wikidata Data Model for SPARQL Agents

This guide explains the Wikidata data model and its RDF representation. It is intended as a reference for agents that work with Wikidata and need to understand how entities, statements, qualifiers, references, ranks, and values are represented.

## 1. Core Mental Model

Wikidata stores knowledge as **statements about entities**.

A simple statement has the form:

```text
subject entity → property → value
```

Example:

```text
Douglas Adams (Q42) → place of birth (P19) → Cambridge (Q350)
```

In the simplified RDF representation:

```sparql
wd:Q42 wdt:P19 wd:Q350 .
```

A complete Wikidata statement may also contain:

- qualifiers that add context;
- references that identify supporting sources;
- a rank that indicates which statements should normally be preferred.

Wikidata statements therefore contain more information than ordinary subject–predicate–object triples.

---

## 2. Main Wikidata Entity Types

### 2.1 Items

Items represent things, people, places, organizations, events, concepts, and other entities.

Item identifiers begin with `Q`.

```text
Q42       Douglas Adams
Q5        human
Q183      Germany
Q3918     university
```

In RDF and SPARQL, items use the `wd:` prefix:

```sparql
wd:Q42
```

### 2.2 Properties

Properties describe relationships or attributes.

Property identifiers begin with `P`.

```text
P31       instance of
P279      subclass of
P19       place of birth
P569      date of birth
```

The same property identifier may appear with different RDF prefixes depending on which part of the statement model is being accessed:

```sparql
wdt:P31  # direct or truthy property value
p:P31    # link from an entity to a statement node
ps:P31   # main value of a statement
pq:P31   # qualifier value attached to a statement
pr:P31   # reference value recorded in a source
```

### 2.3 Lexicographical entities

Wikidata also supports lexicographical data.

The main entity types are:

```text
Lexeme     L...
Form       L...-F...
Sense      L...-S...
```

These entities represent words, their grammatical forms, and their meanings.

Most general-knowledge queries primarily use items and properties.

### 2.4 Entity schemas

Entity schemas describe expected modelling structures for classes of Wikidata entities.

Their identifiers begin with `E`.

```text
E...
```

Entity schemas are commonly expressed using Shape Expressions.

---

## 3. Wikidata Page Namespaces

Wikidata uses MediaWiki page namespaces to organize different kinds of pages.

Important namespaces include:

| Namespace | Purpose |
|---|---|
| Main namespace | Wikidata items such as `Q42` |
| `Property:` | Property pages such as `Property:P31` |
| `Lexeme:` | Lexicographical entities |
| `EntitySchema:` | Entity schemas |
| `Wikidata:` | Project documentation and policies |
| `Help:` | Help pages |
| `User:` | User pages |
| `Talk:` | Discussion pages |

These page namespaces should not be confused with RDF prefixes such as `wd:`, `wdt:`, `p:`, and `pq:`.

---

## 4. Entity Terms

Wikidata entities may contain human-readable terms.

### 4.1 Labels

A label is the primary name of an entity in a particular language.

Example:

```text
Q42
English label: Douglas Adams
```

### 4.2 Descriptions

A description is a short phrase used to distinguish an entity from others with similar labels.

Example:

```text
English description:
English writer and humorist
```

### 4.3 Aliases

Aliases are alternative names, spellings, abbreviations, or common forms of a name.

Example:

```text
Douglas Noël Adams
Douglas Noel Adams
```

### 4.4 Language dependence

Labels, descriptions, and aliases are language-specific.

An entity can have different terms in multiple languages.

In RDF, labels are represented as language-tagged literals:

```sparql
wd:Q42 rdfs:label "Douglas Adams"@en .
```

Labels are not guaranteed to be unique. Entity identifiers, rather than labels, provide stable identity.

---

## 5. Statements

A statement expresses a property-value assertion about an entity.

Example:

```text
Douglas Adams
  place of birth
  Cambridge
```

The basic components are:

```text
subject
property
value
```

A full statement may contain:

```text
main value
qualifiers
references
rank
statement identifier
```

Conceptually:

```text
entity
  └── property statement
        ├── main value
        ├── qualifier values
        ├── references
        └── rank
```

Wikidata may contain multiple statements using the same property for one entity.

For example, an entity may have several occupations, citizenships, awards, positions, or historical population values.

---

## 6. Claims, Statements, and Snaks

Wikibase documentation distinguishes several related concepts.

### Claim

A claim is a property-value assertion, possibly including qualifiers.

### Statement

A statement is a claim together with:

- references;
- rank.

### Snak

A snak is a property-value component within a statement.

Snaks are used for:

- the main statement value;
- qualifiers;
- reference values.

A snak can contain:

```text
a concrete value
an unknown value
an explicit no-value marker
```

In many practical contexts, the term **statement** is used broadly for the full Wikidata assertion.

---

## 7. Direct or Truthy Statements

Wikidata provides a simplified RDF view using the `wdt:` prefix.

Example:

```sparql
wd:Q42 wdt:P19 wd:Q350 .
```

General form:

```sparql
?subject wdt:Pxxx ?value .
```

The `wdt:` representation returns the best-ranked values for a property.

It is often called the:

```text
direct
truthy
simplified
```

representation.

It does not expose:

- qualifiers;
- references;
- statement nodes;
- rank metadata;
- deprecated statements;
- normal-ranked values when preferred values exist.

Example:

```sparql
wd:Q42 wdt:P569 ?birthDate .
```

This representation is convenient for simple property-value access, but it is only a projection of the complete Wikidata statement model.

---

## 8. Full Statement Representation

The full statement model introduces a statement node between the entity and the value.

General pattern:

```sparql
?subject p:Pxxx ?statement .
?statement ps:Pxxx ?value .
```

Example:

```sparql
wd:Q42 p:P19 ?statement .
?statement ps:P19 wd:Q350 .
```

Conceptually:

```text
wd:Q42
  └── p:P19
        └── statement node
              └── ps:P19
                    └── wd:Q350
```

The statement node provides a place to attach:

- qualifiers;
- references;
- rank information;
- detailed value nodes.

Statement nodes use identifiers in the `wds:` namespace.

```text
wds:...
```

---

## 9. Important RDF Prefixes

| Prefix | Purpose |
|---|---|
| `wd:` | Wikidata entities and properties |
| `wdt:` | Direct or truthy property values |
| `p:` | Links an entity to a statement node |
| `ps:` | Main value of a statement |
| `pq:` | Qualifier value |
| `pr:` | Reference value |
| `psv:` | Detailed node for a main statement value |
| `pqv:` | Detailed node for a qualifier value |
| `prv:` | Detailed node for a reference value |
| `wdtn:` | Normalized direct value |
| `psn:` | Normalized main statement value |
| `pqn:` | Normalized qualifier value |
| `prn:` | Normalized reference value |
| `wds:` | Statement nodes |
| `wdref:` | Reference nodes |
| `wdv:` | Complex value nodes |
| `wikibase:` | Wikibase ontology |
| `prov:` | Provenance vocabulary |
| `rdfs:` | RDF Schema vocabulary |
| `schema:` | Schema.org vocabulary |
| `skos:` | SKOS vocabulary |
| `owl:` | Web Ontology Language vocabulary |
| `bd:` | Blazegraph service configuration |

The Wikidata Query Service normally defines these prefixes automatically.

---

## 10. Qualifiers

Qualifiers add context to a statement.

For example:

```text
person
  position held
  president
    start time: 2010
    end time: 2015
```

Qualifiers are attached to the statement node, not directly to the subject or value.

RDF pattern:

```sparql
?subject p:Pxxx ?statement .
?statement ps:Pxxx ?value ;
           pq:Pyyy ?qualifier .
```

Example:

```sparql
?person p:P39 ?statement .
?statement ps:P39 ?position ;
           pq:P580 ?startDate ;
           pq:P582 ?endDate .
```

Common qualifier properties include:

| Property | Meaning |
|---|---|
| `P580` | start time |
| `P582` | end time |
| `P585` | point in time |
| `P1545` | series ordinal |
| `P3831` | object has role |
| `P518` | applies to part |
| `P459` | determination method |
| `P642` | of |

A statement may have:

- no qualifiers;
- one qualifier;
- several qualifiers;
- multiple values for the same qualifier property.

Example:

```text
population: 1,000,000
point in time: 2020
determination method: census
```

The qualifier identifies the context in which the main value is valid.

---

## 11. References

References record the provenance or source of a statement.

A statement connects to a reference node using:

```sparql
prov:wasDerivedFrom
```

General pattern:

```sparql
?subject p:Pxxx ?statement .
?statement ps:Pxxx ?value ;
           prov:wasDerivedFrom ?reference .

?reference pr:Pyyy ?referenceValue .
```

Example:

```sparql
?person p:P569 ?statement .
?statement ps:P569 ?birthDate ;
           prov:wasDerivedFrom ?reference .

?reference pr:P248 ?source .
```

Common reference properties include:

| Property | Meaning |
|---|---|
| `P248` | stated in |
| `P854` | reference URL |
| `P813` | retrieved |
| `P577` | publication date |
| `P143` | imported from Wikimedia project |
| `P1476` | title |
| `P304` | page |
| `P478` | volume |
| `P433` | issue |

A reference can contain several property-value pairs.

Example:

```text
stated in: source item
reference URL: URL
retrieved: date
page: 42
```

A statement may contain:

- no references;
- one reference;
- multiple references.

Reference nodes use identifiers in the `wdref:` namespace.

---

## 12. Statement Ranks

Each statement has a rank.

The three possible ranks are:

```text
preferred
normal
deprecated
```

Their RDF representations are:

```sparql
wikibase:PreferredRank
wikibase:NormalRank
wikibase:DeprecatedRank
```

Rank is attached to the statement node:

```sparql
?statement wikibase:rank ?rank .
```

Example:

```sparql
?subject p:Pxxx ?statement .
?statement ps:Pxxx ?value ;
           wikibase:rank wikibase:PreferredRank .
```

### Preferred rank

Preferred rank marks the statements that should normally be treated as the most relevant when several values exist.

Example:

```text
current population value
current officeholder
officially preferred identifier
```

### Normal rank

Normal rank is the default.

It is used for statements that are valid but are not specially preferred.

### Deprecated rank

Deprecated rank is used for statements considered incorrect, obsolete, or unsuitable for normal use.

Ranks are not confidence scores and do not replace references.

### Truthy values and rank

The `wdt:` representation behaves approximately as follows:

- if preferred statements exist, return preferred values;
- otherwise, return normal-ranked values;
- do not return deprecated values.

The full statement representation may expose statements of all ranks.

---

## 13. Statement Values and Datatypes

Each Wikidata property has an expected datatype.

Common datatypes include:

| Datatype | Example |
|---|---|
| Wikibase item | `wd:Q183` |
| String | `"ABC"` |
| External identifier | `"0000-0002-1825-0097"` |
| Time | date or timestamp |
| Quantity | numeric value with optional unit |
| Globe coordinate | latitude and longitude |
| URL | an IRI |
| Commons media | media filename |
| Monolingual text | text with a language |
| Mathematical expression | mathematical notation |
| Musical notation | music notation |
| Geographic shape | Commons geoshape |
| Tabular data | Commons tabular data |
| Wikibase property | a property entity |
| Wikibase lexeme | a lexeme entity |
| Wikibase form | a form entity |
| Wikibase sense | a sense entity |

Examples:

```text
date of birth (P569)           → time
population (P1082)             → quantity
coordinate location (P625)     → globe coordinate
official website (P856)        → URL
country (P17)                  → item
ORCID iD (P496)                → external identifier
```

A value is not always another Wikidata item.

---

## 14. Entity-Valued Statements

Many Wikidata properties point to another Wikidata entity.

Example:

```sparql
wd:Q42 wdt:P19 wd:Q350 .
```

Here:

```text
subject: Q42
property: P19
value: Q350
```

Common entity-valued properties include:

```text
instance of
subclass of
country
occupation
employer
author
part of
located in the administrative territorial entity
```

Entity values normally use the `wd:` prefix.

---

## 15. Literal-Valued Statements

Some properties point to literal values.

### String

```sparql
?entity wdt:Pxxx ?string .
```

### External identifier

External identifiers are represented as strings in direct values.

```sparql
?researcher wdt:P496 ?orcid .
```

### URL

```sparql
?entity wdt:P856 ?website .
```

### Monolingual text

Monolingual text values include a language tag.

```text
"text"@en
```

Literal values should not be treated as Wikidata entity identifiers.

---

## 16. Time Values

Time values may contain more information than a simple date.

A Wikidata time value may include:

- timestamp;
- precision;
- calendar model;
- timezone information.

Simple access:

```sparql
?entity wdt:P569 ?birthDate .
```

Full statement value:

```sparql
?statement ps:P569 ?birthDate .
```

Detailed value node:

```sparql
?statement psv:P569 ?valueNode .

?valueNode wikibase:timeValue ?date ;
           wikibase:timePrecision ?precision ;
           wikibase:timeCalendarModel ?calendar .
```

Time precision may represent:

```text
year
month
day
decade
century
other levels
```

For example, a value displayed as `1950` may not imply a precise day.

---

## 17. Quantity Values

Quantity values may include:

- amount;
- unit;
- upper bound;
- lower bound;
- normalized amount.

Simple access:

```sparql
?entity wdt:P2048 ?height .
```

Detailed value representation:

```sparql
?statement psv:P2048 ?valueNode .

?valueNode wikibase:quantityAmount ?amount ;
           wikibase:quantityUnit ?unit .
```

Optional bounds:

```sparql
?valueNode wikibase:quantityLowerBound ?lower ;
           wikibase:quantityUpperBound ?upper .
```

Units are represented as Wikidata entities.

Example:

```text
metre
kilogram
square kilometre
United States dollar
```

Normalized values may be accessed through prefixes such as:

```text
wdtn:
psn:
pqn:
prn:
```

---

## 18. Coordinate Values

Coordinate values may include:

- latitude;
- longitude;
- globe;
- precision.

Simple access:

```sparql
?place wdt:P625 ?coordinates .
```

Detailed value representation:

```sparql
?statement psv:P625 ?valueNode .

?valueNode wikibase:geoLatitude ?latitude ;
           wikibase:geoLongitude ?longitude ;
           wikibase:geoGlobe ?globe ;
           wikibase:geoPrecision ?precision .
```

Most coordinates use Earth as the globe, but Wikidata can represent locations on other celestial bodies.

---

## 19. Normalized Values

Some values have normalized representations.

Normalized predicates include:

```text
wdtn:
psn:
pqn:
prn:
```

These are useful for values such as:

- external identifiers converted into URLs;
- quantities converted to normalized units.

Example conceptually:

```sparql
?entity wdtn:P496 ?orcidURL .
```

The original literal value may be available through:

```sparql
?entity wdt:P496 ?orcidString .
```

The normalized representation depends on the property and value type.

---

## 20. Special Values

Wikidata supports two special value states:

```text
unknown value
no value
```

### Unknown value

An unknown value means that a value exists, but its identity is not known.

Example:

```text
a person has a date of birth, but the date is unknown
```

### No value

No value means that the property explicitly does not apply or has no value.

Example:

```text
an entity has no official website
```

These differ from simply having no statement for the property.

The RDF model uses constructs related to:

```sparql
wikibase:SomeValue
wikibase:NoValue
```

Special values are represented using statement-level structures rather than ordinary `wdt:` triples.

---

## 21. Multiple Statements for the Same Property

An entity may have several statements using the same property.

Example:

```text
person
  occupation → writer
  occupation → screenwriter
  occupation → novelist
```

This may reflect:

- multiple simultaneously valid values;
- historical values;
- values applying to different contexts;
- competing claims;
- values from different sources.

Qualifiers and ranks distinguish the meanings of these statements.

Example:

```text
population → 1,000,000
  point in time → 2020

population → 1,100,000
  point in time → 2024
```

The property-value pair alone is insufficient to capture the temporal distinction.

---

## 22. Classification Model

Wikidata commonly distinguishes between instances and classes.

### Instance of

```text
instance of (P31)
```

This connects an individual entity to a class.

Example:

```text
Douglas Adams → instance of → human
```

```sparql
wd:Q42 wdt:P31 wd:Q5 .
```

### Subclass of

```text
subclass of (P279)
```

This connects one class to a more general class.

Example:

```text
university → subclass of → educational institution
```

```sparql
?class wdt:P279 ?parentClass .
```

Conceptually:

```text
individual
  └── instance of
        └── class
              └── subclass of
                    └── broader class
```

Property paths may traverse the class hierarchy:

```sparql
?entity wdt:P31/wdt:P279* ?class .
```

The `P31` and `P279` distinction is central to the Wikidata type model.

---

## 23. Geographic and Administrative Modelling

Wikidata uses several properties for different kinds of geographic relationships.

| Property | Meaning |
|---|---|
| `P17` | country |
| `P131` | located in the administrative territorial entity |
| `P276` | location |
| `P159` | headquarters location |
| `P19` | place of birth |
| `P20` | place of death |
| `P625` | coordinate location |
| `P706` | located in or next to body of water |
| `P361` | part of |

Administrative containment commonly forms a hierarchy:

```text
neighborhood
  → borough
  → city
  → state
  → country
```

This hierarchy is often represented using repeated `P131` relations.

```sparql
?place wdt:P131* ?administrativeArea .
```

`P17` and `P131` model different concepts:

```text
P17   country membership
P131  administrative containment
```

---

## 24. Part–Whole Relations

Several properties can describe part–whole relations.

Common examples include:

| Property | Meaning |
|---|---|
| `P361` | part of |
| `P527` | has part |
| `P2670` | has parts of the class |
| `P131` | administrative containment |
| `P150` | contains the administrative territorial entity |
| `P463` | member of |
| `P355` | subsidiary |

These properties are not interchangeable.

For example:

```text
city → located in administrative entity → state
chapter → part of → book
company → subsidiary → company
person → member of → organization
```

The exact property reflects the semantic nature of the relationship.

---

## 25. Sitelinks

Items may contain sitelinks to pages on Wikimedia projects.

Examples include:

```text
English Wikipedia
German Wikipedia
Wikivoyage
Wikisource
Wikiquote
```

Sitelinks are represented using Schema.org vocabulary.

Example pattern:

```sparql
?article schema:about wd:Q42 ;
         schema:isPartOf <https://en.wikipedia.org/> .
```

The page title or URL can be obtained from the article resource.

Sitelinks are different from entity labels:

```text
label      human-readable entity name
sitelink   link to a Wikimedia project page
```

---

## 26. Labels in RDF

Labels are exposed through RDF predicates such as:

```sparql
rdfs:label
skos:altLabel
schema:description
```

Example:

```sparql
wd:Q42 rdfs:label "Douglas Adams"@en .
```

Aliases may be represented using:

```sparql
skos:altLabel
```

Descriptions may be represented using:

```sparql
schema:description
```

The Wikidata Query Service also provides a label service:

```sparql
SERVICE wikibase:label {
  bd:serviceParam wikibase:language "[AUTO_LANGUAGE],en".
}
```

This service resolves entity variables into corresponding label variables, such as:

```text
?personLabel
?personDescription
```

---

## 27. Property Metadata

Properties are themselves Wikidata entities.

A property can have:

- a label;
- a description;
- aliases;
- datatype;
- constraints;
- examples;
- formatter URLs;
- subject and value type expectations.

Example property entity:

```sparql
wd:P31
```

The property datatype can be accessed through Wikibase ontology terms.

Conceptually:

```sparql
wd:P31 wikibase:propertyType wikibase:WikibaseItem .
```

Property entities may also connect to their RDF predicates through properties such as:

```text
wikibase:directClaim
wikibase:claim
wikibase:statementProperty
wikibase:qualifier
wikibase:reference
```

Conceptual mapping:

```sparql
wd:P31 wikibase:directClaim wdt:P31 ;
       wikibase:claim p:P31 ;
       wikibase:statementProperty ps:P31 ;
       wikibase:qualifier pq:P31 ;
       wikibase:reference pr:P31 .
```

This mapping reflects how one Wikidata property is represented across different RDF layers.

---

## 28. Property Constraints

Wikidata properties may define constraints describing expected modelling practices.

Common constraint types include:

```text
type constraint
value-type constraint
single-value constraint
distinct-values constraint
mandatory qualifier constraint
allowed qualifiers constraint
format constraint
range constraint
conflicts-with constraint
inverse constraint
symmetric constraint
item-requires-statement constraint
```

Constraints are guidance and quality-control mechanisms.

They are not always strict logical rules, and violations may be legitimate exceptions.

Property constraints are themselves modelled as Wikidata statements, often with qualifiers specifying constraint parameters.

---

## 29. Inverse and Related Properties

Some Wikidata properties have inverse or closely related counterparts.

Examples:

```text
parent organization ↔ subsidiary
part of ↔ has part
contains administrative entity ↔ located in administrative entity
author ↔ author of
```

However, inverse statements are not always explicitly materialized.

For example:

```text
A part of B
```

does not guarantee that the graph also contains:

```text
B has part A
```

The data model permits asymmetric coverage, even when two properties are conceptually inverses.

---

## 30. Complete Statement Graph

A full statement can be visualized as follows:

```text
subject entity
  │
  └── p:Pxxx
        │
        ▼
   statement node
        │
        ├── ps:Pxxx ───────────────► main value
        │
        ├── pq:Pyyy ───────────────► qualifier value
        │
        ├── pq:Pzzz ───────────────► qualifier value
        │
        ├── wikibase:rank ─────────► rank
        │
        └── prov:wasDerivedFrom
                  │
                  ▼
             reference node
                  │
                  ├── pr:Paaa ─────► reference value
                  └── pr:Pbbb ─────► reference value
```

Example:

```sparql
wd:Qxxx p:P39 ?statement .

?statement ps:P39 wd:Qyyy ;
           pq:P580 ?start ;
           pq:P582 ?end ;
           wikibase:rank wikibase:NormalRank ;
           prov:wasDerivedFrom ?reference .

?reference pr:P248 ?source ;
           pr:P813 ?retrieved .
```

---

## 31. Simple and Detailed Value Representations

Wikidata RDF commonly provides two representations of a value.

### Simple value

```sparql
?statement ps:Pxxx ?value .
```

The simple value is usually sufficient for direct comparison or display.

### Detailed value node

```sparql
?statement psv:Pxxx ?valueNode .
```

The detailed node exposes additional metadata.

Examples:

```text
time precision
calendar model
quantity unit
quantity bounds
coordinate precision
globe
```

Equivalent patterns exist for qualifiers and references:

```text
pq:   simple qualifier value
pqv:  detailed qualifier value

pr:   simple reference value
prv:  detailed reference value
```

Normalized forms use:

```text
psn:
pqn:
prn:
```

---

## 32. Truthy Versus Complete Representation

The relationship between the simplified and complete models can be summarized as follows.

### Simplified representation

```sparql
wd:Q42 wdt:P19 wd:Q350 .
```

Properties:

```text
compact
easy to query
best-ranked values only
no statement metadata
```

### Complete representation

```sparql
wd:Q42 p:P19 ?statement .
?statement ps:P19 wd:Q350 .
```

Properties:

```text
preserves statement identity
supports qualifiers
supports references
supports ranks
supports detailed values
may include historical or deprecated statements
```

The simplified triple is derived from the full statement representation.

It should not be interpreted as the complete native structure of the Wikidata assertion.

---

## 33. Compact Prefix Map

```text
ENTITY
wd:Q42

PROPERTY ENTITY
wd:P19

DIRECT/TRUTHY VALUE
wd:Q42 wdt:P19 wd:Q350

ENTITY TO STATEMENT
wd:Q42 p:P19 ?statement

MAIN STATEMENT VALUE
?statement ps:P19 wd:Q350

QUALIFIER
?statement pq:P580 ?start

REFERENCE NODE
?statement prov:wasDerivedFrom ?reference

REFERENCE VALUE
?reference pr:P248 ?source

STATEMENT RANK
?statement wikibase:rank wikibase:PreferredRank

DETAILED MAIN VALUE
?statement psv:Pxxx ?valueNode

DETAILED QUALIFIER VALUE
?statement pqv:Pxxx ?valueNode

DETAILED REFERENCE VALUE
?reference prv:Pxxx ?valueNode
```

## Core Modelling Rule

Use the RDF layer that corresponds to the information represented in Wikidata:

```text
Simple, best-ranked property value
    → wdt:

Complete statement
    → p: + ps:

Statement qualifier
    → p: + ps: + pq:

Statement reference
    → p: + ps: + prov:wasDerivedFrom + pr:

Statement rank
    → p: + ps: + wikibase:rank

Detailed time, quantity, or coordinate value
    → psv:, pqv:, or prv:
```

The direct `wdt:` representation is a simplified view of Wikidata statements. The full statement representation preserves qualifiers, references, ranks, historical values, and other statement-level information.
