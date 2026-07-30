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
import { formatDateTime } from "@/lib/datetime";
import type { ManagedDocument } from "@/lib/types";

export default function DocumentDetailPage() {
  const { tenantSlug, documentId } = useParams<{ tenantSlug: string; documentId: string }>();
  const { user } = useTenantUser(tenantSlug);
  const [document, setDocument] = useState<ManagedDocument | null>(null);
  const [error, setError] = useState("");
  const [working, setWorking] = useState(false);
  useEffect(() => {
    void tenantApi.document(tenantSlug, documentId).then(setDocument).catch((caught) => setError(caught.message));
  }, [tenantSlug, documentId]);
  if (!user) return <main className="p-8">Loading…</main>;

  async function action(kind: "retry" | "reindex") {
    if (!document) return;
    setWorking(true);
    setError("");
    try {
      setDocument(await (
        kind === "retry"
          ? tenantApi.retryDocument(tenantSlug, document.id)
          : tenantApi.reindexDocument(tenantSlug, document.id)
      ));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Document action failed.");
    } finally {
      setWorking(false);
    }
  }

  const version = document?.current_version;
  const timeline: [string, string | null][] = version ? [
    ["Received", version.received_at],
    ["Stored", version.stored_at],
    ["Queued", version.queued_at],
    ["Parsing started", version.parsing_started_at],
    ["Parsing completed", version.parsed_at],
    ["Chunking started", version.chunking_started_at],
    ["Chunking completed", version.chunked_at],
    ["Embedding started", version.embedding_started_at],
    ["Embedding completed", version.embedding_completed_at],
    ["Indexing started", version.indexing_started_at],
    ["Indexing completed", version.indexing_completed_at],
  ] : [];

  return (
    <TenantAdministration title="Document details">
      {error && <Alert>{error}</Alert>}
      {!document ? <p className="text-sm text-slate-500">Loading document…</p> : (
        <div className="space-y-5">
          <div className="flex justify-end gap-2">
            {user.role === "tenant_admin" && <>
              {!document.is_deleted && <Button variant="outline" disabled={working} onClick={() => action("reindex")}>Re-index</Button>}
              {!document.is_deleted && (
                document.current_version?.ingestion_status === "FAILED"
                || ["NOT_CONFIGURED", "EMBEDDING_UNAVAILABLE", "QDRANT_UNAVAILABLE"].includes(document.current_version?.error_code ?? "")
              ) && <Button variant="outline" disabled={working} onClick={() => action("retry")}>Retry</Button>}
              <DocumentDeleteAction tenantSlug={tenantSlug} document={document} onDeleted={setDocument} />
            </>}
          </div>
          <div className="flex flex-wrap gap-2">
            <PipelineBadge label={document.processing_status} ready={document.processing_status.startsWith("Indexed")} title={document.blocking_reason ?? `Current pipeline state: ${document.processing_status}.`} />
            <PipelineBadge label={`Worker: ${document.worker_status}`} ready={["Idle", "Busy"].includes(document.worker_status)} title="Health reported by the PEKA ingestion runtime." />
            <PipelineBadge label={`${document.chunk_count} chunks`} ready={document.chunk_count > 0} title="Chunks generated for the current document version." />
            <PipelineBadge label={`Embedding: ${document.embedding_status}`} ready={document.embedding_status === "Complete"} title="Embedding state for the current document version." />
            <PipelineBadge label={document.indexed ? "Indexed" : "Not indexed"} ready={document.indexed} title="Whether the current chunks were written to Qdrant." />
            <PipelineBadge label={document.searchable ? "Searchable" : "Not searchable"} ready={document.searchable} title="Whether the current document version is available to PEKA Knowledge Search." />
          </div>
          <div className="grid gap-5 lg:grid-cols-2">
            <Card>
              <CardHeader><h2 className="text-lg font-semibold">{document.filename}</h2></CardHeader>
              <CardContent><dl className="space-y-3 text-sm"><Field label="Path" value={document.relative_path} /><Field label="Extension" value={document.extension} /><Field label="Declared MIME type" value={document.mime_type} /><Field label="Source" value={document.source_id} /><Field label="Last-seen connector ID" value={document.connector_id ?? "Historical source"} /><Field label="Document key" value={document.document_key} /><Field label="Deleted" value={document.is_deleted ? "Yes" : "No"} /></dl></CardContent>
            </Card>
            <Card>
              <CardHeader><h2 className="text-lg font-semibold">Current version</h2></CardHeader>
              <CardContent>{!version ? <p className="text-sm text-slate-500">No current binary version.</p> : <dl className="space-y-3 text-sm"><Field label="Status" value={document.processing_status} /><Field label="Source freshness" value={document.source_freshness} /><Field label="Last synchronized" value={document.last_synchronized_at ? formatDateTime(document.last_synchronized_at, user.tenant_timezone) : "Historical source"} /><Field label="SHA-256" value={version.content_hash} /><Field label="Storage" value={version.storage_status} /><Field label="Detected format" value={version.detected_format ?? "Pending"} /><Field label="Source format" value={version.source_format ?? "Pending"} /><Field label="Detection confidence" value={version.format_detection_confidence == null ? "Pending" : `${Math.round(version.format_detection_confidence * 100)}%`} />{version.format_detection_reason && <Field label="Detection reason" value={version.format_detection_reason} />}<Field label="Parser" value={version.parser_name ?? "Pending"} /><Field label="Chunker" value={version.chunker_name ?? "Pending"} /><Field label="Embedding" value={version.embedding_model ?? document.embedding_status} /><Field label="Chunks" value={String(document.chunk_count)} />{document.blocking_reason && <Field label="Blocking reason" value={document.blocking_reason} />}{version.error_message && <Field label="Last error" value={version.error_message} />}</dl>}</CardContent>
            </Card>
          </div>
          {version && <Card>
            <CardHeader><h2 className="text-lg font-semibold">Ingestion timeline</h2></CardHeader>
            <CardContent><dl className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">{timeline.map(([label, timestamp]) => <Field key={label} label={label} value={timestamp ? formatDateTime(timestamp, user.tenant_timezone) : "Pending"} />)}</dl></CardContent>
          </Card>}
          <Card>
            <CardHeader><h2 className="text-lg font-semibold">Version history</h2></CardHeader>
            <CardContent><div className="space-y-3">{document.versions.map((item) => <div key={item.id} className="rounded border p-3 text-sm"><div className="flex justify-between gap-3"><span className="font-medium">{item.ingestion_status}</span><time className="text-slate-500">{formatDateTime(item.received_at, user.tenant_timezone)}</time></div><div className="mt-1 break-all text-xs text-slate-500">{item.content_hash}</div></div>)}</div></CardContent>
          </Card>
        </div>
      )}
    </TenantAdministration>
  );
}

function PipelineBadge({ label, ready, title }: { label: string; ready: boolean; title: string }) {
  return <span title={title} className={`rounded-full px-2 py-1 text-xs font-medium ${ready ? "bg-emerald-100 text-emerald-800" : "bg-amber-100 text-amber-800"}`}>{label}</span>;
}

function Field({ label, value }: { label: string; value: string }) {
  return <div><dt className="text-xs font-medium uppercase text-slate-500">{label}</dt><dd className="break-all">{value}</dd></div>;
}
