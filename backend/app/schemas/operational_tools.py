"""Strict connector operational-tool RPC contracts."""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


ALLOWED_OPERATIONAL_TOOLS = {
    "get_inventory_summary",
    "count_assets",
    "search_assets",
    "get_asset_details",
    "get_asset_status",
    "get_asset_utilization",
    "get_asset_log_evidence",
    "search_tickets",
    "get_ticket",
    "get_ticket_counts",
    "get_asset_tickets",
    "correlate_tickets_with_evidence",
    "get_all_ticket_sources",
    "ticketing_search_records",
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
    "knowledge_search",
}


class OperationalToolRequestView(BaseModel):
    id: UUID
    tool_name: str
    arguments: dict[str, Any]
    expires_at: datetime
    claim_token: str


class OperationalToolResultSubmission(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claim_token: str = Field(min_length=20, max_length=512)
    status: Literal["completed", "failed"]
    result: dict[str, Any] | None = None
    error_code: str | None = Field(default=None, max_length=100)
    error_message: str | None = Field(default=None, max_length=500)
