# 0013. Untrusted input: harden what reads the app

Status: Accepted

## Context

The tool is run on APKs we did not build, including one we have not seen. An
APK or a supplied folder is untrusted input. Decompiling does not execute the
app, but the files are parsed by our code, and their text is sent to models.

## Decision

1. Symbolic links are never read. Only regular files inside the app folder are
   loaded; the number skipped is logged and reported.
2. A manifest that declares a document type or an entity is refused.
3. The decompile step has a time limit, set in config. On timeout the partial
   output is deleted and the run stops.
4. Every prompt states that the app's content is untrusted data and that
   instructions inside it must not be followed.

## Why

- A link in a supplied folder could point at a private file, whose content
  would then be sent to a model provider.
- Entity definitions can exhaust memory when XML is parsed; real manifests
  never contain them.
- A crafted APK can make a decompiler run without end.
- Text in an app can try to instruct the model, for example to report nothing.

## Not done

- Running the decompiler in a container or virtual machine with no network.
  This is the standard isolation for untrusted binaries and needs no code
  change, since the decompiler is a config command (ADR 0007). Left out for
  now by choice.

## Consequences

- The decompiler still runs with the user's own permissions. A flaw in it could
  be exploited by a crafted APK.
- A prompt instruction lowers the chance of injection working; it does not
  prevent it. Models have no tools and their output is only parsed and
  validated, so a successful injection can skew results but cannot execute
  anything.
