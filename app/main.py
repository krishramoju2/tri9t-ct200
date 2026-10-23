
from pathlib import Path
from datetime import datetime, timezone
import hashlib
import json
import shutil
import tempfile
import unicodedata

from fastapi import FastAPI, File, HTTPException, UploadFile
from pydantic import BaseModel, Field

from app.parser import parse_pdf
from app.db import get_connection
from app.mongo import check_mongodb_connection
from app.qa_store import save_qa_test_cases, list_qa_test_cases
from app.llm import generate_qa_cases


app = FastAPI(
    title="CT-200 Document Ingestion API",
    description=(
        "Ingests technical manuals, manages document versions, "
        "saves section selections, generates QA test cases using an LLM, "
        "and tracks source changes."
    ),
    version="0.6.0",
)


class SelectionRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    section_ids: list[int] = Field(min_length=1)


class QATestCase(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    expected_answer: str = Field(min_length=1, max_length=5000)
    test_type: str = Field(default="functional", max_length=50)
    source_sections: list[str] = Field(default_factory=list)
    evidence_quote: str | None = None


class QATestCasesRequest(BaseModel):
    test_cases: list[QATestCase] = Field(min_length=1, max_length=100)
    model_name: str = Field(default="manual-test", max_length=100)


def _normalize_heading(value):
    """Normalize heading text for version-to-version matching."""
    value = unicodedata.normalize("NFKC", value or "")
    return " ".join(value.casefold().split())


def _latest_sections_for_filename(connection, filename):
    """Return sections from the latest ingested version of a filename."""
    rows = connection.execute("""
        SELECT sec.id, sec.section_number, sec.heading, sec.page,
               sec.document_order, sec.content, sec.content_hash
        FROM documents AS doc
        JOIN sections AS sec ON sec.document_id = doc.id
        WHERE doc.filename = ?
          AND doc.version_number = (
              SELECT MAX(version_number)
              FROM documents
              WHERE filename = ?
          )
        ORDER BY sec.document_order
    """, (filename, filename)).fetchall()

    return [dict(row) for row in rows]


def _compare_snapshot_to_latest(snapshot, latest_sections):
    """
    Compare saved source nodes with the latest document version.

    Matching uses section number and normalized heading, followed by
    a content-hash comparison. Duplicate matches are flagged as ambiguous.
    """
    reasons = []

    for saved in snapshot:
        saved_number = saved.get("section_number")
        saved_heading = _normalize_heading(saved.get("heading"))

        matches = [
            current
            for current in latest_sections
            if current.get("section_number") == saved_number
            and _normalize_heading(current.get("heading")) == saved_heading
        ]

        if not matches:
            reasons.append(
                "Source section "
                f"{saved_number or saved.get('section_id')} "
                "is missing or its heading/number changed."
            )
            continue

        saved_hash = saved.get("content_hash")
        current_hashes = {
            current.get("content_hash") for current in matches
        }

        if saved_hash not in current_hashes:
            reasons.append(
                "Source section "
                f"{saved_number or saved.get('section_id')} "
                "has changed since generation."
            )

        if len(matches) > 1:
            reasons.append(
                "Multiple sections share the same number and heading; "
                "version matching may be ambiguous."
            )

    return {
        "is_stale": bool(reasons),
        "stale_reasons": list(dict.fromkeys(reasons)),
    }


def _snapshot_for_sources(snapshot, source_sections):
    """
    Return only the source nodes cited by one test case.

    The model returns section identifiers, normally section numbers.
    If an identifier is ambiguous, preserve every matching node rather
    than silently choosing one.
    """
    wanted = set(source_sections or [])
    selected = []

    for node in snapshot:
        section_number = node.get("section_number")
        section_id = node.get("section_id")

        identifier = (
            section_number
            if section_number
            else f"node:{section_id}"
        )

        if identifier in wanted:
            selected.append(node)

    return selected


def _snapshot_node(section):
    """Build a compact source snapshot suitable for MongoDB storage."""
    return {
        "section_id": section["section_id"],
        "section_number": section["section_number"],
        "heading": section["heading"],
        "page": section["page"],
        "content": section["content"],
        "content_hash": section["content_hash"],
        "tables": section["tables"],
        "lists": section["lists"],
        "warnings": section["warnings"],
    }


@app.get("/")
def root():
    return {
        "message": "CT-200 Document Ingestion API",
        "version": app.version,
        "docs": "/docs",
        "health": "/health",
    }


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/health/mongodb")
def mongodb_health():
    try:
        return check_mongodb_connection()
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=f"MongoDB connection failed: {str(exc)}",
        ) from exc


@app.get("/documents")
def list_documents():
    with get_connection() as connection:
        rows = connection.execute("""
            SELECT id, filename, version_number, source_hash,
                   section_count, created_at
            FROM documents
            ORDER BY filename, version_number
        """).fetchall()

    return {"documents": [dict(row) for row in rows]}


@app.post("/ingest")
def ingest_document(file: UploadFile = File(...)):
    if not file.filename or Path(file.filename).suffix.lower() != ".pdf":
        raise HTTPException(
            status_code=400,
            detail="Please upload a PDF file.",
        )

    filename = Path(file.filename).name
    temp_path = None

    try:
        with tempfile.NamedTemporaryFile(
            delete=False,
            suffix=".pdf",
        ) as temp_file:
            temp_path = Path(temp_file.name)
            shutil.copyfileobj(file.file, temp_file)

        source_hash = hashlib.sha256(
            temp_path.read_bytes()
        ).hexdigest()

        # Check for an identical file and calculate the next version.
        with get_connection() as connection:
            existing = connection.execute("""
                SELECT id, filename, version_number, source_hash,
                       section_count
                FROM documents
                WHERE filename = ? AND source_hash = ?
                ORDER BY version_number DESC
                LIMIT 1
            """, (filename, source_hash)).fetchone()

            if existing:
                return {
                    "message": (
                        "This exact document has already been ingested."
                    ),
                    "document_id": existing["id"],
                    "filename": existing["filename"],
                    "version_number": existing["version_number"],
                    "source_hash": existing["source_hash"],
                    "section_count": existing["section_count"],
                    "already_ingested": True,
                }

            latest = connection.execute("""
                SELECT MAX(version_number) AS latest_version
                FROM documents
                WHERE filename = ?
            """, (filename,)).fetchone()

            version_number = (latest["latest_version"] or 0) + 1

        sections = parse_pdf(str(temp_path))

        if not sections:
            raise ValueError(
                "No document sections were extracted from this PDF."
            )

        with get_connection() as connection:
            cursor = connection.execute("""
                INSERT INTO documents (
                    filename, version_number, source_hash,
                    section_count, created_at
                ) VALUES (?, ?, ?, ?, ?)
            """, (
                filename,
                version_number,
                source_hash,
                len(sections),
                datetime.now(timezone.utc).isoformat(),
            ))

            document_id = cursor.lastrowid

            for item in sections:
                connection.execute("""
                    INSERT INTO sections (
                        document_id, section_number, heading, page,
                        document_order, content, tables_json, lists_json,
                        content_hash, parent_section, warnings_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    document_id,
                    item["section_number"],
                    item["heading"],
                    item["page"],
                    item["document_order"],
                    item["content"],
                    json.dumps(item["tables"], ensure_ascii=False),
                    json.dumps(item["lists"], ensure_ascii=False),
                    item["content_hash"],
                    item["parent_section"],
                    json.dumps(item["warnings"], ensure_ascii=False),
                ))

        return {
            "message": "Document ingested and saved successfully.",
            "document_id": document_id,
            "filename": filename,
            "version_number": version_number,
            "source_hash": source_hash,
            "section_count": len(sections),
            "already_ingested": False,
        }

    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=422,
            detail=f"Could not process PDF: {str(exc)}",
        ) from exc
    finally:
        file.file.close()
        if temp_path and temp_path.exists():
            temp_path.unlink()


@app.get("/documents/{document_id}/sections")
def get_document_sections(document_id: int):
    with get_connection() as connection:
        document = connection.execute(
            "SELECT id FROM documents WHERE id = ?",
            (document_id,),
        ).fetchone()

        if document is None:
            raise HTTPException(
                status_code=404,
                detail="Document not found.",
            )

        rows = connection.execute("""
            SELECT id, section_number, heading, page, document_order,
                   content, tables_json, lists_json, content_hash,
                   parent_section, warnings_json
            FROM sections
            WHERE document_id = ?
            ORDER BY document_order
        """, (document_id,)).fetchall()

    sections = []

    for row in rows:
        item = dict(row)
        item["tables"] = json.loads(item.pop("tables_json"))
        item["lists"] = json.loads(item.pop("lists_json"))
        item["warnings"] = json.loads(item.pop("warnings_json"))
        sections.append(item)

    return {
        "document_id": document_id,
        "sections": sections,
    }


@app.post("/documents/{document_id}/selections")
def create_selection(document_id: int, request: SelectionRequest):
    section_ids = list(dict.fromkeys(request.section_ids))
    selection_name = request.name.strip()

    if not selection_name:
        raise HTTPException(
            status_code=422,
            detail="Selection name cannot be blank.",
        )

    with get_connection() as connection:
        document = connection.execute(
            "SELECT id FROM documents WHERE id = ?",
            (document_id,),
        ).fetchone()

        if document is None:
            raise HTTPException(
                status_code=404,
                detail="Document not found.",
            )

        placeholders = ",".join("?" for _ in section_ids)

        rows = connection.execute(f"""
            SELECT id, content_hash
            FROM sections
            WHERE document_id = ? AND id IN ({placeholders})
        """, [document_id] + section_ids).fetchall()

        sections_by_id = {row["id"]: row for row in rows}

        missing_ids = [
            section_id
            for section_id in section_ids
            if section_id not in sections_by_id
        ]

        if missing_ids:
            raise HTTPException(
                status_code=400,
                detail={
                    "message": (
                        "Some section IDs do not belong to this document."
                    ),
                    "invalid_section_ids": missing_ids,
                },
            )

        cursor = connection.execute("""
            INSERT INTO selections (document_id, name, created_at)
            VALUES (?, ?, ?)
        """, (
            document_id,
            selection_name,
            datetime.now(timezone.utc).isoformat(),
        ))

        selection_id = cursor.lastrowid

        for section_id in section_ids:
            connection.execute("""
                INSERT INTO selection_sections (
                    selection_id, section_id, content_hash_at_selection
                ) VALUES (?, ?, ?)
            """, (
                selection_id,
                section_id,
                sections_by_id[section_id]["content_hash"],
            ))

    return {
        "message": "Section selection saved successfully.",
        "selection_id": selection_id,
        "document_id": document_id,
        "name": selection_name,
        "section_ids": section_ids,
        "section_count": len(section_ids),
    }


@app.get("/documents/{document_id}/selections")
def list_document_selections(document_id: int):
    with get_connection() as connection:
        document = connection.execute(
            "SELECT id FROM documents WHERE id = ?",
            (document_id,),
        ).fetchone()

        if document is None:
            raise HTTPException(
                status_code=404,
                detail="Document not found.",
            )

        rows = connection.execute("""
            SELECT s.id, s.document_id, s.name, s.created_at,
                   COUNT(ss.id) AS section_count
            FROM selections AS s
            LEFT JOIN selection_sections AS ss
                ON ss.selection_id = s.id
            WHERE s.document_id = ?
            GROUP BY s.id
            ORDER BY s.id DESC
        """, (document_id,)).fetchall()

    return {
        "document_id": document_id,
        "selections": [dict(row) for row in rows],
    }


@app.get("/selections/{selection_id}")
def get_selection(selection_id: int):
    with get_connection() as connection:
        selection = connection.execute("""
            SELECT s.id, s.document_id, s.name, s.created_at, d.filename,
                   d.version_number
            FROM selections AS s
            JOIN documents AS d ON d.id = s.document_id
            WHERE s.id = ?
        """, (selection_id,)).fetchone()

        if selection is None:
            raise HTTPException(
                status_code=404,
                detail="Selection not found.",
            )

        rows = connection.execute("""
            SELECT sec.id AS section_id, sec.section_number, sec.heading,
                   sec.page, sec.content, sec.content_hash,
                   ss.content_hash_at_selection
            FROM selection_sections AS ss
            JOIN sections AS sec ON sec.id = ss.section_id
            WHERE ss.selection_id = ?
            ORDER BY sec.document_order
        """, (selection_id,)).fetchall()

        latest_sections = _latest_sections_for_filename(
            connection,
            selection["filename"],
        )

    snapshot = [
        {
            "section_id": row["section_id"],
            "section_number": row["section_number"],
            "heading": row["heading"],
            "content_hash": row["content_hash_at_selection"],
        }
        for row in rows
    ]

    comparison = _compare_snapshot_to_latest(snapshot, latest_sections)
    selected_sections = []

    for row in rows:
        item = dict(row)

        # This compares the selected version to the latest ingested version,
        # rather than comparing two copies of the same immutable database row.
        saved_node = {
            "section_id": item["section_id"],
            "section_number": item["section_number"],
            "heading": item["heading"],
            "content_hash": item["content_hash_at_selection"],
        }

        item["latest_version_staleness"] = _compare_snapshot_to_latest(
            [saved_node],
            latest_sections,
        )

        selected_sections.append(item)

    return {
        "selection": dict(selection),
        "section_count": len(selected_sections),
        "sections": selected_sections,
        "latest_version_staleness": comparison,
    }


@app.post("/selections/{selection_id}/generate-qa-cases")
def generate_selection_qa_cases(selection_id: int):
    """Generate QA cases from the exact sections saved in a selection."""

    with get_connection() as connection:
        selection = connection.execute("""
            SELECT s.id, s.document_id, s.name, d.filename,
                   d.version_number
            FROM selections AS s
            JOIN documents AS d ON d.id = s.document_id
            WHERE s.id = ?
        """, (selection_id,)).fetchone()

        if selection is None:
            raise HTTPException(
                status_code=404,
                detail="Selection not found.",
            )

        rows = connection.execute("""
            SELECT sec.id AS section_id, sec.section_number, sec.heading,
                   sec.page, sec.content, sec.content_hash,
                   sec.tables_json, sec.lists_json, sec.warnings_json
            FROM selection_sections AS ss
            JOIN sections AS sec ON sec.id = ss.section_id
            WHERE ss.selection_id = ?
            ORDER BY sec.document_order
        """, (selection_id,)).fetchall()

    if not rows:
        raise HTTPException(
            status_code=422,
            detail="The selection contains no sections.",
        )

    metadata = []
    snapshot = []
    text_parts = []
    allowed_identifiers = set()

    for row in rows:
        item = dict(row)

        section_number = item["section_number"]
        identifier = (
            section_number
            if section_number
            else f"node:{item['section_id']}"
        )

        if section_number:
            allowed_identifiers.add(section_number)

        allowed_identifiers.add(identifier)

        tables = json.loads(item.pop("tables_json"))
        lists = json.loads(item.pop("lists_json"))
        warnings = json.loads(item.pop("warnings_json"))

        metadata.append({
            "section_identifier": identifier,
            "section_number": section_number,
            "heading": item["heading"],
            "page": item["page"],
        })

        snapshot.append({
            "section_id": item["section_id"],
            "section_number": section_number,
            "heading": item["heading"],
            "page": item["page"],
            "content": item["content"],
            "content_hash": item["content_hash"],
            "tables": tables,
            "lists": lists,
            "warnings": warnings,
        })

        text_parts.append(
            f"Section identifier: {identifier}\n"
            f"Heading: {item['heading']}\n"
            f"Page: {item['page']}\n"
            f"Content:\n{item['content']}\n"
            f"Tables:\n{json.dumps(tables, ensure_ascii=False)}\n"
            f"Lists:\n{json.dumps(lists, ensure_ascii=False)}"
        )

    section_text = "\n\n".join(text_parts)

    try:
        generated = generate_qa_cases(
            section_text=section_text,
            section_metadata=metadata,
            count=4,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail=f"Could not generate QA cases: {str(exc)}",
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"LLM generation failed: {str(exc)}",
        ) from exc

    test_cases = generated["test_cases"]

    # Validate references and prepare per-case source snapshots before saving.
    for index, case in enumerate(test_cases, start=1):
        cited_sections = case.get("source_sections", [])

        invalid_sources = [
            source
            for source in cited_sections
            if source not in allowed_identifiers
        ]

        if not cited_sections or invalid_sources:
            raise HTTPException(
                status_code=502,
                detail={
                    "message": (
                        "The model returned invalid source-section "
                        "references. No cases were saved."
                    ),
                    "case_number": index,
                    "invalid_sources": invalid_sources,
                },
            )

        case_snapshot = _snapshot_for_sources(snapshot, cited_sections)

        if not case_snapshot:
            raise HTTPException(
                status_code=502,
                detail={
                    "message": (
                        "Could not map the cited sections to the saved "
                        "source snapshot. No cases were saved."
                    ),
                    "case_number": index,
                    "source_sections": cited_sections,
                },
            )

        # Store the exact nodes cited by this particular QA case.
        case["source_snapshot"] = case_snapshot

    try:
        saved = save_qa_test_cases(
            document_id=selection["document_id"],
            selection_id=selection_id,
            test_cases=test_cases,
            model_name=generated["model_name"],
            document_version_number=selection["version_number"],
        )
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Could not save generated QA cases: {str(exc)}",
        ) from exc

    # Avoid returning the internal snapshot payload redundantly in the response.
    response_cases = []

    for case in test_cases:
        response_case = {
            key: value
            for key, value in case.items()
            if key != "source_snapshot"
        }
        response_cases.append(response_case)

    return {
        "message": "QA test cases generated and saved successfully.",
        "document_id": selection["document_id"],
        "document_version_number": selection["version_number"],
        "selection_id": selection_id,
        "generation_id": saved["generation_id"],
        "model_name": generated["model_name"],
        "generated_count": len(test_cases),
        "saved_count": saved["saved_count"],
        "qa_case_ids": saved["qa_case_ids"],
        "source_sections": metadata,
        "test_cases": response_cases,
        "staleness": {
            "is_stale": False,
            "message": (
                "Cases were generated from the saved selection snapshot. "
                "Recheck staleness when retrieving them."
            ),
        },
    }


@app.post("/selections/{selection_id}/qa-cases")
def create_qa_cases(selection_id: int, request: QATestCasesRequest):
    """Manually save QA cases, for testing or importing existing cases."""

    with get_connection() as connection:
        selection = connection.execute("""
            SELECT id, document_id
            FROM selections
            WHERE id = ?
        """, (selection_id,)).fetchone()

        if selection is None:
            raise HTTPException(
                status_code=404,
                detail="Selection not found.",
            )

    try:
        result = save_qa_test_cases(
            document_id=selection["document_id"],
            selection_id=selection_id,
            test_cases=[
                item.model_dump() for item in request.test_cases
            ],
            model_name=request.model_name,
        )

        return {
            "message": "QA test cases saved successfully.",
            "document_id": selection["document_id"],
            "selection_id": selection_id,
            **result,
        }

    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Could not save QA test cases: {str(exc)}",
        ) from exc


@app.get("/selections/{selection_id}/qa-cases")
def get_qa_cases(selection_id: int):
    """Retrieve saved cases and compare their source snapshots to latest version."""

    with get_connection() as connection:
        selection = connection.execute("""
            SELECT s.id, s.document_id, d.filename, d.version_number
            FROM selections AS s
            JOIN documents AS d ON d.id = s.document_id
            WHERE s.id = ?
        """, (selection_id,)).fetchone()

        if selection is None:
            raise HTTPException(
                status_code=404,
                detail="Selection not found.",
            )

        latest_sections = _latest_sections_for_filename(
            connection,
            selection["filename"],
        )

    try:
        cases = list_qa_test_cases(selection_id=selection_id)
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Could not retrieve QA test cases: {str(exc)}",
        ) from exc

    for case in cases:
        snapshot = case.get("source_snapshot")

        if not snapshot:
            case["is_stale"] = None
            case["stale_reasons"] = [
                "No source snapshot is available for this case."
            ]
            case["staleness_status"] = "unknown"
            continue

        comparison = _compare_snapshot_to_latest(
            snapshot,
            latest_sections,
        )

        case["is_stale"] = comparison["is_stale"]
        case["stale_reasons"] = comparison["stale_reasons"]
        case["staleness_status"] = (
            "stale" if comparison["is_stale"] else "current"
        )

    return {
        "selection_id": selection_id,
        "document_version_at_selection": selection["version_number"],
        "count": len(cases),
        "test_cases": cases,
    }
