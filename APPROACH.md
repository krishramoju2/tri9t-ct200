# Engineering Approach — CT-200 Document Intelligence API

## 1. Overview

The CT-200 Document Intelligence API converts a technical PDF manual into structured document sections, supports versioned ingestion, and generates QA test-case ideas from selected content using a large language model (LLM). The implementation separates PDF parsing, relational metadata storage, LLM interaction, and generated-output persistence.

FastAPI exposes the workflow through HTTP endpoints and Swagger UI. SQLite stores document metadata, versions, parsed sections, and selections. MongoDB stores generated QA records and source snapshots.

## 2. Document Parsing Decisions

### 2.1 Text Extraction and Structure

The parser uses pypdf to extract text from PDF pages and pdfplumber to assist with table extraction. Extracted content is organized into section nodes containing section identifiers, headings, page numbers, document order, content, table data, list data, hashes, parent-section information, and warnings.

This approach was selected because the supplied CT-200 manual contains selectable PDF text. A full OCR pipeline was therefore unnecessary for the initial implementation. Scanned PDFs would require OCR before reliable text and hierarchy extraction.

### 2.2 Irregularities and Limitations

The manual contains structural irregularities, including a subsection with a missing intermediate parent heading, sections appearing out of numerical order, and repeated headings such as Error Codes. The parser preserves distinct occurrences rather than assuming that every heading is globally unique.

PDF tables are more difficult to reconstruct than ordinary paragraphs because their logical structure is not always represented by text order. Coordinate-based table extraction can produce fragmented tables. The parser preserves extracted table information and emits warnings where interpretation may require review.

The parser does not silently claim that all document hierarchy, tables, or lists have been reconstructed perfectly. Parser warnings and automated tests are used to make known limitations visible.

### 2.3 Content Hashing

A SHA-256 hash is calculated for extracted section content. Hashes provide a deterministic way to identify content changes without comparing entire sections manually. A hash difference indicates a change in the normalized content, but does not explain whether the change is semantically important.

## 3. Data Storage and Separation

SQLite stores relational entities such as documents, document versions, parsed sections, selections, and links between selections and sections. This supports querying version metadata and preserving the content hashes recorded when a selection was created.

MongoDB stores generated QA cases, generation identifiers, source-section references, model information, timestamps, and source snapshots. This document-oriented representation accommodates variable LLM output metadata without requiring every generated field to be represented as a relational column.

The separation keeps document structure and selection relationships distinct from generated artifacts.

## 4. Versioning and Source Matching

A document record includes its filename, version number, source hash, section count, and ingestion timestamp. An identical source hash can be recognized as an already-ingested file. A changed PDF submitted under the same filename is intended to create a subsequent version in the same version history.

Selections record the content hashes of their selected sections at selection time. Generated QA records preserve source snapshots so that later retrieval can compare the original source content with the latest ingested content.

Source matching uses section identifiers and content metadata. This works when identifiers remain stable across versions, but it has limitations. Duplicate section identifiers, moved headings, renamed sections, and major document restructuring can make exact matching ambiguous. A missing source snapshot results in an unknown staleness state rather than a confident current result.

A stale result means that the source changed and the case should be reviewed. It does not necessarily mean that the case is invalid. Conversely, a current result does not prove that its expected answer is semantically correct.

## 5. LLM Prompting and Output Validation

The LLM receives selected source content and instructions to produce a requested number of QA test-case ideas in structured JSON. The intended output includes a question, expected answer, test type, source-section identifiers, and an evidence quote.

The implementation requests JSON output from the provider and validates the returned structure. Validation checks the presence and types of required fields, the requested case count, valid source-section references, and whether the evidence quote appears in the supplied source content after normalization.

If validation fails, the implementation retries with validation feedback, subject to the configured attempt limit. If the output remains invalid, generation should fail explicitly rather than being treated as a successful result.

Evidence-quote validation is a grounding aid, not a complete semantic correctness check. A model can quote a genuine source sentence and still produce an expected answer that adds unsupported behavior. Generated cases must therefore be reviewed before they are treated as authoritative test specifications.

## 6. Failure Modes and Handling

### 6.1 Invalid or Unreadable PDF

A PDF may contain no extractable text, malformed content, or an unexpected structure. The ingestion path should return a clear error rather than create an apparently valid document with no useful sections.

### 6.2 Fragmented Tables

PDF table boundaries can be misinterpreted, particularly when cells span multiple lines or tables have complex layouts. The parser preserves available table data and warnings, but human verification may be required.

### 6.3 Invalid LLM Output

The provider may return malformed JSON, omit fields, generate the wrong number of cases, or reference source sections outside the selection. Schema and source-reference validation reduce these risks. A bounded retry avoids accepting malformed output indefinitely.

### 6.4 Unsupported Expected Answers

A syntactically valid response may still contain assumptions that the manual does not support. Evidence matching alone cannot eliminate this failure. A stronger future implementation would distinguish direct source statements from inferred behavior and require explicit evidence for each expected answer.

### 6.5 Missing Snapshots

Older or manually created records may lack source snapshots. Their staleness cannot be established reliably, so they should be reported as unknown instead of being assumed current.

### 6.6 Database or Provider Unavailability

MongoDB may be unavailable, and the LLM provider may reject requests, time out, or change model availability. The API should expose clear failures and avoid reporting generation as successful when persistence or validation has failed.

## 7. Engineering Decision Log

### Decision 1: Silent Wrong-Result Risk

**Risk:** The most serious risk is a plausible-looking QA case whose expected answer asserts behavior not documented in the manual.

**Detection:** Validate the response structure, require valid source references and source evidence, and expose parser warnings. These checks detect structural and some grounding failures but do not prove semantic entailment. Human review remains necessary for safety-related requirements.

### Decision 2: Simplicity Over Correctness

**Trade-off:** The initial parser uses selectable PDF text extraction and coordinate-assisted table extraction rather than a full OCR and document-layout pipeline.

**First likely production failure:** A scanned manual or a complex multi-column PDF may produce incomplete text, incorrect reading order, or fragmented tables. This can silently affect the downstream QA cases unless parser warnings and content-quality checks are reviewed.

**Mitigation:** Add OCR fallback, stronger layout reconstruction, and representative tests using scanned and structurally complex PDFs.

### Decision 3: Unhandled Input

**Input:** A valid PDF whose text layer is empty or unusable.

**Expected behavior:** The system should reject ingestion with an actionable error, or explicitly report that OCR is required. It should not create a successful ingestion record that appears complete but contains no usable sections.

## 8. What I Would Do Differently

With additional time, I would implement a dedicated document-layout pipeline with OCR fallback, explicit parent-child hierarchy validation, and better table reconstruction. I would add deterministic integration tests for ingestion, repeated uploads, version changes, snapshot persistence, and stale-case retrieval.

I would also strengthen semantic grounding by checking whether each expected answer is entailed by the cited source, preserving exact source spans, and flagging inferred requirements for human review. Finally, I would add concurrency protection for version creation, pinned dependency versions, structured logging, and a reproducible deployment configuration.

## 9. Validation Status

The development environment has demonstrated document ingestion, section selection, LLM-based case generation, MongoDB persistence, and retrieval. The parser test suite has passed seven tests in the recorded run.

The Version 1-to-Version 2 workflow must be exercised separately to verify stale-case detection. Table reconstruction, per-case snapshot precision, and semantic correctness also require additional validation. These are documented limitations rather than capabilities assumed to be fully solved.
