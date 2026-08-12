from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.connector_security import hash_connector_secret
from app.db.base import Base
from app.models.connector import (
    ConnectorCapability,
    ManagedConnector,
    ManagedConnectorStatus,
    OperationalToolRequest,
)
from app.models.tenant import Tenant, TenantStatus
from app.models.tenant_user import TenantUser, TenantUserAuthSource, TenantUserRole
from app.schemas.operational_tools import OperationalToolResultSubmission
from app.services.assistant_operational import (
    build_operational_context,
    classify_assistant_intent,
    format_operational_result,
    format_reused_operational_evidence,
)
from app.services.operational_tool_service import (
    OperationalToolConflict,
    OperationalToolService,
    OperationalToolUnavailable,
)


@pytest.mark.parametrize(
    ("question", "destination", "tool"),
    [
        ("How many Linux servers do I have?", "operational", "count_assets"),
        ("How many servers?", "operational", "count_assets"),
        ("What is the total server count?", "operational", "get_inventory_summary"),
        ("What is the IP of util001?", "operational", "get_asset_details"),
        ("What is the status of util001?", "operational", "get_asset_status"),
        (
            "What is the CPU utilization of util001?",
            "operational",
            "get_asset_utilization",
        ),
        (
            "What is the resource utilization of util001?",
            "operational",
            "get_asset_utilization",
        ),
        ("Summarize the Ventana Runbook", "document", None),
        (
            "Which servers do not have Prometheus metrics?",
            "operational",
            "search_assets",
        ),
        ("Show servers", "operational", "search_assets"),
        ("List servers", "operational", "search_assets"),
        ("Which servers", "operational", "search_assets"),
        ("What servers", "operational", "search_assets"),
        ("Show inventory", "operational", "search_assets"),
        ("Display inventory", "operational", "search_assets"),
        ("Show Linux servers", "operational", "search_assets"),
        ("Which Linux servers?", "operational", "search_assets"),
        ("Show Windows servers", "operational", "search_assets"),
        ("How is util001?", "operational", "get_asset_status"),
        ("Health of util001", "operational", "get_asset_status"),
        ("Give me a health report for util001", "operational", "get_asset_status"),
        ("Which servers are monitored?", "operational", "search_assets"),
        ("Which monitored servers are unhealthy?", "operational", "search_assets"),
        ("Show errors for util001", "operational", "get_asset_log_evidence"),
        ("Authentication failures on util001", "operational", "get_asset_log_evidence"),
        ("What changed for util001?", "operational", "get_asset_status"),
    ],
)
def test_deterministic_intent_routing(question, destination, tool):
    intent = classify_assistant_intent(question)
    assert intent.destination == destination
    assert intent.tool_name == tool


@pytest.mark.parametrize(
    ("question", "tool", "expected_arguments"),
    [
        ("Show ticket 10023", "get_ticket", {"ticket_number": "10023", "view": "full"}),
        (
            "What is the status of ticket 10031?",
            "get_ticket",
            {"ticket_number": "10031", "view": "status"},
        ),
        (
            "What is the latest update on ticket 10023?",
            "get_ticket",
            {"ticket_number": "10023", "view": "latest_update"},
        ),
        (
            "Who owns ticket 10031?",
            "get_ticket",
            {"ticket_number": "10031", "view": "owner"},
        ),
        (
            "How many open tickets are there?",
            "ticketing_search_records",
            {"state": "open", "mode": "count"},
        ),
        (
            "How many tickets were updated today?",
            "ticketing_search_records",
            {"state": "all", "mode": "count"},
        ),
        (
            "Are there any active incidents?",
            "ticketing_search_records",
            {"state": "open", "mode": "count"},
        ),
        (
            "Find tickets about memory problems",
            "ticketing_search_records",
            {"state": "all", "mode": "search"},
        ),
        (
            "Show access requests",
            "ticketing_search_records",
            {"state": "all", "mode": "search"},
        ),
        (
            "What tickets are associated with util001?",
            "ticketing_search_records",
            {"identifier": "util001", "mode": "asset"},
        ),
        (
            "What happened recently on util001?",
            "ticketing_search_records",
            {"identifier": "util001", "mode": "asset"},
        ),
    ],
)
def test_zammad_intents_are_deterministic(question, tool, expected_arguments):
    intent = classify_assistant_intent(question)
    assert intent.destination == "operational"
    assert intent.tool_name == tool
    for key, value in expected_arguments.items():
        assert intent.arguments[key] == value


def test_asset_ticket_pronoun_reuses_active_operational_asset():
    intent = classify_assistant_intent(
        "Does it have any incidents?",
        operational_context={
            "tool_name": "get_asset_status",
            "arguments": {"identifier": "util001"},
            "active_asset": {"identifier": "util001"},
        },
    )
    assert intent.destination == "operational"
    assert intent.tool_name == "ticketing_search_records"
    assert intent.arguments["identifier"] == "util001"


def test_ticket_correlation_requires_and_reuses_prior_evidence():
    missing = classify_assistant_intent("Did anyone report this issue?")
    assert missing.destination == "clarification"
    assert missing.tool_name == "correlate_tickets_with_evidence"

    intent = classify_assistant_intent(
        "Did anyone report this issue?",
        operational_context={
            "evidence_snapshot": {
                "identifier": "util001",
                "timeline": [
                    {"observed_at": "2026-08-01T10:00:00Z"},
                    {"observed_at": "2026-08-01T10:05:00Z"},
                ],
                "assessment": {
                    "relevant_log_evidence": [
                        {"severity": "error", "summary": "process failed"}
                    ]
                },
            },
        },
    )
    assert intent.destination == "operational"
    assert intent.tool_name == "correlate_tickets_with_evidence"
    assert intent.arguments["identifier"] == "util001"
    assert intent.arguments["error_strings"] == ["process failed"]


def test_ticket_formatting_preserves_state_freshness_and_non_causality():
    exact = format_operational_result(
        "get_ticket",
        {"ticket_number": "10023", "view": "latest_update"},
        {
            "ticket": {
                "number": "10023",
                "state": "open",
                "title": "Memory pressure",
                "latest_update": {
                    "at": "2026-08-01T10:00:00Z",
                    "author": "Operator",
                    "text": "Heap limit increased.",
                },
            },
            "live": False,
            "cache_timestamp": "2026-08-01T10:01:00Z",
            "warning": "Zammad timed out; using cache.",
        },
    )
    assert "#10023" in exact
    assert "Heap limit increased" in exact
    assert "Cached connector data" in exact
    assert "Zammad timed out" in exact

    correlation = format_operational_result(
        "correlate_tickets_with_evidence",
        {"identifier": "util001"},
        {
            "correlations": [
                {
                    "number": "10023",
                    "title": "Memory pressure",
                    "classification": "possibly_related",
                    "score": 65,
                    "reasons": ["same asset", "overlapping time window"],
                }
            ],
            "availability": {"cache_timestamp": "2026-08-01T10:01:00Z"},
        },
    )
    assert "possibly related" in correlation
    assert "do not prove causation" in correlation


def test_health_format_keeps_ticket_evidence_distinct_from_monitoring_health():
    report = format_operational_result(
        "get_asset_status",
        {"identifier": "util001", "detail_level": "detailed"},
        {
            "match_status": "found",
            "asset": {"hostname": "util001", "reachable": True},
            "utilization": {},
            "assessment": {"overall_health": "healthy", "evidence": []},
            "related_tickets": {
                "open_tickets": [
                    {
                        "number": "10038",
                        "title": "Request sudo access",
                        "state": "open",
                        "ticket_type": "service_request",
                    }
                ],
                "recently_closed_tickets": [],
                "availability": {"cache_timestamp": "2026-08-01T10:01:00Z"},
            },
        },
    )
    assert "### Related tickets" in report
    assert "Service Request" in report
    assert "do not change the monitoring-derived health assessment" in report


def test_ticket_search_is_concise_explainable_linked_and_timezone_aware():
    answer = format_operational_result(
        "search_tickets",
        {"query": "memory-related tickets", "limit": 5},
        {
            "count": 1,
            "requested_limit": 5,
            "concept_family": "memory",
            "tickets": [
                {
                    "number": "11007",
                    "external_id": "126",
                    "title": "util001 memory pressure",
                    "state": "closed",
                    "ticket_type": "incident",
                    "updated_at": "2026-07-31T19:23:00.073000+00:00",
                    "summary": "Host memory exceeded 94% during indexing.",
                    "latest_update": "A full article body that should not be rendered.",
                    "web_url": "http://zammad.example.test/#ticket/zoom/126",
                    "relevance": {
                        "score": 0.98,
                        "confidence": "high",
                        "match_reasons": [
                            "Exact title match: memory pressure",
                            "Article body contains: memory utilization",
                        ],
                    },
                }
            ],
        },
        "Asia/Kolkata",
    )
    assert "[\\#11007" not in answer
    assert (
        "[#11007 — util001 memory pressure](<http://zammad.example.test/#ticket/zoom/126>)"
        in answer
    )
    assert "1 Aug 2026, 12:53 AM IST" in answer
    assert "score 0.98" in answer
    assert "Host memory exceeded 94%" in answer
    assert "full article body" not in answer.casefold()


def test_ticket_search_no_result_and_requested_limit_messages_are_explicit():
    no_access = format_operational_result(
        "search_tickets",
        {"query": "user asking for access", "limit": 5},
        {
            "count": 0,
            "requested_limit": 5,
            "concept_family": "access_request",
            "tickets": [],
        },
    )
    assert no_access == (
        "## Matching current provider tickets\n\nFound 0 clearly matching tickets.\n\n"
        "No tickets clearly related to user access requests were found.\n\n"
        "- **Freshness:** Cached connector data from an unknown time."
    )
    fewer = format_operational_result(
        "search_tickets",
        {"query": "", "state": "open", "limit": 5},
        {"count": 3, "requested_limit": 5, "tickets": []},
    )
    assert "There are only 3 open tickets, so all 3 are shown." in fewer

    provider_label = format_operational_result(
        "search_tickets",
        {"query": "memory", "limit": 5},
        {
            "count": 0,
            "requested_limit": 5,
            "tickets": [],
            "ticketing_provider": {
                "display_name": "ServiceNow",
                "integration_type": "servicenow",
            },
        },
    )
    assert provider_label.startswith("## Matching ServiceNow tickets")


def test_asset_ticket_output_groups_direct_and_indirect_relationships():
    answer = format_operational_result(
        "get_asset_tickets",
        {"identifier": "lin001"},
        {
            "match_status": "found",
            "direct_tickets": [
                {
                    "number": "11002",
                    "title": "lin001 high CPU",
                    "state": "closed",
                    "ticket_type": "incident",
                    "updated_at": "2026-08-01T00:00:00Z",
                    "summary": "CPU incident.",
                    "web_url": "https://zammad.example.test/#ticket/zoom/121",
                    "relationship": "primary_affected_asset",
                }
            ],
            "indirect_tickets": [
                {
                    "number": "11009",
                    "title": "Loki delay affected lin001 logs",
                    "state": "closed",
                    "ticket_type": "incident",
                    "updated_at": "2026-08-01T00:00:00Z",
                    "summary": "Telemetry delay.",
                    "web_url": "https://zammad.example.test/#ticket/zoom/129",
                    "relationship": "monitoring_relationship",
                }
            ],
            "availability": {},
        },
    )
    assert "### Directly related" in answer
    assert "### Indirectly related" in answer
    assert answer.index("#11002") < answer.index("### Indirectly related")
    assert answer.index("#11009") > answer.index("### Indirectly related")


def test_default_health_is_concise_and_detailed_health_remains_available():
    raw_loki = (
        "server returned HTTP status 400: entry for stream has timestamp too new: "
        "2026-08-01T14:02:34Z"
    )
    context = {
        "tool_name": "get_asset_status",
        "arguments": {"identifier": "lin001"},
        "active_asset": {"identifier": "lin001"},
    }
    detailed = classify_assistant_intent(
        "Show the detailed health evidence for lin001", context
    )
    assert detailed.tool_name == "get_asset_status"
    assert detailed.arguments["detail_level"] == "detailed"

    concise = format_operational_result(
        "get_asset_status",
        {"identifier": "lin001"},
        {
            "match_status": "found",
            "asset": {
                "hostname": "lin001",
                "reachable": True,
                "prometheus_health": "healthy",
            },
            "utilization": {
                "cpu_percent": 2.13,
                "memory_percent": 17.18,
                "disk_percent": 49.25,
            },
            "assessment": {
                "overall_health": "healthy",
                "relevant_log_evidence": [
                    {
                        "summary": raw_loki,
                        "impact_classification": "monitoring_pipeline_issue",
                    }
                ],
                "conclusion": "Current metrics remain normal.",
            },
            "related_tickets": {"direct_tickets": [], "indirect_tickets": []},
        },
    )
    assert "lin001 is healthy" in concise
    assert "### Current state" in concise
    assert "One Loki timestamp synchronization anomaly was detected." in concise
    assert raw_loki not in concise
    assert "### Filesystems" not in concise
    assert "### Top CPU processes" not in concise

    detailed_answer = format_operational_result(
        "get_asset_status",
        {"identifier": "lin001", "detail_level": "detailed"},
        {
            "match_status": "found",
            "detail_level": "detailed",
            "asset": {
                "hostname": "lin001",
                "reachable": True,
                "prometheus_health": "healthy",
            },
            "utilization": {
                "cpu_percent": 2.13,
                "memory_percent": 17.18,
                "disk_percent": 49.25,
            },
            "assessment": {
                "overall_health": "healthy",
                "evidence": ["Current metrics remain normal."],
            },
            "log_evidence": {
                "available": True,
                "lookback_hours": 24,
                "counts_by_category": {"errors": 1},
                "evidence": [
                    {
                        "source": "loki",
                        "category": "errors",
                        "severity": "error",
                        "observed_at": "2026-08-01T14:02:35Z",
                        "summary": raw_loki,
                    }
                ],
            },
            "related_tickets": {"direct_tickets": [], "indirect_tickets": []},
        },
    )
    assert raw_loki in detailed_answer


def test_ticket_link_escapes_title_injection_and_missing_url_degrades_to_text():
    answer = format_operational_result(
        "get_ticket",
        {"ticket_number": "11004", "view": "status"},
        {
            "ticket": {
                "number": "11004",
                "title": "[unsafe](https://evil.example)",
                "state": "open",
                "web_url": None,
            }
        },
    )
    assert "https://evil.example" in answer
    assert "\\[unsafe\\](https://evil.example)" in answer
    assert "## Ticket **#11004" in answer


def test_ambiguous_reference_requests_clarification():
    intent = classify_assistant_intent(
        "What is the resource utilization of this server?"
    )
    assert intent.destination == "clarification"
    assert "hostname or FQDN" in (intent.clarification or "")


def test_factual_formatting_handles_not_found_ambiguity_and_missing_metrics():
    assert (
        format_operational_result(
            "get_asset_details",
            {"identifier": "util001"},
            {"match_status": "not_found"},
        )
        == "I could not find a server named util001 in the current tenant inventory."
    )
    ambiguous = format_operational_result(
        "get_asset_details",
        {"identifier": "util001"},
        {
            "match_status": "ambiguous",
            "candidates": [{"fqdn": "util001.a.test"}, {"fqdn": "util001.b.test"}],
        },
    )
    assert "util001.a.test" in ambiguous and "Please specify" in ambiguous
    unavailable = format_operational_result(
        "get_asset_utilization",
        {"identifier": "util001"},
        {
            "match_status": "found",
            "utilization": {
                "asset": "util001",
                "cpu_percent": 0.0,
                "memory_percent": None,
                "disk_percent": None,
                "metric_timestamp": "2026-01-01T00:00:00Z",
            },
        },
    )
    assert "**CPU:** 0.00%" in unavailable
    assert "**Memory:** Unavailable" in unavailable


def test_operational_followup_reuses_previous_count_filters():
    context = {
        "tool_name": "count_assets",
        "arguments": {"os_family": "linux"},
    }
    for question in (
        "What are those servers?",
        "What are those 8 servers?",
        "Which ones?",
    ):
        intent = classify_assistant_intent(question, context)
        assert intent.destination == "operational"
        assert intent.tool_name == "search_assets"
        assert intent.arguments == {
            "os_family": "linux",
            "environment": None,
            "missing_prometheus": None,
            "prometheus_health": None,
            "limit": 50,
        }


def test_prometheus_correlation_search_filters_are_deterministic():
    monitored = classify_assistant_intent("Which servers are monitored?")
    assert monitored.arguments == {
        "missing_prometheus": False,
        "prometheus_health": None,
        "limit": 50,
    }
    unhealthy = classify_assistant_intent("Which monitored servers are unhealthy?")
    assert unhealthy.arguments == {
        "missing_prometheus": False,
        "prometheus_health": "unhealthy",
        "limit": 50,
    }


def test_log_evidence_routing_uses_allowlisted_categories_and_windows():
    errors = classify_assistant_intent("Show errors for util001 in the last 7 days")
    assert errors.arguments == {
        "identifier": "util001",
        "category": "errors",
        "lookback_hours": 168,
    }
    oom = classify_assistant_intent("Was there an OOM on util001 in the last month?")
    assert oom.arguments == {
        "identifier": "util001",
        "category": "oom",
        "lookback_hours": 720,
    }


@pytest.mark.parametrize(
    ("question", "family", "tool", "mode"),
    [
        ("Is util001 healthy?", "health", "get_asset_status", "health"),
        ("Check util001", "health", "get_asset_status", "health"),
        ("Analyse util001", "health", "get_asset_status", "health"),
        (
            "Is there anything wrong with util001?",
            "health",
            "get_asset_status",
            "health",
        ),
        ("Why is util001 slow?", "performance", "get_asset_status", "performance"),
        ("util001 performance", "performance", "get_asset_status", "performance"),
        ("util001 is overloaded", "performance", "get_asset_status", "performance"),
        ("Investigate util001", "health", "get_asset_status", "health"),
    ],
)
def test_operational_intent_families(question, family, tool, mode):
    intent = classify_assistant_intent(question)
    assert intent.destination == "operational"
    assert intent.intent_family == family
    assert intent.tool_name == tool
    assert intent.arguments == {"identifier": "util001", "mode": mode}


@pytest.mark.parametrize(
    ("question", "category"),
    [
        ("Any errors?", "errors"),
        ("Show errors", "errors"),
        ("Recent errors", "errors"),
        ("Warnings", "warnings"),
        ("Recent crashes", "crashes"),
        ("Exceptions", "exceptions"),
        ("Authentication failures", "auth_failures"),
    ],
)
def test_missing_asset_preserves_pending_log_intent(question, category):
    clarification = classify_assistant_intent(question)
    assert clarification.destination == "clarification"
    assert clarification.tool_name == "get_asset_log_evidence"
    assert clarification.arguments == {"category": category, "lookback_hours": 24}
    assert clarification.intent_family == (
        "warnings" if category == "warnings" else "errors"
    )

    followup = classify_assistant_intent(
        "util001",
        {
            "tool_name": clarification.tool_name,
            "arguments": clarification.arguments,
            "pending": True,
            "intent_family": clarification.intent_family,
        },
    )
    assert followup.destination == "operational"
    assert followup.tool_name == "get_asset_log_evidence"
    assert followup.arguments == {
        "category": category,
        "lookback_hours": 24,
        "identifier": "util001",
    }


def test_operational_evidence_has_priority_over_document_routing():
    operational = classify_assistant_intent(
        "How is util001 according to the operations runbook?"
    )
    assert operational.destination == "operational"
    assert operational.tool_name == "get_asset_status"

    document = classify_assistant_intent("Summarize the operations runbook")
    assert document.destination == "document"


@pytest.mark.parametrize(
    ("question", "family", "tool", "mode_or_category"),
    [
        ("Is something wrong with util001?", "health", "get_asset_status", "health"),
        ("Does util001 look OK?", "health", "get_asset_status", "health"),
        ("How is util001 doing?", "health", "get_asset_status", "health"),
        ("Everything OK on util001?", "health", "get_asset_status", "health"),
        ("util001 feels slow.", "performance", "get_asset_status", "performance"),
        ("util001 sluggish.", "performance", "get_asset_status", "performance"),
        (
            "Server util001 is lagging.",
            "performance",
            "get_asset_status",
            "performance",
        ),
        ("Did anything fail recently?", "errors", "get_asset_log_evidence", "errors"),
        ("Anything failing?", "errors", "get_asset_log_evidence", "errors"),
        ("What broke?", "errors", "get_asset_log_evidence", "errors"),
        ("Anything concerning?", "warnings", "get_asset_log_evidence", "warnings"),
        ("What happened on util001?", "timeline", "get_asset_status", "timeline"),
        (
            "Has anything changed on util001?",
            "timeline",
            "get_asset_status",
            "timeline",
        ),
        ("Show the timeline for util001", "timeline", "get_asset_status", "timeline"),
    ],
)
def test_milestone_36_natural_language_families(
    question, family, tool, mode_or_category
):
    intent = classify_assistant_intent(question)
    assert intent.intent_family == family
    assert intent.tool_name == tool
    assert intent.arguments
    key = "mode" if tool == "get_asset_status" else "category"
    assert intent.arguments[key] == mode_or_category


@pytest.mark.parametrize(
    ("question", "identifier"),
    [
        ("Check server util001", "util001"),
        ("Check host util001.demo.internal", "util001.demo.internal"),
        ("Check the util001 server", "util001"),
        ("Check 172.16.165.12", "172.16.165.12"),
    ],
)
def test_tolerant_asset_recognition(question, identifier):
    intent = classify_assistant_intent(question)
    assert intent.destination == "operational"
    assert intent.arguments == {"identifier": identifier, "mode": "health"}


def test_active_asset_resolves_references_and_implicit_followups():
    context = {
        "active_identifier": "util001.demo.internal",
        "arguments": {"identifier": "util001.demo.internal", "mode": "health"},
    }
    for question, family in (
        ("Check that server.", "health"),
        ("Is it healthy?", "health"),
        ("Anything unusual?", "health"),
        ("CPU seems high.", "performance"),
    ):
        intent = classify_assistant_intent(question, context)
        assert intent.destination == "operational"
        assert intent.intent_family == family
        assert intent.arguments["identifier"] == "util001.demo.internal"

    logs = classify_assistant_intent("Show me the logs.", context)
    assert logs.tool_name == "get_asset_log_evidence"
    assert logs.arguments["identifier"] == "util001.demo.internal"


def test_followups_without_retained_evidence_never_fall_back_to_rag():
    context = {"active_identifier": "util001.demo.internal"}
    current = classify_assistant_intent("Is this still happening?", context)
    assert current.destination == "operational"
    assert current.arguments == {
        "identifier": "util001.demo.internal",
        "mode": "health",
    }

    why = classify_assistant_intent("Why?", context)
    assert why.destination == "contextual"
    answer = format_reused_operational_evidence(
        why.arguments["action"], why.evidence_context
    )
    assert "No deterministic conclusion was retained" in answer

    ambiguous = classify_assistant_intent("Is this still happening?")
    assert ambiguous.destination == "clarification"
    assert "No previous operational evidence" in ambiguous.clarification


def test_explanatory_followups_reuse_bounded_evidence_without_connector_tool():
    result = {
        "asset": {"fqdn": "util001.demo.internal"},
        "utilization": {
            "cpu_percent": 12.0,
            "memory_percent": 60.0,
            "metric_timestamp": "2026-07-30T12:00:00Z",
        },
        "assessment": {
            "overall_health": "healthy",
            "conclusion": "Current metrics are within thresholds.",
            "evidence": ["No relevant Loki events were found."],
            "relevant_log_evidence": [],
            "unrelated_log_evidence": [],
        },
        "log_evidence": {
            "available": True,
            "lookback_hours": 24,
            "evidence": [],
            "counts_by_category": {},
        },
        "timeline": [
            {
                "source": "prometheus",
                "category": "metrics_observation",
                "observed_at": "2026-07-30T12:00:00Z",
                "summary": "Prometheus utilization metrics observed.",
            }
        ],
    }
    original = classify_assistant_intent("How is util001?")
    context = build_operational_context(original, result)
    assert context
    assert context["active_identifier"] == "util001.demo.internal"
    assert "evidence_snapshot" in context

    why = classify_assistant_intent("Why?", context)
    assert why.destination == "contextual"
    assert why.tool_name == "reuse_operational_evidence"
    explanation = format_reused_operational_evidence(
        why.arguments["action"], why.evidence_context
    )
    assert "Current metrics are within thresholds." in explanation

    current = classify_assistant_intent("Is this still happening?", context)
    assert current.destination == "contextual"
    answer = format_reused_operational_evidence(
        current.arguments["action"], current.evidence_context
    )
    assert "2026-07-30T12:00:00Z" in answer
    assert "without a fresh health check" in answer


def test_timeline_format_explains_sequence_and_missing_evidence_explicitly():
    report = format_operational_result(
        "get_asset_status",
        {"identifier": "util001", "mode": "timeline"},
        {
            "asset": {"fqdn": "util001.demo.internal", "reachable": True},
            "utilization": {"metric_timestamp": "2026-07-30T13:10:00Z"},
            "log_evidence": {"available": True, "evidence": []},
            "assessment": {
                "overall_health": "healthy",
                "mode": "timeline",
                "conclusion": (
                    "No relevant Loki events were found; the latest Prometheus "
                    "observation is the only time-stamped evidence."
                ),
                "relevant_log_evidence": [],
                "unrelated_log_evidence": [],
                "evidence": [],
            },
            "timeline": [
                {
                    "source": "prometheus",
                    "category": "metrics_observation",
                    "observed_at": "2026-07-30T13:10:00Z",
                    "summary": "Prometheus utilization metrics observed.",
                }
            ],
        },
    )
    assert "## Operational timeline" in report
    assert "### Operational sequence" in report
    assert "Prometheus / metrics observation" in report
    assert "No relevant Loki events were found" in report


def test_health_report_format_contains_evidence_and_all_required_sections():
    report = format_operational_result(
        "get_asset_status",
        {"identifier": "util001", "detail_level": "detailed"},
        {
            "match_status": "found",
            "asset": {
                "hostname": "util001",
                "fqdn": "util001.example.test",
                "primary_ip": "10.0.0.1",
                "operating_system": "Linux",
                "reachable": True,
                "prometheus_health": "healthy",
                "last_observed_at": "2026-07-30T00:00:00Z",
            },
            "utilization": {
                "cpu_percent": 91.0,
                "load_average_1m": 1.2,
                "memory_percent": 65.0,
                "disk_percent": 82.0,
                "metric_timestamp": "2026-07-30T00:00:00Z",
                "filesystems": [{"mountpoint": "/", "used_percent": 82.0}],
                "top_cpu_processes": [{"name": "java", "cpu_percent": 45.0}],
                "top_memory_processes": [{"name": "java", "memory_bytes": 104857600}],
            },
            "assessment": {
                "overall_health": "critical",
                "evidence": ["CPU utilization is 91.00% (critical ≥ 90%)."],
                "recommendations": ["Inspect the top CPU process."],
            },
            "log_evidence": {
                "available": True,
                "lookback_hours": 24,
                "matched_streams": [{"labels": {"host": "util001"}}],
                "last_log_at": "2026-07-30T00:01:00Z",
                "counts_by_category": {"errors": 1},
                "evidence": [
                    {
                        "source": "loki",
                        "category": "errors",
                        "severity": "error",
                        "observed_at": "2026-07-30T00:01:00Z",
                        "summary": "service failed",
                    }
                ],
            },
            "timeline": [
                {
                    "source": "loki",
                    "category": "errors",
                    "observed_at": "2026-07-30T00:01:00Z",
                    "summary": "service failed",
                }
            ],
        },
    )

    for heading in (
        "### Inventory",
        "### Prometheus",
        "### Utilisation",
        "### Filesystems",
        "### Top CPU processes",
        "### Top memory processes",
        "### Assessment",
        "### Loki findings",
        "### Evidence timeline",
        "### Recommendations",
    ):
        assert heading in report
    assert "**Overall health:** critical" in report
    assert "CPU utilization is 91.00%" in report
    assert "Loki / errors:** service failed" in report


@pytest.fixture()
def rpc():
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, expire_on_commit=False)()
    tenant = Tenant(
        slug="tools",
        name="Tools",
        display_name="Tools",
        status=TenantStatus.ACTIVE,
        timezone="UTC",
    )
    other = Tenant(
        slug="other-tools",
        name="Other Tools",
        display_name="Other Tools",
        status=TenantStatus.ACTIVE,
        timezone="UTC",
    )
    db.add_all([tenant, other])
    db.flush()
    user = TenantUser(
        tenant_id=tenant.id,
        username="operator",
        email="operator@tools.test",
        full_name="Operator",
        auth_source=TenantUserAuthSource.LOCAL,
        password_hash="unused",
        is_active=True,
        role=TenantUserRole.TENANT_USER,
    )
    connector = ManagedConnector(
        tenant_id=tenant.id,
        name="Tools connector",
        instance_id=uuid4(),
        version="1.0",
        environment="test",
        status=ManagedConnectorStatus.CONNECTED,
        secret_hash=hash_connector_secret("connector-secret"),
        registered_at=datetime.now(UTC),
        last_seen_at=datetime.now(UTC),
        heartbeat_interval_seconds=300,
    )
    other_connector = ManagedConnector(
        tenant_id=other.id,
        name="Other connector",
        instance_id=uuid4(),
        version="1.0",
        environment="test",
        status=ManagedConnectorStatus.CONNECTED,
        secret_hash=hash_connector_secret("other-secret"),
        registered_at=datetime.now(UTC),
        last_seen_at=datetime.now(UTC),
        heartbeat_interval_seconds=300,
    )
    db.add_all([user, connector, other_connector])
    db.flush()
    now = datetime.now(UTC)
    db.add_all(
        [
            ConnectorCapability(
                connector_id=connector.id,
                tenant_id=tenant.id,
                name="operational_tools",
                last_reported_at=now,
            ),
            ConnectorCapability(
                connector_id=other_connector.id,
                tenant_id=other.id,
                name="operational_tools",
                last_reported_at=now,
            ),
        ]
    )
    db.commit()
    yield db, tenant, other, user, connector, other_connector
    db.close()
    engine.dispose()


def test_rpc_is_tenant_scoped_claimed_once_and_replay_safe(rpc):
    db, tenant, other, user, connector, other_connector = rpc
    service = OperationalToolService(db)
    request = service.create(
        tenant.id, user.id, "search_tickets", {"query": "memory", "limit": 20}
    )

    assert service.claim(other_connector) is None
    claim = service.claim(connector)
    assert claim is not None
    service.submit(
        connector,
        request.id,
        OperationalToolResultSubmission(
            claim_token=claim.claim_token,
            status="completed",
            result={"count": 1, "tickets": [{"number": "10023"}]},
        ),
    )
    assert service.result(tenant.id, request.id).result["count"] == 1
    with pytest.raises(OperationalToolUnavailable):
        service.result(other.id, request.id)
    with pytest.raises(OperationalToolConflict):
        service.submit(
            connector,
            request.id,
            OperationalToolResultSubmission(
                claim_token=claim.claim_token,
                status="completed",
                result={"count": 99},
            ),
        )
    assert db.get(OperationalToolRequest, request.id).attempt_count == 1


def test_connector_without_operational_tool_capability_is_unavailable(rpc):
    db, tenant, _, user, connector, _ = rpc
    capability = (
        db.query(ConnectorCapability)
        .filter_by(
            connector_id=connector.id,
            name="operational_tools",
        )
        .one()
    )
    db.delete(capability)
    db.commit()

    with pytest.raises(
        OperationalToolUnavailable,
        match="No active connector",
    ):
        OperationalToolService(db).create(
            tenant.id,
            user.id,
            "count_assets",
            {},
        )
