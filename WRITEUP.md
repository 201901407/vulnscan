# Astra take-home: design and results

On InsecureShop, general lessons written by a frontier model raised a small open model's recall from 54.4% to 75.4%. This was measured over three runs per arm against the 19 vulnerabilities documented in the InsecureShop README.

The unchanged tool was also run once on a second app, OVAA, where recall went from 55.6% to 88.9%.

Each design choice is recorded with its reasoning in the repository's `adr/` folder.

## 1. Result

The student's mean recall rose by 21.1 percentage points with lessons, and the two ranges do not overlap.

| Scan | Runs (of 19) | Mean recall | Mean precision |
| --- | --- | --- | --- |
| Student without lessons | 10, 10, 11 | 54.4% | 97.8% |
| Student with lessons | 14, 14, 15 | 75.4% | 95.6% |
| Teacher | 18 | 94.7% | |

Recall is the share of the 19 documented vulnerabilities that at least one finding matched.

How it was measured:

- **Three runs per arm**, each scored separately, because model output varies between runs.
- **One variable.** Both arms use the same prompt, settings and split of the app. Only the lessons differ.
- **Precision held**, so the lessons did not work by making the student flag everything.
- **Evidence checked.** A finding counts only if the code it quotes exists in the app.

Four vulnerabilities were never found without lessons and were found in every run with them: arbitrary code execution, access to protected components, FileProvider paths, and insecure `setResult`.

## 2. What was built

The tool takes an APK or a decompiled folder and runs six stages.

1. **Ingest.** Load the manifest, the app's own code, security-relevant resources and the names of bundled dependencies. Library code and static files are left out.
2. **Teacher scan.** The frontier model returns findings in a fixed shape: category, type, severity, location, quoted evidence and a description.
3. **Evidence check.** Code confirms that each finding's quoted evidence exists in the app.
4. **Lessons.** In one pass, the teacher turns its verified findings into general lessons: a pattern, the platform identifiers that signal it, why it is exploitable, and when it is safe.
5. **Student scans.** The open model scans with the same prompt, with and without the lessons.
6. **Matching and scoring.** Each finding is matched to the reference list, and recall and precision are computed.

Lessons are kept general in two ways. Before the teacher writes them, code replaces the app's own names with placeholders. Afterwards, code rejects any lesson that still contains an app-specific name. The ground-truth list is never used to write lessons.

Nothing in the code is specific to InsecureShop. Models, app path and thresholds are in one config file, and adding a model is a config change.

## 3. Match function

**Definition.** Two findings are the same vulnerability when they share a root cause: one fix would resolve both.

### Why root cause, and not a field

A match rule needs something to compare. Each candidate field fails alone:

| Field | Why it cannot decide alone |
| --- | --- |
| Type or category | Labels are noisy. Models name the same bug differently, and one bug can fairly carry several labels |
| Location | One class can hold several bugs, and one bug can span several classes |
| Text | The same bug is described in different words |

Each field is partial evidence about the root cause. The match function therefore gives all of them to a judge and lets no single one accept or reject a pair.

### Input: one shape for both sides

Model findings and reference entries are loaded into the same schema, so the matcher never needs to know where either side came from.

| Field | Model finding | Reference entry | Notes |
| --- | --- | --- | --- |
| `id` | Set by code (`F1`, `F2`, ...) | Set by code (`R1`, `R2`, ...) | Never produced by a model |
| `title` | Required | Required | One line |
| `description` | Required | Required | Why it is exploitable |
| `category` | Required | Optional | One OWASP MASVS group, or `other`. An unknown value is rewritten to `other` |
| `type` | Required | Optional | Short free-text name of the weakness |
| `severity` | Required | Optional | `critical`, `high`, `medium`, `low` or `info` |
| `locations` | Required | Optional | List of `{file, symbol, line}` |
| `evidence` | Required | Optional | Code quoted from the app |
| `cwe` | Optional | Optional | Format-checked only (`CWE-<n>`) |

The InsecureShop README gives one line per vulnerability, so its 19 reference entries carry only `title` and `description`. A model finding that lacks a required field is dropped as malformed and counted in the report.

### Algorithm

1. **Filter.** Only findings that passed the evidence check are scored. A finding whose quoted code is not in the app is excluded before matching.
2. **Batch.** Findings are sent to the judge in batches of 20 (a config value), each batch together with the full reference list.
3. **Judge.** For every finding in the batch, the judge returns the one reference entry with the same root cause, or `null`, plus a one-line reason. It is given every field except internal bookkeeping; in particular it cannot see which arm (with or without lessons) a finding came from.
4. **Validate.** Code checks the reply. A finding with no answer, or an answer naming an entry that does not exist, is treated as unassigned and counted. An unparseable reply is retried once.
5. **Score.**

```
recall    = reference entries with at least one finding assigned / all reference entries
precision = findings assigned to an entry / findings judged
```

The judge's instructions state the test directly: share a root cause, weigh every field together, different wording does not prevent a match, and the same category or file does not make one.

The judge's reply has this shape:

```json
{"assignments": [
  {"finding_id": "F12", "reference_id": "R5", "reason": "Both describe an embedded intent passed to startActivity without validation."},
  {"finding_id": "F2",  "reference_id": null, "reason": "No reference entry covers a debuggable build."}
]}
```

A real pair from the reported run, to show what the judge decides:

| | Student finding | Reference entry R5 |
| --- | --- | --- |
| Title | Intent redirection via nested Intent extra | Access to Protected Components |
| Location | `WebView2Activity.java` | Not given |
| Evidence or description | `getParcelableExtra("extra_intent")` passed to `startActivity` | "The app takes an embedded Intent and passes it to method like startActivity" |

Different titles, no shared location field, same root cause: the judge matched them.

### Properties that code enforces

- **One entry per finding.** A finding maps to at most one entry, so a vague finding cannot claim several.
- **Duplicates count once.** Several findings on the same entry add one to recall.
- **The judge is never the student.** Config validation rejects a run where the judge is listed as a student.
- **One judge per comparison.** The same judge model and prompt score every run being compared.
- **Auditable.** Each scan's assignments and reasons are saved as `<scan>.match.json`.
- **No ground truth needed.** Without a reference file, the teacher's verified findings become the reference, and the report labels recall as agreement with the teacher.

### Rejected alternatives

| Approach | Why not |
| --- | --- |
| Rules on type and location | One field would decide, and a prose reference list has neither |
| Embedding similarity | Ignores location, and needs a threshold tuned on one app |
| Rules that discard pairs first, judge decides the rest | Considered and deferred. A single noisy field could still discard a true match, and at this size the judge can read everything. It becomes necessary when the reference list no longer fits in one prompt |

### How well the judge did

A model grading models is the weak point, so a second model with access to the app's code audited all 133 assignments. It is not a human review.

| Scan | Assignments | Disagreements |
| --- | --- | --- |
| Teacher | 23 | 0 |
| Student without lessons | 41 | 17 |
| Student with lessons | 69 | 9 |
| **Total** | **133** | **26 (agreement 80.5%)** |

Every assignment behind the four gained vulnerabilities was confirmed. The disagreements were of two kinds:

- **Same pattern, different component.** For example, a finding about a provider class that the manifest never registers was credited to the entry for the real exported provider.
- **Right bug, wrong entry.** Several entries describe "load an arbitrary URL in a WebView" in different activities, and the judge often picked the wrong one of them.

Both trace to the reference list: one-line entries that name no class give the judge nothing to separate similar bugs with. Applying the audit's corrections lowers baseline recall to 43.9% and raises the lift to 31.6 points. The judge's 21.1 points is reported as the result because it is the smaller figure and comes from the pipeline as designed.

## 4. Models used and why

| Role | Model | Why |
| --- | --- | --- |
| Teacher | Claude Opus 5.5 | The teacher sets the ceiling for what the student can be taught, so it should be the strongest model available |
| Student | `openai/gpt-oss-20b` | A small open-weight model is the realistic case for running cheaply at scale, and a weaker starting point leaves room to measure a lift |
| Judge | Gemini 3 Flash (preview) | A different model from both the teacher and the student, so no model grades its own output |

Any of the three can be swapped in the config file.

## 5. A real app with 1M+ lines of code

What the tool does today:

- Sends only the app's own code. Library code is dropped and dependencies are passed by name.
- Strips build-generated files and unreadable compiler metadata.
- Splits the code across several calls when it exceeds a model's input limit, with the manifest in each call.
- Gives each call only the lessons relevant to the code in it.
- Saves each stage, so a long run can stop and resume.

The known limit is that splitting by file can miss a bug that spans files in different calls.

What I would add at that scale:

1. Rank code by attack surface, starting from the entry points the manifest declares.
2. Follow call paths from those entry points instead of reading every file.
3. Run a cheap pattern pre-filter, so only suspicious code reaches the model.
4. Summarise modules first, then send the risky ones in full.
5. Merge duplicate findings across calls.
6. Cache results by file hash, so unchanged code is not scanned again.

## 6. Dynamic analysis

One bug type that dynamic analysis catches and static analysis cannot: a flaw in the backend's behaviour. The APK contains no backend code, so such a flaw only shows when the app runs against a live server. A typical example is broken authorization, where an API returns another user's order when the ID in the request is changed. Dynamic analysis reaches these flaws as long as they show up in what the server returns or does.

**How the system extends.** The static pipeline's findings become hypotheses for an agent to test on a running app. The finding shape, the evidence rule and the matching stay the same. Evidence becomes a runtime observation instead of quoted code.

**Confirming a vulnerability.** A crash only shows that something broke. The agent needs an oracle for each bug class: an observable effect that can only happen if the bug is real. I would plant canaries, which are unique markers placed in a private file and in a second test account's data, and watch where they appear: in intercepted traffic, in shared storage, in the log, or in a helper "attacker" app installed on the same device. For the authorization example, account A's session fetching account B's canary is the proof. A finding is confirmed only when it reproduces from a clean state.

**Reaching the right screen.** The agent reads the screen through the accessibility tree and acts by tapping and typing, with seeded test accounts for login. It should not tap its way everywhere. The manifest and the static findings name the entry points, so exported components and deep links can be launched directly with a crafted intent. Coverage is measured against what static analysis says exists: the share of declared activities reached, and the share of API endpoints found in the code that were seen in traffic.

**Scale.** Each run starts from a snapshot of an emulator with the app installed, the proxy certificate trusted and the accounts seeded. The emulator is discarded afterwards, so no state leaks between runs. Runs are independent jobs on a pool of workers, each with a time limit. A flaky run is retried, and each step's result is saved so that a retry repeats only what failed.

**SSL pinning.** Traffic goes through an intercepting proxy whose certificate the emulator trusts. Pinning is bypassed by hooking the app's certificate checks at runtime, or by repackaging the app with pinning removed. The things most likely to break:

- Pinning done in native code or in a non-standard network stack, which generic hooks miss.
- Tamper, root or hook detection that makes the app refuse to run.
- Traffic that never reaches the proxy, such as protocols that ignore the system proxy setting.

When a bypass fails, the run should report that traffic was not visible, not that nothing was found.

### Architecture

```
+---------------------------+        +-------------------------------+
|  Static pipeline          |        |  Agent                        |
|  findings = hypotheses    | -----> |  plans steps, picks an oracle |
|  entry points from the    |        |  for each hypothesis          |
|  manifest                 |        +-------------------------------+
+---------------------------+              |                  ^
                                           | taps, text,      | screen tree,
                                           | crafted intents  | traffic, logs,
                                           v                  | files
+----------------------------------------------------------------------+
|  One disposable worker                                               |
|                                                                      |
|   Emulator restored from a snapshot                                  |
|     - target app, with pinning bypassed                              |
|     - helper "attacker" app                                          |
|     - seeded test accounts and canary data                           |
|              |                                                       |
|              | all app traffic                                       |
|              v                                                       |
|   Intercepting proxy  <---------->  Live backend (test accounts)     |
+----------------------------------------------------------------------+
                                           |
                                           v
                      +--------------------------------------+
                      |  Oracles                             |
                      |  did a canary appear where it        |
                      |  should not?                         |
                      +--------------------------------------+
                                           |
                                           v
                      +--------------------------------------+
                      |  Confirmed findings, in the same     |
                      |  shape as static findings            |
                      |  -> matching and report              |
                      +--------------------------------------+
```

## 7. A second app

To check that nothing depends on InsecureShop, I ran the unchanged tool on OVAA, Oversecured's deliberately vulnerable Android app, which documents 18 vulnerabilities. This is one run per arm, so it is a check and not a measurement.

| Scan | Found (of 18) | Recall | Precision |
| --- | --- | --- | --- |
| Teacher | 18 | 100% | 67.9% |
| Student without lessons | 10 | 55.6% | 75.0% |
| Student with lessons | 16 | 88.9% | 75.0% |

**Real findings versus noise.** The teacher reported 28 findings, and all 28 quoted code that exists in the app. 19 matched the 18 documented vulnerabilities. The other 9 are issues the list does not include, such as a debuggable build, cleartext HTTP and AES in ECB mode. These are genuine weaknesses outside the list, mostly of lower severity, and not noise.

**What broke.** No code change was needed to run a new app. Four things surfaced:

- **A masking gap.** OVAA's package words appeared inside URLs and other strings that the masker did not cover. I fixed this with a general rule: the words of an app's package that no bundled library shares are masked wherever they sit inside an identifier, path or URL.
- **The reference converter** expects a title and a description per entry. OVAA's list is one sentence per entry, so each sentence became both.
- **One compiler-generated file** was kept as app code. It is harmless, and a config pattern would skip it.
- **The judge once left out findings that matched nothing**, instead of answering "none". Code treats a missing answer as no match and counts it, so the score was unaffected.

**What it suggests.** The student's unaided recall was nearly the same on both apps (54.4% and 55.6%). The judge was also more accurate here: of 68 assignments, a second model disputed one. OVAA's entries name the class involved, which supports the point in section 3 that a reference list with locations makes the judge reliable.

## 8. Limits

- **These runs cannot show that the lessons generalize.** On both apps, the lessons were written from the same app the student was then rescanned on. Only applying one app's lessons to a different app can test whether they transfer.
- **InsecureShop is public** and widely written up, so the teacher may have recalled some of it instead of finding it.
- **Three runs per arm** give a range, not a statistical test.
- **The judge is a model**, and so is its auditor.
- **A finding can satisfy only one entry**, so a model that reports two related bugs together is credited for one. The teacher's single miss is this case.
- **The reference list is incomplete**, so real issues outside the 19 entries count against precision.
- **The evidence check** shows that quoted code exists, not that it is vulnerable.
