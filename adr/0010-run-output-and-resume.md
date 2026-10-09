# 0010. Run output and resume: one folder per run, one file per stage

Status: Accepted

## Context

The recall numbers must be auditable (ADR 0001, 0003, 0009 all say results are
"saved with the run"). A run makes many model calls under provider rate limits, so it
can die midway, and repeating finished calls wastes credit.

## Decision

1. Each run writes to its own folder under the configured runs directory.
2. Each stage saves its result as one JSON file as soon as it finishes:

   ```
   runs/<timestamp>/
     config.yaml                        the config used
     teacher.scan.json                  teacher findings, evidence status
     teacher.match.json                 only when a ground truth is given
     lessons.json                       kept and dropped lessons
     lessons.txt                        all kept lessons, as rendered for prompts
     <student>.<arm>.<n>.scan.json      arm is baseline or lessons
     <student>.<arm>.<n>.match.json     judge assignments and reasons
     report.json, report.md
   ```

3. Resume: given an existing run folder, a stage whose file exists is loaded
   instead of run. A resumed run uses the config saved in that folder.

## Why

- One file per stage makes every number traceable to the output behind it.
- Resume falls out of the same files, so it needs no extra state.
- Using the saved config stops a resumed run mixing results from two setups.

## Consequences

- To redo a stage, delete its file and resume.
- Config never contains keys (ADR 0006), so the saved copy is safe to share.
