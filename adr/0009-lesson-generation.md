# 0009. Lesson generation: teacher's findings, masked input, leak guard

Status: Accepted

## Context

The assignment says: "Have the frontier model turn its findings into general
lessons in a single pass", and "Lessons must be general rules, never
instance-specific." A lesson that names something from the scanned app hands the
student the answer and makes the recall lift meaningless. The teacher has just
read the app, so a prompt instruction alone will not prevent this.

## Decision

1. Source. Lessons come only from the teacher's own verified findings
   (ADR 0003). The reference list is never consulted, not even to pick findings.
2. Single pass. One teacher call writes all lessons, and no lesson is rewritten.
   If the reply cannot be parsed, the same call is repeated once (ADR 0006);
   that is a transport retry, not a second pass over the lessons.
3. Mask the input. Before that call, code replaces names the app defines
   (package, classes, string values, URLs) with placeholders such as `<CLASS_1>`.
   Platform names are left as they are. A string literal counts as app-defined
   only if it is a URL, contains the app's package, is an identifier-like key,
   or is a long key-like token. Other literals, such as cipher or MIME names,
   are left, because a lesson may need them. A bare domain counts as a URL, and
   the app's display name is masked too. So are the words of the app's package
   that no bundled library shares, but only where they sit inside an
   identifier, path or URL (`acme://shop/`, `acme.plugin.Loader`); as plain
   words in a sentence they are left, so ordinary language is not disturbed.
   The set is derived from the app itself; there is no fixed word list. String literals that the Kotlin
   compiler generates (metadata annotations, null-check calls) are ignored:
   they repeat member and parameter names, including platform method names
   that lessons are meant to use.
4. Leak guard. After the call, code checks each lesson for the app's distinctive
   names and for leftover placeholders. Short common words are ignored: a
   single-word class name (such as `Util`) never counts as a leak. A config
   allow-list holds terms that never count as leaks.
5. On failure, drop the lesson. It is saved with the run but not shown to the
   student.
6. Report per run: lessons dropped, with the text and triggering term; and
   categories present in the teacher's findings with no surviving lesson.

## Why

- Keeping the reference list out of the loop means lessons cannot teach to the test.
- The teacher cannot leak a name it never sees, so drops should be rare.
- Dropping, not rewriting, keeps the single pass and never repairs a leak by hand.
- Reporting uncovered categories shows when a real pattern went untaught.

## Rejected

- Asking the teacher to rewrite a failed lesson: a second pass.
- Blanking the name out of a failed lesson: leaves broken or still-revealing text.
- Filtering teacher findings by the reference list first: leaks the answer key.

## Consequences

- A dropped lesson can lower the lift; the report makes that visible.
- A false alarm is fixed by adding the term to the allow-list and running again.
- A secret that looks like an ordinary word (a plain username, say) cannot be
  recognised by its shape, so it is neither masked nor caught by the guard.
- A lesson can still identify code by description without using a name. Lessons
  are few, so they are also read by hand.
