# vulnscan

A teacher-to-student vulnerability scanning loop for decompiled Android apps.

A strong "teacher" model scans an app and turns its findings into general
lessons. A cheaper "student" model scans the same app with and without those
lessons, and the tool measures how much the student's recall improves.

Results and design reasoning are in [WRITEUP.md](WRITEUP.md) and [`adr/`](adr/).

## Requirements

- Python 3.11 or newer.
- [jadx](https://github.com/skylot/jadx) on the `PATH`, with a Java runtime, to
  scan an APK (`brew install jadx` on macOS, or a release download elsewhere).
  Tested with jadx 1.5.6. A decompiled or source folder needs neither.
- An API key for each model you configure.

## Install

```bash
python3.11 -m venv .venv
.venv/bin/pip install -e ".[dev]"
cp .env.example .env
```

## Run it on a new APK

1. **Set the models.** In `config.yaml`, replace each `PROVIDER/MODEL` with a
   [LiteLLM model name](https://docs.litellm.ai/docs/providers), for example
   `anthropic/<model>` for the teacher and `groq/openai/gpt-oss-20b` for the
   student. Set each `api_key_env` to the name of the environment variable that
   holds that model's key. The judge may be the same model as the teacher: set
   `roles.judge: teacher` and remove the `judge` entry.
2. **Set the keys.** Put those variables in `.env` (or export them). Keys are
   read only from the environment and are never written to a run folder.
3. **Check what will be scanned.** This decompiles the APK and lists the files
   the models would see. It makes no model calls.

   ```bash
   .venv/bin/vulnscan ingest --app path/to/app.apk
   ```

   Confirm the package name is right and the list holds the app's own code. If
   it does not, see [Troubleshooting](#troubleshooting).
4. **Run.**

   ```bash
   .venv/bin/vulnscan run --app path/to/app.apk
   ```

   With no reference list, the student is scored against the teacher's
   findings. To score against known vulnerabilities, add
   `--reference path/to/reference.yaml` (see [Reference list](#reference-list)).
5. **Read the result.** The report is printed at the end and saved as
   `runs/<timestamp>/report.md`.

`--app` and `--reference` override `app.path` and `app.reference` in the config,
so nothing else needs to change between apps.

## What a run does, and how long it takes

| Stage | Model calls |
| --- | --- |
| Teacher scan | 1, or more if the app exceeds the teacher's input budget |
| Lessons | 1 |
| Student scans | 2 arms x `scan.repeats` (default 3) x calls per scan |
| Judging | 1 per scored scan for every 20 findings |

A scan is split across several calls when the app's code exceeds a model's
`input_budget_tokens`. With a small budget, a student scan of a small app takes
10 to 20 calls. Set the budget so that input plus `max_output_tokens` stays
under the provider's tokens-per-minute limit.

When a provider answers "rate limited" or "service unavailable", the tool waits
for the time the provider states and retries, up to `llm.max_attempts` times.
Any other error stops the run.

**A stopped run loses nothing.** Each stage is saved as it finishes. Continue
with:

```bash
.venv/bin/vulnscan run --resume runs/<timestamp>
```

A resumed run uses the config saved in that folder. To redo a stage, delete its
file and resume.

## Output

Each run writes a folder under `runs/`:

| File | Content |
| --- | --- |
| `report.md`, `report.json` | Recall and precision per arm, the lift, lessons kept and dropped |
| `teacher.scan.json` | The teacher's findings, each with its evidence status |
| `lessons.json`, `lessons.txt` | Lessons kept and dropped, and the text shown to students |
| `<student>.<arm>.<n>.scan.json` | One student scan; `arm` is `baseline` or `lessons` |
| `*.match.json` | The judge's assignment and reason for every finding |
| `config.yaml` | The config the run used |

In the report, recall is the share of reference entries that at least one
finding matched. With more than one run per arm, the report says whether the
two ranges overlap. When the teacher is the reference, the report states that
recall means agreement with the teacher.

## Configuration

Everything that varies is in `config.yaml`. Settings not listed there have
defaults in `src/vulnscan/config.py` and can be added to the file.

| Setting | Meaning |
| --- | --- |
| `models.<name>.model` | LiteLLM model name |
| `models.<name>.api_key_env` | Environment variable holding the key |
| `models.<name>.input_budget_tokens` | How much prompt one call may carry |
| `models.<name>.max_output_tokens` | Output limit per call, including reasoning tokens |
| `models.<name>.temperature` | Default 0.2; set it if a provider requires another value |
| `models.<name>.extra` | Any other provider parameters |
| `models.<name>.adapter` | `manual` writes each prompt to a file and waits for a saved reply, for a model with no API access |
| `roles` | Which model is teacher, which are students (a list), which is judge |
| `scan.repeats` | Runs per student arm |
| `evidence.check` | `exclude` (default), `flag` or `off` for findings whose quoted code is not in the app |
| `match.judge_temperature` | Default 0 |
| `ingest.include_packages`, `ingest.exclude_packages` | Override which packages count as the app's own code |
| `ingest.decompiler` | The decompile command; default `jadx -d {out} {apk}` |
| `llm.max_attempts` | Retries on rate limits and unavailability; default 5 |

Adding a model is a new entry under `models` and its name under `roles`. No
code changes.

## Reference list

A YAML (or JSON) list. Each entry needs a `title` and a `description`:

```yaml
- title: Hardcoded API key
  description: A third-party API key is embedded in the app's code.
- title: Exported activity loads untrusted URLs
  description: An exported activity passes intent data to a WebView.
```

A published Markdown list can be converted by rule, with no model involved:

```bash
.venv/bin/vulnscan reference LIST.md -o reference.yaml --section "Heading"
```

`--section` limits it to list items under headings containing that text. Review
the output before using it. Entries that name the class or component involved
make the judge more accurate.

## Troubleshooting

| Message or symptom | Cause and fix |
| --- | --- |
| `environment variable X is not set` | The key named by `api_key_env` is missing from the environment or `.env` |
| `decompiler 'jadx' not found` | Install jadx, or set `ingest.decompiler` |
| `decompiler exited with status N` (a warning) | Normal. jadx reports an error when it cannot decompile some classes; the run continues with what it produced |
| `no readable AndroidManifest.xml` | The folder is an unzipped APK with a binary manifest. Pass the `.apk` file, or decompile it first |
| `no app source files found` | The app's code is not under the packages the manifest points to. Set `ingest.include_packages` to the app's package prefix |
| The file list is mostly library code | Add the unwanted prefixes to `ingest.exclude_packages` |
| `prompt overhead exceeds its input budget` | The manifest and instructions alone exceed `input_budget_tokens`. Raise it |
| A provider rejects `temperature` | Set that model's `temperature`, or `match.judge_temperature`, to the value the provider requires |
| The run stops on a provider error | Resume it; finished stages are reused |
| Few or no findings on an obfuscated app | Class and method names are meaningless after obfuscation. The scan runs, but quality drops |

## Safety

- **An APK is untrusted input.** The tool never runs the app; it only reads the
  decompiled files. The decompiler itself runs with your user's permissions, so
  for an APK you do not trust, run the tool in a container or virtual machine.
- **The app's code is sent to the model providers** you configure.

## How it works

| Stage | Module | Decision record |
| --- | --- | --- |
| Load the app: manifest, app code, resources, dependency names | `ingest.py` | ADR 0007, 0008, 0013 |
| Scan with one prompt for every model | `scan.py`, `prompts/` | ADR 0002 |
| Check quoted evidence exists in the app | `evidence.py` | ADR 0003 |
| Teacher writes lessons in one pass; app names are masked and leaks dropped | `lessons.py`, `names.py` | ADR 0005, 0009 |
| A judge model assigns each finding to a reference entry by root cause | `match.py` | ADR 0001 |
| Repeat each student arm, report mean and range | `pipeline.py`, `report.py` | ADR 0004, 0010 |
| Model access behind one small interface | `llm.py` | ADR 0006 |
| Reference list conversion | `reference.py` | ADR 0012 |

## Tests

```bash
.venv/bin/python -m pytest
```

Tests run against a small made-up app and scripted model replies, so they need
no keys and make no network calls.
