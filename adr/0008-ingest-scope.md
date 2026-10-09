# 0008. Ingest scope: app code, dependency names, security-relevant resources

Status: Accepted

## Context

The assignment asks ingest to "load the decompiled app: manifest, code, and
resources", and the tool must run on an unseen APK. Scale ("a real app with 1M+
lines of code") is asked for as a written answer, not as a build. Decompiled
output is mostly bundled library code and static files, and a small student
model may have a tight token allowance.

## Decision

1. App code only. Keep source files in or beneath the package of the manifest
   itself, the application class and the launcher activity. A merged manifest
   also declares library components, so other components are not used as
   anchors. Config include and exclude lists override this.
2. Dependencies by name, not code, in two tiers:
   - Resolved: Maven coordinates (`group:artifact:version`), the industry
     standard identifier, read from metadata left in the package
     (`META-INF` version and `pom.properties` files) or from Gradle build files
     when the input is a source tree.
   - Unresolved: for library code with no such metadata, the top-most package
     that holds code, labelled as a package name with no known version.

   When a scan is split across calls, the list is sent with the first call
   only, and later calls are told to leave problems in the manifest itself to
   the first call, so they are not reported once per call. Repeating it in every call cost about a fifth of a split scan's input
   tokens.
3. Resources by allow-list. Always the manifest; string values and XML config
   files; small text files such as JSON, properties, HTML and JavaScript.
   The allow-list of file types and a size cap live in config.
4. Excluded: images, fonts, media, stylesheets, layouts and other binaries.
5. Over-budget fallback. Prompt size is estimated as characters divided by a
   config value, default 3.5. Measured on a full scan prompt for a decompiled
   app, after the stripping in rule 7, real counts were 3.6 characters per
   token (Gemini) and 4.3 (OpenAI-family), so 3.5 stays an overestimate for
   both while splitting a scan into fewer calls than a lower value would.
   Without that stripping Gemini's ratio fell to 2.6, below the default, so the
   estimate is only safe together with rule 7. No tokenizer is
   used: it is model-specific and may download data at run time.
   If the app code exceeds a model's budget, pack whole
   files into as many calls as needed, include the manifest in each, and
   concatenate the findings. Log when this happens; never truncate silently.
   A single file larger than the budget is sent in a call of its own, with a
   warning. Splitting files is deferred; packing lives in one function so it
   can be added there.
6. Generated files are skipped. Build tools write resource indexes and
   data-binding classes into the app's package; they cannot hold a
   vulnerability and can be very large. Filename patterns are in config, and
   the number skipped is logged. Build-config classes are kept, since they can
   hold keys.

7. Unreadable noise is stripped from kept source files, by patterns in config.
   The default removes only the `d1` field of Kotlin's `@Metadata` annotation:
   binary-encoded data shown as escape sequences. It holds no logic or
   constants, a model cannot decode it, and it costs close to one token per
   character. The readable `d2` field (original class and member names) is
   kept, because it can be the best clue in an obfuscated app.

## Why

- Library code is not the app's own attack surface and would swamp the prompt.
- Dependency names let a model reason about vulnerable libraries cheaply.
- An allow-list is safer than a block-list: unknown file types stay out.
- Config files and bundled scripts can hold secrets or logic, so text assets stay.
- The fallback keeps the tool working on a larger unseen app for little code.

## Rejected

- Sending everything decompiled: too large, mostly irrelevant.
- No fallback: the tool would fail or truncate on a larger app.
- Smart chunking now: over-engineering for a first slice.

## Deferred to the written scale answer

- Ranking code by attack surface and following call paths from entry points.
- A cheap pattern pre-filter, module summaries, per-chunk lesson selection.
- Merging duplicate findings across chunks; caching results by file hash.

## Consequences

- With per-model budgets the teacher may scan in one call and a student in
  several. The prompt and code are the same; only the split differs.
- Packing by file can miss a bug that spans files in different chunks.
- In a split scan, later calls do not see the dependency list, so a finding
  that needs both a dependency and code from a later call is less likely.
- Coordinates survive only where the build left metadata. An obfuscated or
  stripped app may yield only unresolved package names, so
  known-vulnerable-library findings will be weak there.
- Mapping packages to libraries by a curated database or by code fingerprints
  is what dedicated tools do; that belongs to the written scale answer.
- App code outside those three anchor packages is missed unless added in config
  (e.g. an app whose ID differs from its code namespace and has no application
  class).
