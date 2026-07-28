# PEKA Platform Vision

> Status: Authoritative Product and Architecture Vision  
> Audience: Founders, Executives, Architects, Platform Engineers, Product Engineers  
> Scope: PEKA SaaS control plane, tenant applications, connectors, knowledge platform, and AI services

## 1. Executive Summary

PEKA is a commercial, multi-tenant SaaS platform for enterprise knowledge, infrastructure intelligence, and AI-assisted operations.

PEKA is not a re-skinned version of a legacy AI application. It is a platform designed from the ground up to support many enterprise customers, strong tenant isolation, secure connectivity to customer environments, extensible connectors, governed knowledge ingestion, and a replaceable AI provider layer.

The long-term objective is to give enterprise teams one secure place to:

- connect internal systems without opening inbound firewall access,
- ingest and govern operational knowledge,
- search and retrieve tenant-owned information,
- ask grounded questions with verifiable citations,
- inspect infrastructure and operational context,
- extend the platform through future integrations, routing, tools, and actions,
- preserve enterprise security, auditability, and tenant separation throughout.

PEKA must be designed for long-term maintainability rather than short-term demonstrations.

## 2. Product Vision

PEKA should become the enterprise intelligence layer between customer systems and human operators.

The platform should help users answer questions such as:

- How is this system installed?
- What infrastructure supports this application?
- Which runbook applies to this incident?
- What changed recently?
- Which monitoring signals are relevant?
- Which tickets or documents contain the answer?
- What action should be taken next?
- Can PEKA execute an approved operational action?

The platform will evolve in stages.

### Stage 1: Secure Connectivity

Customer environments connect to PEKA through an outbound-only connector.

### Stage 2: Knowledge Ingestion

PEKA receives documents and structured data, stores the source material, processes it, and builds searchable tenant knowledge.

### Stage 3: Grounded AI

Users ask questions and receive answers based only on tenant-owned evidence with citations.

### Stage 4: Intent Routing

PEKA determines whether a question should use documents, monitoring, logs, CMDB, tickets, or another capability.

### Stage 5: Tools and Actions

PEKA can perform approved actions through governed connectors and plugins.

### Stage 6: Enterprise Automation

PEKA becomes a policy-controlled assistant for diagnosis, remediation, reporting, and operational workflows.

## 3. Core Product Principles

### 3.1 Multi-Tenancy Is Foundational

Tenant isolation is not a feature added later. It is a platform invariant.

Every tenant-owned object must carry immutable tenant identity.

Tenant identity must be resolved server-side from authenticated context, not from browser-supplied identifiers.

Tenant boundaries must apply to:

- users,
- connectors,
- documents,
- document versions,
- chunks,
- embeddings,
- vector searches,
- AI requests,
- citations,
- configuration,
- audit events,
- future tools,
- future actions.

### 3.2 Connector Communication Is Outbound Only

Customer connectors initiate all communication to PEKA over HTTPS.

The connector must not require inbound access from the SaaS platform.

This reduces customer firewall changes and supports enterprise security expectations.

### 3.3 Connector Collects; SaaS Understands

The connector should remain lightweight and operationally simple.

The connector is responsible for:

- local source configuration,
- data collection,
- document discovery,
- secure delivery,
- local retry,
- health reporting,
- upgrade readiness.

The SaaS platform is responsible for:

- tenant identity,
- durable storage,
- parsing,
- chunking,
- embeddings,
- vector indexing,
- retrieval,
- AI reasoning,
- authorization,
- audit,
- policy,
- orchestration.

Business intelligence and AI logic should not drift into the connector.

### 3.4 Source Data Remains the System of Record

PostgreSQL and object storage are the durable systems of record.

Vector indexes are derived, rebuildable representations.

Qdrant must never become the authoritative source of document state.

### 3.5 Knowledge Service Is the Retrieval Boundary

All retrieval from tenant knowledge must occur through Knowledge Service.

AI services, UI routes, and future routing components must not access Qdrant directly.

This protects tenant isolation and creates one place for:

- filtering,
- version handling,
- deleted-document exclusion,
- score normalization,
- citation metadata,
- future reranking,
- future hybrid search.

### 3.6 Providers Are Replaceable

PEKA must not be architecturally tied to one AI provider.

Development may use Ollama.

Production may use:

- Azure OpenAI,
- OpenAI,
- Anthropic,
- Gemini,
- vLLM,
- private inference clusters,
- future enterprise model providers.

Provider substitution must not require rewriting application services.

### 3.7 AI Answers Must Be Grounded

Models are not sources of truth.

Tenant knowledge is the source of evidence.

AI answers must:

- use retrieved evidence,
- cite supporting sources,
- state when evidence is insufficient,
- avoid fabricated facts,
- avoid claiming actions were performed,
- avoid exposing internal reasoning.

### 3.8 Security and Operability Over Convenience

PEKA should prefer explicit configuration, safe failure, auditability, and clear operator diagnostics over hidden behavior.

The platform must remain administratively usable when AI providers or vector services are unavailable.

## 4. Platform Personas

### 4.1 Platform Administrator

Responsible for operating the PEKA SaaS platform.

Capabilities include:

- create tenant,
- deactivate tenant,
- delete tenant according to policy,
- manage platform users,
- inspect platform-wide health,
- inspect tenant and connector status,
- launch authorized tenant portals,
- manage platform configuration,
- review audit information.

### 4.2 Platform Read-Only Executive

Designed for executive or demonstration access.

This role needs a bird's-eye view of:

- tenants served,
- tenant status,
- connector health,
- product adoption,
- high-level usage,
- authorized tenant portal launch.

This role must not alter platform state.

### 4.3 Tenant Administrator

Responsible for tenant configuration.

Capabilities include:

- manage tenant users,
- create users where local auth is enabled,
- reset user passwords where applicable,
- configure tenant SSO,
- inspect connectors,
- inspect document ingestion,
- retry or re-index failed documents,
- view tenant health,
- manage future integrations.

### 4.4 Tenant User

Uses PEKA for search and AI assistance.

Capabilities depend on tenant policy but normally include:

- ask grounded questions,
- view citations,
- inspect permitted knowledge,
- use future operational capabilities.

### 4.5 Connector Administrator

Configures local connector data sources and inspects connector status.

## 5. Identity and Authentication

### 5.1 Platform Authentication

The PEKA platform administration plane uses local platform authentication initially.

Platform users are separate from tenant users.

### 5.2 Tenant Authentication

Tenant applications support enterprise SSO, initially through OIDC.

Local tenant authentication may exist for bootstrap or explicitly enabled cases.

### 5.3 Tenant Addressing

Tenant portals use a stable tenant slug and immutable internal tenant UUID.

Preferred public addressing:

```text
https://<tenant-slug>.peka.example
```

The slug is human-readable.

The UUID is the permanent internal identity.

Renaming a tenant slug must not change tenant ownership or internal references.

### 5.4 Self-Service Profile

Every authenticated user should have profile controls in the top-right application area.

Where local credentials apply, users should be able to reset their own password without administrator involvement.

## 6. High-Level Architecture

```text
                         ┌──────────────────────────┐
                         │      PEKA SaaS           │
                         │                          │
 Users ────────────────► │ Platform / Tenant UI     │
                         │ API / Auth / Policy      │
                         │ Document Service         │
                         │ Knowledge Service        │
                         │ AI Services              │
                         │ Audit / Health           │
                         └────────────┬─────────────┘
                                      │
                         outbound HTTPS only
                                      │
                         ┌────────────▼─────────────┐
                         │   Customer Connector     │
                         │                          │
                         │ Local source adapters    │
                         │ Delivery queue           │
                         │ Local settings UI        │
                         │ Health / heartbeat       │
                         └───────┬───────┬──────────┘
                                 │       │
                ┌────────────────┘       └─────────────────┐
                ▼                                          ▼
        Documents / CMDB                          Prometheus / Loki /
        Tickets / Repositories                    future enterprise systems
```

## 7. SaaS Control Plane

The control plane manages:

- platform users,
- tenants,
- tenant lifecycle,
- tenant identities,
- tenant SSO,
- connector registration,
- platform-wide health,
- product configuration,
- audit.

The control plane must not expose tenant data to unauthorized platform roles.

Executive read-only access may launch tenant portals only when explicitly authorized.

## 8. Tenant Application Plane

Each tenant receives an isolated application experience.

Initial tenant capabilities include:

- AI Assistant,
- document administration,
- connector status,
- tenant user management,
- SSO configuration,
- tenant security configuration,
- user profile.

The tenant landing experience should prioritize useful product functionality rather than an empty dashboard.

## 9. Connector Architecture

### 9.1 Registration

Each connector registers through a controlled handshake and receives a stable connector identity.

Connector identity should not rely only on MAC address.

A secure registration token and issued connector credentials should define trust.

Hardware or installation identifiers may help detect clones but must not be the sole authentication mechanism.

### 9.2 Authentication

Connector credentials must be:

- tenant-bound,
- connector-bound,
- revocable,
- rotatable,
- auditable.

Monthly rotation may be supported but must be implemented safely without creating avoidable outages.

### 9.3 Clone and Restore Handling

Cloned or restored connector instances must not silently duplicate a trusted connector identity.

The platform should detect competing installations and require explicit administrative reconciliation.

### 9.4 Heartbeat

Connectors send periodic heartbeats.

The SaaS platform records:

- last seen,
- connector version,
- health,
- source status,
- delivery backlog,
- supported capabilities.

### 9.5 Retirement

Connectors offline beyond a configured policy period may be marked stale or retired.

Retirement should be reversible where operationally appropriate.

### 9.6 Upgrade Control

Connector upgrades are centrally governed.

Unsupported versions may be blocked according to policy, but upgrades should not be forced in a way that risks customer environments without a controlled release process.

## 10. Document and Knowledge Architecture

The document pipeline is:

```text
Connector
→ Document API
→ Document Service
→ Object Storage
→ Ingestion Worker
→ Parser
→ Chunk Service
→ Embeddings
→ Qdrant
→ Knowledge Service
```

Supported source formats may include:

- TXT,
- Markdown,
- CSV,
- PDF,
- DOCX,
- XLSX.

Document state must be durable and explicit.

Examples:

- received,
- queued,
- parsing,
- chunking,
- embedding,
- indexing,
- indexed,
- blocked,
- failed,
- deleted.

Retry and re-index are distinct operations.

### Retry

Retry resumes failed processing and should reuse valid intermediate artifacts.

### Re-index

Re-index rebuilds vector representations and should avoid duplicate active points.

## 11. AI Architecture

The initial AI flow is:

```text
Tenant Question
→ AI Controller
→ AI Answer Service
→ Knowledge Service
→ Prompt Builder
→ LLM Provider
→ Grounded Answer
→ Citations
```

The initial AI capability is document-grounded answering only.

The following are intentionally deferred:

- conversations,
- intent routing,
- tools,
- actions,
- agents,
- live infrastructure diagnosis,
- monitoring and log integration.

## 12. LLM Provider Strategy

PEKA uses a provider abstraction with capability methods such as:

- embed,
- generate,
- stream.

Embedding and generation may use different provider configurations even when they share a provider family.

Development reference:

- native Ollama,
- `nomic-embed-text`,
- `qwen3:8b`,
- Apple Metal GPU.

Production provider selection remains configurable.

## 13. Security Model

### 13.1 Tenant Isolation

Tenant isolation must be enforced in:

- application services,
- repositories,
- retrieval,
- citations,
- APIs,
- UI authorization,
- background jobs.

### 13.2 Secrets

Secrets must never appear in:

- source control,
- frontend bundles,
- logs,
- health responses,
- exception payloads.

### 13.3 Prompt Injection

Retrieved content is untrusted.

Documents must never be promoted to system instructions.

### 13.4 Audit

Security-sensitive and administrative events should be auditable.

Examples:

- tenant creation,
- user creation,
- password reset,
- connector registration,
- connector revocation,
- SSO changes,
- document deletion,
- re-index,
- future action execution.

## 14. Reliability and Degraded Operation

PEKA should fail in layers.

Examples:

- If Qdrant is down, tenant administration remains available.
- If the chat model is unavailable, ingestion remains available.
- If the connector is offline, existing tenant knowledge remains searchable.
- If embedding generation is unavailable, uploads remain queued with a visible reason.

Health reporting must distinguish:

- healthy,
- degraded,
- unavailable,
- not configured.

## 15. Observability

The platform should expose safe operational signals for:

- API health,
- database health,
- object storage health,
- worker heartbeat,
- queued jobs,
- connector heartbeat,
- embedding provider,
- vector store,
- chat provider,
- tenant usage,
- error rates,
- latency.

Content and secrets should not be logged by default.

## 16. Deployment Model

Initial deployment may use a practical modular monolith with separate worker processes.

Logical service boundaries must still be clear.

Potential deployable units include:

- backend API,
- frontend,
- ingestion worker,
- PostgreSQL,
- object storage,
- Qdrant,
- future event broker,
- future AI workers.

Premature microservices should be avoided.

## 17. Data Ownership

Tenant data belongs to the tenant.

PEKA must support future policies for:

- retention,
- deletion,
- export,
- legal hold,
- encryption,
- regional hosting,
- data residency.

## 18. Extensibility

Future integrations may include:

- Prometheus,
- Loki,
- CMDB,
- Zammad,
- document repositories,
- ticketing systems,
- cloud platforms,
- virtualization platforms,
- identity systems.

Each integration should be exposed through a governed capability or plugin contract rather than hardcoded into the core AI service.

## 19. Future Routing Architecture

Intent routing will be introduced only after grounded answering is stable.

The future router may select among:

- document knowledge,
- metrics,
- logs,
- CMDB,
- tickets,
- tools,
- actions.

The router must not replace tenant authorization or provider abstractions.

## 20. Future Tool and Action Architecture

Future actions must include:

- explicit permissions,
- tenant policy,
- connector capability verification,
- validation,
- approval where required,
- audit,
- idempotency,
- safe rollback where possible.

The model must never directly execute arbitrary commands.

## 21. Product Roadmap

### Phase 1: Platform Foundation

- tenant management,
- platform users,
- tenant users,
- SSO,
- connector registration,
- core UI.

### Phase 2: Knowledge Foundation

- document upload,
- processing,
- embeddings,
- Qdrant,
- Knowledge Service,
- document administration.

### Phase 3: AI Answering

- Prompt Builder,
- LLM Provider,
- grounded answers,
- citations,
- streaming,
- minimal AI Assistant UI.

### Phase 4: Conversations

- history,
- titles,
- retention,
- context management,
- user controls.

### Phase 5: Routing and Integrations

- metrics,
- logs,
- CMDB,
- tickets,
- knowledge routing.

### Phase 6: Tools and Actions

- governed operational workflows,
- approvals,
- connector-executed actions,
- audit.

## 22. Architectural Non-Goals

PEKA should not:

- become a thin UI wrapper around one model,
- expose Qdrant directly to application features,
- place business intelligence in the connector,
- rely on browser-provided tenant identity,
- expose model reasoning,
- assume all enterprise customers use the same identity provider,
- require inbound customer firewall rules,
- treat vector search as the source of truth,
- add agents before deterministic services are stable.

## 23. Success Criteria

PEKA succeeds when:

- customers can securely connect internal systems without inbound access,
- tenant data remains isolated,
- source documents are durably governed,
- users receive useful grounded answers,
- citations are verifiable,
- providers can be replaced,
- degraded dependencies do not collapse the platform,
- future capabilities can be added without rewriting the foundation.

## 24. Final Vision

PEKA should become a trusted enterprise operations and knowledge platform.

Its value will not come from a single model or one integration.

Its value will come from the combination of:

- secure enterprise connectivity,
- strong tenant isolation,
- governed knowledge,
- replaceable AI,
- verifiable answers,
- extensible operational capabilities,
- disciplined architecture.
