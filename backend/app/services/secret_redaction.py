"""Centralized credential detection and category-preserving redaction."""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass


@dataclass(frozen=True)
class RedactionResult:
    text: str
    detections: dict[str, int]

    @property
    def redacted(self) -> bool:
        return bool(self.detections)


class SecretRedactionService:
    """Redact common enterprise secrets without treating normal IDs as secrets."""

    _patterns = (
        (
            "PRIVATE KEY",
            re.compile(
                r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |ENCRYPTED )?PRIVATE KEY-----"
                r".*?-----END (?:RSA |EC |OPENSSH |DSA |ENCRYPTED )?PRIVATE KEY-----",
                re.IGNORECASE | re.DOTALL,
            ),
        ),
        (
            "TOKEN",
            re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{8,}\b"),
        ),
        (
            "ACCESS KEY",
            re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
        ),
        (
            "TOKEN",
            re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{12,}"),
        ),
        (
            "PASSWORD",
            re.compile(
                r"(?i)\b(?:password|passwd|passphrase|pwd)\s*[:=]\s*"
                r"(?!\[REDACTED)[^\s,;]+"
            ),
        ),
        (
            "TOKEN",
            re.compile(
                r"(?i)\b(?:access[_ -]?token|refresh[_ -]?token|bearer[_ -]?token|token)"
                r"\s*[:=]\s*(?!\[REDACTED)[^\s,;]+"
            ),
        ),
        (
            "SECRET",
            re.compile(
                r"(?i)\b(?:api[_ -]?key|access[_ -]?key|private[_ -]?key|"
                r"client[_ -]?secret|secret)\s*[:=]\s*(?!\[REDACTED)[^\s,;]+"
            ),
        ),
        (
            "PASSWORD",
            re.compile(
                r"(?i)\b(?:postgres(?:ql)?|mysql|mariadb|mongodb(?:\+srv)?|redis)"
                r"://[^/\s:@]+:[^@\s/]+@[^/\s]+"
            ),
        ),
        (
            "PASSWORD",
            re.compile(r"(?i)\bhttps?://[^/\s:@]+:[^@\s/]+@[^/\s]+"),
        ),
        (
            "SECRET",
            re.compile(
                r"(?im)^(?:[A-Z][A-Z0-9_]*(?:PASSWORD|PASSWD|PWD|SECRET|TOKEN|"
                r"API_KEY|ACCESS_KEY|PRIVATE_KEY|CLIENT_SECRET)[A-Z0-9_]*)="
                r"(?!\[REDACTED).+$"
            ),
        ),
    )

    def __init__(self, enabled: bool = True) -> None:
        self.enabled = enabled

    def redact(self, value: str) -> RedactionResult:
        if not self.enabled or not value:
            return RedactionResult(value, {})
        text = value
        counts: Counter[str] = Counter()
        for category, pattern in self._patterns:
            def replacement(match: re.Match[str], label: str = category) -> str:
                counts[label] += 1
                return f"[REDACTED {label}]"

            text = pattern.sub(replacement, text)
        return RedactionResult(text, dict(counts))
