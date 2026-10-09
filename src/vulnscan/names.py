from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import urlparse

from .ingest import App

STRING_RE = re.compile(r'"((?:[^"\\\n]|\\.){3,200})"')
XML_TEXT_RE = re.compile(r"<string[^>]*>([^<]{3,200})</string>")
URL_RE = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*://\S+")
KEY_RE = re.compile(r"[A-Za-z][A-Za-z0-9]*(?:_[A-Za-z0-9]+)+|[a-z]+(?:[A-Z][a-z0-9]+)+")
HUMP_RE = re.compile(r"[A-Z][a-z0-9]+")
PLACEHOLDER_RE = re.compile(r"<(?:APP|PACKAGE|CLASS|STRING|URL)(?:_\d+)?>")
DOMAIN_RE = re.compile(r"(?:[a-z0-9-]+\.)+([a-z]{2,})")
LABEL_RE = re.compile(r'<application[^>]*\sandroid:label="([^"]+)"')
# Kotlin compiler output: metadata lists member names and null checks repeat parameter
# names as string literals. Neither is a value the app defines, and both include
# platform method names that lessons are meant to use.
COMPILER_NOISE_RE = re.compile(r"^.*(?:@Metadata\(|\bIntrinsics\.).*$", re.MULTILINE)
PLATFORM_NAMESPACES = ("android.", "androidx.", "java.", "javax.", "kotlin.")
FILE_EXTENSIONS = {
    "json", "xml", "html", "htm", "txt", "js", "css", "db", "png", "jpg", "properties",
    "java", "kt", "so", "dex", "apk", "pdf", "zip",
}

# Characters that join a name to its neighbours inside an identifier, path or URL.
JOINERS = r"[./:_%=\-]"
MIN_PART_CHARS = 3
MIN_KEY_CHARS = 5
MIN_TOKEN_CHARS = 20
MIN_TOKEN_DIGITS = 5
MIN_CLASS_CHARS = 4


def is_app_literal(value: str, package: str) -> bool:
    """Whether a string literal is specific to the app (ADR 0009).

    URLs, strings holding the app's package, identifier-like keys, and long
    digit-heavy tokens (keys, IDs) qualify. Platform literals such as cipher
    transformations or MIME types do not, because a lesson may need them.
    """
    if URL_RE.fullmatch(value) or (package and package in value) or _is_domain(value):
        return True
    if len(value) >= MIN_KEY_CHARS and KEY_RE.fullmatch(value):
        return True
    return (
        len(value) >= MIN_TOKEN_CHARS
        and not any(c.isspace() for c in value)
        and sum(c.isdigit() for c in value) >= MIN_TOKEN_DIGITS
        and any(c.isalpha() for c in value)
    )


def _is_domain(value: str) -> bool:
    found = DOMAIN_RE.fullmatch(value)
    return bool(
        found
        and found.group(1) not in FILE_EXTENSIONS
        and not value.startswith(PLATFORM_NAMESPACES)
    )


def _app_label(app: App) -> str:
    """The app's display name, resolved through its string resources if needed."""
    found = LABEL_RE.search(app.manifest.text)
    label = found.group(1) if found else ""
    if label.startswith("@string/"):
        entry = re.compile(rf'<string name="{re.escape(label[8:])}"[^>]*>([^<]*)</string>')
        matches = (entry.search(file.text) for file in app.resources)
        label = next((m.group(1).strip() for m in matches if m), "")
    return label


def _package_parts(app: App) -> set[str]:
    """Words of the app's package that no bundled library shares.

    `com` or `android` also occur in library packages, so they are generic.
    What is left (`acme`, `shop`) belongs to this app.
    """
    library_words = {
        word
        for name in [*app.dependencies, *app.unresolved_packages]
        for word in re.split(r"[.:]", name)
    }
    return {
        part
        for part in app.package.split(".")
        if len(part) >= MIN_PART_CHARS and part not in library_words
    }


def _in_identifier(parts: set[str]) -> re.Pattern[str] | None:
    """Matches a package word only where it is joined to a neighbour.

    `acme://shop/login` and `acme.plugin.Loader` match; the plain word in
    "for example" or "release notes" does not, so prose is left alone.
    """
    if not parts:
        return None
    words = "|".join(map(re.escape, sorted(parts, key=len, reverse=True)))
    return re.compile(rf"(?<![a-z])(?:{words})(?={JOINERS})|(?<={JOINERS})(?:{words})(?![a-z])")


def _alternation(terms) -> re.Pattern[str] | None:
    if not terms:
        return None
    longest_first = sorted(terms, key=len, reverse=True)
    return re.compile(r"(?<!\w)(?:" + "|".join(map(re.escape, longest_first)) + r")(?!\w)")


@dataclass
class AppNames:
    """Names the scanned app defines, used to mask lesson input and catch leaks."""

    placeholders: dict[str, str]
    distinctive: set[str]
    package_parts: set[str] = field(default_factory=set)

    @classmethod
    def from_app(cls, app: App) -> AppNames:
        literals: set[str] = set()
        for file in app.files:
            text = COMPILER_NOISE_RE.sub("", file.text)
            literals.update(STRING_RE.findall(text))
            literals.update(XML_TEXT_RE.findall(text))
        literals = {v.strip() for v in literals if is_app_literal(v.strip(), app.package)}
        urls = {v for v in literals if URL_RE.fullmatch(v) or _is_domain(v)}
        hosts = {urlparse(url).netloc for url in urls} - {""}

        placeholders: dict[str, str] = {}
        for number, url in enumerate(sorted(urls | hosts), 1):
            placeholders[url] = f"<URL_{number}>"
        for number, literal in enumerate(sorted(literals - urls), 1):
            placeholders.setdefault(literal, f"<STRING_{number}>")

        distinctive = set(placeholders)
        for number, qualified in enumerate(sorted(set(app.classes)), 1):
            simple = qualified.rpartition(".")[2]
            placeholders.setdefault(qualified, f"<CLASS_{number}>")
            distinctive.add(qualified)
            if len(simple) >= MIN_CLASS_CHARS:
                placeholders.setdefault(simple, f"<CLASS_{number}>")
                # A single capitalised word (Util, Cart) is too common to count as a leak.
                if len(HUMP_RE.findall(simple)) >= 2:
                    distinctive.add(simple)
        if app.package:
            placeholders.setdefault(app.package, "<PACKAGE>")
            distinctive.add(app.package)
        label = _app_label(app)
        if len(label) >= MIN_CLASS_CHARS:
            for form in {label, label.lower()}:
                placeholders.setdefault(form, "<APP>")
                # Same rule as class names: a single common word is not treated as a leak.
                if len(HUMP_RE.findall(label)) >= 2:
                    distinctive.add(form)
        return cls(placeholders, distinctive, _package_parts(app))

    def mask(self, text: str) -> str:
        pattern = _alternation(self.placeholders)
        if pattern:
            text = pattern.sub(lambda m: self.placeholders[m.group()], text)
        parts = _in_identifier(self.package_parts)
        return parts.sub("<APP>", text) if parts else text

    def leaks(self, text: str, allow: list[str]) -> list[str]:
        found = set(PLACEHOLDER_RE.findall(text))
        pattern = _alternation(self.distinctive - set(allow))
        if pattern:
            found.update(pattern.findall(text))
        parts = _in_identifier(self.package_parts - set(allow))
        if parts:
            found.update(parts.findall(text))
        return sorted(found)
