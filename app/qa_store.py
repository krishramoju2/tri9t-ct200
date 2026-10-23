
from datetime import datetime, timezone
from uuid import uuid4

from app.mongo import get_database


COLLECTION_NAME = "qa_test_cases"


def get_qa_collection():
    return get_database()[COLLECTION_NAME]


def save_qa_test_cases(
    document_id,
    selection_id,
    test_cases,
    model_name="unknown",
    source_snapshot=None,
    document_version_number=None,
):
    """Save QA cases with evidence and the exact source used to generate them."""

    if not test_cases:
        raise ValueError("At least one QA test case is required.")

    now = datetime.now(timezone.utc).isoformat()
    generation_id = str(uuid4())
    documents = []

    for index, test_case in enumerate(test_cases, start=1):
        case_snapshot = test_case.get("source_snapshot")

        if case_snapshot is None:
            case_snapshot = source_snapshot or []

        documents.append({
            "document_id": document_id,
            "selection_id": selection_id,
            "generation_id": generation_id,
            "case_number": index,
            "question": test_case["question"],
            "expected_answer": test_case["expected_answer"],
            "evidence_quote": test_case.get("evidence_quote"),
            "test_type": test_case.get("test_type", "functional"),
            "source_sections": test_case.get("source_sections", []),
            "source_snapshot": case_snapshot,
            "document_version_number": document_version_number,
            "model_name": model_name,
            "created_at": now,
        })

    result = get_qa_collection().insert_many(documents)

    return {
        "generation_id": generation_id,
        "saved_count": len(result.inserted_ids),
        "qa_case_ids": [str(item_id) for item_id in result.inserted_ids],
    }


def list_qa_test_cases(document_id=None, selection_id=None, limit=100):
    """Return QA cases newest first."""

    query = {}

    if document_id is not None:
        query["document_id"] = document_id

    if selection_id is not None:
        query["selection_id"] = selection_id

    records = (
        get_qa_collection()
        .find(query)
        .sort("_id", -1)
        .limit(limit)
    )

    results = []

    for record in records:
        record["id"] = str(record.pop("_id"))
        results.append(record)

    return results


def delete_qa_test_cases(selection_id):
    """Delete all QA cases associated with a selection."""

    result = get_qa_collection().delete_many({
        "selection_id": selection_id
    })

    return {
        "deleted_count": result.deleted_count
    }
