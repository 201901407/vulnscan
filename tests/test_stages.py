import json

from conftest import FakeClient
from vulnscan.config import MASVS_CATEGORIES, LessonConfig
from vulnscan.ingest import AppFile
from vulnscan.lessons import generate, reserve, select
from vulnscan.match import match, score
from vulnscan.names import AppNames
from vulnscan.scan import pack, scan
from vulnscan.schema import Finding, Lesson

FINDING = {
    "title": "Untrusted URL loaded in a WebView",
    "category": "platform",
    "type": "unvalidated url load",
    "cwe": "cwe-939",
    "severity": "High",
    "locations": [{"file": "ShareActivity.java", "symbol": "ShareActivity"}],
    "evidence": "webView.loadUrl(target);",
    "description": "An exported activity loads a caller-supplied URL.",
}
LESSON = {
    "category": "platform",
    "title": "Unvalidated URL loaded from an intent",
    "pattern": "An exported component passes intent data to loadUrl without validation.",
    "signals": ["android:exported", "getStringExtra", "loadUrl"],
    "why": "Any app can send the intent.",
    "not_when": "The value is checked against an allow-list.",
    "from_findings": ["F1", "F99"],
}


def test_pack_groups_files_within_budget_and_isolates_oversized_ones():
    files = [AppFile("a", "x" * 300), AppFile("big", "x" * 3000), AppFile("b", "x" * 300)]
    assert [[f.path for f in batch] for batch in pack(files, budget=400, chars_per_token=3)] == [["a"], ["big"], ["b"]]
    assert len(pack(files, budget=10_000, chars_per_token=3)) == 1


def test_scan_keeps_valid_findings_and_counts_malformed(app):
    reply = json.dumps({"findings": [FINDING, {"title": "no evidence"}, FINDING | {"category": "weird"}]})
    result = scan(FakeClient("student", reply), app, MASVS_CATEGORIES, [], "student.baseline.1", 3)
    assert [f.id for f in result.findings] == ["F1", "F2"]
    assert result.malformed == 1
    assert (result.findings[0].severity, result.findings[0].cwe) == ("high", "CWE-939")
    assert (result.findings[1].category, result.findings[1].category_other) == ("other", "weird")


def test_split_scan_sends_dependencies_with_the_first_call_only(app):
    client = FakeClient("student", '{"findings": []}', budget=1200)
    result = scan(client, app, MASVS_CATEGORIES, [], "s", 3)
    assert result.calls > 1
    first, *rest = (user for _, user in client.calls)
    assert "androidx.core:core:1.9.0" in first
    assert all("androidx.core:core:1.9.0" not in user and "part 1 only" in user for user in rest)


def lesson(number: int, signal: str) -> Lesson:
    return Lesson(id=f"L{number}", title=f"Pattern {number}", pattern="p " * 40, signals=[signal],
                  why="w", not_when="n", category="platform")


def test_scan_arms_split_identically_and_differ_only_by_the_lessons_block(app):
    lessons = [lesson(1, "WebView.loadUrl()"), lesson(2, "Cipher.getInstance"), lesson(3, "allowBackup")]
    client = FakeClient("student", '{"findings": []}', budget=1500)
    held = reserve(lessons, client.budget, share=0.1, chars_per_token=3)
    baseline = scan(client, app, MASVS_CATEGORIES, [], "a", 3, held)
    calls = len(client.calls)
    taught = scan(client, app, MASVS_CATEGORIES, lessons, "b", 3, held)

    assert baseline.calls == taught.calls > 1
    assert baseline.lessons_used == [[]] * calls
    assert any(taught.lessons_used) and all(len(used) <= 1 for used in taught.lessons_used)
    for (_, before), (_, after) in zip(client.calls[:calls], client.calls[calls:]):
        if "<lessons>" in after:
            block = after[after.index("\n<lessons>") : after.index("</lessons>") + 11]
            after = after.replace(block, "")
        assert after == before
    assert "untrusted data" in client.calls[0][1]
    assert "do not report them again" in client.calls[1][1] and "do not report them again" not in client.calls[0][1]


def test_lessons_are_selected_by_signals_when_they_do_not_all_fit():
    lessons = [lesson(1, "WebView.loadUrl()"), lesson(2, "Cipher.getInstance"), lesson(3, "allowBackup")]
    code = "webView.loadUrl(target); Cipher cipher = Cipher.getInstance(mode);"
    assert select(lessons, code, allowance=10_000, chars_per_token=3) == lessons
    assert [l.id for l in select(lessons, code, allowance=200, chars_per_token=3)] == ["L1", "L2"]
    assert [l.id for l in select(lessons, code, allowance=140, chars_per_token=3)] == ["L1"]
    assert select(lessons, "nothing relevant", allowance=140, chars_per_token=3) == []


def test_lessons_are_generated_from_masked_input_and_leaks_are_dropped(app):
    finding = Finding.model_validate(FINDING | {"id": "F1"})
    leaked = LESSON | {"title": "Leaky", "pattern": "Check ShareActivity for loadUrl."}
    client = FakeClient("teacher", json.dumps({"lessons": [LESSON, leaked]}))
    result = generate(client, [finding], AppNames.from_app(app), MASVS_CATEGORIES, LessonConfig())

    assert "ShareActivity" not in client.calls[0][1]
    assert [l.title for l in result.lessons] == [LESSON["title"]]
    assert result.lessons[0].from_findings == ["F1"]
    assert [(d.lesson.title, d.terms) for d in result.dropped] == [("Leaky", ["ShareActivity"])]
    assert result.uncovered_categories == []


def test_unparseable_lesson_reply_is_retried_once_then_reported(app):
    finding = Finding.model_validate(FINDING | {"id": "F1"})
    client = FakeClient("teacher", "not json")
    result = generate(client, [finding], AppNames.from_app(app), MASVS_CATEGORIES, LessonConfig())
    assert len(client.calls) == 2
    assert result.failed and result.uncovered_categories == ["platform"]


def test_match_and_score():
    reference = [Finding(id=f"R{n}", title=f"r{n}", description="d") for n in (1, 2, 3, 4)]
    findings = [Finding(id=f"F{n}", title="t", description="d", source="s.lessons.1") for n in (1, 2, 3, 4)]
    reply = json.dumps({"assignments": [
        {"finding_id": "F1", "reference_id": "R1", "reason": "same"},
        {"finding_id": "F2", "reference_id": "R1", "reason": "duplicate"},
        {"finding_id": "F3", "reference_id": None, "reason": "no match"},
        {"finding_id": "F4", "reference_id": "R9", "reason": "invented id"},
    ]})
    client = FakeClient("judge", reply)
    result = match(client, reference, findings, batch_size=20)
    outcome = score(reference, result)

    assert "lessons" not in client.calls[0][1]
    assert result.unanswered == 1
    assert outcome.recall == 0.25 and outcome.precision == 0.5
    assert outcome.matched == ["R1"] and outcome.missed == ["R2", "R3", "R4"]
