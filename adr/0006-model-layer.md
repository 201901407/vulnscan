# 0006. Model layer: small interface, no providers in code, model registry in config

Status: Accepted (amended: library-backed instead of hand-written adapters)

## Context

No starter repo is provided, so we wire the model clients. The assignment asks us
to "keep the model layer behind a small interface so adding a model is a config
change", and extensibility is a judging criterion. Models differ in more than
transport: not all support structured output, some reject certain parameters, and
context sizes vary.

## Decision

1. One small interface: send a prompt, get text back. The rest of the pipeline
   knows nothing about providers.
2. Two implementations behind it, chosen per model in config:
   - LiteLLM (default). A model is a string in config
     (e.g. `groq/openai/gpt-oss-20b`); no provider is named in code.
   - Manual. The prompt is written to a file in the run folder and the run
     stops; a person gives it to a model by hand (for example through a chat
     interface), saves the reply to a named file, and resumes. Files are keyed by a hash of the prompt, so a reply is only ever
     used for the exact prompt it answers.
3. Plain JSON, validated by us: every model is asked for JSON in prompt text; our
   code parses and checks it against the schema, with one retry. Valid items in
   a reply are kept; malformed ones are skipped and counted in the report. No
   provider-specific output feature is required.
4. A model registry in config: named entries with model string, key variable,
   context budget, temperature and extra parameters. The roles (teacher,
   students, judge) point at entries; `students` is a list.
5. API keys come from environment variables named in config.
6. Default student: `openai/gpt-oss-20b`, a small open-weight model. `students`
   stays a list, so more can be added in config. The teacher is chosen in config.
7. Rate limits and overload: when a provider answers 429 (rate limited) or 503
   (service unavailable), wait for the time in its retry-after header (read from
   where the library exposes the provider's response headers) and try
   again, up to a maximum number of attempts set in config. Without the header,
   use a short increasing wait. There is no per-model rate setting. Other
   errors stop the run, which can then be resumed (ADR 0010).

## Why

- Adding a model on almost any provider is a config line, with no code.
- Relying only on text in, text out means any model can fill any role.
- Per-model settings in config absorb differences in context size and parameters.
- It is the least code, which suits a working first slice.
- Only one file knows the library exists, so it can be replaced.
- A small student is the realistic cheap model the assignment describes
  ("cheaper open models ... at scale") and leaves room to measure a lift. The
  assignment asks for one open model, and each extra student multiplies run time.

## Rejected

- Hand-written adapters per wire format: bakes formats into code and makes one
  provider a special case, for no gain the assignment asks for.
- Requiring native structured output: excludes models that lack it.

## Deferred (with trigger)

- Native structured output as a per-model switch: if plain JSON proves unreliable.

## Consequences

- A manual model cannot have its temperature or system prompt set, and the app
  adds its own; results are less reproducible than an API call. Reports must
  say when a role was filled by hand and by which model.
- Manual suits roles called a few times (teacher scan, lesson writing). The
  judge is called once per scored scan and is better automated.

- One third-party dependency, pinned to a fixed version.
- One more layer to look through when a call fails.
- Provider rate limits bound how much code fits in a call; the budget is config.
- If more than one student is run, every result is reported, not the best one.
