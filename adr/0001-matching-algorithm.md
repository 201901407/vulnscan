# 0001. Matching: judge assigns each finding by root cause

Status: Accepted (replaces the earlier "rules reject, judge accepts" draft)

## Context

Recall needs a yes/no answer to "are these two findings the same vulnerability?".
The answer must hold on any app, whether the reference list is prose, structured,
or absent (student scored against teacher).

No single field identifies a vulnerability: type labels are noisy, one location
can hold several bugs, one bug can span several locations, and wording varies.

## Decision

Anchor on root cause. Two findings match when one fix would resolve both.

1. Load both sides into the same finding shape. The reference is ground truth if
   present, otherwise the teacher's findings.
2. A judge model sees the full reference list and a batch of findings, all
   fields. For each finding it returns one reference entry or none, with a
   one-line reason.
   A finding the judge leaves unanswered, or assigns to an entry that does not
   exist, is treated as unassigned and counted in the run.
3. Recall = reference entries with at least one finding assigned / total entries.
   Precision = findings assigned / total findings.

The judge is a fixed model, never the student. It has its own config entry and
defaults to the most capable model configured (the teacher). Its temperature is
a config value, default 0. Where a provider advises against low temperatures
for a model, the provider's value is used; Google advises 1.0 for all Gemini 3
models and warns that lower values can cause looping or worse reasoning.
Assignments and reasons are saved with each run.

## Why

- No field acts as a gate, so one noisy field cannot lose a match.
- Each finding gets at most one entry, so a vague finding cannot claim several.
- One prompt handles any reference shape and any app; there are no thresholds.
- It is the smallest design that works end to end.

## Rejected

- Rules on type and location: a single field decides, and prose lists lack them.
- Embedding similarity: ignores location; needs a threshold tuned on one app.

## Deferred (with trigger)

- Cheap candidate filter: when the reference list no longer fits in a prompt.
- Fixed category list: if filtering or per-category reporting is needed.
- Per-pair verdict cache: when the same runs are re-scored often.

## Consequences

- A model grades models. The saved assignments of reported runs are audited and
  the agreement rate is stated next to the recall numbers. Where no reviewer
  with the security background is available, the audit is done by a second,
  stronger model with access to the app's code, and is reported as such, not as
  a human review.
- A judge that must run above temperature 0 is less repeatable. Its saved
  assignments are the record of each run, and the hand review matters more.
