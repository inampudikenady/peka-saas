from app.schemas.operational_tools import ALLOWED_OPERATIONAL_TOOLS
from app.services.assistant_operational import (
    classify_assistant_intent,
    format_operational_result,
)


def test_servicenow_tools_are_explicitly_allow_listed() -> None:
    expected = {
        "servicenow_get_status",
        "servicenow_get_incident",
        "servicenow_search_incidents",
        "servicenow_list_open_incidents",
        "servicenow_get_incident_updates",
        "servicenow_get_ci",
        "servicenow_get_ci_relationships",
        "servicenow_get_ci_tickets",
        "servicenow_search_problems",
        "servicenow_search_changes",
        "get_all_ticket_sources",
        "ticketing_search_records",
    }
    assert expected <= ALLOWED_OPERATIONAL_TOOLS
    assert "servicenow_query_table" not in ALLOWED_OPERATIONAL_TOOLS
    assert "servicenow_rest_request" not in ALLOWED_OPERATIONAL_TOOLS


def test_servicenow_incident_and_relationship_intents_are_deterministic() -> None:
    update = classify_assistant_intent("What is the latest update on INC0010001?")
    assert update.tool_name == "servicenow_get_incident_updates"
    assert update.arguments == {"number": "INC0010001"}

    incidents = classify_assistant_intent("Show open ServiceNow incidents for util001")
    assert incidents.tool_name == "servicenow_list_open_incidents"
    assert incidents.arguments["identifier"] == "util001"

    problems = classify_assistant_intent("Show ServiceNow problems related to util001")
    assert problems.tool_name == "servicenow_search_problems"
    assert problems.arguments["identifier"] == "util001"

    source_implicit_incidents = classify_assistant_intent(
        "How many open incidents are there?"
    )
    assert source_implicit_incidents.tool_name == "servicenow_list_open_incidents"

    source_implicit_changes = classify_assistant_intent(
        "What changes were made to util001?"
    )
    assert source_implicit_changes.tool_name == "servicenow_search_changes"
    assert source_implicit_changes.arguments["identifier"] == "util001"

    relationships = classify_assistant_intent("What runs on util001?")
    assert relationships.tool_name == "servicenow_get_ci_relationships"
    assert relationships.arguments == {"identifier": "util001", "max_depth": 3}

    all_sources = classify_assistant_intent("Show all ticket sources related to win001")
    assert all_sources.tool_name == "get_all_ticket_sources"
    assert all_sources.arguments == {"identifier": "win001"}


def test_servicenow_formatting_preserves_source_and_stale_warning() -> None:
    answer = format_operational_result(
        "servicenow_search_incidents",
        {"query": "memory", "limit": 25},
        {
            "source": "servicenow",
            "record_type": "incident",
            "count": 1,
            "records": [
                {
                    "number": "INC0010001",
                    "short_description": "Memory pressure on util001",
                    "state": "In Progress",
                    "assigned_to": "Alice",
                }
            ],
            "availability": {
                "enabled": True,
                "stale": True,
                "cache_timestamp": "2026-08-04T10:00:00Z",
            },
        },
        "UTC",
    )
    assert "ServiceNow Incident results" in answer
    assert "INC0010001" in answer
    assert "stale" in answer
    assert "Zammad" not in answer


def test_multi_source_formatting_keeps_sources_and_counts_distinct() -> None:
    answer = format_operational_result(
        "get_all_ticket_sources",
        {"identifier": "win001"},
        {
            "sources": {
                "servicenow": {
                    "records": [
                        {"number": "INC0010001", "short_description": "Windows outage"}
                    ],
                    "availability": {"stale": False},
                },
                "zammad": {
                    "direct_tickets": [
                        {"number": "11012", "title": "Host unavailable"}
                    ],
                    "availability": {"stale": False},
                },
            }
        },
        "UTC",
    )
    assert "ServiceNow:** 1 records" in answer
    assert "Zammad:** 1 tickets" in answer
    assert "Combined:** 2 records" in answer
    assert "ServiceNow INC0010001" in answer
    assert "Zammad ticket #11012" in answer


def test_generic_ticket_routing_discovers_providers_but_explicit_routing_is_scoped() -> (
    None
):
    generic = classify_assistant_intent("What are my open tickets?")
    assert generic.tool_name == "ticketing_search_records"
    assert generic.arguments["providers"] == []
    assert generic.arguments["state"] == "open"
    assert generic.arguments["query"] == ""

    ci_specific = classify_assistant_intent("Show open tickets for util001")
    assert ci_specific.tool_name == "ticketing_search_records"
    assert ci_specific.arguments["identifier"] == "util001"

    zammad = classify_assistant_intent("Show Zammad tickets for util001")
    assert zammad.tool_name == "ticketing_search_records"
    assert zammad.arguments["providers"] == ["zammad"]

    servicenow = classify_assistant_intent(
        "How many open ServiceNow incidents are there?"
    )
    assert servicenow.tool_name == "servicenow_list_open_incidents"


def test_normalized_ticket_formatting_handles_provider_states_and_legacy_keys() -> None:
    service_only = format_operational_result(
        "ticketing_search_records",
        {"mode": "search", "state": "open"},
        {
            "configured_providers": ["zammad", "servicenow"],
            "enabled_providers": ["servicenow"],
            "selected_providers": ["servicenow"],
            "providers": [
                {
                    "source": "servicenow",
                    "record_type": "incident",
                    "status": "ok",
                    "enabled": True,
                    "stale": False,
                    "incidents": [
                        {
                            "external_id": "INC0010001",
                            "title": "Exporter unavailable",
                            "state": "In Progress",
                        }
                    ],
                }
            ],
        },
        "UTC",
    )
    assert "ServiceNow:** 1 incidents" in service_only
    assert "ServiceNow INC0010001" in service_only
    assert "No active ticketing provider" not in service_only
    assert "Zammad" not in service_only

    combined = format_operational_result(
        "ticketing_search_records",
        {"mode": "count", "state": "open"},
        {
            "enabled_providers": ["zammad", "servicenow"],
            "providers": [
                {"source": "servicenow", "status": "ok", "count": 4, "records": []},
                {"source": "zammad", "status": "ok", "count": 3, "records": []},
            ],
        },
        "UTC",
    )
    assert "ServiceNow:** 4 incidents" in combined
    assert "Zammad:** 3 tickets" in combined
    assert "Combined:** 7 records" in combined

    disabled = format_operational_result(
        "ticketing_search_records",
        {"mode": "search", "state": "open"},
        {
            "configured_providers": ["zammad", "servicenow"],
            "enabled_providers": [],
            "providers": [],
        },
        "UTC",
    )
    assert disabled == "No active ticketing provider is configured."

    limited = format_operational_result(
        "ticketing_search_records",
        {"mode": "search", "state": "open", "limit": 5},
        {
            "enabled_providers": ["servicenow"],
            "providers": [
                {
                    "source": "servicenow",
                    "status": "ok",
                    "count": 8,
                    "records": [
                        {
                            "external_id": f"INC{index:07d}",
                            "title": f"Incident {index}",
                            "state": "Open",
                        }
                        for index in range(1, 6)
                    ],
                }
            ],
        },
        "UTC",
    )
    assert "Showing 5 of 8 matching records." in limited
    assert "show all matching tickets" in limited

    stale = format_operational_result(
        "ticketing_search_records",
        {"mode": "search", "state": "open"},
        {
            "enabled_providers": ["servicenow"],
            "providers": [
                {
                    "source": "servicenow",
                    "status": "ok",
                    "count": 0,
                    "records": [],
                    "stale": True,
                    "last_synced_at": "2026-08-05T00:30:00Z",
                }
            ],
        },
        "UTC",
    )
    assert "cache is stale" in stale
