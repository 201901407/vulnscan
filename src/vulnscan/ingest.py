from __future__ import annotations

import hashlib
import logging
import os
import re
import shutil
import subprocess
import xml.etree.ElementTree as ET
from collections import Counter
from dataclasses import dataclass, field
from fnmatch import fnmatch
from pathlib import Path

from .config import IngestConfig

log = logging.getLogger(__name__)

MANIFEST_NAME = "AndroidManifest.xml"
# A real manifest never declares a document type; entity definitions can exhaust memory on parse.
XML_DECLARATIONS = (b"<!DOCTYPE", b"<!ENTITY")
ANDROID_NS = "{http://schemas.android.com/apk/res/android}"
PACKAGE_RE = re.compile(r"^\s*package\s+([\w.]+)", re.MULTILINE)
METADATA_DIR = "META-INF"
GRADLE_SUFFIXES = (".gradle", ".gradle.kts")
GRADLE_DEPENDENCY_RE = re.compile(
    r"""^\s*(?:\w*[iI]mplementation|api|compile\w*|runtimeOnly)\b.*?['"]([\w.-]+:[\w.-]+:[^'"\s:]+)['"]""",
    re.MULTILINE,
)


class IngestError(Exception):
    pass


@dataclass(frozen=True)
class AppFile:
    path: str
    text: str


@dataclass
class App:
    """What ingest keeps from a decompiled app (ADR 0008)."""

    package: str
    manifest: AppFile
    sources: list[AppFile]
    resources: list[AppFile]
    dependencies: list[str]
    unresolved_packages: list[str]
    classes: list[str]
    skipped: dict[str, int] = field(default_factory=dict)

    @property
    def files(self) -> list[AppFile]:
        return [self.manifest, *self.sources, *self.resources]

    def summary(self) -> dict:
        return {
            "package": self.package,
            "manifest": self.manifest.path,
            "source_files": len(self.sources),
            "resource_files": len(self.resources),
            "dependencies": len(self.dependencies),
            "unresolved_packages": len(self.unresolved_packages),
            "skipped": self.skipped,
        }


def load_app(path: Path, config: IngestConfig) -> App:
    root = _resolve(path, config)
    files, symlinks = _walk(root, set(config.skip_dirs))
    manifest_path, manifest = _find_manifest(files)
    package = manifest.get("package", "")
    prefixes = _app_prefixes(manifest, package, config.include_packages)

    strip = [re.compile(pattern) for pattern in config.strip_patterns]
    sources, resources, classes = [], [], []
    coordinates: set[str] = set()
    library_packages: set[str] = set()
    skipped: Counter[str] = Counter()
    if symlinks:
        skipped["symlinks"] = symlinks
        log.warning("skipped %d symbolic links; only regular files are read", symlinks)
    for file in files:
        relative = file.relative_to(root).as_posix()
        if METADATA_DIR in file.parts or file.name.endswith(GRADLE_SUFFIXES):
            coordinates.update(_coordinates(file))
        elif file.suffix in config.source_extensions:
            source_package = _package_of(file)
            if _under(source_package, config.exclude_packages):
                continue
            if not _under(source_package, prefixes):
                library_packages.add(source_package)
            elif any(fnmatch(file.name, pattern) for pattern in config.generated_patterns):
                skipped["generated"] += 1
            else:
                text = _read(file)
                for pattern in strip:
                    text = pattern.sub("", text)
                sources.append(AppFile(relative, text))
                classes.append(f"{source_package}.{file.stem}")
        elif file != manifest_path and _matches(relative, config.resource_patterns):
            if file.stat().st_size > config.max_resource_bytes:
                skipped["oversized_resources"] += 1
                log.warning("skipping resource over the size cap: %s", relative)
            else:
                resources.append(AppFile(relative, _read(file)))

    if not sources:
        raise IngestError(
            f"no app source files found under {root} for packages {sorted(prefixes)}; "
            "decompile the app first or set ingest.include_packages"
        )
    if skipped["generated"]:
        log.info("skipped %d generated files", skipped["generated"])
    return App(
        package=package,
        manifest=AppFile(manifest_path.relative_to(root).as_posix(), _read(manifest_path)),
        sources=sources,
        resources=resources,
        dependencies=sorted(coordinates),
        unresolved_packages=_package_roots(
            library_packages, {coordinate.split(":")[0] for coordinate in coordinates}
        ),
        classes=classes,
        skipped=dict(skipped),
    )


def _resolve(path: Path, config: IngestConfig) -> Path:
    if path.is_dir():
        return path
    if not path.is_file():
        raise IngestError(f"app path does not exist: {path}")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()[:12]
    out = config.cache_dir / f"{path.stem}-{digest}"
    if out.is_dir() and any(out.iterdir()):
        return out
    out.mkdir(parents=True, exist_ok=True)
    command = [part.format(out=out, apk=path) for part in config.decompiler]
    log.info("decompiling %s", path.name)
    try:
        result = subprocess.run(
            command, capture_output=True, text=True, timeout=config.decompiler_timeout_seconds
        )
    except FileNotFoundError as error:
        raise IngestError(
            f"decompiler '{command[0]}' not found; install it or set ingest.decompiler"
        ) from error
    except subprocess.TimeoutExpired as error:
        shutil.rmtree(out, ignore_errors=True)
        raise IngestError(
            f"decompiler exceeded {config.decompiler_timeout_seconds:.0f}s and was stopped"
        ) from error
    if result.returncode != 0:
        # Decompilers commonly exit non-zero after partial failures; the manifest check decides.
        log.warning("decompiler exited with status %d", result.returncode)
    return out


def _walk(root: Path, skip_dirs: set[str]) -> tuple[list[Path], int]:
    """Regular files under root, and how many symbolic links were left out.

    A link could point outside the app folder, and its target would be sent to a model.
    """
    found, symlinks = [], 0
    for directory, subdirs, names in os.walk(root, followlinks=False):
        subdirs[:] = [d for d in subdirs if d not in skip_dirs]
        for name in names:
            path = Path(directory, name)
            if path.is_symlink():
                symlinks += 1
            else:
                found.append(path)
    return sorted(found), symlinks


def _find_manifest(files: list[Path]) -> tuple[Path, ET.Element]:
    candidates = sorted((f for f in files if f.name == MANIFEST_NAME), key=lambda f: len(f.parts))
    for candidate in candidates:
        content = candidate.read_bytes()
        if any(declaration in content for declaration in XML_DECLARATIONS):
            raise IngestError(f"{candidate} declares a document type or entity; refusing to parse")
        try:
            root = ET.fromstring(content)
        except ET.ParseError:
            continue
        if root.tag == "manifest":
            return candidate, root
    raise IngestError(
        f"no readable {MANIFEST_NAME} found; an unzipped APK holds a binary manifest "
        "and must be decompiled first"
    )


def _app_prefixes(manifest: ET.Element, package: str, include: list[str]) -> set[str]:
    """Anchor packages: the manifest's own, the application class and the launcher activity."""
    anchors = {package, *include}
    application = manifest.find("application")
    if application is not None:
        names = [application.get(f"{ANDROID_NS}name")]
        for tag in ("activity", "activity-alias"):
            for component in application.iter(tag):
                if _is_launcher(component):
                    names.append(
                        component.get(f"{ANDROID_NS}targetActivity")
                        or component.get(f"{ANDROID_NS}name")
                    )
        for name in filter(None, names):
            anchors.add(_qualify(name, package).rpartition(".")[0])
    anchors.discard("")
    if not anchors:
        raise IngestError("cannot tell which packages are app code; set ingest.include_packages")
    return anchors


def _is_launcher(component: ET.Element) -> bool:
    for intent_filter in component.iter("intent-filter"):
        values = {child.get(f"{ANDROID_NS}name") for child in intent_filter}
        if {"android.intent.action.MAIN", "android.intent.category.LAUNCHER"} <= values:
            return True
    return False


def _qualify(name: str, package: str) -> str:
    if name.startswith("."):
        return package + name
    return name if "." in name else f"{package}.{name}"


def _package_of(file: Path) -> str:
    with file.open("rb") as handle:
        head = handle.read(4096).decode("utf-8", errors="replace")
    found = PACKAGE_RE.search(head)
    return found.group(1) if found else ""


def _under(package: str, prefixes) -> bool:
    return any(package == prefix or package.startswith(prefix + ".") for prefix in prefixes)


def _coordinates(file: Path) -> list[str]:
    """Maven coordinates (group:artifact:version) recorded in a metadata or build file."""
    if file.name.endswith(GRADLE_SUFFIXES):
        return GRADLE_DEPENDENCY_RE.findall(_read(file))
    if file.suffix == ".version" and "_" in file.stem:
        group, _, artifact = file.stem.partition("_")
        version = _read(file).strip()
        return [f"{group}:{artifact}:{version}"] if version else []
    if file.name == "pom.properties":
        pairs = (line.split("=", 1) for line in _read(file).splitlines() if "=" in line)
        fields = {key.strip(): value.strip() for key, value in pairs}
        if {"groupId", "artifactId", "version"} <= fields.keys():
            return [f"{fields['groupId']}:{fields['artifactId']}:{fields['version']}"]
    return []


def _package_roots(packages: set[str], resolved_groups: set[str]) -> list[str]:
    """Library packages with no coordinates: top-most packages holding code, minus resolved groups."""
    packages = packages - {""}

    def has_ancestor(package: str) -> bool:
        parts = package.split(".")
        return any(".".join(parts[:depth]) in packages for depth in range(1, len(parts)))

    roots = {p for p in packages if not has_ancestor(p)}
    return sorted(root for root in roots if not _under(root, resolved_groups))


def _matches(relative: str, patterns: list[str]) -> bool:
    return any(fnmatch(relative, p) or fnmatch(relative, f"*/{p}") for p in patterns)


def _read(file: Path) -> str:
    return file.read_text(encoding="utf-8", errors="replace")
