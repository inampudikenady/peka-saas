"""Conservative structured-text detection and safe DokuWiki normalization."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class FormatDetection:
    detected_format: str
    confidence: float
    reason: str
    source_format: str


_DOKU_HEADING = re.compile(r"(?m)^\s*(={2,6})\s+\S.*?\s+\1\s*$")
_DOKU_CODE = re.compile(r"<(?:code|file)(?:[ |][^>]*)?>", re.IGNORECASE)
_DOKU_LINK = re.compile(r"\[\[[^\]\n]+(?:\|[^\]\n]+)?\]\]")
_DOKU_TABLE = re.compile(r"(?m)^\s*(?:\^[^^\n]+\^|\|[^|\n]+\|)\s*$")
_DOKU_LIST = re.compile(r"(?m)^\s{2,}[*-]\s+\S")
_MD_HEADING = re.compile(r"(?m)^\s{0,3}#{1,6}\s+\S")
_MD_FENCE = re.compile(r"(?m)^\s{0,3}(?:```|~~~)[\w+-]*\s*$")
_MD_LINK = re.compile(r"\[[^\]\n]+\]\([^) \n]+(?:\s+\"[^\"]*\")?\)")
_MD_TABLE = re.compile(r"(?m)^\s*\|?.+\|.+\|?\s*\n\s*\|?\s*:?-{3,}")
_MD_LIST = re.compile(r"(?m)^\s{0,3}(?:[-+*]|\d+[.)])\s+\S")
_MD_INLINE_CODE = re.compile(r"`[^`\n]+`")


def detect_text_format(
    filename: str,
    mime_type: str | None,
    content: str,
) -> FormatDetection:
    """Classify text conservatively; isolated punctuation never wins detection."""
    extension = Path(filename).suffix.lower()
    declared = (mime_type or "").split(";", 1)[0].strip().lower()

    doku_signals = {
        "heading": len(_DOKU_HEADING.findall(content)),
        "code_or_file": len(_DOKU_CODE.findall(content)),
        "link": len(_DOKU_LINK.findall(content)),
        "table": len(_DOKU_TABLE.findall(content)),
        "list": len(_DOKU_LIST.findall(content)),
    }
    markdown_signals = {
        "heading": len(_MD_HEADING.findall(content)),
        "fence": len(_MD_FENCE.findall(content)) // 2,
        "link": len(_MD_LINK.findall(content)),
        "table": len(_MD_TABLE.findall(content)),
        "list": len(_MD_LIST.findall(content)),
        "inline_code": len(_MD_INLINE_CODE.findall(content)),
    }
    doku_score = (
        4 * doku_signals["heading"]
        + 4 * doku_signals["code_or_file"]
        + 2 * doku_signals["link"]
        + 3 * doku_signals["table"]
        + doku_signals["list"]
    )
    markdown_score = (
        3 * markdown_signals["heading"]
        + 4 * markdown_signals["fence"]
        + 2 * markdown_signals["link"]
        + 3 * markdown_signals["table"]
        + markdown_signals["list"]
        + markdown_signals["inline_code"]
    )
    strong_doku = (
        doku_signals["heading"] > 0
        or doku_signals["code_or_file"] > 0
        or doku_signals["table"] > 0
        or sum(value > 0 for value in doku_signals.values()) >= 2
    )
    strong_markdown = (
        markdown_signals["fence"] > 0
        or markdown_signals["table"] > 0
        or markdown_signals["heading"] > 0
        or sum(value > 0 for value in markdown_signals.values()) >= 3
    )

    if strong_doku and doku_score >= markdown_score:
        present = ", ".join(key for key, value in doku_signals.items() if value)
        confidence = min(0.99, 0.72 + min(doku_score, 18) / 75)
        return FormatDetection(
            "dokuwiki",
            round(confidence, 2),
            f"Strong DokuWiki signatures: {present}.",
            "dokuwiki_export" if extension == ".txt" else "dokuwiki",
        )
    if strong_markdown and markdown_score > doku_score:
        present = ", ".join(key for key, value in markdown_signals.items() if value)
        confidence = min(0.98, 0.68 + min(markdown_score, 18) / 75)
        return FormatDetection(
            "markdown",
            round(confidence, 2),
            f"Strong Markdown signatures: {present}.",
            "markdown_text_export" if extension == ".txt" else "markdown",
        )
    if extension in {".md", ".markdown"} or declared in {
        "text/markdown",
        "text/x-markdown",
    }:
        return FormatDetection(
            "markdown",
            0.62,
            "Declared Markdown extension or MIME type without conflicting content.",
            "markdown",
        )
    return FormatDetection(
        "plain_text",
        0.9 if extension == ".txt" or declared == "text/plain" else 0.65,
        "No sufficiently strong structured-text signatures; using plain text.",
        "plain_text",
    )


_DOKU_HEADING_LINE = re.compile(r"^\s*(={2,6})\s*(.*?)\s*\1\s*$")
_DOKU_OPEN = re.compile(
    r"<(?P<tag>code|file)(?:(?:\s+|\|)(?P<language>[^>\s]+))?[^>]*>",
    re.IGNORECASE,
)
_DOKU_CLOSE = re.compile(r"</(?:code|file)>", re.IGNORECASE)
_DOKU_LINK_INLINE = re.compile(r"\[\[([^|\]]+)(?:\|([^\]]+))?\]\]")
_DOKU_MONO = re.compile(r"''([^'\n]+)''")
_HTML_TAG = re.compile(r"<(?!/?(?:code|file)\b)[^>\n]+>", re.IGNORECASE)


def _inline(value: str) -> str:
    value = _DOKU_LINK_INLINE.sub(
        lambda match: f"[{match.group(2) or match.group(1)}]({match.group(1)})",
        value,
    )
    value = _DOKU_MONO.sub(lambda match: f"`{match.group(1)}`", value)
    return _HTML_TAG.sub(
        lambda match: match.group(0).replace("<", "&lt;").replace(">", "&gt;"),
        value,
    )


def _line(value: str) -> str:
    list_item = re.match(r"^(\s{2,})([*-])\s+(.*)$", value)
    if not list_item:
        return _inline(value)
    depth = max(0, len(list_item.group(1)) // 2 - 1)
    marker = "-" if list_item.group(2) == "*" else "1."
    return f"{'  ' * depth}{marker} {_inline(list_item.group(3))}"


def _table_block(lines: list[str]) -> list[str]:
    rows: list[list[str]] = []
    header = lines[0].lstrip().startswith("^")
    for line in lines:
        delimiter = "^" if line.lstrip().startswith("^") else "|"
        rows.append(
            [
                _inline(cell.strip())
                for cell in line.strip().strip(delimiter).split(delimiter)
            ]
        )
    width = max((len(row) for row in rows), default=0)
    rows = [row + [""] * (width - len(row)) for row in rows]
    rendered = ["| " + " | ".join(row) + " |" for row in rows]
    if header and rendered:
        rendered.insert(1, "| " + " | ".join("---" for _ in range(width)) + " |")
    return rendered


def normalize_dokuwiki(content: str) -> str:
    """Normalize supported DokuWiki structures without executing embedded markup."""
    source = content.replace("\r\n", "\n").replace("\r", "\n")
    output: list[str] = []
    lines = source.splitlines()
    index = 0
    in_code = False

    while index < len(lines):
        line = lines[index]
        if in_code:
            close = _DOKU_CLOSE.search(line)
            if close:
                if line[: close.start()]:
                    output.append(line[: close.start()])
                output.append("```")
                remainder = line[close.end() :]
                if remainder:
                    output.append(_line(remainder))
                in_code = False
            else:
                output.append(line)
            index += 1
            continue

        heading = _DOKU_HEADING_LINE.match(line)
        if heading:
            level = min(6, max(1, 7 - len(heading.group(1))))
            output.append(f"{'#' * level} {_inline(heading.group(2).strip())}")
            index += 1
            continue

        if line.lstrip().startswith(("^", "|")) and (
            line.rstrip().endswith("^") or line.rstrip().endswith("|")
        ):
            table_lines: list[str] = []
            while index < len(lines):
                candidate = lines[index]
                if not (
                    candidate.lstrip().startswith(("^", "|"))
                    and candidate.rstrip().endswith(("^", "|"))
                ):
                    break
                table_lines.append(candidate)
                index += 1
            output.extend(_table_block(table_lines))
            continue

        open_tag = _DOKU_OPEN.search(line)
        if open_tag:
            prefix = line[: open_tag.start()]
            if prefix:
                output.append(_line(prefix))
            language = (open_tag.group("language") or "text").strip().lower()
            remainder = line[open_tag.end() :]
            close = _DOKU_CLOSE.search(remainder)
            output.append(f"```{language}")
            if close:
                output.append(remainder[: close.start()])
                output.append("```")
                suffix = remainder[close.end() :]
                if suffix:
                    output.append(_line(suffix))
            else:
                if remainder:
                    output.append(remainder)
                in_code = True
            index += 1
            continue

        output.append(_line(line))
        index += 1

    if in_code:
        output.append("```")
    return "\n".join(output).strip() + "\n"
