
from app.parser import parse_pdf


def test_ct200_manual_sections():
    sections = parse_pdf("data/ct200_manual.pdf")

    # The manual should contain 27 detected sections.
    assert len(sections) == 27

    # Each section must have the required metadata.
    for section in sections:
        assert section["section_number"]
        assert section["heading"]
        assert section["page"] >= 1
        assert section["document_order"] >= 1
        assert section["content_hash"]
        assert "warnings" in section


def test_missing_parent_heading_is_detected():
    sections = parse_pdf("data/ct200_manual.pdf")

    battery_section = next(
        section
        for section in sections
        if section["section_number"] == "2.1.1.1"
    )

    assert "Missing parent heading: 2.1.1" in battery_section["warnings"]


def test_duplicate_error_code_headings_are_preserved():
    sections = parse_pdf("data/ct200_manual.pdf")

    error_sections = [
        section
        for section in sections
        if section["heading"] == "Error Codes"
    ]

    assert len(error_sections) == 2
    assert {section["section_number"] for section in error_sections} == {
        "4.2",
        "7.1",
    }
