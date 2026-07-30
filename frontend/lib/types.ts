export type PlatformTokenResponse = { access_token: string; token_type: string };
export type PlatformRole = "platform_admin" | "platform_readonly";
export type PlatformUser = { id: string; username: string; email: string; full_name: string; role: PlatformRole; is_active: boolean; last_login_at: string | null; created_at: string; updated_at: string };
export type PlatformUserInput = { username: string; email: string; full_name: string; role: PlatformRole };
export type PlatformInvitation = { user: PlatformUser; setup_link: string; expires_at: string };
export type TenantStatus = "active" | "suspended" | "retired";
export type Tenant = {
  id: string; slug: string; name: string; display_name: string;
  status: TenantStatus; primary_domain: string | null; subdomain: string | null;
  tenant_url: string | null; timezone: string; created_at: string; updated_at: string;
};
export type TenantCreate = {
  slug: string; display_name: string; name?: string;
  timezone: string; initial_admin_email: string; initial_admin_full_name: string;
};
export type TenantCreateResponse = { tenant: Tenant; admin_setup_link: string };
export type TenantAdminInvite = {
  email: string; full_name: string; expires_at: string; used_at: string | null;
  status: "pending" | "used" | "expired"; setup_link: string | null;
};
export type TenantPlatformSummary = {
  sso_enabled: boolean; sso_redirect_uri: string | null;
  local_admin_active: boolean; active_user_count: number;
  administrator_count: number; connector_count: number;
};
export type TenantAdministrator = {id:string;email:string;full_name:string;username:string|null;is_active:boolean;last_login_at:string|null;auth_source:"local"|"sso"};
export type DevelopmentEmail = {id:string;tenant_id:string;tenant_slug:string;tenant_name:string;recipient:string;subject:string;body_text:string;action_url:string;delivery_state:string;created_at:string};
export type TenantAuditEvent = {id:string;tenant_id:string|null;tenant_slug:string;tenant_display_name:string;actor_username:string;action:string;changes:Record<string,{old:unknown;new:unknown}>;request_id:string|null;created_at:string};
export type TenantMe = {
  id: string; email: string; full_name: string; auth_source: "local" | "sso"; tenant_id: string;
  tenant_slug: string; tenant_name: string; tenant_timezone: string;
  role: "tenant_admin" | "tenant_user";
  username: string | null; is_active: boolean; last_login_at: string | null;
};
export type TenantUser = { id: string; tenant_id: string; username: string | null; email: string; full_name: string; auth_source: "local" | "sso"; role: "tenant_admin" | "tenant_user"; is_active: boolean; last_login_at: string | null };
export type TenantUserInvitation = { user: TenantUser; setup_link: string; expires_at: string };
export type PlatformSettings = { platform_name:string;environment:string;default_timezone:string;application_version:string;support_contact:string|null;platform_base_url:string;tenant_base_url:string;url_mode:string;public_frontend_url:string;api_base_path:string };
export type SSOProvider = "microsoft_entra" | "generic_oidc";
export type TenantSSOConfig = {
  provider: SSOProvider; entra_tenant_id: string | null;
  issuer_url: string | null; client_id: string | null;
  client_secret_configured: boolean; redirect_uri: string | null; enabled: boolean;
};
export type TenantSSOUpdate = {
  provider: SSOProvider; entra_tenant_id?: string | null;
  issuer_url?: string | null; client_id: string;
  client_secret?: string | null; enabled: boolean;
};
export type TenantSSOLoginOptions = {provider:SSOProvider|null;enabled:boolean};
export type TenantSSOTest = {success:boolean;issuer_url:string;authorization_endpoint:string;token_endpoint:string;jwks_uri:string;message:string};
export type ConnectorStatus = "connected" | "in_sync" | "degraded" | "out_of_sync" | "disconnected" | "authentication_failed" | "retired";
export type ManagedConnector = {
  id: string; tenant_id: string; tenant_name: string | null; tenant_slug: string | null;
  tenant_timezone: string | null;
  name: string; instance_id: string; version: string; environment: string; status: ConnectorStatus;
  registered_at: string; last_heartbeat_at: string | null; last_seen_at: string | null;
  heartbeat_interval_seconds: number; source_total: number; source_healthy: number;
  source_unhealthy: number; source_disabled: number; retired_at: string | null;
  created_at: string; updated_at: string;
};
export type ConnectorHeartbeat = {
  received_at: string; reported_at: string; version: string; reported_status: string; uptime_seconds: number;
  source_total: number; source_healthy: number; source_unhealthy: number; source_disabled: number; accepted: boolean;
};
export type ConnectorEvent = { event_type: string; occurred_at: string; detail: string | null };
export type ConnectorDetail = ManagedConnector & { capabilities: string[]; recent_heartbeats: ConnectorHeartbeat[]; recent_events: ConnectorEvent[] };
export type RegistrationToken = {
  id: string; tenant_id: string; expires_at: string; used_at: string | null; created_by_user_id: string | null;
  created_at: string; revoked_at: string | null; intended_connector_name: string | null; status: "active" | "used" | "expired" | "revoked";
};
export type RegistrationTokenCreated = RegistrationToken & { registration_token: string };
export type DocumentVersion = { id:string;content_hash:string;size_bytes:number;ingestion_status:string;storage_status:string;parser_name:string|null;detected_format:string|null;source_format:string|null;format_detection_confidence:number|null;format_detection_reason:string|null;chunker_name:string|null;embedding_provider:string|null;embedding_model:string|null;received_at:string;stored_at:string|null;queued_at:string|null;parsing_started_at:string|null;parsed_at:string|null;chunking_started_at:string|null;chunked_at:string|null;embedding_started_at:string|null;embedding_completed_at:string|null;indexing_started_at:string|null;indexing_completed_at:string|null;indexed_at:string|null;error_code:string|null;error_message:string|null };
export type IngestionHealth = {runtime_mode:string;worker_status:string;last_heartbeat_at:string|null;runtime_started_at:string|null;current_job_id:string|null;queued_job_count:number;processing_job_count:number;failed_job_count:number;latest_job_claimed_at:string|null;latest_successful_job_at:string|null;latest_safe_error:string|null;embedding_status:string;qdrant_status:string;remediation:string|null};
export type DocumentDeletionState = {delete_eligible:boolean;delete_unavailable_reason:string|null;deletion_in_progress:boolean};
export type ManagedDocument = DocumentDeletionState & { id:string;connector_id:string|null;created_by_connector_id:string|null;last_seen_by_connector_id:string|null;last_synchronized_at:string|null;source_freshness:"current"|"stale"|"historical";source_connector_name:string|null;source_connector_status:string;source_id:string;document_key:string;filename:string;extension:string;relative_path:string;mime_type:string;is_deleted:boolean;current_version:DocumentVersion|null;versions:DocumentVersion[];chunk_count:number;embedding_status:string;indexed:boolean;searchable:boolean;processing_status:string;blocking_reason:string|null;worker_status:string;created_at:string;updated_at:string };
export type ManagedDocumentListItem = DocumentDeletionState & { id:string;connector_id:string|null;created_by_connector_id:string|null;last_seen_by_connector_id:string|null;last_synchronized_at:string|null;source_freshness:"current"|"stale"|"historical";source_connector_name:string|null;source_connector_status:string;source_id:string;filename:string;mime_type:string;ingestion_status:string;processing_status:string;blocking_reason:string|null;worker_status:string;chunk_count:number;embedding_status:string;indexed:boolean;searchable:boolean;is_deleted:boolean;updated_at:string };
export type AIAnswerFilters = { connector_id?:string|null;source_id?:string|null;document_id?:string|null };
export type AIAnswerRequest = { query:string;top_k?:number;filters?:AIAnswerFilters;conversation_id?:string|null };
export type AIAnswerCitation = {
  citation_id:string;source_type:string;document_id:string;version_id:string;
  chunk_id:string;title:string;page_number:number|null;section_title:string|null;
  sheet_name:string|null;row_start:number|null;row_end:number|null;score:number;
  excerpt?:string|null;document_type?:string|null;source_system?:string|null;
  source_id?:string|null;ingested_at?:string|null;revision?:string|null;
  sensitive_content_redacted?:boolean;redaction_categories?:string[];
};
export type AIAnswerResponse = { answer:string;grounded:boolean;code:string|null;citations:AIAnswerCitation[];retrieval:{result_count:number;included_count:number;top_k:number};model:{provider:string;model:string}|null;request_id:string };
export type AIPromptSuggestions = {has_indexed_knowledge:boolean;suggestions:string[];onboarding_guidance:string|null};
export type AIConversationMessage = {
  id:string;role:"user"|"assistant";content:string;
  status:"streaming"|"completed"|"failed"|"cancelled";
  created_at:string;completed_at:string|null;model:string|null;prompt_version:string|null;
  citations:AIAnswerCitation[];retrieval_metadata:Record<string,unknown>;
  failure_metadata:Record<string,unknown>;
  context_message_ids:string[];
};
export type AIConversationSummary = {
  id:string;title:string;created_at:string;updated_at:string;last_message_at:string;
  is_archived:boolean;last_message_preview:string|null;
};
export type AIConversation = AIConversationSummary & {messages:AIConversationMessage[]};
export type AIConversationList = {items:AIConversationSummary[];total:number;limit:number;offset:number};
export type AICitationEvidence = {message_id:string;citation:AIAnswerCitation};
