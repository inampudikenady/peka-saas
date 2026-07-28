"use client";

import { useState } from "react";
import { Alert } from "@/components/alert";
import { Button } from "@/components/ui/button";
import { tenantApi } from "@/lib/api";
import type { ManagedDocument, ManagedDocumentListItem } from "@/lib/types";

type DeletableDocument = Pick<
  ManagedDocumentListItem,
  "id" | "connector_id" | "filename" | "delete_eligible" |
  "delete_unavailable_reason" | "deletion_in_progress" | "is_deleted"
>;

export function DocumentDeleteAction({
  tenantSlug,
  document,
  onDeleted,
}: {
  tenantSlug: string;
  document: DeletableDocument;
  onDeleted: (updated: ManagedDocument) => void;
}) {
  const [confirming, setConfirming] = useState(false);
  const [working, setWorking] = useState(false);
  const [error, setError] = useState("");

  if (document.deletion_in_progress) {
    return (
      <Button
        variant="destructive"
        className="h-8 px-3"
        disabled
        title={document.delete_unavailable_reason ?? "Deletion is already in progress."}
      >
        Deleting…
      </Button>
    );
  }

  if (!document.delete_eligible) {
    const label = document.is_deleted ? "Deleted" : "Delete unavailable";
    return (
      <span
        className="text-xs text-slate-500"
        title={document.delete_unavailable_reason ?? label}
      >
        {label}
      </span>
    );
  }

  if (!confirming) {
    return (
      <Button
        variant="destructive"
        className="h-8 px-3"
        title={`Delete ${document.filename} from PEKA`}
        onClick={() => setConfirming(true)}
      >
        Delete
      </Button>
    );
  }

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={`Delete ${document.filename}`}
      className="min-w-72 rounded-md border border-red-200 bg-red-50 p-3 text-left"
    >
      <p className="font-medium text-red-900">Delete {document.filename}?</p>
      <p className="mt-1 text-xs text-red-800">
        This document will be removed from PEKA knowledge.
      </p>
      {error && <div className="mt-2"><Alert>{error}</Alert></div>}
      <div className="mt-3 flex gap-2">
        <Button
          variant="destructive"
          className="h-8 px-3"
          disabled={working}
          onClick={async () => {
            setWorking(true);
            setError("");
            try {
              onDeleted(await tenantApi.deleteDocument(
                tenantSlug, document.id, document.connector_id
              ));
              setConfirming(false);
            } catch (caught) {
              setError(
                caught instanceof Error ? caught.message : "Document deletion failed."
              );
            } finally {
              setWorking(false);
            }
          }}
        >
          {working ? "Deleting…" : "Confirm delete"}
        </Button>
        <Button
          variant="outline"
          className="h-8 px-3"
          disabled={working}
          onClick={() => { setConfirming(false); setError(""); }}
        >
          Cancel
        </Button>
      </div>
    </div>
  );
}
