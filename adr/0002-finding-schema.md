# 0002. Finding schema: flat, standard vocabulary, room for custom values

Status: Accepted

## Context

Teacher, student and reference entries all load into one finding shape (ADR 0001).
It should use industry vocabulary, allow bug types we did not anticipate, and be
simple enough for a small open model to emit without breaking.

## Decision

A flat JSON object. Fields map onto SARIF 2.1.0 concepts.

| Field | Required | Rule |
| --- | --- | --- |
| `title` | Yes | One line |
| `category` | Yes | One value from the config list, or `other` |
| `type` | Yes | Short free-text name of the specific weakness |
| `cwe` | No | Format check only (`CWE-` plus digits) |
| `severity` | Yes | critical, high, medium, low, info (CVSS bands) |
| `locations` | Models: yes. Reference: no | List of file, class or component, optional line |
| `evidence` | Models: yes. Reference: no | Code quoted from the app (checked, ADR 0003) |
| `description` | Yes | Why it is exploitable |
| `extra` | No | Free-form; e.g. a CVE ID for a vulnerable library |

- The default category list is the eight OWASP MASVS control groups. It lives in
  config, so another platform can swap in its own standard.
- An unknown category is rewritten to `other`; the finding is kept.
- Code, not the model, adds the finding ID, model name and run.

## Why

- Flat beats nested: small models break deep structures, and a broken output
  looks like a missed bug.
- An enforced category makes results reportable per group and gives lessons a
  general structure. Matching does not depend on it, so a wrong label costs no
  recall.
- MASVS is a published, widely adopted mobile standard, so the list is not shaped
  by any one app.
- `type` and `other` leave room for what the list does not cover.
- CWE is too large to enforce and small models mislabel it, so it is optional.
  CVE identifies a disclosed bug in a product version, so it is not a type field.

## Rejected

- Emit SARIF directly: too nested for a small model. An exporter can come later.
- CWE as the enforced field: 900+ values, several valid per bug.
- Free-text type only: nothing to group or report by.

## Consequences

- MASVS groups are coarse; most Android-specific bugs fall under "platform".
- We borrow MASVS group names as buckets. This is not a MASVS compliance claim.
