import pytest

from vulnscan.cli import main
from vulnscan.config import MASVS_CATEGORIES
from vulnscan.reference import ReferenceFormatError, convert, parse_markdown_list
from vulnscan.schema import load_reference

LIST = """# Notes app

## Setup

- Install the app

## Known issues

1. **Hardcoded key:** An API key is embedded
   in the app's code.
2. Open redirect: The share screen loads any URL.
* Debug logging enabled

## Credits

- Someone
"""


def test_items_become_entries_with_text_copied_exactly():
    assert parse_markdown_list(LIST, section="known issues") == [
        {"title": "Hardcoded key", "description": "An API key is embedded in the app's code."},
        {"title": "Open redirect", "description": "The share screen loads any URL."},
        {"title": "Debug logging enabled", "description": "Debug logging enabled"},
    ]


def test_without_a_section_every_list_item_is_read():
    assert len(parse_markdown_list(LIST)) == 5


def test_unsupported_or_empty_input_is_an_error(tmp_path):
    (tmp_path / "list.csv").write_text("title,description\n")
    (tmp_path / "empty.md").write_text("No list here.\n")
    with pytest.raises(ReferenceFormatError, match="no converter"):
        convert(tmp_path / "list.csv")
    with pytest.raises(ReferenceFormatError, match="no list items"):
        convert(tmp_path / "empty.md")


def test_command_writes_yaml_the_pipeline_can_load_and_never_overwrites(tmp_path):
    source, out = tmp_path / "list.md", tmp_path / "reference.yaml"
    source.write_text(LIST)
    assert main(["reference", str(source), "-o", str(out), "--section", "Known issues"]) == 0
    reference = load_reference(out, MASVS_CATEGORIES)
    assert [(entry.id, entry.title) for entry in reference][:2] == [("R1", "Hardcoded key"), ("R2", "Open redirect")]
    assert main(["reference", str(source), "-o", str(out)]) == 1
