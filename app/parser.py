
import re
import hashlib
import unicodedata
from pypdf import PdfReader


def normalize_text(text):
    text = unicodedata.normalize("NFKC", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def calculate_hash(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def parse_pdf(pdf_path):
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
        "Regulatory Information",
    }

    heading_pattern = re.compile(r"^(\d+(?:\.\d+)*)\s+(.+)$")
    top_level_pattern = re.compile(r"^(\d+)\.\s+(.+)$")

    current_section = None

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

                # A numbered subsection must contain a dot.
                if "." not in section_number:
                    match = None

            if match is None:
                match = top_level_pattern.match(line)

                if not match:
                    if current_section is not None:
                        current_section["content"] += "\n" + line
                    continue

                section_number = match.group(1)
                heading = match.group(2).strip()

                if heading not in known_top_level_headings:
                    if current_section is not None:
                        current_section["content"] += "\n" + line
                    continue

            document_order += 1

            parts = section_number.split(".")
            parent_section = ".".join(parts[:-1]) if len(parts) > 1 else None

            node = {
                "section_number": section_number,
                "heading": heading,
                "page": page_number,
                "document_order": document_order,
                "content": "",
                "content_hash": "",
                "parent_section": parent_section,
                "warnings": [],
            }

            nodes.append(node)
            current_section = node

    # Normalize content and hash the heading plus its extracted content.
    for node in nodes:
        node["content"] = normalize_text(node["content"])
        hash_input = node["heading"] + "\n" + node["content"]
        node["content_hash"] = calculate_hash(hash_input)

    section_numbers = {node["section_number"] for node in nodes}

    for node in nodes:
        parent = node["parent_section"]

        if parent and parent not in section_numbers:
            node["warnings"].append("Missing parent heading: " + parent)

    return nodes


if __name__ == "__main__":
    sections = parse_pdf("data/ct200_manual.pdf")

    print("CT-200 SECTION EXTRACTION")
    print("=" * 70)
    print("Sections detected:", len(sections))

    print("\nFirst 3 sections with content:")
    for section in sections[:3]:
        print("\nSection:", section["section_number"], "-", section["heading"])
        print("Page:", section["page"])
        print("Content:", section["content"][:250])
        print("Content hash:", section["content_hash"])

    print("\nSections with warnings:")
    for section in sections:
        if section["warnings"]:
            print(section["section_number"], section["warnings"])
