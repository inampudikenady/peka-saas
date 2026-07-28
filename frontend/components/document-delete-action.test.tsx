import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { DocumentDeleteAction } from "./document-delete-action";

const deleteDocument = vi.fn();

vi.mock("@/lib/api", () => ({
  tenantApi: {
    deleteDocument: (...args: unknown[]) => deleteDocument(...args),
  },
}));

const activeDocument = {
  id: "doc-1",
  connector_id: "connector-1",
  filename: "peka-live-charlie.xlsx",
  is_deleted: false,
  delete_eligible: true,
  delete_unavailable_reason: null,
  deletion_in_progress: false,
};

beforeEach(() => {
  deleteDocument.mockReset();
});

it("confirms the named document and warns that PEKA knowledge is affected", async () => {
  const onDeleted = vi.fn();
  deleteDocument.mockResolvedValue({
    ...activeDocument,
    is_deleted: true,
    delete_eligible: false,
    delete_unavailable_reason: "Deletion is already in progress.",
    deletion_in_progress: true,
  });
  render(
    <DocumentDeleteAction
      tenantSlug="acme"
      document={activeDocument}
      onDeleted={onDeleted}
    />
  );

  fireEvent.click(screen.getByRole("button", { name: "Delete" }));
  expect(screen.getByRole("dialog", {
    name: "Delete peka-live-charlie.xlsx",
  })).toBeInTheDocument();
  expect(screen.getByText(
    "This document will be removed from PEKA knowledge."
  )).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Confirm delete" }));

  await waitFor(() => expect(deleteDocument).toHaveBeenCalledWith(
    "acme", "doc-1", "connector-1"
  ));
  expect(onDeleted).toHaveBeenCalledOnce();
});

it("does not show a delete button for deleted documents", () => {
  render(
    <DocumentDeleteAction
      tenantSlug="acme"
      document={{
        ...activeDocument,
        is_deleted: true,
        delete_eligible: false,
        delete_unavailable_reason: "This document has already been deleted.",
      }}
      onDeleted={vi.fn()}
    />
  );

  expect(screen.queryByRole("button", { name: "Delete" })).not.toBeInTheDocument();
  expect(screen.getByText("Deleted")).toHaveAttribute(
    "title", "This document has already been deleted."
  );
});

it("disables deletion while a tombstone is already in progress", () => {
  render(
    <DocumentDeleteAction
      tenantSlug="acme"
      document={{
        ...activeDocument,
        is_deleted: true,
        delete_eligible: false,
        deletion_in_progress: true,
        delete_unavailable_reason: "Deletion is already in progress.",
      }}
      onDeleted={vi.fn()}
    />
  );

  expect(screen.getByRole("button", { name: "Deleting…" })).toBeDisabled();
});

it("shows a reason when legacy ownership cannot be established", () => {
  render(
    <DocumentDeleteAction
      tenantSlug="acme"
      document={{
        ...activeDocument,
        delete_eligible: false,
        delete_unavailable_reason:
          "Document connector ownership cannot be established safely.",
      }}
      onDeleted={vi.fn()}
    />
  );

  expect(screen.getByText("Delete unavailable")).toHaveAttribute(
    "title", "Document connector ownership cannot be established safely."
  );
  expect(screen.queryByRole("button", { name: "Delete" })).not.toBeInTheDocument();
});
