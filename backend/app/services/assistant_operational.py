"""Deterministic operational intent routing and factual tool-result formatting."""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal
from urllib.parse import urlparse
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy.orm import Session

from app.models.tenant import Tenant
from app.services.operational_tool_service import (
    OperationalToolService,
    OperationalToolUnavailable,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AssistantIntent:
    destination: Literal["document", "operational", "clarification", "contextual"]
    tool_name: str | None = None
    arguments: dict[str, Any] | None = None
    clarification: str | None = None
    intent_family: str | None = None
    evidence_context: dict[str, Any] | None = None


@dataclass(frozen=True)
class OperationalAnswer:
    text: str
    tool_name: str
    tool_request_id: UUID | None
    result: dict[str, Any] | None


_IDENTIFIER = r"([A-Za-z0-9][A-Za-z0-9._-]{0,254})"


@dataclass(frozen=True)
class OperationalIntentFamily:
    """Central definition for deterministic operational language families."""

    name: str
    patterns: tuple[str, ...]
    tool_name: str
    mode: str | None = None
    category: str | None = None
    clarification: str = "Which server should I check?"


OPERATIONAL_INTENT_FAMILIES: tuple[OperationalIntentFamily, ...] = (
    OperationalIntentFamily(
        "performance",
        (
            r"\b(?:performance|slow|sluggish|lagging|overloaded)\b",
            r"\b(?:cpu|memory)\s+(?:seems|looks|is)\s+high\b",
            r"\bhigh\s+(?:cpu|memory)\b",
            r"\bresponse\s+is\s+slow\b",
            r"\bserver\s+is\s+lagging\b",
            r"\binvestigate\s+performance\b",
        ),
        "get_asset_status",
        mode="performance",
        clarification="Which server should I investigate for performance?",
    ),
    OperationalIntentFamily(
        "timeline",
        (
            r"\bwhat happened\b",
            r"\brecent\s+(?:activity|events?)\b",
            r"\b(?:show\s+(?:me\s+)?(?:the\s+)?)?timeline\b",
            r"\bwhat changed\b",
            r"\bhas anything changed\b",
            r"\banything happen(?:ed)?\b",
            r"\b(?:show\s+)?(?:operational\s+)?activity\b",
            r"\brecent operational events?\b",
        ),
        "get_asset_status",
        mode="timeline",
        clarification="Which server should I build the operational timeline for?",
    ),
    OperationalIntentFamily(
        "warnings",
        (
            r"\bwarnings?\b",
            r"\bwarning (?:events?|logs?)\b",
            r"\banything concerning\b",
        ),
        "get_asset_log_evidence",
        category="warnings",
        clarification="Which server should I check for warning evidence?",
    ),
    OperationalIntentFamily(
        "errors",
        (
            r"\b(?:errors?|exceptions?|crashes?|problems?)\b",
            r"\b(?:did anything|what)\s+(?:fail|failed)\b",
            r"\banything (?:fail|failing)\b",
            r"\brecent failures?\b",
            r"\bfailures?\s+(?:today|recently)\b",
            r"\bwhat broke\b",
            r"\b(?:show\s+(?:me\s+)?)?(?:the\s+)?logs?\b",
            r"\bauth(?:entication)? failures?\b",
            r"\b(?:kernel|filesystem|out of memory|oom)\b",
        ),
        "get_asset_log_evidence",
        clarification="Which server should I check for log evidence?",
    ),
    OperationalIntentFamily(
        "health",
        (
            r"\b(?:health|healthy|unhealthy|system status)\b",
            r"\bhow is\b",
            r"\b(?:check|analyse|analyze|investigate)\b",
            r"\b(?:is|anything|something)\s+(?:there\s+)?wrong\b",
            r"\banything unusual\b",
            r"\blook\s+ok\b",
            r"\bhow is .+ doing\b",
            r"\beverything\s+ok\b",
            r"\b(?:broken|acting up|misbehaving|degraded|unstable)\b",
            r"\b(?:responsive|stuck|hung|recovering)\b",
            r"\b(?:healthy again|normal now|back online|offline|online|down)\b",
            r"\bstatus\s+(?:of|for|on)\b",
        ),
        "get_asset_status",
        mode="health",
    ),
)

_REFERENCE_PATTERN = re.compile(
    r"\b(?:this|that|the same|current)\s+(?:server|asset|host|machine)\b"
    r"|\b(?:it|there)\b",
    re.IGNORECASE,
)
_CURRENT_FOLLOWUP_PATTERN = (
    r"(?:is (?:this|that|it) still happening|"
    r"is (?:this|that|it) happening now|"
    r"is (?:this|that|it) resolved|"
    r"is (?:it|the server) (?:healthy again|normal now|recovering))\??"
)
_NON_IDENTIFIERS = {
    "about",
    "anything",
    "asset",
    "check",
    "current",
    "doing",
    "for",
    "from",
    "health",
    "host",
    "investigate",
    "it",
    "machine",
    "on",
    "performance",
    "server",
    "status",
    "system",
    "that",
    "there",
    "the",
    "this",
    "with",
}


def _candidate_identifier(value: str | None) -> str | None:
    if not value:
        return None
    candidate = value.strip().rstrip("?.!,").casefold()
    if candidate in _NON_IDENTIFIERS:
        return None
    return value.strip().rstrip("?.!,")


def _identifier(query: str) -> str | None:
    for pattern in (
        rf"\b(?:server|host|machine|asset)\s+(?:named\s+)?{_IDENTIFIER}\b",
        rf"\bthe\s+{_IDENTIFIER}\s+(?:server|host|machine|asset)\b",
        rf"\b(?:of|for|about|on|from)\s+{_IDENTIFIER}\b",
        rf"\brelated\s+to\s+{_IDENTIFIER}\b",
        rf"\bmade\s+to\s+{_IDENTIFIER}\b",
        rf"\b(?:with|check|analyse|analyze|investigate)\s+{_IDENTIFIER}\b",
        rf"\bhow\s+is\s+{_IDENTIFIER}\b",
        rf"\bwhy\s+is\s+{_IDENTIFIER}\s+(?:slow|overloaded|unhealthy)\b",
        rf"\b{_IDENTIFIER}\s+(?:performance|(?:feels?\s+)?(?:slow|sluggish|lagging)|"
        rf"is\s+(?:slow|overloaded|sluggish|lagging|broken|unhealthy|offline|online|down)|looks?\s+ok|"
        rf"is\s+doing)\b",
        rf"\b(?:is|does)\s+{_IDENTIFIER}\s+(?:healthy|unhealthy|look\s+ok)\b",
        rf"\bis\s+{_IDENTIFIER}\s+(?:currently\s+)?reachable\b",
        rf"\bdetails?\s+(?:for\s+)?{_IDENTIFIER}\b",
    ):
        match = re.search(pattern, query, re.IGNORECASE)
        if match:
            candidate = _candidate_identifier(match.group(1))
            if candidate:
                return candidate
    ip = re.search(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", query)
    if ip:
        return ip.group(0)
    return None


def _active_identifier(context: dict[str, Any] | None) -> str | None:
    if not isinstance(context, dict):
        return None
    active = _candidate_identifier(str(context.get("active_identifier") or ""))
    if active:
        return active
    arguments = context.get("arguments")
    if isinstance(arguments, dict):
        return _candidate_identifier(str(arguments.get("identifier") or ""))
    return None


def _resolve_identifier(
    query: str,
    context: dict[str, Any] | None,
    *,
    allow_implicit_context: bool,
) -> str | None:
    explicit = _identifier(query)
    if explicit:
        return explicit
    if _REFERENCE_PATTERN.search(query) or allow_implicit_context:
        return _active_identifier(context)
    return None


def _matches_family(query: str, family: OperationalIntentFamily) -> bool:
    return any(re.search(pattern, query, re.IGNORECASE) for pattern in family.patterns)


def _lookback_hours(query: str) -> int:
    if re.search(r"\b(?:30 days?|month)\b", query):
        return 720
    if re.search(r"\b(?:7 days?|week)\b", query):
        return 168
    if re.search(r"\b(?:3 days?|72 hours?)\b", query):
        return 72
    if re.search(r"\b6 hours?\b", query):
        return 6
    if re.search(r"\b(?:last|past)\s+hour\b", query):
        return 1
    return 24


def _log_category(query: str, default: str | None = None) -> str | None:
    for pattern, value in (
        (r"\b(?:out of memory|oom)\b", "oom"),
        (r"\bcrash", "crashes"),
        (r"\bauth(?:entication)? failures?\b", "auth_failures"),
        (r"\bexceptions?\b", "exceptions"),
        (r"\brestarts?\b", "restarts"),
        (r"\bwarnings?\b|\banything concerning\b", "warnings"),
        (r"\bkernel\b", "kernel"),
        (r"\b(?:filesystem|disk (?:error|failure))\b", "filesystem"),
        (r"\berrors?\b|\bfail(?:ed|ing|ures?)?\b|\bbroke\b|\bproblems?\b", "errors"),
    ):
        if re.search(pattern, query):
            return value
    return default


def classify_assistant_intent(
    query: str,
    operational_context: dict[str, Any] | None = None,
) -> AssistantIntent:
    clean = " ".join(query.strip().split())
    lower = clean.casefold()
    pending = (
        operational_context
        if isinstance(operational_context, dict)
        and operational_context.get("pending") is True
        else None
    )
    pending_identifier = _identifier(clean) or _candidate_identifier(clean)
    if (
        pending
        and pending_identifier
        and (
            re.fullmatch(_IDENTIFIER, clean.rstrip("?.!"))
            or re.match(r"^(?:server|host|machine|asset)\s+", lower)
        )
    ):
        followup_identifier = pending_identifier
        if followup_identifier.casefold() not in {
            "yes",
            "no",
            "thanks",
            "cancel",
            "stop",
        }:
            arguments = dict(pending.get("arguments") or {})
            arguments["identifier"] = followup_identifier
            return AssistantIntent(
                "operational",
                str(pending.get("tool_name")),
                arguments,
                intent_family=str(pending.get("intent_family") or "operational"),
            )
    evidence_snapshot = (
        operational_context.get("evidence_snapshot")
        if isinstance(operational_context, dict)
        and isinstance(operational_context.get("evidence_snapshot"), dict)
        else None
    )
    if evidence_snapshot and re.fullmatch(
        r"(?:why|explain(?: why)?|what caused (?:it|that)|"
        r"why is (?:it|this|that|the server) unhealthy)\??",
        lower,
    ):
        return AssistantIntent(
            "contextual",
            "reuse_operational_evidence",
            {"action": "explain"},
            intent_family="explanation",
            evidence_context=evidence_snapshot,
        )
    if evidence_snapshot and re.fullmatch(_CURRENT_FOLLOWUP_PATTERN, lower):
        return AssistantIntent(
            "contextual",
            "reuse_operational_evidence",
            {"action": "current"},
            intent_family="explanation",
            evidence_context=evidence_snapshot,
        )
    active_identifier = _active_identifier(operational_context)
    if re.search(
        r"\b(?:detailed health evidence|full health evidence|detailed metrics|"
        r"complete metrics|full operational evidence)\b",
        lower,
    ):
        identifier = _resolve_identifier(
            clean, operational_context, allow_implicit_context=True
        )
        if not identifier:
            return AssistantIntent(
                "clarification",
                "get_asset_status",
                {"mode": "health", "detail_level": "detailed"},
                clarification="Which server should I show detailed health evidence for?",
                intent_family="health",
            )
        return AssistantIntent(
            "operational",
            "get_asset_status",
            {"identifier": identifier, "mode": "health", "detail_level": "detailed"},
            intent_family="health",
        )
    if re.fullmatch(_CURRENT_FOLLOWUP_PATTERN, lower):
        if active_identifier:
            return AssistantIntent(
                "operational",
                "get_asset_status",
                {"identifier": active_identifier, "mode": "health"},
                intent_family="health",
            )
        return AssistantIntent(
            "clarification",
            "get_asset_status",
            {"mode": "health"},
            clarification=(
                "Which server should I check? No previous operational evidence "
                "is available for this conversation."
            ),
            intent_family="health",
        )
    if (
        active_identifier
        and operational_context
        and re.fullmatch(r"(?:why|explain(?: why)?)\??", lower)
    ):
        return AssistantIntent(
            "contextual",
            "reuse_operational_evidence",
            {"action": "explain"},
            intent_family="explanation",
            evidence_context={"identifier": active_identifier},
        )
    servicenow_incident = re.search(r"\b(INC\d+)\b", clean, re.IGNORECASE)
    if servicenow_incident:
        return AssistantIntent(
            "operational",
            "servicenow_get_incident_updates"
            if re.search(r"\b(?:latest update|updates?|work notes?|comments?)\b", lower)
            else "servicenow_get_incident",
            {"number": servicenow_incident.group(1).upper()},
            intent_family="servicenow",
        )
    if re.search(
        r"\b(?:how many|list|show)\b.*\b(?:open|active)\b.*\bincidents?\b", lower
    ):
        identifier = _resolve_identifier(
            clean, operational_context, allow_implicit_context=False
        )
        return AssistantIntent(
            "operational",
            "servicenow_list_open_incidents",
            {"query": None, "identifier": identifier, "limit": 50},
            intent_family="servicenow",
        )
    if re.search(r"\b(?:show|list|what|which)\b.*\bproblems?\b", lower):
        identifier = _resolve_identifier(
            clean, operational_context, allow_implicit_context=False
        )
        return AssistantIntent(
            "operational",
            "servicenow_search_problems",
            {
                "query": None if identifier else clean,
                "identifier": identifier,
                "limit": 25,
            },
            intent_family="servicenow",
        )
    if re.search(r"\b(?:show|list|what|which)\b.*\bchanges?\b", lower):
        identifier = _resolve_identifier(
            clean, operational_context, allow_implicit_context=False
        )
        return AssistantIntent(
            "operational",
            "servicenow_search_changes",
            {
                "query": None if identifier else clean,
                "identifier": identifier,
                "limit": 25,
            },
            intent_family="servicenow",
        )
    if "servicenow" in lower:
        if re.search(
            r"\b(?:status|configured|connected|enabled)\b", lower
        ) and not re.search(r"\b(?:incident|problem|change|ci|relationship)\b", lower):
            return AssistantIntent(
                "operational", "servicenow_get_status", {}, intent_family="servicenow"
            )
        if re.search(
            r"\b(?:how many|list|show)\b.*\b(?:open|active)\b.*\bincidents?\b", lower
        ):
            identifier = _resolve_identifier(
                clean, operational_context, allow_implicit_context=False
            )
            return AssistantIntent(
                "operational",
                "servicenow_list_open_incidents",
                {"query": None, "identifier": identifier, "limit": 50},
                intent_family="servicenow",
            )
        if re.search(r"\bproblems?\b", lower):
            identifier = _resolve_identifier(
                clean, operational_context, allow_implicit_context=False
            )
            return AssistantIntent(
                "operational",
                "servicenow_search_problems",
                {
                    "query": None if identifier else clean,
                    "identifier": identifier,
                    "limit": 25,
                },
                intent_family="servicenow",
            )
        if re.search(r"\bchanges?\b", lower):
            identifier = _resolve_identifier(
                clean, operational_context, allow_implicit_context=False
            )
            return AssistantIntent(
                "operational",
                "servicenow_search_changes",
                {
                    "query": None if identifier else clean,
                    "identifier": identifier,
                    "limit": 25,
                },
                intent_family="servicenow",
            )
        if re.search(r"\bincidents?\b", lower):
            identifier = _resolve_identifier(
                clean, operational_context, allow_implicit_context=False
            )
            if identifier:
                return AssistantIntent(
                    "operational",
                    "servicenow_get_ci_tickets",
                    {"identifier": identifier, "max_depth": 3},
                    intent_family="servicenow",
                )
            return AssistantIntent(
                "operational",
                "servicenow_search_incidents",
                {"query": clean, "limit": 25},
                intent_family="servicenow",
            )
    if "zammad" in lower and re.search(r"\b(?:tickets?|incidents?)\b", lower):
        identifier = _resolve_identifier(
            clean, operational_context, allow_implicit_context=False
        )
        return AssistantIntent(
            "operational",
            "ticketing_search_records",
            {
                "mode": "asset" if identifier else "search",
                "state": "open" if re.search(r"\b(?:open|active)\b", lower) else "all",
                "query": None if identifier else "",
                "identifier": identifier,
                "providers": ["zammad"],
                "limit": 50,
            },
            intent_family="tickets",
        )
    if re.search(r"\ball\s+(?:ticket\s+)?sources?\b", lower):
        identifier = _resolve_identifier(
            clean, operational_context, allow_implicit_context=True
        )
        if not identifier:
            return AssistantIntent(
                "clarification",
                "get_all_ticket_sources",
                {},
                clarification="Which server or service should I inspect across ticket sources?",
                intent_family="tickets",
            )
        return AssistantIntent(
            "operational",
            "get_all_ticket_sources",
            {"identifier": identifier},
            intent_family="tickets",
        )
    if re.search(
        r"\b(?:what runs on|what depends on|relationships? for|services?.*affected.*(?:down|fails?))\b",
        lower,
    ):
        identifier = _resolve_identifier(
            clean, operational_context, allow_implicit_context=True
        )
        if not identifier:
            return AssistantIntent(
                "clarification",
                "servicenow_get_ci_relationships",
                {"max_depth": 3},
                clarification="Which configuration item should I inspect?",
                intent_family="servicenow",
            )
        return AssistantIntent(
            "operational",
            "servicenow_get_ci_relationships",
            {"identifier": identifier, "max_depth": 3},
            intent_family="servicenow",
        )
    ticket_number_match = re.search(
        r"\b(?:ticket\s*#?\s*)?(\d{4,})\b",
        clean,
        re.IGNORECASE,
    )
    ticket_language = bool(
        re.search(
            r"\b(?:tickets?|incidents?|latest update|who owns|reported this issue|"
            r"known ticket|access requests?|permission requests?|authentication-related|"
            r"authentication incidents?|login incidents?)\b",
            lower,
        )
    )
    if ticket_number_match and (
        ticket_language
        or re.search(r"\b(?:status|show|state|owner|owns|update)\b", lower)
    ):
        view = (
            "latest_update"
            if "latest update" in lower
            else "owner"
            if re.search(r"\bwho owns?\b", lower)
            else "status"
            if re.search(r"\b(?:status|state)\b", lower)
            else "full"
        )
        return AssistantIntent(
            "operational",
            "get_ticket",
            {"ticket_number": ticket_number_match.group(1), "view": view},
            intent_family="tickets",
        )
    if re.search(
        r"\b(?:tickets? during this error|did anyone report this issue|"
        r"tickets? related to (?:the|this)|ticket opened when|"
        r"current alert related to a known ticket)\b",
        lower,
    ):
        if not evidence_snapshot:
            return AssistantIntent(
                "clarification",
                "correlate_tickets_with_evidence",
                {},
                clarification=(
                    "I need a previous health, performance, or error investigation "
                    "before I can correlate tickets with operational evidence."
                ),
                intent_family="ticket_correlation",
            )
        timeline = evidence_snapshot.get("timeline") or []
        timestamps = sorted(
            str(item.get("observed_at"))
            for item in timeline
            if isinstance(item, dict) and item.get("observed_at")
        )
        assessment = evidence_snapshot.get("assessment") or {}
        relevant = assessment.get("relevant_log_evidence") or []
        return AssistantIntent(
            "operational",
            "correlate_tickets_with_evidence",
            {
                "identifier": evidence_snapshot.get("identifier") or active_identifier,
                "evidence_start": timestamps[0] if timestamps else None,
                "evidence_end": timestamps[-1] if timestamps else None,
                "error_strings": [
                    str(item.get("summary"))[:500]
                    for item in relevant
                    if isinstance(item, dict)
                    and item.get("summary")
                    and str(item.get("severity") or "").casefold()
                    in {"error", "critical"}
                ][:10],
                "warning_strings": [
                    str(item.get("summary"))[:500]
                    for item in relevant
                    if isinstance(item, dict)
                    and item.get("summary")
                    and str(item.get("severity") or "").casefold() == "warning"
                ][:10],
                "service_names": [],
                "symptoms": clean[:1000],
            },
            intent_family="ticket_correlation",
        )
    if re.search(r"\bhow many\b.*\b(?:tickets?|incidents?)\b", lower) or re.search(
        r"\bare there any active incidents?\b", lower
    ):
        updated_from = (
            datetime.now(UTC)
            .replace(hour=0, minute=0, second=0, microsecond=0)
            .isoformat()
            if "today" in lower
            else None
        )
        return AssistantIntent(
            "operational",
            "ticketing_search_records",
            {
                "mode": "count",
                "state": (
                    "closed"
                    if "closed" in lower
                    else "open"
                    if re.search(r"\b(?:open|active)\b", lower)
                    else "all"
                ),
                "query": None,
                "identifier": None,
                "providers": [],
                "limit": 50,
                "updated_from": updated_from,
            },
            intent_family="tickets",
        )
    asset_ticket_language = bool(
        re.search(
            r"\b(?:tickets?|incidents?)\s+(?:are\s+)?(?:for|associated with)\b|"
            r"\b(?:tickets?|incidents?)\s+related\s+to\b|"
            r"\b(?:have|has)\s+(?:any\s+)?incidents?\b|"
            r"\bwhat happened recently on\b",
            lower,
        )
    )
    if asset_ticket_language:
        identifier = _resolve_identifier(
            clean, operational_context, allow_implicit_context=True
        )
        if not identifier:
            return AssistantIntent(
                "clarification",
                "ticketing_search_records",
                {"recently_closed_days": 30},
                clarification="Which server should I check for related tickets?",
                intent_family="tickets",
            )
        return AssistantIntent(
            "operational",
            "ticketing_search_records",
            {
                "mode": "asset",
                "state": "open" if re.search(r"\b(?:open|active)\b", lower) else "all",
                "query": None,
                "identifier": identifier,
                "providers": [],
                "limit": 50,
            },
            intent_family="tickets",
        )
    if ticket_language or re.search(
        r"\b(?:memory related|high memory usage|asking for access|login or permission|"
        r"disk space|application failures?)\b",
        lower,
    ):
        requested_limit = 5
        number_match = re.search(
            r"\b(\d{1,2})\s+(?:most\s+recent(?:ly updated)?|latest|open|tickets?)\b",
            lower,
        )
        word_limits = {
            "one": 1,
            "two": 2,
            "three": 3,
            "four": 4,
            "five": 5,
            "six": 6,
            "seven": 7,
            "eight": 8,
            "nine": 9,
            "ten": 10,
        }
        for word, value in word_limits.items():
            if re.search(
                rf"\b{word}\s+(?:most\s+recent(?:ly updated)?|latest|open|tickets?)\b",
                lower,
            ):
                requested_limit = value
                break
        if number_match:
            requested_limit = min(50, max(1, int(number_match.group(1))))
        recency_listing = bool(
            re.search(
                r"\b(?:most recently updated|most recent|latest)\s+(?:open\s+)?tickets?\b",
                lower,
            )
        )
        generic_listing = bool(
            re.search(
                r"\b(?:what are|show|list)\s+(?:my\s+)?(?:open|active|current)?\s*tickets?\b",
                lower,
            )
        )
        return AssistantIntent(
            "operational",
            "ticketing_search_records",
            {
                "mode": "search",
                "query": "" if recency_listing or generic_listing else clean,
                "state": (
                    "open"
                    if re.search(r"\b(?:open|active)\b", lower)
                    else "closed"
                    if "closed" in lower
                    else "all"
                ),
                "identifier": None,
                "providers": [],
                "limit": requested_limit,
            },
            intent_family="tickets",
        )
    if evidence_snapshot and re.fullmatch(r"what happened\??", lower):
        return AssistantIntent(
            "contextual",
            "reuse_operational_evidence",
            {"action": "timeline"},
            intent_family="timeline",
            evidence_context=evidence_snapshot,
        )
    if re.search(
        r"\b(?:what are those(?: \d+)? servers?|which ones|what are those servers?)\b",
        lower,
    ):
        previous_arguments = (
            operational_context.get("arguments")
            if isinstance(operational_context, dict)
            else None
        )
        if isinstance(previous_arguments, dict):
            return AssistantIntent(
                "operational",
                "search_assets",
                {
                    "os_family": previous_arguments.get("os_family"),
                    "environment": previous_arguments.get("environment"),
                    "missing_prometheus": previous_arguments.get("missing_prometheus"),
                    "prometheus_health": previous_arguments.get("prometheus_health"),
                    "limit": 50,
                },
                intent_family="inventory",
            )
        return AssistantIntent(
            "clarification",
            clarification="Which previous server count should I expand?",
        )
    if re.search(r"\b(?:cpu|memory|disk|resource)\s+(?:usage|utili[sz]ation)\b", lower):
        identifier = _resolve_identifier(
            clean, operational_context, allow_implicit_context=True
        )
        if not identifier:
            return AssistantIntent(
                "clarification",
                "get_asset_utilization",
                {},
                clarification=(
                    "Which server should I check for resource utilization? "
                    "Please provide its hostname or FQDN."
                ),
                intent_family="performance",
            )
        return AssistantIntent(
            "operational",
            "get_asset_utilization",
            {"identifier": identifier},
            intent_family="performance",
        )
    if re.search(r"\b(?:how many|number of)\b", lower):
        family = (
            "linux" if "linux" in lower else "windows" if "windows" in lower else None
        )
        return AssistantIntent(
            "operational",
            "count_assets",
            {"os_family": family},
            intent_family="inventory",
        )
    if re.search(r"\btotal\s+(?:server|asset|inventory)\s+count\b", lower):
        return AssistantIntent("operational", "get_inventory_summary", {})
    if re.search(
        r"\b(?:without|do not have|missing|no)\s+prometheus\s+metrics?\b", lower
    ):
        return AssistantIntent(
            "operational",
            "search_assets",
            {"missing_prometheus": True, "limit": 50},
        )
    if re.search(
        r"\b(?:monitored\s+servers?|servers?.*\bmonitored)\b",
        lower,
    ):
        return AssistantIntent(
            "operational",
            "search_assets",
            {
                "missing_prometheus": False,
                "prometheus_health": ("unhealthy" if "unhealthy" in lower else None),
                "limit": 50,
            },
        )
    if re.search(r"\b(?:status|reachable|observed)\b", lower):
        identifier = _resolve_identifier(
            clean, operational_context, allow_implicit_context=True
        )
        if identifier:
            return AssistantIntent(
                "operational",
                "get_asset_status",
                {"identifier": identifier, "mode": "health"},
                intent_family="health",
            )
    if re.search(r"\b(?:ip(?: address)?|operating system|details?)\b", lower):
        identifier = _resolve_identifier(
            clean, operational_context, allow_implicit_context=True
        )
        if identifier:
            return AssistantIntent(
                "operational",
                "get_asset_details",
                {"identifier": identifier},
                intent_family="inventory",
            )
    if re.search(
        r"\b(?:list|show|which|what|display)\b.*\b(?:servers?|inventory)\b",
        lower,
    ):
        family = (
            "linux" if "linux" in lower else "windows" if "windows" in lower else None
        )
        environment_match = re.search(
            r"\b(?:in|environment)\s+(?:the\s+)?([A-Za-z0-9._-]+)\s+environment\b",
            clean,
            re.IGNORECASE,
        )
        return AssistantIntent(
            "operational",
            "search_assets",
            {
                "os_family": family,
                "environment": (
                    environment_match.group(1) if environment_match else None
                ),
                "missing_prometheus": None,
                "prometheus_health": None,
                "limit": 50,
            },
            intent_family="inventory",
        )
    if re.fullmatch(
        r"(?:linux|windows)\s+(?:servers?|hosts?|machines?|assets?)\.?", lower
    ):
        family = "linux" if "linux" in lower else "windows"
        return AssistantIntent(
            "operational",
            "search_assets",
            {
                "os_family": family,
                "environment": None,
                "missing_prometheus": None,
                "prometheus_health": None,
                "limit": 50,
            },
            intent_family="inventory",
        )
    if re.fullmatch(r"(?:inventory|assets?|machines?|hosts?)\.?", lower):
        return AssistantIntent(
            "operational",
            "search_assets",
            {
                "os_family": None,
                "environment": None,
                "missing_prometheus": None,
                "prometheus_health": None,
                "limit": 50,
            },
            intent_family="inventory",
        )
    for intent_definition in OPERATIONAL_INTENT_FAMILIES:
        if not _matches_family(lower, intent_definition):
            continue
        identifier = _resolve_identifier(
            clean,
            operational_context,
            allow_implicit_context=True,
        )
        if not identifier:
            return AssistantIntent(
                "clarification",
                intent_definition.tool_name,
                (
                    {
                        "category": _log_category(lower, intent_definition.category),
                        "lookback_hours": _lookback_hours(lower),
                    }
                    if intent_definition.tool_name == "get_asset_log_evidence"
                    else {"mode": intent_definition.mode}
                ),
                clarification=intent_definition.clarification,
                intent_family=intent_definition.name,
            )
        family_arguments: dict[str, Any] = {"identifier": identifier}
        if intent_definition.tool_name == "get_asset_status":
            family_arguments["mode"] = intent_definition.mode
        else:
            family_arguments.update(
                {
                    "category": _log_category(lower, intent_definition.category),
                    "lookback_hours": _lookback_hours(lower),
                }
            )
        return AssistantIntent(
            "operational",
            intent_definition.tool_name,
            family_arguments,
            intent_family=intent_definition.name,
        )
    if re.search(
        r"\b(?:summari[sz]e|procedure|runbook|document|guide|how do i)\b",
        lower,
    ):
        return AssistantIntent("document")
    # Reserved Milestone 3.5 intent family: tickets. No tool or routing is
    # activated until a future allow-listed connector capability exists.
    return AssistantIntent("document")


def build_operational_context(
    intent: AssistantIntent,
    result: dict[str, Any] | None,
    previous_context: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Build bounded, durable context for deterministic operational follow-ups."""
    if intent.destination == "document":
        return None
    previous = previous_context if isinstance(previous_context, dict) else {}
    arguments = dict(intent.arguments or {})
    context: dict[str, Any] = {
        "tool_name": intent.tool_name,
        "arguments": arguments,
        "pending": intent.destination == "clarification",
        "intent_family": intent.intent_family,
    }
    active = _candidate_identifier(str(arguments.get("identifier") or ""))
    if result:
        asset = result.get("asset")
        if isinstance(asset, dict):
            active = _candidate_identifier(
                str(
                    asset.get("fqdn")
                    or asset.get("hostname")
                    or asset.get("canonical_name")
                    or active
                    or ""
                )
            )
    previous_active = _active_identifier(previous)
    if not active:
        active = previous_active
    if active:
        context["active_identifier"] = active

    snapshot = _evidence_snapshot(result, active) if result else None
    if not snapshot and (
        not active or not previous_active or active == previous_active
    ):
        prior_snapshot = previous.get("evidence_snapshot")
        if isinstance(prior_snapshot, dict):
            snapshot = prior_snapshot
    if snapshot:
        context["evidence_snapshot"] = snapshot
    return context


def _evidence_snapshot(
    result: dict[str, Any],
    active_identifier: str | None,
) -> dict[str, Any] | None:
    """Retain only evidence needed for follow-up explanations."""
    assessment = result.get("assessment")
    logs = result.get("log_evidence")
    utilization = result.get("utilization")
    timeline = result.get("timeline")
    if not any(
        isinstance(value, dict | list)
        for value in (
            assessment,
            logs,
            utilization,
            timeline,
        )
    ):
        return None
    asset_value = result.get("asset")
    asset: dict[str, Any] = asset_value if isinstance(asset_value, dict) else {}
    name = (
        asset.get("fqdn")
        or asset.get("hostname")
        or asset.get("canonical_name")
        or active_identifier
    )
    snapshot: dict[str, Any] = {"identifier": name}
    if isinstance(assessment, dict):
        snapshot["assessment"] = {
            key: assessment.get(key)
            for key in (
                "overall_health",
                "mode",
                "conclusion",
                "evidence",
                "correlations",
                "recommendations",
            )
            if assessment.get(key) is not None
        }
        snapshot["assessment"]["relevant_log_evidence"] = list(
            assessment.get("relevant_log_evidence") or []
        )[:8]
        snapshot["assessment"]["unrelated_log_evidence"] = list(
            assessment.get("unrelated_log_evidence") or []
        )[:3]
    if isinstance(utilization, dict):
        snapshot["utilization"] = {
            key: utilization.get(key)
            for key in (
                "cpu_percent",
                "memory_percent",
                "disk_percent",
                "load_average_1m",
                "metric_timestamp",
                "unavailable_reason",
                "error_code",
            )
            if utilization.get(key) is not None
        }
    if isinstance(logs, dict):
        snapshot["log_evidence"] = {
            "available": logs.get("available"),
            "lookback_hours": logs.get("lookback_hours"),
            "last_log_at": logs.get("last_log_at"),
            "counts_by_category": logs.get("counts_by_category") or {},
            "unavailable_reason": logs.get("unavailable_reason"),
            "error_code": logs.get("error_code"),
            "evidence": list(logs.get("evidence") or [])[:8],
        }
        if not isinstance(assessment, dict):
            counts = logs.get("counts_by_category") or {}
            total = sum(value for value in counts.values() if isinstance(value, int))
            if logs.get("available") is False:
                conclusion = (
                    "Loki evidence was unavailable: "
                    f"{logs.get('unavailable_reason') or logs.get('error_code') or 'no reason was reported'}."
                )
            elif total:
                conclusion = (
                    f"{total} relevant Loki event"
                    f"{'s were' if total != 1 else ' was'} found in the collected window."
                )
            else:
                conclusion = (
                    "No relevant Loki events were found in the collected time window."
                )
            snapshot["assessment"] = {
                "conclusion": conclusion,
                "evidence": [],
                "relevant_log_evidence": list(logs.get("evidence") or [])[:8],
                "unrelated_log_evidence": [],
            }
    if isinstance(timeline, list):
        snapshot["timeline"] = list(timeline)[:12]
    return snapshot


def format_reused_operational_evidence(
    action: str,
    snapshot: dict[str, Any],
) -> str:
    name = snapshot.get("identifier") or "the active server"
    assessment = snapshot.get("assessment") or {}
    utilization = snapshot.get("utilization") or {}
    logs = snapshot.get("log_evidence") or {}
    conclusion = assessment.get("conclusion")
    evidence = assessment.get("evidence") or []
    correlations = assessment.get("correlations") or []
    relevant = assessment.get("relevant_log_evidence") or logs.get("evidence") or []

    if action == "timeline":
        lines = [f"## What happened — {name}", "", "### Operational sequence", ""]
        lines.extend(_timeline_lines(snapshot.get("timeline") or [], relevant))
    elif action == "current":
        lines = [f"## Current assessment from existing evidence — {name}", ""]
        observed_at = utilization.get("metric_timestamp")
        if observed_at:
            lines.append(f"- The latest collected metrics are from **{observed_at}**.")
        else:
            lines.append(
                "- No Prometheus metrics timestamp was retained, so current metric "
                "state cannot be confirmed."
            )
        if logs.get("available") is False:
            lines.append(
                "- Loki evidence was unavailable: "
                f"{logs.get('unavailable_reason') or 'no reason was reported'}."
            )
        elif relevant:
            last_log = logs.get("last_log_at") or "an unknown time"
            lines.append(
                f"- Relevant Loki evidence was last observed at **{last_log}**."
            )
        else:
            lines.append(
                "- No relevant Loki events were present in the collected evidence."
            )
    else:
        lines = [f"## Explanation — {name}", ""]

    lines.extend(["", "### Assessment", ""])
    if conclusion:
        lines.append(f"- **Why:** {conclusion}")
    else:
        lines.append(
            "- No deterministic conclusion was retained from the previous investigation."
        )
    lines.extend(f"- {item}" for item in evidence)
    if correlations:
        lines.extend(["", "### Evidence correlation", ""])
        lines.extend(f"- {item}" for item in correlations)
    if action == "current":
        lines.extend(
            [
                "",
                "- This answer reuses the previously collected evidence. It cannot "
                "confirm changes after the timestamps above without a fresh health check.",
            ]
        )
    return "\n".join(lines)


def _timeline_lines(
    timeline: list[dict[str, Any]],
    relevant_logs: list[dict[str, Any]],
    timezone_name: str = "Asia/Kolkata",
) -> list[str]:
    relevant_keys = {
        (item.get("observed_at"), item.get("category"), item.get("summary"))
        for item in relevant_logs
    }
    selected = [
        item
        for item in timeline
        if item.get("source") == "prometheus"
        or (item.get("observed_at"), item.get("category"), item.get("summary"))
        in relevant_keys
    ]
    if not selected:
        return [
            "- No relevant time-stamped Loki events or Prometheus observations "
            "were available to construct a sequence."
        ]
    lines: list[str] = []
    for item in sorted(
        selected,
        key=lambda value: str(value.get("observed_at") or ""),
    )[:12]:
        source = str(item.get("source") or "unknown").title()
        category = str(item.get("category") or "observation").replace("_", " ")
        lines.append(
            f"- **{_human_timestamp(item.get('observed_at'), timezone_name)} — "
            f"{source} / {category}:** "
            f"{item.get('summary') or 'Evidence observed.'}"
        )
    return lines


def _asset_candidates(result: dict[str, Any]) -> str:
    candidates = result.get("candidates") or []
    names = [
        item.get("fqdn") or item.get("hostname") or item.get("canonical_name")
        for item in candidates
        if isinstance(item, dict)
    ]
    return ", ".join(str(name) for name in names if name)


def _human_timestamp(value: Any, timezone_name: str) -> str:
    if not value:
        return "unavailable"
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        try:
            zone = ZoneInfo(timezone_name)
        except ZoneInfoNotFoundError:
            zone = ZoneInfo("Asia/Kolkata")
        local = parsed.astimezone(zone)
        return f"{local.day} {local.strftime('%b %Y, %I:%M %p %Z').lstrip('0')}"
    except (TypeError, ValueError):
        return str(value)


def _escape_markdown(value: Any) -> str:
    return re.sub(r"([\\`*_[\]{}<>])", r"\\\1", str(value or ""))


def _ticket_link(ticket: dict[str, Any]) -> str:
    number = _escape_markdown(
        ticket.get("number") or ticket.get("ticket_number") or "unknown"
    )
    title = _escape_markdown(ticket.get("title") or "Untitled")
    label = f"#{number} — {title}"
    raw_url = str(ticket.get("web_url") or "")
    parsed = urlparse(raw_url)
    if (
        parsed.scheme in {"http", "https"}
        and parsed.hostname
        and not parsed.username
        and not parsed.password
        and "<" not in raw_url
        and ">" not in raw_url
    ):
        return f"[{label}](<{raw_url}>)"
    return f"**{label}**"


def format_operational_result(
    tool_name: str,
    arguments: dict[str, Any],
    result: dict[str, Any],
    timezone_name: str = "Asia/Kolkata",
) -> str:
    match_status = result.get("match_status")
    identifier = str(arguments.get("identifier") or "that server")
    if tool_name == "ticketing_search_records":
        return _format_normalized_ticketing_result(arguments, result, timezone_name)
    if tool_name == "get_all_ticket_sources":
        return _format_all_ticket_sources(arguments, result, timezone_name)
    if tool_name.startswith("servicenow_"):
        return _format_servicenow_result(tool_name, arguments, result, timezone_name)
    if match_status == "not_found":
        return f"I could not find a server named {identifier} in the current tenant inventory."
    if match_status == "ambiguous":
        candidates = _asset_candidates(result)
        return (
            f"I found multiple matches for {identifier}: {candidates}. "
            "Please specify the hostname or FQDN."
        )
    if tool_name == "count_assets":
        family = arguments.get("os_family")
        qualifier = f" {str(family).title()}" if family else ""
        return f"You have {int(result.get('count', 0))}{qualifier} servers in the current inventory."
    if tool_name == "get_inventory_summary":
        return f"You have {int(result.get('total_count', 0))} servers in the current inventory."
    if tool_name == "search_assets":
        assets = result.get("assets") or []
        if not assets:
            return (
                "I could not find any matching servers in the current tenant inventory."
            )
        heading = (
            "Servers without Prometheus metrics"
            if arguments.get("missing_prometheus")
            else "Matching servers"
        )
        lines = [f"### {heading}", "", f"Found {len(assets)} servers.", ""]
        for item in assets:
            if not isinstance(item, dict):
                continue
            name = (
                item.get("fqdn") or item.get("hostname") or item.get("canonical_name")
            )
            metrics = (
                item.get("prometheus_health")
                if item.get("metrics_available")
                else "metrics unavailable"
            )
            lines.append(
                f"- **{name}** — IP: {item.get('primary_ip') or 'unavailable'}; "
                f"OS: {item.get('operating_system') or 'unavailable'}; "
                f"Prometheus: {metrics}; "
                f"last scrape: {item.get('last_scrape_at') or 'never'}"
            )
        return "\n".join(lines)
    if tool_name == "get_asset_details":
        asset = result.get("asset") or {}
        name = asset.get("fqdn") or asset.get("hostname") or asset.get("canonical_name")
        return "\n".join(
            [
                f"### Inventory — {name}",
                "",
                f"- **Hostname:** {asset.get('hostname') or name or 'unavailable'}",
                f"- **IP:** {asset.get('primary_ip') or 'unavailable'}",
                f"- **Operating system:** {asset.get('operating_system') or 'unavailable'}",
                f"- **Environment:** {asset.get('environment') or 'unavailable'}",
                (
                    "- **Prometheus:** "
                    f"{asset.get('prometheus_health') or 'unavailable'}; "
                    f"last scrape {asset.get('last_scrape_at') or 'never'}"
                ),
            ]
        )
    if tool_name == "get_asset_status":
        asset = result.get("asset") or {}
        utilization = result.get("utilization") or {}
        assessment = result.get("assessment") or {}
        logs = result.get("log_evidence") or {}
        mode = str(arguments.get("mode") or assessment.get("mode") or "health")
        detail_level = str(
            arguments.get("detail_level") or result.get("detail_level") or "concise"
        )
        relevant_logs = (
            assessment.get("relevant_log_evidence") or []
            if "relevant_log_evidence" in assessment
            else logs.get("evidence") or []
        )
        unrelated_logs = assessment.get("unrelated_log_evidence") or []
        name = asset.get("fqdn") or asset.get("hostname") or asset.get("canonical_name")
        reachable = asset.get("reachable")
        reachability = (
            "Yes"
            if reachable is True
            else "No"
            if reachable is False
            else "Unavailable"
        )
        if mode == "health" and detail_level != "detailed":
            return _format_concise_health(
                name or identifier,
                reachability,
                asset,
                utilization,
                assessment,
                result.get("related_tickets") or {},
                result.get("ticket_health_context") or {},
                timezone_name,
            )
        lines = [
            (
                f"## Performance assessment — {name}"
                if mode == "performance"
                else f"## Operational timeline — {name}"
                if mode == "timeline"
                else f"## Health report — {name}"
            ),
            "",
            "### Inventory",
            "",
            f"- **Hostname:** {asset.get('hostname') or name or 'unavailable'}",
            f"- **IP:** {asset.get('primary_ip') or 'unavailable'}",
            f"- **Operating system:** {asset.get('operating_system') or 'unavailable'}",
            "- **Evidence source:** Connector inventory",
            "",
            (
                "### Current performance"
                if mode == "performance"
                else "### Current state"
                if mode == "timeline"
                else "### Prometheus"
            ),
            "",
            f"- **Overall health:** {assessment.get('overall_health') or 'unknown'}",
            f"- **Reachable:** {reachability}",
            f"- **Last observed:** {_human_timestamp(asset.get('last_observed_at'), timezone_name)}",
            f"- **Prometheus health:** {asset.get('prometheus_health') or 'unavailable'}",
            f"- **Last metrics timestamp:** {_human_timestamp(utilization.get('metric_timestamp'), timezone_name)}",
            "- **Evidence source:** Prometheus",
            "",
            "### Utilisation",
            "",
            f"- **CPU:** {_percent(utilization.get('cpu_percent'))}",
            f"- **Load average (1m):** {_number(utilization.get('load_average_1m'))}",
            f"- **Memory:** {_percent(utilization.get('memory_percent'))}",
            f"- **Disk maximum:** {_percent(utilization.get('disk_percent'))}",
        ]
        lines.extend(_filesystem_lines(utilization))
        lines.extend(_process_lines(utilization))
        lines.extend(["", "### Loki findings", ""])
        if logs.get("available"):
            lines.extend(
                [
                    f"- **Window:** Last {logs.get('lookback_hours', 24)} hours",
                    f"- **Correlated streams:** {len(logs.get('matched_streams') or [])}",
                    f"- **Last matching log:** {_human_timestamp(logs.get('last_log_at'), timezone_name) if logs.get('last_log_at') else 'none'}",
                    "- **Evidence source:** Loki",
                ]
            )
            counts: dict[str, int] = {}
            for item in relevant_logs:
                category = str(item.get("category") or "unknown")
                counts[category] = counts.get(category, 0) + 1
            nonzero = [
                f"{str(category).replace('_', ' ')}: {count}"
                for category, count in counts.items()
                if isinstance(count, int) and count > 0
            ]
            lines.append(
                "- **Relevant findings:** "
                + (", ".join(nonzero) if nonzero else "No relevant events.")
            )
            lines.extend(
                _log_evidence_lines(relevant_logs, limit=8, timezone_name=timezone_name)
            )
            if unrelated_logs:
                lines.extend(
                    [
                        "",
                        "#### Historical evidence assessed as unrelated",
                        "",
                        (
                            f"- {len(unrelated_logs)} event"
                            f"{'s' if len(unrelated_logs) != 1 else ''} were excluded "
                            "from the operational conclusion because they did not align "
                            "with the current Prometheus observation."
                        ),
                    ]
                )
                for item in unrelated_logs[:3]:
                    lines.append(
                        f"- **{item.get('observed_at') or 'unknown time'}** "
                        f"[{str(item.get('category') or 'event').replace('_', ' ')}] "
                        f"{item.get('summary') or 'Evidence observed.'} — "
                        f"{item.get('relevance_reason') or 'Not relevant to the current question.'}"
                    )
        else:
            lines.extend(
                [
                    f"- **Availability:** Unknown ({logs.get('error_code') or 'LOKI_UNAVAILABLE'})",
                    f"- **Reason:** {logs.get('unavailable_reason') or 'No Loki evidence is available.'}",
                    "- **Evidence source:** Loki",
                ]
            )
        lines.extend(
            [
                "",
                (
                    "### Operational sequence"
                    if mode == "timeline"
                    else "### Evidence timeline"
                ),
                "",
            ]
        )
        timeline = result.get("timeline") or []
        lines.extend(_timeline_lines(timeline, relevant_logs, timezone_name))
        correlations = assessment.get("correlations") or []
        if correlations:
            lines.extend(["", "#### Correlation", ""])
            lines.extend(f"- {item}" for item in correlations)
        elif unrelated_logs:
            lines.extend(
                [
                    "",
                    "#### Correlation",
                    "",
                    "- No temporal relationship was found between the historical Loki "
                    "events and the current Prometheus observation.",
                ]
            )
        lines.extend(["", "### Assessment", ""])
        if assessment.get("conclusion"):
            lines.append(f"- **Why:** {assessment['conclusion']}")
        evidence = assessment.get("evidence") or [
            utilization.get("unavailable_reason")
            or "No assessment evidence is available."
        ]
        lines.extend(f"- {item}" for item in evidence)
        lines.extend(["", "### Recommendations", ""])
        recommendations = assessment.get("recommendations") or []
        lines.extend(f"- {item}" for item in recommendations)
        if not recommendations:
            lines.append("- No evidence-backed remediation is recommended.")
        related_tickets = result.get("related_tickets") or {}
        availability = related_tickets.get("availability") or {}
        open_tickets = related_tickets.get("open_tickets") or []
        closed_tickets = related_tickets.get("recently_closed_tickets") or []
        lines.extend(["", "### Related tickets", ""])
        if open_tickets or closed_tickets:
            for ticket in [*open_tickets, *closed_tickets]:
                kind = (
                    str(ticket.get("ticket_type") or "unknown")
                    .replace("_", " ")
                    .title()
                )
                lines.append(
                    f"- {_ticket_link(ticket)} "
                    f"— {ticket.get('state') or 'unknown'} ({kind})"
                )
                if ticket.get("latest_update"):
                    lines.append(f"  Latest update: {ticket['latest_update']}")
                lines.append(
                    f"  Updated: {_human_timestamp(ticket.get('updated_at'), timezone_name)}; "
                    f"relationship: {str(ticket.get('relationship') or 'direct').replace('_', ' ')}"
                )
            if any(
                ticket.get("ticket_type")
                in {"service_request", "access_request", "maintenance", "change"}
                for ticket in open_tickets
            ):
                lines.append(
                    "- Open service, access, maintenance, and change requests are context and do not change "
                    "the monitoring-derived health assessment."
                )
        elif availability.get("error_code"):
            lines.append(
                f"- Ticket information is unavailable ({availability['error_code']}): "
                f"{availability.get('last_error') or 'no connector-local ticket evidence is available.'}"
            )
        elif availability.get("enabled") is False:
            lines.append("- Zammad ticket enrichment is disabled or not configured.")
        else:
            lines.append(
                "- No directly related open or recently closed tickets were found."
            )
        servicenow = result.get("servicenow_records") or {}
        service_records = servicenow.get("records") or []
        service_availability = servicenow.get("availability") or {}
        lines.extend(["", "### Related ServiceNow records", ""])
        if service_records:
            for record in service_records:
                lines.append(
                    f"- **ServiceNow {record.get('number')}** "
                    f"[{record.get('record_type')}]: {record.get('short_description') or 'No description'} "
                    f"— {record.get('state') or 'unknown'}"
                )
        elif service_availability.get("enabled") is False:
            lines.append("- ServiceNow enrichment is disabled or not configured.")
        else:
            lines.append(
                "- No directly related ServiceNow incidents, problems, or changes were found."
            )
        if service_availability.get("stale"):
            lines.append(
                "- ServiceNow cached data is stale and is not presented as current."
            )
        return "\n".join(lines)
    if tool_name == "get_asset_log_evidence":
        asset = result.get("asset") or {}
        logs = result.get("log_evidence") or {}
        name = asset.get("fqdn") or asset.get("hostname") or asset.get("canonical_name")
        lines = [
            f"## Log evidence — {name or identifier}",
            "",
            f"- **Window:** Last {logs.get('lookback_hours') or arguments.get('lookback_hours', 24)} hours",
            "- **Evidence source:** Loki",
        ]
        if not logs.get("available"):
            lines.extend(
                [
                    f"- **Availability:** Unknown ({logs.get('error_code') or 'LOKI_UNAVAILABLE'})",
                    f"- **Reason:** {logs.get('unavailable_reason') or 'No Loki evidence is available.'}",
                ]
            )
            return "\n".join(lines)
        lines.extend(
            [
                f"- **Correlated streams:** {len(logs.get('matched_streams') or [])}",
                f"- **Last matching log:** {_human_timestamp(logs.get('last_log_at'), timezone_name) if logs.get('last_log_at') else 'none'}",
                "",
                "### Findings",
                "",
            ]
        )
        counts = logs.get("counts_by_category") or {}
        findings = [
            (category, count)
            for category, count in counts.items()
            if isinstance(count, int) and count > 0
        ]
        if findings:
            lines.extend(
                f"- **{str(category).replace('_', ' ').title()}:** {count}"
                for category, count in findings
            )
        else:
            lines.append("- No matching events were found in the requested window.")
        lines.extend(
            _log_evidence_lines(
                logs.get("evidence") or [], limit=25, timezone_name=timezone_name
            )
        )
        lines.extend(["", "### Assessment", ""])
        total = sum(count for _category, count in findings)
        requested = _category_event_label(str(arguments.get("category") or ""))
        if total:
            lines.append(
                f"- **Why:** {total} matching {requested} event"
                f"{'s' if total != 1 else ''} matched the requested server and time window."
            )
            recommendation = _log_recommendation(str(arguments.get("category") or ""))
            if recommendation:
                lines.extend(
                    [
                        "",
                        "### Recommendation",
                        "",
                        f"- {recommendation}",
                    ]
                )
        else:
            lines.append(
                f"- No relevant Loki {requested} events were found for "
                f"{name or identifier} during the requested period."
            )
        return "\n".join(lines)
    if tool_name == "get_asset_utilization":
        utilization = result.get("utilization") or {}
        name = utilization.get("asset") or identifier
        lines = [
            f"## Resource utilisation — {name}",
            "",
            f"- **CPU:** {_percent(utilization.get('cpu_percent'))}",
            f"- **Load average (1m):** {_number(utilization.get('load_average_1m'))}",
            f"- **Memory:** {_percent(utilization.get('memory_percent'))}",
            f"- **Disk maximum:** {_percent(utilization.get('disk_percent'))}",
            f"- **Metrics timestamp:** {_human_timestamp(utilization.get('metric_timestamp'), timezone_name)}",
        ]
        lines.extend(_filesystem_lines(utilization))
        if utilization.get("unavailable_reason"):
            lines.extend(
                [
                    "",
                    "### Metrics availability",
                    "",
                    f"- **{utilization.get('error_code') or 'METRICS_UNAVAILABLE'}:** "
                    f"{utilization['unavailable_reason']}",
                ]
            )
        return "\n".join(lines)
    if tool_name == "get_ticket_counts":
        requested = str(arguments.get("requested_state") or "all")
        value = (
            result.get("open")
            if requested == "open"
            else result.get("closed")
            if requested == "closed"
            else result.get("total_visible")
        )
        lines = [
            "## Zammad ticket counts",
            "",
            f"- **{requested.title()} tickets:** {int(value or 0)}",
            f"- **Total visible:** {int(result.get('total_visible') or 0)}",
            f"- **Open:** {int(result.get('open') or 0)}",
            f"- **Closed:** {int(result.get('closed') or 0)}",
            f"- **New:** {int(result.get('new') or 0)}",
            f"- **Pending:** {int(result.get('pending') or 0)}",
        ]
        lines.extend(_ticket_freshness_lines(result, timezone_name))
        return "\n".join(lines)
    if tool_name == "get_ticket":
        ticket = result.get("ticket") or {}
        view = str(arguments.get("view") or "full")
        lines = [
            f"## Ticket {_ticket_link(ticket)}",
            "",
            f"- **State:** {ticket.get('state') or 'unknown'}",
            f"- **Type:** {str(ticket.get('ticket_type') or 'unknown').replace('_', ' ').title()}",
        ]
        if view in {"full", "owner"}:
            lines.extend(
                [
                    f"- **Owner:** {ticket.get('owner') or 'unassigned'}",
                    f"- **Group:** {ticket.get('group') or 'unavailable'}",
                ]
            )
        if view == "full":
            lines.extend(
                [
                    f"- **Priority:** {ticket.get('priority') or 'unavailable'}",
                    f"- **Created:** {_human_timestamp(ticket.get('created_at'), timezone_name)}",
                    f"- **Updated:** {_human_timestamp(ticket.get('updated_at'), timezone_name)}",
                    "",
                    "### Initial description",
                    "",
                    ticket.get("initial_description")
                    or "No readable initial description is available.",
                ]
            )
        latest = ticket.get("latest_update") or {}
        if view in {"full", "latest_update"}:
            lines.extend(
                [
                    "",
                    "### Latest meaningful update",
                    "",
                    f"- **At:** {_human_timestamp(latest.get('at'), timezone_name)}",
                    f"- **Author:** {latest.get('author') or 'unavailable'}",
                    f"- {latest.get('text') or 'No meaningful permitted article was found.'}",
                ]
            )
        if view == "full":
            lines.extend(["", "### Article timeline", ""])
            articles = ticket.get("articles") or []
            if articles:
                for article in articles[-12:]:
                    marker = "automated" if article.get("automated") else "human update"
                    lines.append(
                        f"- **{_human_timestamp(article.get('created_at'), timezone_name)}** "
                        f"({marker}; {article.get('author') or article.get('sender') or 'unknown author'}): "
                        f"{article.get('body_text') or 'No readable text.'}"
                    )
            else:
                lines.append("- No permitted article history is available.")
        lines.extend(_ticket_freshness_lines(result, timezone_name))
        return "\n".join(lines)
    if tool_name == "search_tickets":
        tickets = result.get("tickets") or []
        count = int(result.get("count") or 0)
        provider = result.get("ticketing_provider") or {}
        provider_name = _escape_markdown(
            provider.get("display_name")
            or provider.get("integration_type")
            or "current provider"
        )
        requested_limit = int(
            result.get("requested_limit") or arguments.get("limit") or 5
        )
        lines = [
            f"## Matching {provider_name} tickets",
            "",
            (
                f"There are only {count} {str(arguments.get('state') or 'matching')} tickets, "
                f"so all {count} are shown."
                if count < requested_limit and not arguments.get("query")
                else f"Found {count} clearly matching ticket{'s' if count != 1 else ''}."
            ),
            "",
        ]
        if tickets:
            lines.extend(
                _ticket_summary_line(ticket, timezone_name) for ticket in tickets
            )
        else:
            family = str(result.get("concept_family") or "")
            no_results = {
                "access_request": "No tickets clearly related to user access requests were found.",
                "authentication_incident": "No tickets clearly related to authentication incidents were found.",
                "memory": "No tickets clearly related to memory problems were found.",
            }
            lines.append(
                no_results.get(
                    family,
                    "No tickets met the deterministic relevance threshold for this search.",
                )
            )
        lines.extend(_ticket_freshness_lines(result, timezone_name))
        return "\n".join(lines)
    if tool_name == "get_asset_tickets":
        if result.get("match_status") == "not_found":
            return f"I could not resolve {arguments.get('identifier')} to a canonical CMDB asset."
        direct = result.get("direct_tickets") or []
        indirect = result.get("indirect_tickets") or []
        lines = [
            f"## Tickets for {arguments.get('identifier')}",
            "",
            "### Directly related",
            "",
        ]
        lines.extend(_ticket_summary_line(ticket, timezone_name) for ticket in direct)
        if not direct:
            lines.append("- No directly related tickets were found.")
        lines.extend(["", "### Indirectly related", ""])
        lines.extend(_ticket_summary_line(ticket, timezone_name) for ticket in indirect)
        if not indirect:
            lines.append("- No indirectly related tickets were found.")
        lines.extend(
            _ticket_availability_lines(result.get("availability") or {}, timezone_name)
        )
        return "\n".join(lines)
    if tool_name == "correlate_tickets_with_evidence":
        correlations = result.get("correlations") or []
        lines = ["## Ticket correlation", ""]
        if correlations:
            for ticket in correlations:
                lines.append(
                    f"- {_ticket_link(ticket)}: "
                    f"{str(ticket.get('classification') or 'insufficient_evidence').replace('_', ' ')} "
                    f"(score {ticket.get('score')}; reasons: {', '.join(ticket.get('reasons') or [])})."
                )
            lines.append(
                "- Time and text overlap indicate correlation only; they do not prove causation."
            )
        else:
            lines.append(
                "- No ticket had sufficient deterministic evidence to correlate with the operational window."
            )
        lines.extend(
            _ticket_availability_lines(result.get("availability") or {}, timezone_name)
        )
        return "\n".join(lines)
    return "The connector returned an unsupported operational result."


def _format_normalized_ticketing_result(
    arguments: dict[str, Any], result: dict[str, Any], timezone_name: str
) -> str:
    providers = list(result.get("providers") or [])
    enabled = list(result.get("enabled_providers") or [])
    requested = list(result.get("requested_providers") or [])
    if not enabled:
        return "No active ticketing provider is configured."
    if not providers and requested:
        labels = [
            "ServiceNow" if item == "servicenow" else "Zammad" for item in requested
        ]
        return f"{' and '.join(labels)} is not enabled for this connector."

    def records_for(provider: dict[str, Any]) -> list[dict[str, Any]]:
        return list(
            provider.get("records")
            or provider.get("incidents")
            or provider.get("tickets")
            or []
        )

    total = sum(
        int(
            provider.get("total")
            if provider.get("total") is not None
            else provider.get("count")
            if provider.get("count") is not None
            else len(records_for(provider))
        )
        for provider in providers
    )
    mode = str(arguments.get("mode") or "search")
    state = str(arguments.get("state") or "open")
    identifier = arguments.get("identifier")
    heading = (
        f"## {state.title()} tickets for {identifier}"
        if mode == "asset" and identifier
        else f"## {state.title()} tickets"
    )
    lines = [heading, "", "### Provider counts", ""]
    for provider in providers:
        source = str(provider.get("source") or "unknown")
        label = (
            "ServiceNow"
            if source == "servicenow"
            else "Zammad"
            if source == "zammad"
            else source
        )
        noun = "incidents" if source == "servicenow" else "tickets"
        if provider.get("status") == "error":
            lines.append(
                f"- **{label}:** unavailable — {provider.get('error_message')}"
            )
        else:
            count = int(
                provider.get("total")
                if provider.get("total") is not None
                else provider.get("count")
                if provider.get("count") is not None
                else len(records_for(provider))
            )
            lines.append(f"- **{label}:** {count} {noun}")
    if len(providers) > 1:
        lines.append(f"- **Combined:** {total} records")
    displayed = sum(
        len(records_for(provider))
        for provider in providers
        if provider.get("status") == "ok"
    )
    if mode != "count" and displayed < total:
        lines.extend(
            [
                "",
                f"Showing {displayed} of {total} matching records.",
                "Ask to show all matching tickets to retrieve the remaining "
                f"{total - displayed}.",
            ]
        )
    for provider in providers:
        if provider.get("status") != "ok":
            continue
        source = str(provider.get("source") or "unknown")
        label = (
            "ServiceNow"
            if source == "servicenow"
            else "Zammad"
            if source == "zammad"
            else source
        )
        records = records_for(provider)
        if records:
            lines.extend(["", f"### {label}", ""])
            for record in records:
                external_id = (
                    record.get("external_id") or record.get("number") or "unknown"
                )
                prefix = (
                    f"ServiceNow {external_id}"
                    if source == "servicenow"
                    else f"Zammad #{external_id}"
                )
                title = (
                    record.get("title")
                    or record.get("short_description")
                    or "No description"
                )
                lines.append(
                    f"- **{prefix}**: {title} — {record.get('state') or 'Unknown'}"
                )
        if provider.get("stale"):
            lines.append(
                f"- **{label} cache is stale:** last synchronized "
                f"{_human_timestamp(provider.get('last_synced_at'), timezone_name)}."
            )
    if mode != "count" and not any(records_for(provider) for provider in providers):
        lines.extend(
            ["", "No matching records were found in the enabled ticket providers."]
        )
    return "\n".join(lines)


def _format_all_ticket_sources(
    arguments: dict[str, Any], result: dict[str, Any], timezone_name: str
) -> str:
    sources = result.get("sources") or {}
    zammad = sources.get("zammad") or {}
    servicenow = sources.get("servicenow") or {}
    zammad_tickets = [
        *list(zammad.get("direct_tickets") or []),
        *list(zammad.get("indirect_tickets") or []),
        *list(zammad.get("potential_tickets") or []),
    ]
    servicenow_records = list(servicenow.get("records") or [])
    lines = [
        f"## Ticket sources for {arguments.get('identifier')}",
        "",
        "### Counts",
        "",
        f"- **ServiceNow:** {len(servicenow_records)} records",
        f"- **Zammad:** {len(zammad_tickets)} tickets",
        f"- **Combined:** {len(servicenow_records) + len(zammad_tickets)} records",
    ]
    if servicenow_records:
        lines.extend(["", "### ServiceNow", ""])
        lines.extend(
            f"- **ServiceNow {item.get('number') or item.get('external_id')}**: "
            f"{item.get('short_description') or 'No description'}"
            for item in servicenow_records
        )
    if zammad_tickets:
        lines.extend(["", "### Zammad", ""])
        lines.extend(
            f"- **Zammad ticket #{item.get('number') or item.get('external_id')}**: "
            f"{item.get('title') or item.get('subject') or 'No description'}"
            for item in zammad_tickets
        )
    for label, source in (("ServiceNow", servicenow), ("Zammad", zammad)):
        availability = source.get("availability") or {}
        if source.get("available") is False:
            lines.append(f"- **{label} unavailable:** {source.get('error_message')}")
        elif availability.get("stale"):
            timestamp = availability.get("cache_timestamp")
            lines.append(
                f"- **{label} cache is stale:** last synchronized "
                f"{_human_timestamp(timestamp, timezone_name)}."
            )
    if not servicenow_records and not zammad_tickets:
        lines.extend(["", "No related records were found in either enabled source."])
    return "\n".join(lines)


def _format_servicenow_result(
    tool_name: str,
    arguments: dict[str, Any],
    result: dict[str, Any],
    timezone_name: str,
) -> str:
    availability = result.get("availability") or {}
    if availability.get("enabled") is False:
        return "ServiceNow is disabled for this connector."
    freshness = []
    if availability.get("cache_timestamp"):
        freshness.append(
            f"- **Cache timestamp:** {_human_timestamp(availability['cache_timestamp'], timezone_name)}"
        )
    if availability.get("stale"):
        freshness.append(
            "- **Warning:** ServiceNow cached data is stale and may not reflect the current source state."
        )
    if tool_name == "servicenow_get_status":
        counts = result.get("counts") or {}
        lines = [
            "## ServiceNow integration",
            "",
            f"- **Enabled:** {'Yes' if result.get('enabled') else 'No'}",
            f"- **Configured:** {'Yes' if result.get('configured') else 'No'}",
            f"- **Connected:** {'Yes' if result.get('connected') else 'No'}",
            f"- **Last successful synchronization:** {_human_timestamp(result.get('last_successful_sync_at'), timezone_name)}",
        ]
        lines.extend(
            f"- **{str(key).replace('_', ' ').title()}:** {value}"
            for key, value in counts.items()
        )
        if result.get("last_sync_error"):
            lines.append(f"- **Last error:** {result['last_sync_error']}")
        return "\n".join(lines)
    if tool_name in {"servicenow_get_incident", "servicenow_get_incident_updates"}:
        incident = result.get("incident")
        if not incident:
            return f"No ServiceNow incident {arguments.get('number')} was found."
        lines = [
            f"## ServiceNow {incident.get('number')}",
            "",
            f"- **Summary:** {incident.get('short_description') or 'Unavailable'}",
            f"- **State:** {incident.get('state') or 'Unknown'}",
            f"- **Priority:** {incident.get('priority') or 'Unavailable'}",
            f"- **Assigned to:** {incident.get('assigned_to') or 'Unassigned'}",
            f"- **Assignment group:** {incident.get('assignment_group') or 'Unassigned'}",
        ]
        if incident.get("latest_update"):
            lines.extend(
                [
                    "",
                    "### Latest meaningful update",
                    "",
                    f"- **At:** {_human_timestamp(incident.get('latest_update_at'), timezone_name)}",
                    f"- {incident['latest_update']}",
                ]
            )
        if tool_name.endswith("updates"):
            lines.extend(["", "### Updates", ""])
            for update in result.get("updates") or []:
                lines.append(
                    f"- **{_human_timestamp(update.get('created_at'), timezone_name)}** ({update.get('element')}; {update.get('created_by') or 'unknown'}): {update.get('value')} "
                )
        lines.extend(freshness)
        return "\n".join(lines)
    if tool_name in {
        "servicenow_get_ci",
        "servicenow_get_ci_relationships",
        "servicenow_get_ci_tickets",
    }:
        ci = result.get("ci")
        if not ci:
            return f"No ServiceNow configuration item matched {arguments.get('identifier')}."
        lines = [
            f"## ServiceNow CI: {ci.get('name') or ci.get('external_sys_id')}",
            "",
            f"- **Class:** {ci.get('sys_class_name')}",
            f"- **FQDN:** {ci.get('fqdn') or 'Unavailable'}",
            f"- **IP address:** {ci.get('ip_address') or 'Unavailable'}",
        ]
        if tool_name.endswith("relationships"):
            lines.extend(["", "### Relationships", ""])
            for relationship in result.get("relationships") or []:
                lines.append(
                    f"- {relationship.get('parent') or relationship.get('parent_sys_id')} — **{relationship.get('type')}** → {relationship.get('child') or relationship.get('child_sys_id')} (depth {relationship.get('depth')})"
                )
            if not result.get("relationships"):
                lines.append("- No cached relationships were found.")
        if tool_name.endswith("tickets"):
            lines.extend(["", "### Related ServiceNow records", ""])
            for record in result.get("records") or []:
                lines.append(
                    f"- **{record.get('number')}** [{record.get('record_type')}]: {record.get('short_description')} — {record.get('state')}"
                )
            if not result.get("records"):
                lines.append(
                    "- No directly related incidents, problems, or changes were found."
                )
        lines.extend(freshness)
        return "\n".join(lines)
    records = result.get("records") or []
    record_type = str(result.get("record_type") or "record")
    lines = [
        f"## ServiceNow {record_type.replace('_', ' ').title()} results",
        "",
        f"Found {int(result.get('count') or 0)} matching records.",
        "",
    ]
    for record in records:
        lines.append(
            f"- **{record.get('number')}**: {record.get('short_description') or 'No description'} — {record.get('state') or 'Unknown'}; assigned to {record.get('assigned_to') or 'unassigned'}"
        )
    if not records:
        lines.append("- No matching ServiceNow records were found.")
    lines.extend(freshness)
    return "\n".join(lines)


def _concise_log_observation(item: dict[str, Any]) -> str:
    """Describe log evidence without exposing a full raw event by default."""
    summary = str(item.get("summary") or "")
    lowered = summary.casefold()
    impact = str(item.get("impact_classification") or "unknown")
    if "timestamp too new" in lowered or (
        "timestamp" in lowered and ("ahead of" in lowered or "clock" in lowered)
    ):
        return "One Loki timestamp synchronization anomaly was detected."
    if "firmware" in lowered and any(
        token in lowered for token in ("parse", "parsing", "metadata")
    ):
        return "One firmware metadata parsing error was detected."
    return {
        "monitoring_pipeline_issue": "One monitoring pipeline anomaly was detected.",
        "configuration_issue": "One configuration anomaly was detected.",
        "active_operational_issue": "One active operational log issue was detected.",
        "likely_operational_issue": "One likely operational log issue was detected.",
        "isolated_anomaly": "One isolated log anomaly was detected.",
    }.get(impact, "One relevant log anomaly was detected.")


def _format_concise_health(
    name: str,
    reachability: str,
    asset: dict[str, Any],
    utilization: dict[str, Any],
    assessment: dict[str, Any],
    related_tickets: dict[str, Any],
    ticket_context: dict[str, Any],
    timezone_name: str,
) -> str:
    health = str(assessment.get("overall_health") or "unknown")
    observations = assessment.get("relevant_log_evidence") or []
    anomaly_count = sum(
        item.get("impact_classification")
        not in {"routine_system_event", "historical", "informational"}
        for item in observations
    )
    intro = f"{name} is {health}"
    if anomaly_count:
        intro += (
            f", with {anomaly_count} recent log anomal"
            f"{'ies' if anomaly_count != 1 else 'y'}"
        )
    lines = [intro + ".", "", "### Current state", ""]
    lines.extend(
        [
            f"- **Reachable:** {reachability}",
            f"- **Prometheus:** {asset.get('prometheus_health') or 'unavailable'}",
            f"- **CPU:** {_percent(utilization.get('cpu_percent'))}",
            f"- **Memory:** {_percent(utilization.get('memory_percent'))}",
            f"- **Highest disk usage:** {_percent(utilization.get('disk_percent'))}",
        ]
    )
    lines.extend(["", "### Recent observations", ""])
    important = [
        item
        for item in observations
        if item.get("impact_classification") != "routine_system_event"
    ][:3]
    if important:
        rendered_observations: list[str] = []
        for item in important:
            observation = _concise_log_observation(item)
            if observation not in rendered_observations:
                rendered_observations.append(observation)
                lines.append(f"- {observation}")
        if health == "healthy":
            lines.append(
                "- Current reachability and resource metrics do not show ongoing degradation."
            )
    else:
        lines.append("- No current operationally impactful log evidence was found.")

    direct = related_tickets.get("direct_tickets")
    if direct is None:
        direct = [
            *(related_tickets.get("open_tickets") or []),
            *(related_tickets.get("recently_closed_tickets") or []),
        ]
    direct = direct or []
    indirect = related_tickets.get("indirect_tickets") or []
    lines.extend(["", "### Related tickets", ""])
    if direct:
        for ticket in direct[:5]:
            lines.append(
                f"- {_ticket_link(ticket)} — {ticket.get('state') or 'unknown'}, "
                f"{str(ticket.get('ticket_type') or 'unknown').replace('_', ' ')}; updated "
                f"{_human_timestamp(ticket.get('updated_at'), timezone_name)}"
            )
    if indirect:
        for ticket in indirect[:3]:
            relationship = str(ticket.get("relationship") or "indirect").replace(
                "_", " "
            )
            lines.append(
                f"- {_ticket_link(ticket)} — indirectly related ({relationship}), "
                f"{ticket.get('state') or 'unknown'}"
            )
    if not direct and not indirect:
        lines.append("- No directly or indirectly related tickets were found.")

    lines.extend(["", "### Assessment", ""])
    if ticket_context.get("closed_incident_count") and health == "healthy":
        lines.append(
            "- Previous incidents are closed. Current metrics are within normal thresholds, "
            "so there is no evidence those issues remain active."
        )
    non_health_open_count = ticket_context.get("non_health_open_count")
    if non_health_open_count is None:
        non_health_open_count = sum(
            ticket.get("is_open", str(ticket.get("state") or "").casefold() != "closed")
            and ticket.get("ticket_type")
            in {"service_request", "access_request", "maintenance", "change"}
            for ticket in direct
        )
    if non_health_open_count:
        lines.append(
            "- Open service, access, maintenance, or change requests are context only and "
            "do not change monitoring-derived health."
        )
    lines.append(
        f"- {ticket_context.get('assessment') or assessment.get('conclusion') or 'No additional health impact is established.'}"
    )
    recommendations = assessment.get("recommendations") or []
    if recommendations:
        lines.append(f"- {recommendations[0]}")
    return "\n".join(lines)


def _ticket_summary_line(ticket: dict[str, Any], timezone_name: str) -> str:
    kind = str(ticket.get("ticket_type") or "unknown").replace("_", " ")
    relevance = ticket.get("relevance") or {}
    reasons = relevance.get("match_reasons") or []
    return (
        f"- {_ticket_link(ticket)}\n"
        f"  Status: {ticket.get('state') or 'unknown'} · Type: {kind.title()} · "
        f"Updated: {_human_timestamp(ticket.get('updated_at'), timezone_name)}\n"
        f"  Summary: {ticket.get('summary') or 'No concise summary is available.'}"
        + (
            f"\n  Match: {'; '.join(str(reason) for reason in reasons[:2])} "
            f"({relevance.get('confidence') or 'unknown'} confidence, "
            f"score {relevance.get('score')})"
            if relevance
            else ""
        )
    )


def _ticket_freshness_lines(result: dict[str, Any], timezone_name: str) -> list[str]:
    if result.get("live"):
        return ["", "- **Freshness:** Validated live with Zammad."]
    cache = result.get("cache_timestamp")
    warning = result.get("warning")
    return [
        "",
        f"- **Freshness:** Cached connector data from "
        f"{_human_timestamp(cache, timezone_name) if cache else 'an unknown time'}.",
        *([f"- **Live validation unavailable:** {warning}"] if warning else []),
    ]


def _ticket_availability_lines(
    availability: dict[str, Any], timezone_name: str
) -> list[str]:
    lines = [
        "",
        f"- **Ticket cache timestamp:** "
        f"{_human_timestamp(availability.get('cache_timestamp'), timezone_name) if availability.get('cache_timestamp') else 'never'}",
    ]
    if availability.get("stale"):
        lines.append("- **Freshness:** Cached ticket data is stale.")
    if availability.get("last_error"):
        lines.append(f"- **Zammad availability:** {availability['last_error']}")
    return lines


def _percent(value: Any) -> str:
    return f"{value:.2f}%" if isinstance(value, int | float) else "Unavailable"


def _number(value: Any) -> str:
    return f"{value:.2f}" if isinstance(value, int | float) else "Unavailable"


def _filesystem_lines(utilization: dict[str, Any]) -> list[str]:
    filesystems = utilization.get("filesystems") or []
    if not filesystems:
        return ["", "### Filesystems", "", "- Filesystem metrics unavailable."]
    lines = ["", "### Filesystems", ""]
    for item in filesystems:
        lines.append(
            f"- **{item.get('mountpoint') or 'unknown'}:** "
            f"{_percent(item.get('used_percent'))} used"
        )
    return lines


def _process_lines(utilization: dict[str, Any]) -> list[str]:
    lines = ["", "### Top CPU processes", ""]
    cpu = utilization.get("top_cpu_processes") or []
    lines.extend(
        (f"- **{item.get('name') or 'unknown'}:** {_percent(item.get('cpu_percent'))}")
        for item in cpu
    )
    if not cpu:
        lines.append("- Process metrics unavailable.")
    lines.extend(["", "### Top memory processes", ""])
    memory = utilization.get("top_memory_processes") or []
    lines.extend(
        (
            f"- **{item.get('name') or 'unknown'}:** "
            f"{float(item.get('memory_bytes', 0)) / 1024 / 1024:.2f} MiB"
        )
        for item in memory
    )
    if not memory:
        lines.append("- Process metrics unavailable.")
    return lines


def _log_evidence_lines(
    evidence: list[dict[str, Any]],
    *,
    limit: int,
    timezone_name: str = "Asia/Kolkata",
) -> list[str]:
    if not evidence:
        return []
    lines = ["", "#### Matching events", ""]
    for item in evidence[:limit]:
        lines.append(
            f"- **{_human_timestamp(item.get('observed_at'), timezone_name)}** "
            f"[{str(item.get('severity') or 'unknown').upper()} / "
            f"{str(item.get('category') or 'event').replace('_', ' ')}] "
            f"{item.get('summary') or 'Evidence observed.'}"
        )
    return lines


def _log_recommendation(category: str) -> str | None:
    return {
        "oom": "Review memory pressure and application heap limits because OOM evidence was found.",
        "crashes": "Inspect the affected process and crash context because crash evidence was found.",
        "exceptions": "Review the exception context and stack trace because exception evidence was found.",
        "auth_failures": "Review the authentication source and frequency because failures were found.",
        "restarts": "Review the service restart history and preceding events because restarts were found.",
        "filesystem": "Inspect filesystem health and capacity because filesystem failure evidence was found.",
        "errors": "Review the affected component because matching error evidence was found.",
        "warnings": "Review repeated warnings if they coincide with user-visible impact.",
    }.get(category)


def _category_event_label(category: str) -> str:
    return {
        "errors": "error",
        "warnings": "warning",
        "restarts": "restart",
        "crashes": "crash",
        "exceptions": "exception",
        "auth_failures": "authentication failure",
        "kernel": "kernel failure",
        "filesystem": "filesystem failure",
        "oom": "out-of-memory",
        "application_failures": "application failure",
    }.get(category, "operational")


class OperationalAssistantService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.tools = OperationalToolService(db)

    async def answer(
        self,
        tenant_id: UUID,
        user_id: UUID,
        intent: AssistantIntent,
    ) -> OperationalAnswer:
        if intent.destination == "contextual":
            return OperationalAnswer(
                format_reused_operational_evidence(
                    str((intent.arguments or {}).get("action") or "explain"),
                    intent.evidence_context or {},
                ),
                intent.tool_name or "reuse_operational_evidence",
                None,
                None,
            )
        if intent.destination == "clarification":
            return OperationalAnswer(
                intent.clarification or "Please clarify the server.",
                "clarification",
                None,
                None,
            )
        assert intent.tool_name is not None
        arguments = intent.arguments or {}
        try:
            request = self.tools.create(tenant_id, user_id, intent.tool_name, arguments)
            if intent.tool_name == "ticketing_search_records":
                logger.info(
                    "ticket_provider_selection tenant_id=%s connector_id=%s intent=%s "
                    "requested_providers=%s selected_tool=%s operational_request_id=%s",
                    tenant_id,
                    request.connector_id,
                    intent.intent_family,
                    arguments.get("providers") or ["zammad", "servicenow"],
                    intent.tool_name,
                    request.id,
                )
        except OperationalToolUnavailable as exc:
            return OperationalAnswer(str(exc), intent.tool_name, None, None)
        while True:
            current = self.tools.result(tenant_id, request.id)
            if current.status == "completed":
                result = current.result or {}
                if intent.tool_name == "ticketing_search_records":
                    provider_results = list(result.get("providers") or [])
                    logger.info(
                        "ticket_tool_result tenant_id=%s connector_id=%s request_id=%s "
                        "tool=%s configured=%s enabled=%s selected=%s records=%s stale=%s "
                        "final_answer_path=normalized_ticketing",
                        tenant_id,
                        current.connector_id,
                        current.id,
                        intent.tool_name,
                        result.get("configured_providers") or [],
                        result.get("enabled_providers") or [],
                        result.get("selected_providers") or [],
                        sum(int(item.get("count") or 0) for item in provider_results),
                        any(bool(item.get("stale")) for item in provider_results),
                    )
                tenant = self.db.get(Tenant, tenant_id)
                return OperationalAnswer(
                    format_operational_result(
                        intent.tool_name,
                        arguments,
                        result,
                        str(
                            tenant.timezone
                            if tenant and tenant.timezone
                            else "Asia/Kolkata"
                        ),
                    ),
                    intent.tool_name,
                    request.id,
                    result,
                )
            if current.status == "failed":
                if intent.tool_name == "ticketing_search_records":
                    logger.warning(
                        "ticket_tool_result tenant_id=%s connector_id=%s request_id=%s "
                        "tool=%s status=failed error_code=%s final_answer_path=tool_error",
                        tenant_id,
                        current.connector_id,
                        current.id,
                        intent.tool_name,
                        current.error_code,
                    )
                return OperationalAnswer(
                    current.error_message
                    or "The connector could not complete the operational query.",
                    intent.tool_name,
                    request.id,
                    None,
                )
            if current.status == "expired":
                return OperationalAnswer(
                    "The active connector did not answer the operational query before it expired.",
                    intent.tool_name,
                    request.id,
                    None,
                )
            await asyncio.sleep(0.25)
