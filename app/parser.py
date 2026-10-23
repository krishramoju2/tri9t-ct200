
import re
import hashlib
import unicodedata
from pypdf import PdfReader


def normalize_text(text):
    """Normalize ligatures and whitespace in extracted text."""
    text = unicodedata.normalize("NFKC", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def calculate_hash(text):
    """Calculate a SHA-256 content hash."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def parse_pdf(pdf_path):
    """Extract numbered headings and detect missing parents."""

    reader = PdfReader(pdf_path)
    nodes = []
    document_order = 0

    known_top_level_headings = {
        "Device Overview",
        "Physical and Electrical Specifications",
        "Device Operation",
        "Alarms and Safety Behavior",
        "Data Management",
        "Maintenance and Cleaning",
        "Troubleshooting",
        "Regulatory Information"
    }

    # The number must end at a period followed by whitespace.
    # This distinguishes 2.1.1.1 Battery Life from list items.
    heading_pattern = re.compile(
        r"^(\d+(?:\.\d+)*)\s+(.+)$"
    )

    # Also support top-level headings written as "1. Title".
    top_level_pattern = re.compile(
        r"^(\d+)\.\s+(.+)$"
    )

    for page_number, page in enumerate(reader.pages, start=1):
        page_text = page.extract_text() or ""

        for raw_line in page_text.splitlines():
            line = normalize_text(raw_line)

            if not line:
                continue

            match = heading_pattern.match(line)

            if match:
                section_number = match.group(1)
                heading = match.group(2).strip()

                # A section number with multiple components is
                # a subsection, such as 1.1 or 2.1.1.1.
                if "." not in section_number:
                    continue

            else:
                match = top_level_pattern.match(line)

                if not match:
                    continue

                section_number = match.group(1)
                heading = match.group(2).strip()

                if heading not in known_top_level_headings:
                    continue

            document_order += 1
            parts = section_number.split(".")

            parent_section = (
                ".".join(parts[:-1]) if len(parts) > 1 else None
            )

            nodes.append({
                "section_number": section_number,
                "heading": heading,
                "page": page_number,
                "document_order": document_order,
                "content_hash": calculate_hash(line),
                "parent_section": parent_section,
                "warnings": []
            })

    section_numbers = {
        node["section_number"] for node in nodes
    }

    for node in nodes:
        parent = node["parent_section"]

        if parent and parent not in section_numbers:
            node["warnings"].append(
                "Missing parent heading: " + parent
            )

    return nodes

if __name__ == "__main__":
    sections = parse_pdf("data/ct200_manual.pdf")

    print("CT-200 SECTION EXTRACTION")
    print("=" * 70)
    print("Sections detected:", len(sections))

    print("\nFirst 3 sections:")
    for section in sections[:3]:
        print(section)

    print("\nSections with warnings:")
    for section in sections:
        if section["warnings"]:
            print(section["section_number"], section["warnings"])

    print("\nDuplicate heading names:")
    heading_counts = {}

    for section in sections:
        heading = section["heading"]
        heading_counts[heading] = heading_counts.get(heading, 0) + 1

    for heading, count in heading_counts.items():
        if count > 1:
            print(heading, "appears", count, "times")