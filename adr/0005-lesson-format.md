# 0005. Lesson format: stored structured, shown to the model as plain text

Status: Accepted

## Context

Lessons are written by the teacher and read by the student model. They must be
general patterns, never tied to the scanned app, and understandable by any LLM.

## Decision

A lesson is a pattern, not an instance: it has no location and no code from the app.

Stored as one JSON record per lesson:

| Field | Purpose |
| --- | --- |
| `category` | Same list as findings (ADR 0002) |
| `cwe` | Optional weakness type |
| `title` | Short name of the pattern |
| `pattern` | What to look for, stated generally |
| `signals` | Platform-level cues: framework methods, manifest attributes |
| `why` | Why it is exploitable |
| `not_when` | When the pattern is safe |

- One template in code renders each record to short labelled text (about 100
  words) for the prompt. Every student model sees the same text.
- Each lesson is self-contained: no reference to other lessons or to the app.
- Lessons per call: when all lessons fit a set share of the model's input
  budget (config, default a quarter), every call gets all of them. Otherwise a
  call gets only the lessons whose `signals` appear in that call's files, most
  matching signals first, up to the share. Lessons matching only the manifest
  go with the first call. Each scan records which lessons each call received.
- The same share is reserved in the baseline arm, so both arms split the app
  into identical calls and differ only by the lessons shown.
- `signals` are exact platform identifiers, one per entry. Matching uses the
  code-like tokens in a signal and ignores plain words.
- Lessons sit in their own delimited block. The prompt says they are patterns to
  check for, and that only issues present in the given code are to be reported.
- Leak guard: a lesson containing a name the scanned app defines (class, package,
  string, URL) is rejected by code. Platform names are allowed.
- Provenance: each finding sent to the teacher carries a short ID, and the
  teacher returns the IDs it drew on with each lesson. Code checks and stores
  them; the student never sees them. Self-reported, so used for audit only.

## Why

- Structured storage lets code validate, filter and leak-check lessons.
- Plain text is what models follow most reliably, and it needs no vendor feature.
- Reasons and concrete cues help a small model generalise and recognise the pattern.
- `not_when` limits over-flagging, which would raise recall at precision's expense.

## Rejected

- Reusing the finding schema: its location and evidence are what lessons must omit.
- Passing raw JSON to the student: harder for small models to follow.

## Consequences

- A lesson whose signals match nothing in the app is never shown. The report
  states how many lessons reached the student.
- Reserving room for lessons means more calls per scan in both arms.

## Deferred (with trigger)

- Made-up code examples per lesson: to test if lessons prove too abstract. Risks
  disguised app code and over-anchoring.
- Turning lessons and verified findings into fine-tuning data.
