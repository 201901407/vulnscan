"""Shared fixtures. The app is made up; nothing here comes from a real target (ADR 0011)."""

from __future__ import annotations

from pathlib import Path

import pytest

from vulnscan.config import IngestConfig
from vulnscan.ingest import load_app

MANIFEST = """<?xml version="1.0" encoding="utf-8"?>
<manifest xmlns:android="http://schemas.android.com/apk/res/android" package="com.example.notes">
  <application android:name=".NotesApp" android:label="@string/app_name">
    <activity android:name=".ui.MainActivity" android:exported="true">
      <intent-filter>
        <action android:name="android.intent.action.MAIN"/>
        <category android:name="android.intent.category.LAUNCHER"/>
      </intent-filter>
    </activity>
    <activity android:name=".ShareActivity" android:exported="true"/>
    <provider android:name="androidx.core.content.FileProvider"
              android:authorities="com.example.notes.files"/>
  </application>
</manifest>
"""

SHARE_ACTIVITY = """package com.example.notes;

@Metadata(bv = {1, 0, 3}, d1 = {"\\u0000\\u0014\\n\\u0002}\\"x", "\\u0001"}, d2 = {"Lcom/example/notes/ShareActivity;", "onCreate", "onReceivedSslError"}, k = 1, mv = {1, 1, 16})
public class ShareActivity extends Activity {
    protected void onCreate(Bundle state) {
        super.onCreate(state);
        String target = getIntent().getStringExtra("note_url");
        webView.loadUrl(target);
        Cipher cipher = Cipher.getInstance("AES/ECB/PKCS5Padding");
        String api = "https://api.notes.example/v1";
        Intrinsics.checkParameterIsNotNull(state, "savedState");
        boolean trusted = target.endsWith("notes.example");
    }
}
"""

FILES = {
    "resources/AndroidManifest.xml": MANIFEST,
    "sources/com/example/notes/NotesApp.java": "package com.example.notes;\nclass NotesApp {}\n",
    "sources/com/example/notes/ui/MainActivity.java": "package com.example.notes.ui;\nclass MainActivity {}\n",
    "sources/com/example/notes/ShareActivity.java": SHARE_ACTIVITY,
    "sources/com/example/notes/R.java": "package com.example.notes;\nclass R {}\n",
    "sources/com/example/notes/databinding/ActivityMainBinding.java": "package com.example.notes.databinding;\nclass ActivityMainBinding {}\n",
    "sources/androidx/core/content/FileProvider.java": "package androidx.core.content;\nclass FileProvider {}\n",
    "sources/com/squareup/okhttp/Client.java": "package com.squareup.okhttp;\nclass Client {}\n",
    "resources/res/values/strings.xml": '<resources><string name="app_name">QuickNotes</string></resources>\n',
    "resources/res/xml/file_paths.xml": '<paths><root-path name="root" path="/"/></paths>\n',
    "resources/res/layout/main.xml": "<LinearLayout/>\n",
    "resources/assets/config.json": '{"endpoint": "https://api.notes.example/v1"}\n',
    "resources/assets/style.css": "body { color: red; }\n",
    "resources/META-INF/androidx.core_core.version": "1.9.0\n",
    "resources/META-INF/app-metadata.properties": "appMetadataVersion=1.1\n",
}


class FakeClient:
    def __init__(self, name: str, reply, budget: int = 100_000) -> None:
        self.name = name
        self.budget = budget
        self.calls: list[tuple[str, str]] = []
        self._reply = reply

    def complete(self, system: str, user: str) -> str:
        self.calls.append((system, user))
        return self._reply(system, user) if callable(self._reply) else self._reply


@pytest.fixture
def app_dir(tmp_path: Path) -> Path:
    root = tmp_path / "notes"
    for relative, text in FILES.items():
        file = root / relative
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(text)
    (root / "resources/res/drawable").mkdir(parents=True)
    (root / "resources/res/drawable/logo.png").write_bytes(b"\x89PNG\x00\x01")
    return root


@pytest.fixture
def app(app_dir: Path):
    return load_app(app_dir, IngestConfig())
