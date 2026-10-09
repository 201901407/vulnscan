# 0003. Evidence verification: quoted code must exist in the app

Status: Accepted

## Context

Models can invent code. A finding whose evidence does not exist in the app cannot
be trusted, and it should not earn recall or feed a lesson.

## Decision

After every scan, code checks each finding's `evidence` against the ingested app.

1. Remove whitespace on both sides and ignore trivial quoted lines (a few
   characters, such as a lone brace). The evidence is found when at least
   `min_match` of the remaining lines appear. A newline the model wrote as the
   two characters `\n` separates lines like a real one. `min_match` is in config; the
   default is 50%.
2. Search the named file first, then the rest of the app.
3. Label the result:
   - `verified`: found in the named file.
   - `relocated`: found elsewhere. A location mistake; the finding stands.
   - `unverified`: found nowhere.
4. Config `evidence_check` sets what happens to `unverified` findings:
   `off`, `flag`, or `exclude` (default). Excluded findings stay in the saved run
   but are not scored and are not used for lessons.

The same setting applies to the teacher and to every student run.

## Why

- Loose comparison: models reflow and trim code when quoting, and a formatting
  difference is not a hallucination.
- Keep, do not delete: the report can show how many findings failed.
- Same rule for all runs keeps the before/after comparison fair.

## Rejected

- Exact byte match: fails real findings on formatting.
- Deleting failed findings: hides the hallucination rate.

## Consequences

- This proves the code exists, not that it is vulnerable.
- Reports state the count of unverified findings per run.
