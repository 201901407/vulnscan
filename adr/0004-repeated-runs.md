# 0004. Measuring lift: repeat runs, score each separately

Status: Accepted

## Context

Model output varies between runs. With a short reference list, one finding
appearing or not moves recall by several points, so one run per arm cannot
separate a real lift from chance.

## Decision

1. Run each student arm (baseline, with lessons) N times. N is in config; the
   default is 3.
2. Score every run separately with the same judge and reference (ADR 0001).
3. Report mean and range of recall and precision per arm.
4. Lift = mean post-lesson recall minus mean baseline recall.
5. If the two ranges overlap, say the lift is not distinguishable from noise.
   With one run per arm, say that noise is unknown; no verdict is given.
6. Temperature is set per model in config. Scans and lesson writing default to
   0.2; both arms of a student always use the same value. The judge defaults
   to 0 (ADR 0001). A provider's stated requirement overrides these defaults:
   Gemini 3 models run at 1.0.

## Why

- The spread across runs is what shows whether a lift is real.
- Each run is scored on its own, so no extra model step can alter findings.
- A low, non-zero temperature keeps runs repeatable without limiting a model to
  its single most likely answer, and makes the spread across runs meaningful.

## Rejected

- One run per arm: no measure of noise.
- Student merges its own runs into one output: hides the spread, adds an
  unreliable rewrite step, and a union of runs raises baseline recall.

## Deferred (with trigger)

- Merged output across runs (e.g. keep findings seen in most runs): if wanted as
  a product feature to cut false positives. To be done by the matcher in code.

## Consequences

- Student and judge calls scale with N; provider rate limits may slow runs.
