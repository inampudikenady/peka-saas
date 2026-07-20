import type { ConnectorDetail, ManagedConnector, PlatformInvitation, PlatformSettings, PlatformTokenResponse, PlatformUser, PlatformUserInput, RegistrationToken, RegistrationTokenCreated, Tenant, TenantAdminInvite, TenantCreate, TenantCreateResponse, TenantMe, TenantPlatformSummary, TenantSSOConfig, TenantSSOUpdate, TenantUser, TenantUserInvitation } from "@/lib/types";

export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message); }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  const response = await fetch(path, { ...init, headers });
  if (!response.ok) {
    let message = "Something went wrong. Please try again.";
    try { const body = await response.json(); message = body.detail ?? message; } catch {}
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
  connectors: () => platformRequest<ManagedConnector[]>("/api/v1/platform/connectors"),
  connector: (id: string) => platformRequest<ConnectorDetail>(`/api/v1/platform/connectors/${id}`),
};

export const tenantApi = {
  activate: (slug: string, body: { token: string; password: string }) => request<{ authenticated: boolean }>(`${tenantBase(slug)}/auth/activate`, { method: "POST", credentials: "include", body: JSON.stringify(body) }),
  localLogin: (slug: string, body: { username: string; password: string }) => request<{ authenticated: boolean }>(`${tenantBase(slug)}/auth/local-login`, { method: "POST", credentials: "include", body: JSON.stringify(body) }),
  me: (slug: string) => request<TenantMe>(`${tenantBase(slug)}/auth/me`, { credentials: "include" }),
  logout: (slug: string) => request<void>(`${tenantBase(slug)}/auth/logout`, { method: "POST", credentials: "include" }),
  getSSO: (slug: string) => request<TenantSSOConfig>(`${tenantBase(slug)}/admin/security/sso`, { credentials: "include" }),
  updateSSO: (slug: string, body: TenantSSOUpdate) => request<TenantSSOConfig>(`${tenantBase(slug)}/admin/security/sso`, { method: "PUT", credentials: "include", body: JSON.stringify(body) }),
  users: (slug: string) => request<TenantUser[]>(`${tenantBase(slug)}/admin/users`, { credentials: "include" }),
  setUserRole: (slug: string, id: string, role: TenantUser["role"]) => request<TenantUser>(`${tenantBase(slug)}/admin/users/${id}/role`, { method: "PUT", credentials: "include", body: JSON.stringify({ role }) }),
  setUserActive: (slug: string, id: string, active: boolean) => request<TenantUser>(`${tenantBase(slug)}/admin/users/${id}/${active ? "activate" : "deactivate"}`, { method: "POST", credentials: "include" }),
  createUser: (slug:string, body:{full_name:string;email:string;username:string;role:TenantUser["role"]}) => request<TenantUserInvitation>(`${tenantBase(slug)}/admin/users`, {method:"POST",credentials:"include",body:JSON.stringify(body)}),
  resetUserPassword: (slug:string,id:string) => request<TenantUserInvitation>(`${tenantBase(slug)}/admin/users/${id}/password-reset`, {method:"POST",credentials:"include"}),
  changePassword: (slug:string, body:{current_password:string;new_password:string}) => request<void>(`${tenantBase(slug)}/auth/change-password`, {method:"POST",credentials:"include",body:JSON.stringify(body)}),
  connectors: (slug: string) => request<ManagedConnector[]>(`${tenantBase(slug)}/connectors`, { credentials: "include" }),
  connector: (slug: string, id: string) => request<ConnectorDetail>(`${tenantBase(slug)}/connectors/${id}`, { credentials: "include" }),
  retireConnector: (slug: string, id: string) => request<ConnectorDetail>(`${tenantBase(slug)}/connectors/${id}/retire`, { method: "POST", credentials: "include" }),
  registrationTokens: (slug: string) => request<RegistrationToken[]>(`${tenantBase(slug)}/connectors/registration-tokens`, { credentials: "include" }),
  createRegistrationToken: (slug: string, intended_connector_name: string | null) => request<RegistrationTokenCreated>(`${tenantBase(slug)}/connectors/registration-tokens`, { method: "POST", credentials: "include", body: JSON.stringify({ intended_connector_name }) }),
  revokeRegistrationToken: (slug: string, id: string) => request<void>(`${tenantBase(slug)}/connectors/registration-tokens/${id}`, { method: "DELETE", credentials: "include" }),
};
