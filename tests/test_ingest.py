from pathlib import Path

import pytest

from vulnscan.config import IngestConfig
from vulnscan.ingest import IngestError, load_app


def names(files):
    return {Path(f.path).name for f in files}


def test_keeps_app_code_and_skips_libraries_and_generated_files(app):
    assert app.package == "com.example.notes"
    assert names(app.sources) == {"NotesApp.java", "MainActivity.java", "ShareActivity.java"}
    assert app.skipped["generated"] == 2


def test_dependencies_are_coordinates_where_recorded_else_package_roots(app):
    assert app.dependencies == ["androidx.core:core:1.9.0"]
    assert app.unresolved_packages == ["com.squareup.okhttp"]


def test_gradle_and_pom_metadata_give_coordinates(app_dir):
    (app_dir / "build.gradle").write_text(
        "dependencies {\n    implementation 'com.squareup.okhttp:okhttp:2.7.5'\n"
        "    classpath 'com.android.tools.build:gradle:8.0.0'\n}\n"
    )
    pom = app_dir / "resources/META-INF/maven/org.example/lib/pom.properties"
    pom.parent.mkdir(parents=True)
    pom.write_text("groupId=org.example\nartifactId=lib\nversion=2.1\n")
    app = load_app(app_dir, IngestConfig())
    assert app.dependencies == [
        "androidx.core:core:1.9.0", "com.squareup.okhttp:okhttp:2.7.5", "org.example:lib:2.1",
    ]
    assert app.unresolved_packages == []


def test_kotlin_binary_metadata_is_stripped_and_readable_names_kept(app):
    share = next(f for f in app.sources if f.path.endswith("ShareActivity.java"))
    assert "d1 =" not in share.text and "\\u0000" not in share.text
    assert '@Metadata(bv = {1, 0, 3}, d2 = {"Lcom/example/notes/ShareActivity;", "onCreate", "onReceivedSslError"}, k = 1' in share.text


def test_resources_follow_the_allow_list(app):
    assert names(app.resources) == {"strings.xml", "file_paths.xml", "config.json"}
    assert app.manifest.path == "resources/AndroidManifest.xml"


def test_include_and_exclude_override_the_anchors(app_dir):
    config = IngestConfig(include_packages=["com.squareup"], exclude_packages=["com.example.notes.ui"])
    app = load_app(app_dir, config)
    assert names(app.sources) == {"NotesApp.java", "ShareActivity.java", "Client.java"}
    assert app.unresolved_packages == []


def test_oversized_resource_is_skipped_and_counted(app_dir):
    app = load_app(app_dir, IngestConfig(max_resource_bytes=10))
    assert app.resources == []
    assert app.skipped["oversized_resources"] == 3


def test_symlinks_are_never_read(app_dir, tmp_path):
    secret = tmp_path / "credentials.json"
    secret.write_text('{"key": "outside the app folder"}')
    (app_dir / "resources/assets/linked.json").symlink_to(secret)
    app = load_app(app_dir, IngestConfig())
    assert "linked.json" not in names(app.resources)
    assert app.skipped["symlinks"] == 1


def test_manifest_with_entity_declarations_is_refused(app_dir):
    manifest = app_dir / "resources/AndroidManifest.xml"
    manifest.write_text('<!DOCTYPE m [<!ENTITY a "aaaa">]>\n' + manifest.read_text())
    with pytest.raises(IngestError, match="refusing to parse"):
        load_app(app_dir, IngestConfig())


def test_decompiler_is_stopped_at_the_time_limit(tmp_path):
    apk = tmp_path / "app.apk"
    apk.write_bytes(b"PK")
    config = IngestConfig(
        decompiler=["sleep", "5"], decompiler_timeout_seconds=0.2, cache_dir=tmp_path / "cache"
    )
    with pytest.raises(IngestError, match="was stopped"):
        load_app(apk, config)
    assert not any((tmp_path / "cache").iterdir())


def test_binary_manifest_needs_decompiling(tmp_path):
    (tmp_path / "AndroidManifest.xml").write_bytes(b"\x03\x00\x08\x00binary")
    with pytest.raises(IngestError, match="decompiled first"):
        load_app(tmp_path, IngestConfig())


def test_missing_decompiler_is_reported(tmp_path):
    apk = tmp_path / "app.apk"
    apk.write_bytes(b"PK")
    config = IngestConfig(decompiler=["no-such-decompiler", "{apk}", "{out}"], cache_dir=tmp_path / "cache")
    with pytest.raises(IngestError, match="not found"):
        load_app(apk, config)
