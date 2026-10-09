# 0012. Reference list: one YAML format, rule-based converter

Status: Accepted

## Context

Students are scored against a reference list (ADR 0001). The assignment gives
one as prose in a README, and for an unseen app it may arrive in another shape.
The list is the answer key, so it must be identical on every run.

## Decision

1. The pipeline reads one format: a YAML list (JSON also loads). Each entry
   needs `title` and `description`, and may carry any other finding field
   (ADR 0002).
2. A separate command converts a published list into that format using rules,
   never a model. It writes a file to be reviewed before use, and refuses to
   overwrite an existing one.
3. One converter to start, for Markdown lists:
   - each numbered or bulleted item is one entry;
   - a bold lead-in, or the text before the first colon, is the title;
   - the rest is the description; with neither, the item is both;
   - text is copied exactly;
   - an optional section name limits reading to items under matching headings.
4. Converters are registered by file type. Input that no converter reads, or
   that yields no entries, is an error asking for the YAML to be written by hand.

## Why

- Rules give the same output every time; a model could reword, merge or drop
  entries of the answer key.
- Conversion outside the scoring run means the reference cannot change between
  runs.
- Markdown lists are how such lists are most often published.

## Rejected

- Model-based conversion: not deterministic.
- Parsing arbitrary formats: cannot be anticipated; fail loudly instead.

## Consequences

- A list in another shape needs a new converter or hand conversion.
