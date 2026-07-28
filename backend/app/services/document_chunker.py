"""Deterministic, citation-preserving document chunking."""

from dataclasses import dataclass
from typing import Any

from app.services.document_parsers import ParsedDocument


@dataclass(frozen=True)
class Chunk:
    index: int
    text: str
    token_count: int
    page_number: int | None
    sheet_name: str | None
    row_start: int | None
    row_end: int | None
    section_title: str | None
    metadata: dict[str, Any]


def chunk_document(
    parsed: ParsedDocument,
    target_words: int = 600,
    overlap_words: int = 90,
) -> list[Chunk]:
    if parsed.parser_name in {"csv", "openpyxl"}:
        return _chunk_rows(parsed, target_words)
    chunks: list[Chunk] = []
    for section in parsed.sections:
        words = section.text.split()
        if not words:
            continue
        start = 0
        while start < len(words):
            end = min(start + target_words, len(words))
            window = words[start:end]
            chunks.append(
                Chunk(
                    index=len(chunks),
                    text=" ".join(window),
                    token_count=max(1, int(len(window) * 1.3)),
                    page_number=section.page_number,
                    sheet_name=section.sheet_name,
                    row_start=section.row_start,
                    row_end=section.row_end,
                    section_title=section.section_title,
                    metadata=section.metadata,
                )
            )
            if end == len(words):
                break
            start = end - min(overlap_words, end - start - 1)
    return chunks


def _chunk_rows(parsed: ParsedDocument, target_words: int) -> list[Chunk]:
    """Group spreadsheet rows deterministically while repeating each sheet header."""
    chunks: list[Chunk] = []
    groups: dict[str, list] = {}
    for section in parsed.sections:
        groups.setdefault(section.sheet_name or "", []).append(section)
    for sheet_name in sorted(groups):
        rows = groups[sheet_name]
        headers = rows[0].metadata.get("headers") if rows else None
        header = " | ".join(str(item) for item in headers) if headers else rows[0].text if rows else ""
        buffer: list = []
        word_count = 0
        for row in rows:
            row_words = len(row.text.split())
            if buffer and word_count + row_words > target_words:
                chunks.append(_row_chunk(len(chunks), sheet_name or None, header, buffer))
                buffer = []
                word_count = 0
            buffer.append(row)
            word_count += row_words
        if buffer:
            chunks.append(_row_chunk(len(chunks), sheet_name or None, header, buffer))
    return chunks


def _row_chunk(index: int, sheet_name: str | None, header: str, rows: list) -> Chunk:
    first = rows[0]
    last = rows[-1]
    body = "\n".join(row.text for row in rows)
    if body.splitlines()[0] != header:
        body = f"{header}\n{body}"
    return Chunk(
        index=index, text=body, token_count=max(1, int(len(body.split()) * 1.3)),
        page_number=None, sheet_name=sheet_name,
        row_start=first.row_start, row_end=last.row_end,
        section_title=first.section_title, metadata={"header": header},
    )
