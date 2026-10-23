
import re
import hashlib
import json
import unicodedata

import pdfplumber
from pypdf import PdfReader


def normalize_text(text):
    text = unicodedata.normalize("NFKC", text or "")
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


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

    subsection_pattern = re.compile(r"^(\d+(?:\.\d+)+)\s+(.+)$")
    top_level_pattern = re.compile(r"^(\d+)\.\s+(.+)$")

    current_section = None
    page_texts = {}

    for page_number, page in enumerate(reader.pages, start=1):
        page_texts[page_number] = page.extract_text() or ""

    # Extract tables and record their vertical position on each page.
    page_tables = {}

    with pdfplumber.open(pdf_path) as pdf:
        for page_number, page in enumerate(pdf.pages, start=1):
            found_tables = []

            for table in page.find_tables():
                extracted = table.extract() or []
                rows = []

                for row in extracted:
                    cleaned = [
                        normalize_text(cell) if cell else ""
                        for cell in row
                    ]

                    if any(cleaned):
                        rows.append(cleaned)

                if rows:
                    found_tables.append({
                        "top": table.bbox[1],
                        "rows": rows,
                    })

            page_tables[page_number] = found_tables

    # Parse headings and section text.
    for page_number, page_text in page_texts.items():
        for raw_line in page_text.splitlines():
            line = normalize_text(raw_line)

            if not line:
                continue

            match = subsection_pattern.match(line)

            if match:
                section_number = match.group(1)
                heading = match.group(2).strip()
            else:
                match = top_level_pattern.match(line)

                if match and match.group(2).strip() in known_top_level_headings:
                    section_number = match.group(1)
                    heading = match.group(2).strip()
                else:
                    if current_section is not None:
                        current_section["content"] += "\n" + line
                    continue

            document_order += 1
            parts = section_number.split(".")
            parent_section = (
                ".".join(parts[:-1]) if len(parts) > 1 else None
            )

            current_section = {
                "section_number": section_number,
                "heading": heading,
                "page": page_number,
                "document_order": document_order,
                "content": "",
                "tables": [],
                "lists": [],
                "content_hash": "",
                "parent_section": parent_section,
                "warnings": [],
            }

            nodes.append(current_section)

    # Associate each table with the closest section heading above it
    # on the same page. Heading coordinates are estimated from extracted
    # words, so table ownership is marked as a heuristic.
    with pdfplumber.open(pdf_path) as pdf:
        for page_number, page in enumerate(pdf.pages, start=1):
            page_nodes = [
                node for node in nodes if node["page"] == page_number
            ]

            words = page.extract_words() or []

            for node in page_nodes:
                heading_words = node["heading"].split()
                candidates = []

                for word in words:
                    if word["text"] == node["section_number"]:
                        candidates.append(word["top"])

                node["_heading_top"] = min(candidates) if candidates else None

            for table in page_tables.get(page_number, []):
                table_top = table["top"]

                eligible = [
                    node for node in page_nodes
                    if node["_heading_top"] is not None
                    and node["_heading_top"] <= table_top
                ]

                if eligible:
                    owner = max(eligible, key=lambda n: n["_heading_top"])
                    owner["tables"].append(table["rows"])
                    owner["warnings"].append(
                        "Table ownership inferred from page coordinates; verify."
                    )

    # Preserve list items, normalize content and compute full-content hashes.
    for node in nodes:
        node["content"] = normalize_text(node["content"])

        node["lists"] = [
            normalize_text(line)
            for line in node["content"].splitlines()
            if re.match(r"^(?:\d+[.)]|[-•*])\s+", normalize_text(line))
        ]

        node.pop("_heading_top", None)

        hash_payload = {
            "heading": node["heading"],
            "content": node["content"],
            "tables": node["tables"],
            "lists": node["lists"],
        }

        node["content_hash"] = calculate_hash(
            json.dumps(hash_payload, sort_keys=True, ensure_ascii=False)
        )

    section_numbers = {node["section_number"] for node in nodes}

    for node in nodes:
        parent = node["parent_section"]

        if parent and parent not in section_numbers:
            node["warnings"].append("Missing parent heading: " + parent)

    return nodes


if __name__ == "__main__":
    sections = parse_pdf("data/ct200_manual.pdf")

    print("CT-200 STRUCTURED EXTRACTION")
    print("=" * 70)
    print("Sections detected:", len(sections))
    print("Sections containing tables:", sum(bool(s["tables"]) for s in sections))
    print("Sections containing lists:", sum(bool(s["lists"]) for s in sections))

    for section in sections:
        print(
            section["section_number"],
            "|", section["heading"],
            "| Page:", section["page"],
            "| Tables:", len(section["tables"]),
            "| Lists:", len(section["lists"]),
            "| Warnings:", section["warnings"],
        )
