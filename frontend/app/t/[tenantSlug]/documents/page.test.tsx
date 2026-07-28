import { render, screen, waitFor } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import Page from "./page";

const documents = vi.fn().mockResolvedValue([
  { id: "doc-1", connector_id: "connector-1", source_id: "files", filename: "policy.pdf", mime_type: "application/pdf", ingestion_status: "INDEXED", processing_status: "Indexed", blocking_reason: null, worker_status: "Idle", chunk_count: 4, embedding_status: "Complete", indexed: true, searchable: true, is_deleted: false, delete_eligible: true, delete_unavailable_reason: null, deletion_in_progress: false, updated_at: "2026-07-20T11:00:00Z" },
  { id: "doc-2", connector_id: "connector-1", source_id: "files", filename: "queued.txt", mime_type: "text/plain", ingestion_status: "RECEIVED", processing_status: "Queued", blocking_reason: null, worker_status: "Idle", chunk_count: 0, embedding_status: "Pending", indexed: false, searchable: false, is_deleted: false, delete_eligible: true, delete_unavailable_reason: null, deletion_in_progress: false, updated_at: "2026-07-20T11:01:00Z" },
  { id: "doc-3", connector_id: "connector-1", source_id: "files", filename: "legacy.docx", mime_type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document", ingestion_status: "FAILED", processing_status: "Failed", blocking_reason: null, worker_status: "Idle", chunk_count: 0, embedding_status: "Failed", indexed: false, searchable: false, is_deleted: false, delete_eligible: true, delete_unavailable_reason: null, deletion_in_progress: false, updated_at: "2026-07-20T11:02:00Z" },
  { id: "doc-4", connector_id: "connector-1", source_id: "files", filename: "legacy.xlsx", mime_type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", ingestion_status: "EMBEDDING", processing_status: "Embedding", blocking_reason: null, worker_status: "Idle", chunk_count: 2, embedding_status: "Embedding", indexed: false, searchable: false, is_deleted: false, delete_eligible: true, delete_unavailable_reason: null, deletion_in_progress: false, updated_at: "2026-07-20T11:03:00Z" },
]);
vi.mock("next/navigation", () => ({ useParams: () => ({ tenantSlug: "acme" }) }));
vi.mock("@/hooks/use-tenant-user", () => ({ useTenantUser: () => ({ user: { role: "tenant_admin", tenant_name: "Acme", full_name: "Admin", auth_source: "local" } }) }));
vi.mock("@/lib/api", () => ({ tenantApi: { documents: (...args: unknown[]) => documents(...args) } }));
vi.mock("@/components/tenant-shell", () => ({ TenantShell: ({ children }: { children: React.ReactNode }) => <div>{children}</div> }));

it("renders connector documents with ingestion status", async () => {
  render(<Page />);
  await waitFor(() => expect(screen.getByRole("link", { name: "policy.pdf" })).toBeInTheDocument());
  expect(screen.getByText("Worker: Idle")).toBeInTheDocument();
  expect(screen.getByText("Queued")).toBeInTheDocument();
  expect(screen.queryByText("RECEIVED")).not.toBeInTheDocument();
  expect(screen.getAllByText("files")).toHaveLength(4);
  expect(screen.getByText("4")).toBeInTheDocument();
  expect(screen.getByText("Complete")).toBeInTheDocument();
  expect(screen.getAllByText("Indexed")).toHaveLength(3);
  expect(screen.getAllByText("Searchable")).toHaveLength(2);
  expect(screen.queryByText("handbook/policy.pdf")).not.toBeInTheDocument();
  expect(screen.queryByText(/sha256:/)).not.toBeInTheDocument();
  expect(screen.getAllByRole("button", { name: "Delete" })).toHaveLength(4);
  expect(screen.getAllByRole("link", { name: "Details" })).toHaveLength(4);
  expect(documents).toHaveBeenCalledWith("acme", false);
});
