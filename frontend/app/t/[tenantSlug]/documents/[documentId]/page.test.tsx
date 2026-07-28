import { render, screen, waitFor } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import Page from "./page";

const document = vi.fn().mockResolvedValue({
  id: "doc-1",
  connector_id: "connector-1",
  source_id: "files",
  document_key: "policy.pdf",
  filename: "policy.pdf",
  relative_path: "policy.pdf",
  mime_type: "application/pdf",
  is_deleted: false,
  current_version: {
    id: "version-1",
    content_hash: "sha256:abc",
    size_bytes: 100,
    ingestion_status: "INDEXED",
    storage_status: "STORED",
    parser_name: "pdf",
    chunker_name: "structure-aware-word-window",
    embedding_provider: "openai-compatible",
    embedding_model: "nomic-embed-text",
    received_at: "2026-07-23T11:00:00Z",
    indexed_at: "2026-07-23T11:00:02Z",
    error_code: null,
    error_message: null,
  },
  versions: [],
  chunk_count: 3,
  embedding_status: "Complete",
  indexed: true,
  searchable: true,
  processing_status: "Indexed",
  blocking_reason: null,
  delete_eligible: true,
  delete_unavailable_reason: null,
  deletion_in_progress: false,
  worker_status: "Idle",
  created_at: "2026-07-23T11:00:00Z",
  updated_at: "2026-07-23T11:00:02Z",
});

vi.mock("next/navigation", () => ({
  useParams: () => ({ tenantSlug: "acme", documentId: "doc-1" }),
  useRouter: () => ({ replace: vi.fn() }),
  usePathname: () => "/t/acme/administration/documents/doc-1",
}));
vi.mock("@/hooks/use-tenant-user", () => ({
  useTenantUser: () => ({ user: { role: "tenant_admin" } }),
}));
vi.mock("@/lib/api", () => ({
  tenantApi: {
    document: (...args: unknown[]) => document(...args),
    retryDocument: vi.fn(),
    reindexDocument: vi.fn(),
    deleteDocument: vi.fn(),
  },
}));

it("renders live chunk, embedding, indexed, and searchable state", async () => {
  render(<Page />);
  await waitFor(() => expect(
    screen.getByRole("heading", { name: "policy.pdf" })
  ).toBeInTheDocument());
  expect(screen.getByText("3 chunks")).toBeInTheDocument();
  expect(screen.getByText("Embedding: Complete")).toBeInTheDocument();
  expect(screen.getAllByText("Indexed")).toHaveLength(3);
  expect(screen.getByText("Worker: Idle")).toBeInTheDocument();
  expect(screen.getByText("Searchable")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Re-index" })).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Retry" })).not.toBeInTheDocument();
  expect(document).toHaveBeenCalledWith("acme", "doc-1");
});
