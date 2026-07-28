# PEKA UI and Access Model V1

## Ownership boundary

The platform owns platform users, tenant creation and lifecycle, and future licensing and platform settings. It does not configure tenant SSO, users, roles, connectors, AI settings, or data sources.

Each tenant owns its users, roles, SSO, connectors, tenant settings, and future tenant audit and data-source controls.

Platform tenant browsing and tenant lifecycle administration are intentionally separated. `/platform/tenants` and `/platform/tenants/[slug]` are read-only for both platform roles. Tenant creation, lifecycle changes, deletion, and setup-invitation regeneration exist only under `/platform/administration/tenant-management` and require `platform_admin`.

## V1 roles and navigation

### Platform admin

- Tenants
- Administration
  - User management
  - Tenant management
  - Licensing — Coming soon
  - Platform settings

### Platform read-only

- Overview
- Tenants

### Tenant admin

- AI Assistant
- Connectors
- Administration
  - Users
  - Authentication
  - Connectors
  - Tenant settings
  - Audit — Coming soon

### Tenant user

- AI Assistant

The only platform roles are `platform_admin` and `platform_readonly`. The only tenant roles are `tenant_admin` and `tenant_user`.

Platform read-only is the V1 executive/observer persona. Its Overview provides live platform-adoption visibility and quick tenant-portal launch for demonstrations without mutation controls. Platform administrators are operational users and land on Tenants. Overview is exclusive to platform read-only in V1.

Platform and tenant dashboards are removed from V1 and deferred until meaningful operational data exists. `/platform/dashboard` remains only as a role-aware compatibility redirect to Tenants or Overview, and `/t/[tenantSlug]/app` redirects to AI Assistant.

## Bootstrap behavior

The local bootstrap account `admin_{tenant_slug}` receives `tenant_admin`. New SSO-provisioned users receive `tenant_user`. Tenant administrators assign either built-in role from User Management, while backend safeguards preserve at least one active tenant administrator. V1 has no dedicated Roles page; one is deferred to V2 if custom RBAC is introduced.

## Identity lifecycle and profiles

Platform Settings exposes safe general, URL/domain, and runtime configuration only to `platform_admin`; secrets and credentials are never returned.

Tenant administrators manage tenant users. Local users are created inactive without a password and receive a hashed, expiring, one-time setup invitation. Local-user password resets invalidate prior unused reset invitations. SSO users are provisioned as `tenant_user`; their passwords remain managed by the identity provider and PEKA does not offer password reset controls for them.

Both platform roles have a platform profile. Tenant users have tenant-scoped profiles. Local users may change their own password by verifying the current password. Administrator-generated reset links are a separate workflow and never create temporary passwords. SSO profiles display that password management belongs to the identity provider.

## Route map

Platform routes are `/platform/login`, `/platform/overview`, `/platform/tenants`, `/platform/tenants/new`, `/platform/tenants/[slug]`, `/platform/administration` and its `users`, `tenant-management`, `tenant-management/[slug]`, `licensing`, and `settings` sections, plus `/platform/profile` and `/platform/reset-password`. The `/platform/tenants/new` workflow is reached from administrator-only tenant management even though its established route is preserved. Legacy `/platform/dashboard` is a role-aware redirect.

Tenant routes live under `/t/[tenantSlug]`: root resolution, setup, login, the future AI surface, connectors, and `administration` sections for users, authentication, operational documents, settings, and audit. Documents are not normal-user primary navigation. Authenticated tenant roots and legacy `app` routes resolve to the AI placeholder. The legacy `administration/roles` path redirects to User Management so existing bookmarks do not produce a 404.

## Deferred V2 ideas

Custom tenant roles, a dedicated Roles page, permission builders, licensing behavior, tenant audit behavior, AI functionality, and other navigation or role changes are deferred to V2. Role assignment remains part of V1 User Management; a dedicated Roles page may return only if custom RBAC is introduced.

> **This V1 navigation and access model is locked. Proposed UI, navigation, and role changes must be deferred to V2 unless required to fix a security flaw or a broken V1 workflow.**
