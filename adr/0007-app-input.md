# 0007. App input: APK or folder, decompiler behind an interface

Status: Accepted

## Context

The assignment says to load the decompiled app (manifest, code, resources) and
that the tool will be run on an APK we have not seen, with the app path in
config. Decompiled output differs by tool, and a source tree is laid out
differently again.

## Decision

1. The tool accepts either an APK file or a folder.
2. An APK is decompiled first into a cache folder. The decompiler sits behind a
   small interface, with its command in config. The default is jadx.
3. A folder is used as given.
4. Loading is layout-agnostic: the manifest, source files and resource XML are
   found by file type, not by fixed paths.
5. A folder with no readable source or manifest (e.g. an unzipped APK) stops the
   run with a message that it needs decompiling.

## Why

- jadx is the de facto standard: one command gives Java source, the decoded
  manifest and resources.
- Finding files by type handles jadx output, other tools' layouts and original
  source trees with the same code.
- Failing loudly beats scanning nothing and reporting zero findings.

## Rejected

- apktool: outputs smali, which is poor input for a model.
- dex2jar plus a Java decompiler: multi-step, and no resources.
- Androguard: no Java needed, but weaker source output.
- Fixed jadx paths: breaks on any other layout.

## Consequences

- Running on an APK needs jadx and a Java runtime installed.
- Obfuscated apps decompile to meaningless names; the scan still runs, but
  quality will drop. Not addressed in v0.1.
