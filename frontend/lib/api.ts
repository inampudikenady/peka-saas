import type { AIAnswerCitation, AIAnswerRequest, AIAnswerResponse, AICitationEvidence, AIConversation, AIConversationList, AIPromptSuggestions, ConnectorDetail, ManagedConnector, ManagedDocument, ManagedDocumentListItem, PlatformInvitation, PlatformSettings, PlatformTokenResponse, PlatformUser, PlatformUserInput, RegistrationToken, RegistrationTokenCreated, Tenant, TenantAdminInvite, TenantCreate, TenantCreateResponse, TenantMe, TenantPlatformSummary, TenantSSOConfig, TenantSSOLoginOptions, TenantSSOUpdate, TenantUser, TenantUserInvitation } from "@/lib/types";

export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message); }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  const response = await fetch(path, { ...init, headers });
  if (!response.ok) {
    let message = "Something went wrong. Please try again.";
    try { const body = await response.json(); message = body.message ?? body.detail ?? message; } catch {}
    throw new ApiError(response.status, message);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

const TOKEN_KEY = "peka_platform_session";
export const platformSession = {
  get: () => typeof window === "undefined" ? null : sessionStorage.getItem(TOKEN_KEY),
  set: (token: string) => sessionStorage.setItem(TOKEN_KEY, token),
  clear: () => sessionStorage.removeItem(TOKEN_KEY),
};

async function platformRequest<T>(path: string, init: RequestInit = {}) {
  const token = platformSession.get();
  const headers = new Headers(init.headers);
  if (token) headers.set("Authorization", `Bearer ${token}`);
  try { return await request<T>(path, { ...init, headers }); }
  catch (error) { if (error instanceof ApiError && error.status === 401) platformSession.clear(); throw error; }
}

const tenantBase = (slug: string) => `/t/${encodeURIComponent(slug)}/api/v1/tenant`;

export type AIStreamCallbacks = {
  onStatus?: (value: { status:string;request_id?:string;conversation_id?:string;assistant_message_id?:string }) => void;
  onRetrieval?: (value: { result_count:number;included_count:number;top_k:number }) => void;
  onToken: (text: string) => void;
  onCitations: (citations: AIAnswerCitation[]) => void;
  onComplete: (value: { grounded:boolean;code?:string;request_id:string }) => void;
};

async function streamAIAnswer(slug:string, body:AIAnswerRequest, callbacks:AIStreamCallbacks, signal?:AbortSignal) {
  const response = await fetch(`${tenantBase(slug)}/ai/answer/stream`, {
    method: "POST", credentials: "include", signal,
    headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  });
  if (!response.ok || !response.body) {
    let message = "The AI service is temporarily unavailable.";
    try { const value = await response.json(); message = value.message ?? value.detail ?? message; } catch {}
    throw new ApiError(response.status, message);
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let completed = false;
  const dispatch = (frame:string) => {
    let event = "message"; const dataLines:string[] = [];
    for (const line of frame.split(/\r?\n/)) {
      if (line.startsWith("event:")) event = line.slice(6).trim();
      if (line.startsWith("data:")) dataLines.push(line.slice(5).trimStart());
    }
    if (dataLines.length === 0) return;
    const value = JSON.parse(dataLines.join("\n"));
    if (event === "token") callbacks.onToken(value.text);
    else if (event === "citations") callbacks.onCitations(value.citations);
    else if (event === "retrieval") callbacks.onRetrieval?.(value);
    else if (event === "status") callbacks.onStatus?.(value);
    else if (event === "complete") { completed = true; callbacks.onComplete(value); }
    else if (event === "error") throw new ApiError(503, value.message);
  };
  try {
    while (true) {
      const { done, value } = await reader.read();
      buffer += decoder.decode(value, { stream: !done });
      const frames = buffer.split(/\r?\n\r?\n/);
      buffer = frames.pop() ?? "";
      for (const frame of frames) dispatch(frame);
      if (done) break;
    }
    if (buffer.trim()) dispatch(buffer);
    if (!completed) throw new Error("The AI answer stream ended unexpectedly. Please try again.");
  } finally {
    reader.releaseLock();
  }
}

export const platformApi = {
  login: (body: { username: string; password: string }) => request<PlatformTokenResponse>("/api/v1/platform/auth/login", { method: "POST", body: JSON.stringify(body) }),
  tenants: () => platformRequest<Tenant[]>("/api/v1/platform/tenants"),
  tenant: (slug: string) => platformRequest<Tenant>(`/api/v1/platform/tenants/${encodeURIComponent(slug)}`),
  tenantSummary: (slug: string) => platformRequest<TenantPlatformSummary>(`/api/v1/platform/tenants/${encodeURIComponent(slug)}/summary`),
  tenantInvite: (slug: string) => platformRequest<TenantAdminInvite | null>(`/api/v1/platform/tenants/${encodeURIComponent(slug)}/admin-invite`),
  regenerateInvite: (slug: string) => platformRequest<TenantAdminInvite>(`/api/v1/platform/tenants/${encodeURIComponent(slug)}/admin-invite/regenerate`, { method: "POST" }),
  deactivateTenant: (slug: string) => platformRequest<Tenant>(`/api/v1/platform/tenants/${encodeURIComponent(slug)}/deactivate`, { method: "POST" }),
  activateTenant: (slug: string) => platformRequest<Tenant>(`/api/v1/platform/tenants/${encodeURIComponent(slug)}/activate`, { method: "POST" }),
  deleteTenant: (slug: string) => platformRequest<void>(`/api/v1/platform/tenants/${encodeURIComponent(slug)}?confirmation=${encodeURIComponent(slug)}`, { method: "DELETE" }),
  createTenant: (body: TenantCreate) => platformRequest<TenantCreateResponse>("/api/v1/platform/tenants", { method: "POST", body: JSON.stringify(body) }),
  health: () => request<{ status: string }>("/health"),
  me: () => platformRequest<PlatformUser>("/api/v1/platform/auth/me"),
  users: () => platformRequest<PlatformUser[]>("/api/v1/platform/users"),
  user: (id: string) => platformRequest<PlatformUser>(`/api/v1/platform/users/${id}`),
  createUser: (body: PlatformUserInput) => platformRequest<PlatformInvitation>("/api/v1/platform/users", { method: "POST", body: JSON.stringify(body) }),
  updateUser: (id: string, body: Omit<PlatformUserInput, "username">) => platformRequest<PlatformUser>(`/api/v1/platform/users/${id}`, { method: "PUT", body: JSON.stringify(body) }),
  setUserActive: (id: string, active: boolean) => platformRequest<PlatformUser>(`/api/v1/platform/users/${id}/${active ? "activate" : "deactivate"}`, { method: "POST" }),
  passwordReset: (id: string) => platformRequest<PlatformInvitation>(`/api/v1/platform/users/${id}/password-reset`, { method: "POST" }),
  changePassword: (body: { current_password: string; new_password: string }) => platformRequest<void>("/api/v1/platform/auth/change-password", { method: "POST", body: JSON.stringify(body) }),
  resetPassword: (body: { token: string; new_password: string }) => request<void>("/api/v1/platform/auth/reset-password", { method: "POST", body: JSON.stringify(body) }),
  settings: () => platformRequest<PlatformSettings>("/api/v1/platform/settings"),
  connectors: (includeRetired = false) => platformRequest<ManagedConnector[]>(`/api/v1/platform/connectors?include_retired=${includeRetired}`),
  connector: (id: string) => platformRequest<ConnectorDetail>(`/api/v1/platform/connectors/${id}`),
};

export const tenantApi = {
  activate: (slug: string, body: { token: string; password: string }) => request<{ authenticated: boolean }>(`${tenantBase(slug)}/auth/activate`, { method: "POST", credentials: "include", body: JSON.stringify(body) }),
  localLogin: (slug: string, body: { username: string; password: string }) => request<{ authenticated: boolean }>(`${tenantBase(slug)}/auth/local-login`, { method: "POST", credentials: "include", body: JSON.stringify(body) }),
  me: (slug: string) => request<TenantMe>(`${tenantBase(slug)}/auth/me`, { credentials: "include" }),
  logout: (slug: string) => request<void>(`${tenantBase(slug)}/auth/logout`, { method: "POST", credentials: "include" }),
  ssoOptions: (slug: string) => request<TenantSSOLoginOptions>(`${tenantBase(slug)}/auth/sso-options`, { credentials: "include" }),
  getSSO: (slug: string) => request<TenantSSOConfig>(`${tenantBase(slug)}/admin/security/sso`, { credentials: "include" }),
  updateSSO: (slug: string, body: TenantSSOUpdate) => request<TenantSSOConfig>(`${tenantBase(slug)}/admin/security/sso`, { method: "PUT", credentials: "include", body: JSON.stringify(body) }),
  users: (slug: string) => request<TenantUser[]>(`${tenantBase(slug)}/admin/users`, { credentials: "include" }),
  setUserRole: (slug: string, id: string, role: TenantUser["role"]) => request<TenantUser>(`${tenantBase(slug)}/admin/users/${id}/role`, { method: "PUT", credentials: "include", body: JSON.stringify({ role }) }),
  setUserActive: (slug: string, id: string, active: boolean) => request<TenantUser>(`${tenantBase(slug)}/admin/users/${id}/${active ? "activate" : "deactivate"}`, { method: "POST", credentials: "include" }),
  createUser: (slug:string, body:{full_name:string;email:string;username:string;role:TenantUser["role"]}) => request<TenantUserInvitation>(`${tenantBase(slug)}/admin/users`, {method:"POST",credentials:"include",body:JSON.stringify(body)}),
  resetUserPassword: (slug:string,id:string) => request<TenantUserInvitation>(`${tenantBase(slug)}/admin/users/${id}/password-reset`, {method:"POST",credentials:"include"}),
  changePassword: (slug:string, body:{current_password:string;new_password:string}) => request<void>(`${tenantBase(slug)}/auth/change-password`, {method:"POST",credentials:"include",body:JSON.stringify(body)}),
  connectors: (slug: string, includeRetired = false) => request<ManagedConnector[]>(`${tenantBase(slug)}/connectors?include_retired=${includeRetired}`, { credentials: "include" }),
  connector: (slug: string, id: string) => request<ConnectorDetail>(`${tenantBase(slug)}/connectors/${id}`, { credentials: "include" }),
  retireConnector: (slug: string, id: string) => request<ConnectorDetail>(`${tenantBase(slug)}/connectors/${id}/retire`, { method: "POST", credentials: "include" }),
  registrationTokens: (slug: string, includeInactive = false) => request<RegistrationToken[]>(`${tenantBase(slug)}/connectors/registration-tokens?include_inactive=${includeInactive}`, { credentials: "include" }),
  createRegistrationToken: (slug: string) => request<RegistrationTokenCreated>(`${tenantBase(slug)}/connectors/registration-tokens`, { method: "POST", credentials: "include", body: JSON.stringify({}) }),
  revokeRegistrationToken: (slug: string, id: string) => request<void>(`${tenantBase(slug)}/connectors/registration-tokens/${id}`, { method: "DELETE", credentials: "include" }),
  documents: (slug: string, includeDeleted = false) => request<ManagedDocumentListItem[]>(`${tenantBase(slug)}/documents?include_deleted=${includeDeleted}`, { credentials: "include" }),
  document: (slug: string, id: string) => request<ManagedDocument>(`${tenantBase(slug)}/documents/${id}`, { credentials: "include" }),
  retryDocument: (slug: string, id: string) => request<ManagedDocument>(`${tenantBase(slug)}/documents/${id}/retry`, { method: "POST", credentials: "include" }),
  reindexDocument: (slug: string, id: string) => request<ManagedDocument>(`${tenantBase(slug)}/documents/${id}/reindex`, { method: "POST", credentials: "include" }),
  deleteDocument: (slug: string, id: string, connectorId: string) => request<ManagedDocument>(`${tenantBase(slug)}/documents/${id}?connector_id=${encodeURIComponent(connectorId)}`, { method: "DELETE", credentials: "include" }),
  answer: (slug:string, body:AIAnswerRequest) => request<AIAnswerResponse>(`${tenantBase(slug)}/ai/answer`, {method:"POST",credentials:"include",body:JSON.stringify(body)}),
  assistantSuggestions: (slug:string) => request<AIPromptSuggestions>(`${tenantBase(slug)}/ai/suggestions`, {credentials:"include"}),
  streamAnswer: streamAIAnswer,
  conversations: (slug:string, archived=false, limit=30, offset=0) => request<AIConversationList>(`${tenantBase(slug)}/ai/conversations?archived=${archived}&limit=${limit}&offset=${offset}`, {credentials:"include"}),
  conversation: (slug:string,id:string) => request<AIConversation>(`${tenantBase(slug)}/ai/conversations/${encodeURIComponent(id)}`, {credentials:"include"}),
  createConversation: (slug:string,title?:string) => request<AIConversation>(`${tenantBase(slug)}/ai/conversations`, {method:"POST",credentials:"include",body:JSON.stringify({title})}),
  renameConversation: (slug:string,id:string,title:string) => request<AIConversation>(`${tenantBase(slug)}/ai/conversations/${encodeURIComponent(id)}/title`, {method:"PATCH",credentials:"include",body:JSON.stringify({title})}),
  archiveConversation: (slug:string,id:string,is_archived:boolean) => request<AIConversation>(`${tenantBase(slug)}/ai/conversations/${encodeURIComponent(id)}/archive`, {method:"PATCH",credentials:"include",body:JSON.stringify({is_archived})}),
  deleteConversation: (slug:string,id:string) => request<void>(`${tenantBase(slug)}/ai/conversations/${encodeURIComponent(id)}`, {method:"DELETE",credentials:"include"}),
  citationEvidence: (slug:string,conversationId:string,messageId:string,citationId:string) => request<AICitationEvidence>(`${tenantBase(slug)}/ai/conversations/${encodeURIComponent(conversationId)}/messages/${encodeURIComponent(messageId)}/citations/${encodeURIComponent(citationId)}`, {credentials:"include"}),
};
