# Assignment Writeup

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

No single field can decide a match:

| Field | Why it fails alone |
| --- | --- |
| Type or category | Models name the same bug differently, and one bug can fairly carry several labels |
| Location | One class can hold several bugs, and one bug can span several classes |
| Text | The same bug is described in different words |

Each field is partial evidence about the root cause, so all of them go to a judge and none can accept or reject a pair alone.

### Input: one shape for both sides

Model findings and reference entries are loaded into the same schema, so the matcher does not need to know where either side came from.

| Field | Model finding | Reference entry | Notes |
| --- | --- | --- | --- |
| `id` | `F1`, `F2`, ... | `R1`, `R2`, ... | Set by code, never by a model |
| `title`, `description` | Required | Required | |
| `category` | Required | Optional | An OWASP MASVS group or `other`; unknown values become `other` |
| `type` | Required | Optional | Short free-text name of the weakness |
| `severity` | Required | Optional | `critical` to `info` |
| `locations` | Required | Optional | List of `{file, symbol, line}` |
| `evidence` | Required | Optional | Code quoted from the app |
| `cwe` | Optional | Optional | Format-checked only |

InsecureShop's README gives one line per vulnerability, so its 19 entries carry only a title and a description. A model finding missing a required field is dropped and counted.

### Algorithm

1. **Filter.** Only findings that passed the evidence check are scored.
2. **Batch.** Findings go to the judge 20 at a time (a config value), each batch with the full reference list.
3. **Judge.** For each finding the judge returns the one entry with the same root cause, or `null`, with a one-line reason. It sees every field except bookkeeping, so it cannot tell which arm a finding came from. Its instructions state the test: weigh all fields together, different wording does not prevent a match, and the same category or file does not make one.
4. **Validate.** A finding with no answer, or an answer naming a non-existent entry, is treated as unassigned and counted. An unparseable reply is retried once.
5. **Score.**

```
recall    = reference entries with at least one finding assigned / all reference entries
precision = findings assigned to an entry / findings judged
```

The judge's reply:

```json
{"assignments": [
  {"finding_id": "F12", "reference_id": "R5", "reason": "Both pass an embedded intent to startActivity unchecked."},
  {"finding_id": "F2",  "reference_id": null, "reason": "No entry covers a debuggable build."}
]}
```

An example from the reported run: the student's "Intent redirection via nested Intent extra" in `WebView2Activity.java` was matched to the entry "Access to Protected Components", which names no location. The titles differ and there is no shared location field, but the root cause is the same.

Code enforces four properties around the judge:

- **One entry per finding**, so a vague finding cannot claim several, and several findings on one entry count once.
- **The judge is never a student**, and the same judge and prompt score every run being compared.
- **Every assignment is saved** with its reason, as `<scan>.match.json`.
- **No ground truth is needed.** Without a reference file, the teacher's verified findings become the reference, and the report labels recall as agreement with the teacher.

### Rejected alternatives

| Approach | Why not |
| --- | --- |
| Rules on type and location | One field would decide, and a prose reference list has neither |
| Embedding similarity | Ignores location, and needs a threshold tuned on one app |
| Rules discard pairs first, judge decides the rest | Deferred. One noisy field could still discard a true match. It becomes necessary when the reference list no longer fits in one prompt |

### How well the judge did

A model grading models is the weak point, so a second model with access to the app's code audited all 133 assignments. It is not a human review.

| Scan | Assignments | Disagreements |
| --- | --- | --- |
| Teacher | 23 | 0 |
| Student without lessons | 41 | 17 |
| Student with lessons | 69 | 9 |
| **Total** | **133** | **26 (agreement 80.5%)** |

Every assignment behind the four gained vulnerabilities was confirmed. The disagreements were of two kinds: a finding credited to an entry for a similar bug in a different component, and a finding placed on the wrong one of several entries that all describe loading an arbitrary URL in a WebView. Both trace to a reference list whose one-line entries name no class.

With the audit's corrections, baseline recall falls to 43.9% and the lift rises to 31.6 points. The judge's 21.1 points is reported because it is the smaller figure and comes from the pipeline as designed.

## 4. Models used and why

| Role | Model | Why |
| --- | --- | --- |
| Teacher | Claude Opus 5.5 | The teacher sets the ceiling for what the student can be taught, so it should be the strongest model available |
| Student | `openai/gpt-oss-20b` | A small open-weight model is the realistic case for running cheaply at scale, and a weaker starting point leaves room to measure a lift |
| Judge | Gemini 3 Flash (preview) | A different model from both the teacher and the student, so no model grades its own output |

Any of the three can be swapped in the config file.

## 5. A real app with 1M+ lines of code

The tool reads every file of the app's own code and splits the files across calls by size. That is sound for a small app and wrong for a large one.

### What the tool does today

Ingest cuts the input down before any model sees it: library code is dropped and dependencies are passed by name, and build-generated files and unreadable compiler metadata are stripped. If the remaining code exceeds a model's input limit, whole files are packed into as many calls as needed, with the manifest in each. Each call gets only the lessons whose signals appear in its files, and every stage is saved so a long run can resume.

### Why this stops working

Splitting by file treats all code as equally worth reading. At scale that fails in two ways:

- **Most of the budget goes to code no attacker can reach.** A large app has a few hundred places where outside data enters and a great deal of internal code behind them.
- **Bugs get cut in half.** A vulnerability is usually a path: untrusted data enters in one place and reaches a dangerous call in another. When the two ends land in different calls, no call contains the bug.

### What I would do instead

1. **Start from the attack surface.** That is every place attacker-controlled data can enter: exported components, deep links, content providers and WebView bridges, most of them declared in the manifest. Code is ranked by how close it sits to one of these, and scanned in that order.
2. **Follow the data, not the file listing.** A call graph from each entry point gives the paths from untrusted input to sensitive calls. The path replaces the file as the unit of analysis, which keeps both ends of a bug together.
3. **Use a funnel.** A cheap static pass (pattern rules or taint tracking) proposes candidate paths across the whole codebase, and the model judges only those. Pipelines built on CodeQL or Semgrep work this way.
4. **Let the model fetch its own context.** Give it tools to search, open a definition and list callers, so it pulls in what each candidate needs. Agent-based systems such as Google's Big Sleep do this, and it removes the chunking problem instead of tuning it.
5. **Analyse once, reuse.** Summarise each module once and consult the summary before opening the code, as Meta's Infer and Mariana Trench do with function summaries.
6. **Scan only what changed.** Cache results by file hash, so a new version costs only its differences.

Duplicate findings from overlapping paths would also need merging. None of this is built: the assignment asks for a working slice, and these matter only at a scale the test apps do not reach.

## 6. Dynamic analysis

Static analysis reads the app; it never sees the server. So one bug type it cannot catch is a flaw in the backend's behaviour, such as broken authorization, where an API returns another user's order when the ID in the request is changed. The APK contains no backend code, and the flaw shows only when the app runs against a live server.

### Proposed design

The static pipeline's findings become hypotheses, and an agent tests each one on a running app. Four parts do the work:

- **An agent** that plans the steps for a hypothesis and drives the app.
- **A disposable emulator** running the target app next to a helper "attacker" app.
- **A proxy** between the app and the live backend, so the agent can read the traffic.
- **An oracle** that decides whether what was observed proves the bug.

A confirmed finding has the same shape as a static one, with a runtime observation as its evidence, so matching and reporting are reused unchanged.

```
  Static findings            the hypotheses to test
        |
        v
  +-----------+   taps, text, intents   +---------------------------+
  |           | ----------------------> |  Emulator, fresh per run  |
  |   Agent   |                         |  target app + helper app  |
  |           | <---------------------- |                           |
  +-----------+   screen, logs, files   +---------------------------+
        |    ^                                        |
        |    |                                        | all app traffic
        |    |                                        v
        |    |      captured traffic            +-----------+     +---------+
        |    +--------------------------------- |   Proxy   | <-> | Backend |
        v                                       +-----------+     +---------+
  +-----------+
  |  Oracle   |   did the planted marker appear where it should not?
  +-----------+
        |
        v
  Confirmed findings         same shape as static findings; then matched
                             and reported
```

### How each part works

**The oracle: proof, not crashes.** A crash only tells us something broke, not that it was exploitable. The oracle looks for proof in two ways. One is a known signal for each bug type, such as credentials showing up in the logs. The other is planted evidence: the agent pushes dummy data carrying a unique marker through the suspect flow, then checks where the marker turns up. If account A can fetch a marker that belongs to account B, the bug is real. It counts only if it happens again from a clean start.

**The agent: reaching the right screen.** The agent navigates much as a web agent uses the DOM: it reads the screen's element tree, picks an element, and taps or types, logging in with seeded test accounts. It does not tap its way everywhere. The manifest and the static findings name the entry points, so exported components and deep links are launched directly with a crafted intent. Coverage is measured against what static analysis found: the share of declared activities reached, and the share of API endpoints in the code that appeared in traffic.

**The emulator: disposable at scale.** A device is treated like a server instance, never as a machine to look after. A golden image is built once, with the app installed, the proxy certificate trusted and the accounts seeded, and is snapshotted after boot. Each run starts from that snapshot in seconds, on a copy-on-write overlay that is deleted afterwards, so nothing is ever cleaned and no state carries over. Server-grade virtual devices such as Google's Cuttlefish run headless on hosts whose CPU matches the app's architecture, which avoids slow instruction translation. Runs are hermetic and time-limited; an infrastructure failure is retried automatically, while a finding must reproduce on a fresh device. Each hypothesis is one job on a queue, and only what static analysis flagged is run at all.

**The proxy: seeing traffic despite SSL pinning.** The emulator trusts the proxy's certificate. Where the app pins its own certificate, the pinning is bypassed by hooking the app's certificate checks at runtime, or by repackaging the app with pinning removed.

### Limitations

- **Pinning bypass is the most fragile part.** It breaks on pinning done in native code or a non-standard network stack, on tamper, root or hook detection that makes the app refuse to run, and on traffic that never reaches the proxy. When it fails, the run must report that traffic was not visible, not that nothing was found.
- **Some screens expose no element tree.** Custom-drawn interfaces leave the agent with screenshots only.
- **Some apps refuse to run on an emulator.** These need a small pool of real devices.
- **Only observable backend flaws are reachable.** A flaw that never shows in what the server returns or does stays hidden.

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
