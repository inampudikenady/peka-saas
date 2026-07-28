"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { Alert } from "@/components/alert";
import { DocumentDeleteAction } from "@/components/document-delete-action";
import { TenantAdministration } from "@/components/tenant-administration";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { useTenantUser } from "@/hooks/use-tenant-user";
import { tenantApi } from "@/lib/api";
import type { ManagedDocument } from "@/lib/types";

function PipelineBadge({ label, ready, title }: { label: string; ready: boolean; title: string }) {
  return <span title={title} className={`rounded-full px-2 py-1 text-xs font-medium ${ready ? "bg-emerald-100 text-emerald-800" : "bg-amber-100 text-amber-800"}`}>{label}</span>;
}

function TenantShell({ children, title }: { children: React.ReactNode; title: string; slug: string; user: unknown }) {
  return <TenantAdministration title={title}>{children}</TenantAdministration>;
}

export default function DocumentDetailPage() {
  const { tenantSlug, documentId } = useParams<{ tenantSlug: string; documentId: string }>();
  const { user } = useTenantUser(tenantSlug);
  const [document, setDocument] = useState<ManagedDocument | null>(null);
  const [error, setError] = useState("");
  const [working, setWorking] = useState(false);
  useEffect(() => { void tenantApi.document(tenantSlug, documentId).then(setDocument).catch((caught) => setError(caught.message)); }, [tenantSlug, documentId]);
  if (!user) return <main className="p-8">Loading…</main>;
  async function action(kind: "retry" | "reindex") {
    if (!document) return; setWorking(true); setError("");
    try { setDocument(await (kind === "retry" ? tenantApi.retryDocument(tenantSlug, document.id) : tenantApi.reindexDocument(tenantSlug, document.id))); }
    catch (caught) { setError(caught instanceof Error ? caught.message : "Document action failed."); }
    finally { setWorking(false); }
  }
  return <TenantShell slug={tenantSlug} user={user} title="Document details">{error && <Alert>{error}</Alert>}{!document ? <p className="text-sm text-slate-500">Loading document…</p> : <div className="space-y-5"><div className="flex justify-end gap-2">{user.role === "tenant_admin" && <>{!document.is_deleted && <Button variant="outline" disabled={working} onClick={() => action("reindex")}>Re-index</Button>}{!document.is_deleted && (document.current_version?.ingestion_status === "FAILED" || document.current_version?.error_code === "NOT_CONFIGURED" || document.current_version?.error_code === "EMBEDDING_UNAVAILABLE" || document.current_version?.error_code === "QDRANT_UNAVAILABLE") && <Button variant="outline" disabled={working} onClick={() => action("retry")}>Retry</Button>}<DocumentDeleteAction tenantSlug={tenantSlug} document={document} onDeleted={setDocument} /></>}</div><div className="flex flex-wrap gap-2"><PipelineBadge label={document.processing_status} ready={document.processing_status === "Indexed"} title={document.blocking_reason ?? `Current pipeline state: ${document.processing_status}.`} /><PipelineBadge label={`Worker: ${document.worker_status}`} ready={document.worker_status === "Idle" || document.worker_status === "Busy"} title="Health reported by the standalone ingestion worker." /><PipelineBadge label={`${document.chunk_count} chunks`} ready={document.chunk_count > 0} title="Chunks generated for the current document version." /><PipelineBadge label={`Embedding: ${document.embedding_status}`} ready={document.embedding_status === "Complete"} title="Embedding state for the current document version." /><PipelineBadge label={document.indexed ? "Indexed" : "Not indexed"} ready={document.indexed} title="Whether the current chunks were written to Qdrant." /><PipelineBadge label={document.searchable ? "Searchable" : "Not searchable"} ready={document.searchable} title="Whether the current document version is available to PEKA Knowledge Search." /></div><div className="grid gap-5 lg:grid-cols-2"><Card><CardHeader><h2 className="text-lg font-semibold">{document.filename}</h2></CardHeader><CardContent><dl className="space-y-3 text-sm"><Field label="Path" value={document.relative_path} /><Field label="Source" value={document.source_id} /><Field label="Connector ID" value={document.connector_id} /><Field label="Document key" value={document.document_key} /><Field label="MIME type" value={document.mime_type} /><Field label="Deleted" value={document.is_deleted ? "Yes" : "No"} /></dl></CardContent></Card><Card><CardHeader><h2 className="text-lg font-semibold">Current version</h2></CardHeader><CardContent>{!document.current_version ? <p className="text-sm text-slate-500">No current binary version.</p> : <dl className="space-y-3 text-sm"><Field label="Status" value={document.processing_status} /><Field label="SHA-256" value={document.current_version.content_hash} /><Field label="Storage" value={document.current_version.storage_status} /><Field label="Parser" value={document.current_version.parser_name ?? "Pending"} /><Field label="Chunker" value={document.current_version.chunker_name ?? "Pending"} /><Field label="Embedding" value={document.current_version.embedding_model ?? document.embedding_status} /><Field label="Chunks" value={String(document.chunk_count)} />{document.blocking_reason && <Field label="Blocking reason" value={document.blocking_reason} />}{document.current_version.error_message && <Field label="Last error" value={document.current_version.error_message} />}</dl>}</CardContent></Card></div><Card><CardHeader><h2 className="text-lg font-semibold">Version history</h2></CardHeader><CardContent><div className="space-y-3">{document.versions.map((version) => <div key={version.id} className="rounded border p-3 text-sm"><div className="flex justify-between"><span className="font-medium">{version.ingestion_status}</span><time className="text-slate-500">{new Date(version.received_at).toLocaleString()}</time></div><div className="mt-1 break-all text-xs text-slate-500">{version.content_hash}</div></div>)}</div></CardContent></Card></div>}</TenantShell>;
}

function Field({ label, value }: { label: string; value: string }) { return <div><dt className="text-xs font-medium uppercase text-slate-500">{label}</dt><dd className="break-all">{value}</dd></div>; }
