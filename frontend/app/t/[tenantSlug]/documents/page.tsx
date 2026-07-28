"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { Alert } from "@/components/alert";
import { DocumentDeleteAction } from "@/components/document-delete-action";
import { TenantAdministration } from "@/components/tenant-administration";
import { useTenantUser } from "@/hooks/use-tenant-user";
import { tenantApi } from "@/lib/api";
import type { ManagedDocumentListItem } from "@/lib/types";

function StatusBadge({ value, ready, title }: { value: string; ready?: boolean; title: string }) {
  const color = ready === true
    ? "bg-emerald-100 text-emerald-800"
    : ready === false
      ? "bg-amber-100 text-amber-800"
      : "bg-slate-100 text-slate-700";
  return <span title={title} className={`rounded-full px-2 py-1 text-xs font-medium ${color}`}>{value}</span>;
}

function ProcessingBadge({ value, reason }: { value: string; reason: string | null }) {
  const color = value === "Indexed"
    ? "bg-emerald-100 text-emerald-800"
    : value.startsWith("Blocked") || value === "Failed"
      ? "bg-red-100 text-red-800"
      : value === "Deleted"
        ? "bg-slate-100 text-slate-700"
        : "bg-amber-100 text-amber-800";
  return <span title={reason ?? `Current pipeline state: ${value}.`} className={`rounded-full px-2 py-1 text-xs font-medium ${color}`}>{value}</span>;
}

export default function DocumentsPage() {
  const { tenantSlug } = useParams<{ tenantSlug: string }>();
  const { user } = useTenantUser(tenantSlug);
  const [documents, setDocuments] = useState<ManagedDocumentListItem[] | null>(null);
  const [includeDeleted, setIncludeDeleted] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    setDocuments(null);
    void tenantApi.documents(tenantSlug, includeDeleted).then(setDocuments).catch((caught) => setError(caught.message));
  }, [tenantSlug, includeDeleted]);
  if (!user) return <main className="p-8">Loading…</main>;
  return <TenantAdministration title="Documents">
    <div className="mb-5 flex items-end justify-between">
      <div><h2 className="text-2xl font-semibold">Documents</h2><p className="text-sm text-slate-500">Connector-delivered files and ingestion state.</p>{documents?.[0] && <p className="mt-1 text-xs text-slate-500">Worker: {documents[0].worker_status}</p>}</div>
      <label className="text-sm"><input type="checkbox" checked={includeDeleted} onChange={(event) => setIncludeDeleted(event.target.checked)} className="mr-2" />Show deleted documents</label>
    </div>
    {error && <Alert>{error}</Alert>}
    {documents?.length === 0 && <p className="rounded-md border border-dashed p-8 text-center text-sm text-slate-500">No connector documents have been received.</p>}
    {documents && documents.length > 0 && <div className="overflow-x-auto rounded-md border"><table className="w-full text-left text-sm">
      <thead className="bg-slate-50 text-xs uppercase text-slate-500"><tr><th className="p-3">Document</th><th className="p-3">Source</th><th className="p-3">Connector</th><th className="p-3">Type</th><th className="p-3">Ingestion state</th><th className="p-3">Chunks</th><th className="p-3">Embedding</th><th className="p-3">Indexed</th><th className="p-3">Searchable</th><th className="p-3">Updated</th><th className="p-3">Actions</th></tr></thead>
      <tbody>{documents.map((document) => <tr key={document.id} className="border-t">
        <td className="p-3"><Link className="font-medium text-blue-600 hover:underline" href={`/t/${tenantSlug}/administration/documents/${document.id}`}>{document.filename}</Link></td>
        <td className="p-3">{document.source_id}</td><td className="p-3 font-mono text-xs">{document.connector_id.slice(0, 8)}…</td><td className="p-3">{document.mime_type}</td>
        <td className="p-3"><ProcessingBadge value={document.processing_status} reason={document.blocking_reason} /></td>
        <td className="p-3"><StatusBadge value={String(document.chunk_count)} ready={document.chunk_count > 0} title="Chunks generated for the current document version." /></td>
        <td className="p-3"><StatusBadge value={document.embedding_status} ready={document.embedding_status === "Complete"} title="Embedding state for the current document version." /></td>
        <td className="p-3"><StatusBadge value={document.indexed ? "Indexed" : "Not indexed"} ready={document.indexed} title="Whether the current chunks were written to Qdrant." /></td>
        <td className="p-3"><StatusBadge value={document.searchable ? "Searchable" : "Not searchable"} ready={document.searchable} title="Whether the current document version is available to PEKA Knowledge Search." /></td>
        <td className="p-3" title={document.updated_at}>{new Date(document.updated_at).toLocaleString()}</td>
        <td className="p-3"><div className="flex items-start gap-2"><Link className="rounded border border-slate-300 px-3 py-1.5 text-xs font-medium hover:bg-slate-50" href={`/t/${tenantSlug}/administration/documents/${document.id}`}>Details</Link><DocumentDeleteAction tenantSlug={tenantSlug} document={document} onDeleted={(updated) => setDocuments(current => current?.map(item => item.id === updated.id ? {
          ...item,
          is_deleted: updated.is_deleted,
          processing_status: updated.processing_status,
          blocking_reason: updated.blocking_reason,
          delete_eligible: updated.delete_eligible,
          delete_unavailable_reason: updated.delete_unavailable_reason,
          deletion_in_progress: updated.deletion_in_progress,
          indexed: updated.indexed,
          searchable: updated.searchable,
        } : item) ?? [])} /></div></td>
      </tr>)}</tbody>
    </table></div>}
    {!documents && <p className="text-sm text-slate-500">Loading documents…</p>}
  </TenantAdministration>;
}
