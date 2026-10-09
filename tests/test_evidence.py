from vulnscan.config import EvidenceConfig
from vulnscan.evidence import EvidenceIndex, scored
from vulnscan.schema import Finding


def finding(evidence: str, file: str = "ShareActivity.java") -> Finding:
    return Finding(title="t", description="d", evidence=evidence, locations=[{"file": file}])


def status(app, evidence, file="ShareActivity.java", **config) -> str:
    item = finding(evidence, file)
    EvidenceIndex(app).verify([item], EvidenceConfig(**config))
    return item.evidence_status


def test_reformatted_quote_is_verified(app):
    assert status(app, "String target =\n   getIntent().getStringExtra( \"note_url\" );") == "verified"


def test_newlines_escaped_by_the_model_still_separate_lines(app):
    assert status(app, 'webView.loadUrl(target);\\nString api = "https://api.notes.example/v1";') == "verified"


def test_real_code_in_the_wrong_file_is_relocated(app):
    assert status(app, "webView.loadUrl(target);", file="MainActivity.java") == "relocated"


def test_invented_code_is_unverified(app):
    assert status(app, "Runtime.getRuntime().exec(userInput);") == "unverified"


def test_trivial_lines_alone_do_not_verify(app):
    assert status(app, "}\n...\n{") == "unverified"


def test_min_match_decides_partial_quotes(app):
    partial = "webView.loadUrl(target);\nRuntime.getRuntime().exec(userInput);"
    assert status(app, partial) == "verified"
    assert status(app, partial, min_match=1.0) == "unverified"


def test_check_setting_controls_scoring(app):
    item = finding("Runtime.getRuntime().exec(userInput);")
    EvidenceIndex(app).verify([item], EvidenceConfig())
    assert scored([item], EvidenceConfig(check="exclude")) == []
    assert scored([item], EvidenceConfig(check="flag")) == [item]

    untouched = finding("anything at all")
    EvidenceIndex(app).verify([untouched], EvidenceConfig(check="off"))
    assert untouched.evidence_status == "unchecked"
