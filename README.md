# CT-200 Manual Intelligence API

A document-ingestion and LLM-powered QA test-case generation service built with FastAPI. The system extracts structured content from a CT-200 device manual, stores document versions and selections, generates test cases from selected sections, and retains source snapshots for staleness analysis.

## Features

- PDF text extraction and section-based document parsing.
- Section metadata, content hashes, extracted tables, lists, and parser warnings.
- Document version tracking using source-file hashes.
- Selection of document sections for QA generation.
- LLM-powered generation of structured QA test cases.
- JSON response parsing, validation, evidence-quote checks, and retry handling.
- SQLite persistence for documents, sections, versions, and selections.
- MongoDB persistence for generated QA test cases and source snapshots.
- Retrieval of generated cases with staleness information.
- Automated parser tests using pytest.

## Technology Stack

- Python
- FastAPI and Uvicorn
- Pydantic
- SQLite using Python's standard library
- MongoDB and PyMongo
- pypdf and pdfplumber
- Groq-compatible chat-completions API
- pytest and HTTPX

## Project Structure

```text
tri9t-ct200/
├── app/
│   ├── __init__.py
│   ├── db.py
│   ├── llm.py
│   ├── main.py
│   ├── mongo.py
│   ├── parser.py
│   └── qa_store.py
├── data/
│   └── ct200_manual.pdf
├── tests/
│   ├── __init__.py
│   ├── test_parser.py
│   └── test_llm.py
├── .env
├── .gitignore
└── README.md
```

The SQLite database is created locally under `data/`. Do not commit local databases, virtual environments, or API credentials.

## Prerequisites

- Python 3.11 or later, subject to compatibility with installed dependencies.
- MongoDB running locally or an accessible MongoDB instance.
- A valid API key for the configured LLM provider.
- Git.

## Installation

Clone the repository and enter the project directory:

```powershell
git clone <YOUR_GITHUB_REPOSITORY_URL>
cd tri9t-ct200
```

Create and activate a virtual environment:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

Install the required dependencies:

```powershell
python -m pip install fastapi "uvicorn[standard]" pydantic pypdf pdfplumber pymongo python-dotenv pytest httpx python-multipart
```

If the repository contains a dependency file, install from that file instead to reproduce the pinned environment.

## Environment Configuration

Create a `.env` file in the project root:

```dotenv
LLM_API_KEY=your_provider_api_key
LLM_BASE_URL=https://api.groq.com/openai/v1
LLM_MODEL=openai/gpt-oss-120b
```

Replace the placeholder API key with your own key. Never commit `.env` or publish API credentials.

The MongoDB connection is currently configured in `app/mongo.py`. The default local connection is:

```text
mongodb://localhost:27017
```

Ensure MongoDB is running before testing database-dependent endpoints.

## Running the Application

From the project root, activate the virtual environment and run:

```powershell
uvicorn app.main:app --reload
```

Open the interactive Swagger interface:

```text
http://127.0.0.1:8000/docs
```

The health and database endpoints can be used to verify application and MongoDB connectivity.

## API Workflow

Use Swagger to inspect the exact request schemas and execute the endpoints.

1. **Check service health:** verify that the API starts and responds.
2. **Check MongoDB:** use the MongoDB health endpoint.
3. **Ingest a PDF:** upload the CT-200 manual using the document-ingestion endpoint.
4. **Inspect documents:** call `GET /documents` to view ingested document versions.
5. **Inspect sections:** retrieve the parsed sections and their metadata.
6. **Create a selection:** choose the relevant document sections for a QA generation task.
7. **Generate test cases:** submit the selection to the LLM-powered generation endpoint.
8. **Retrieve test cases:** use the selection's QA-cases retrieval endpoint to inspect generated cases and their staleness information.

The generated records include fields such as the question, expected answer, test type, source sections, model name, and source snapshot when available.

## Document Versioning and Staleness

Each ingested document version is identified by its filename, version number, and source hash. Re-ingesting an identical file should not create a new content version. A changed file uploaded under the same filename is intended to create a subsequent version.

Selections retain hashes for their selected section content. Generated QA records retain source snapshots so the application can compare the content used during generation with the latest ingested version.

Staleness outcomes must be interpreted carefully:

- **Current:** the stored source snapshot matches the current source content according to the implemented comparison.
- **Stale:** the comparison identifies a source change.
- **Unknown:** the record lacks enough source information to determine staleness.

A stale result indicates that a case may need review; it does not establish that the test is invalid. Likewise, a current result does not guarantee that the expected answer is semantically correct.

### Version-change demonstration

To demonstrate version tracking:

1. Preserve the original manual as Version 1.
2. Create a separate test copy and make a documented, synthetic change to a section.
3. Ingest the changed PDF using the original filename so it follows the same version history.
4. Verify the versions using `GET /documents`.
5. Retrieve previously generated cases and inspect their staleness status.
6. Confirm that affected cases retain their original source snapshots.

Record the actual responses and observed results. Do not claim successful stale-case detection until this sequence has been executed and verified.

## Testing

Run the automated test suite:

```powershell
python -m pytest -q
```

The parser tests cover section extraction, content hashing, missing-parent detection, duplicate headings, and preservation of important tables.

The project has previously passed **7 tests** in the development environment. Re-run the tests after making changes and record the latest result.

LLM integration tests may require a working provider API key and network connectivity. Clearly distinguish offline unit tests from tests that call the live provider.

## Known Limitations

- PDF text extraction can produce merged words or imperfect table boundaries.
- Some extracted table fragments require manual review.
- A matching evidence quote establishes that text exists in the source; it does not prove that an entire expected answer follows logically from the manual.
- LLM-generated cases may infer behavior that the source does not explicitly specify.
- Staleness detection depends on the accuracy of section matching and source snapshots.
- Duplicate or ambiguous section identifiers can complicate source-to-case matching.
- A case with no source snapshot cannot be reliably assessed for content staleness.

For safety-critical device documentation, generated expected answers should be reviewed against the source before being treated as authoritative.

## Security and Data Handling

- Keep API keys in environment variables and exclude `.env` from Git.
- Do not commit local database files, virtual environments, or generated secrets.
- Restrict access to stored documents and test cases according to the deployment environment.
- Review generated outputs before using them for actual device validation.

## Future Improvements

- Improve table reconstruction and reading-order detection.
- Add more robust structural matching across document versions.
- Store only the source sections directly relevant to each generated case.
- Strengthen semantic grounding and flag unsupported expected answers.
- Add deterministic tests for API, database, and version-change workflows.
- Add concurrency protection for simultaneous ingestion requests.
- Provide a reproducible deployment configuration and pinned dependencies.

## Development Status

The application has demonstrated PDF ingestion, section selection, LLM-based test generation, MongoDB persistence, and retrieval in the development environment. Version-change detection, source-to-case snapshot precision, and semantic correctness require separate verification before the system can be considered fully validated.
