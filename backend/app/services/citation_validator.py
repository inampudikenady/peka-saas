"""Server-owned citation validation and final-answer normalization."""

from __future__ import annotations

import re

from app.schemas.ai_answer import AIAnswerCitation
from app.schemas.document_api import KnowledgeResult
from app.services.llm_provider import suppress_reasoning


_CITATION = re.compile(r"\[(C[1-9][0-9]*)\]")


class CitationValidationError(ValueError):
    pass


def normalize_answer(value: str) -> str:
    return re.sub(r"[ \t]+\n", "\n", suppress_reasoning(value)).strip()


def citation_ids(answer: str) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for citation_id in _CITATION.findall(answer):
        if citation_id not in seen:
            seen.add(citation_id)
            ordered.append(citation_id)
    return ordered


def validate_citations(
    answer: str, citation_map: dict[str, KnowledgeResult]
) -> list[AIAnswerCitation]:
    ids = citation_ids(answer)
    unknown = [citation_id for citation_id in ids if citation_id not in citation_map]
    if unknown:
        raise CitationValidationError("The generated answer used an unknown citation.")
    citations: list[AIAnswerCitation] = []
    for citation_id in ids:
        result = citation_map[citation_id]
        citation = result.citation
        citations.append(
            AIAnswerCitation(
                citation_id=citation_id,
                source_type=result.source_type,
                document_id=result.document_id,
                version_id=result.version_id,
                chunk_id=result.chunk_id,
                title=result.title,
                page_number=citation.page_number,
                section_title=citation.section_title,
                sheet_name=citation.sheet_name,
                row_start=citation.row_start,
                row_end=citation.row_end,
                score=result.score,
                excerpt=result.text,
                document_type=result.metadata.get("document_type"),
                source_system=result.metadata.get("source_system"),
                source_id=result.metadata.get("source_id"),
                ingested_at=result.metadata.get("ingested_at"),
                revision=result.metadata.get("revision"),
                sensitive_content_redacted=bool(
                    result.metadata.get("sensitive_content_redacted")
                ),
                redaction_categories=list(
                    result.metadata.get("redaction_categories") or []
                ),
            )
        )
    return citations
