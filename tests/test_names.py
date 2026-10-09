from vulnscan.names import AppNames, is_app_literal

PACKAGE = "com.example.notes"


def test_app_literals_are_urls_package_strings_keys_and_tokens():
    assert is_app_literal("https://api.notes.example/v1", PACKAGE)
    assert is_app_literal("com.example.notes.files", PACKAGE)
    assert is_app_literal("note_url", PACKAGE)
    assert is_app_literal("eu-west-9:0a1b2c3d-1111-2222-3333-444455556666", PACKAGE)


def test_bare_domains_count_but_file_names_and_platform_namespaces_do_not():
    assert is_app_literal("notes.example", PACKAGE)
    for literal in ("config.json", "android.permission.camera"):
        assert not is_app_literal(literal, PACKAGE)


def test_platform_literals_are_left_alone():
    for literal in ("AES/ECB/PKCS5Padding", "PBKDF2WithHmacSHA256", "text/html", "password",
                    "android.intent.action.VIEW"):
        assert not is_app_literal(literal, PACKAGE)


def test_mask_hides_app_names_and_keeps_platform_names(app):
    masked = AppNames.from_app(app).mask(
        'ShareActivity reads "note_url" then calls loadUrl; uses "AES/ECB/PKCS5Padding" '
        "and https://api.notes.example/v1 in com.example.notes"
    )
    for name in ("ShareActivity", "note_url", "api.notes.example", "com.example.notes"):
        assert name not in masked
    assert "loadUrl" in masked and "AES/ECB/PKCS5Padding" in masked


def test_compiler_artefacts_do_not_make_platform_names_app_defined(app):
    names = AppNames.from_app(app)
    text = "Override onReceivedSslError and check savedState before calling proceed."
    assert names.mask(text) == text
    assert names.leaks(text, []) == []


def test_app_display_name_and_bare_domain_are_masked_and_guarded(app):
    names = AppNames.from_app(app)
    masked = names.mask("QuickNotes trusts any host ending in notes.example (quicknotes scheme).")
    assert "QuickNotes" not in masked and "notes.example" not in masked and "quicknotes" not in masked
    assert names.leaks("This runs inside QuickNotes.", []) == ["QuickNotes"]


def test_package_words_are_masked_inside_identifiers_but_not_in_prose(app):
    names = AppNames.from_app(app)
    assert names.package_parts == {"example", "notes"}
    masked = names.mask("Opens notes://example/login and reads %2Fcom.example.notes%2Fdb, see example.plugin.Loader.")
    assert "notes://" not in masked and "//example/" not in masked
    assert "example.notes" not in masked and "example.plugin" not in masked
    prose = "For example, the release notes mention a common pattern."
    assert names.mask(prose) == prose
    assert names.leaks(prose, []) == []
    assert names.leaks("Send a link such as notes://open to the app.", []) == ["notes"]


def test_leaks_reports_names_and_leftover_placeholders(app):
    names = AppNames.from_app(app)
    assert names.leaks("Exported activities that pass an extra to loadUrl are a risk.", []) == []
    assert names.leaks("Check ShareActivity and <CLASS_2>.", []) == ["<CLASS_2>", "ShareActivity"]
    assert names.leaks("Check ShareActivity.", allow=["ShareActivity"]) == []
