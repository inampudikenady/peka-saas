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
  local_knowledge_store_status?: "healthy" | "degraded" | "unavailable" | null;
  knowledge_document_count?: number; knowledge_indexed_chunk_count?: number;
  last_knowledge_index_activity_at?: string | null;
  created_at: string; updated_at: string;
};
export type ConnectorHeartbeat = {
  received_at: string; reported_at: string; version: string; reported_status: string; uptime_seconds: number;
  source_total: number; source_healthy: number; source_unhealthy: number; source_disabled: number; accepted: boolean;
  local_knowledge_store_status?: "healthy" | "degraded" | "unavailable" | null;
  knowledge_document_count?: number; knowledge_indexed_chunk_count?: number;
  last_knowledge_index_activity_at?: string | null;
};
export type ConnectorEvent = { event_type: string; occurred_at: string; detail: string | null };
export type ConnectorDetail = ManagedConnector & { capabilities: string[]; recent_heartbeats: ConnectorHeartbeat[]; recent_events: ConnectorEvent[] };
export type RegistrationToken = {
  id: string; tenant_id: string; expires_at: string; used_at: string | null; created_by_user_id: string | null;
  created_at: string; revoked_at: string | null; intended_connector_name: string | null; status: "active" | "used" | "expired" | "revoked";
};
export type RegistrationTokenCreated = RegistrationToken & { registration_token: string };
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
