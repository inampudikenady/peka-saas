import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import Page from "./page";

const mocks = vi.hoisted(() => ({
  streamAnswer: vi.fn(), conversations: vi.fn(), conversation: vi.fn(),
  assistantSuggestions: vi.fn(),
  renameConversation: vi.fn(), archiveConversation: vi.fn(),
  deleteConversation: vi.fn(), citationEvidence: vi.fn(), closeMobile: vi.fn(),
  tenantSlug: "acme",
  conversationParam: null as string | null,
  userRole: "tenant_user",
  push: vi.fn(),
  replace: vi.fn(),
  clipboardWrite: vi.fn(),
}));
vi.mock("next/navigation", () => ({
  useParams: () => ({ tenantSlug: mocks.tenantSlug }),
  useRouter: () => ({ push: mocks.push, replace: mocks.replace }),
  useSearchParams: () => ({
    get: (key: string) => key === "conversation" ? mocks.conversationParam : null,
  }),
}));
vi.mock("@/hooks/use-tenant-user", () => ({ useTenantUser: () => ({ user: { role: mocks.userRole, tenant_name: "Acme", full_name: "User", auth_source: "sso" }, error: "" }) }));
vi.mock("@/lib/api", () => ({ tenantApi: mocks }));
vi.mock("@/components/tenant-shell", () => ({
  TenantShell: ({
    children, aiSidebarTop, aiSidebarContent,
  }: {
    children: React.ReactNode;
    aiSidebarTop?: (controls: { closeMobile: () => void }) => React.ReactNode;
    aiSidebarContent?: (controls: { closeMobile: () => void }) => React.ReactNode;
  }) => (
    <div>
      <aside className="bg-slate-950 text-white">
        {aiSidebarTop?.({ closeMobile: mocks.closeMobile })}
        {aiSidebarContent?.({ closeMobile: mocks.closeMobile })}
      </aside>
      {children}
    </div>
  ),
}));

const citation = {
  citation_id: "C1", source_type: "document", document_id: "document-private-id",
  version_id: "version-private-id", chunk_id: "chunk-private-id", title: "vManager Guide",
  page_number: 12, section_title: "Installation", sheet_name: null,
  row_start: null, row_end: null, score: 0.91,
  excerpt: "Install the signed package from the approved repository.",
  document_type: "application/pdf", source_system: "vCenter",
  source_id: "source-private-id", ingested_at: "2026-01-01T00:00:00Z",
  revision: "sha256:revision", sensitive_content_redacted: false,
  redaction_categories: [],
};

const storedPreferences = new Map<string, string>();

beforeEach(() => {
  mocks.tenantSlug = "acme";
  mocks.conversationParam = null;
  mocks.userRole = "tenant_user";
  for (const mock of [
    mocks.streamAnswer, mocks.conversations, mocks.conversation,
    mocks.assistantSuggestions,
    mocks.renameConversation, mocks.archiveConversation, mocks.deleteConversation,
    mocks.citationEvidence, mocks.closeMobile, mocks.push, mocks.replace,
    mocks.clipboardWrite,
  ]) mock.mockReset();
  mocks.clipboardWrite.mockResolvedValue(undefined);
  Object.defineProperty(navigator, "clipboard", {
    configurable: true,
    value: { writeText: mocks.clipboardWrite },
  });
  storedPreferences.clear();
  vi.stubGlobal("localStorage", {
    getItem: (key: string) => storedPreferences.get(key) ?? null,
    setItem: (key: string, value: string) => storedPreferences.set(key, value),
    removeItem: (key: string) => storedPreferences.delete(key),
    clear: () => storedPreferences.clear(),
  });
  mocks.conversations.mockResolvedValue({ items: [], total: 0, limit: 30, offset: 0 });
  mocks.assistantSuggestions.mockResolvedValue({
    has_indexed_knowledge: true,
    suggestions: ["Summarize Acme handbook."],
    onboarding_guidance: null,
  });
  mocks.citationEvidence.mockResolvedValue({
    conversation_id: "conversation-1", message_id: "message-1", citation,
  });
});

it("streams an answer and opens the stored citation evidence", async () => {
  mocks.conversation.mockResolvedValue({
    id: "conversation-1", title: "Installing vManager",
    created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:01Z",
    last_message_at: "2026-01-01T00:00:01Z", is_archived: false,
    last_message_preview: "Install the signed package.",
    messages: [{
      id: "message-1", role: "assistant",
      content: "- Install the signed package. [C1]\n\n  Verify the service.",
      status: "completed", created_at: "2026-01-01T00:00:00Z",
      completed_at: "2026-01-01T00:00:01Z", model: "qwen3:8b",
      prompt_version: "ai-answer-v1", citations: [citation],
      retrieval_metadata: {}, failure_metadata: {}, context_message_ids: [],
    }],
  });
  mocks.streamAnswer.mockImplementation(async (_tenantSlug, _request, callbacks) => {
    callbacks.onStatus({
      status: "started", conversation_id: "conversation-1",
      assistant_message_id: "message-1",
    });
    callbacks.onToken("Install the signed package. [C1]");
    callbacks.onCitations([citation]);
    callbacks.onComplete({ grounded: true, request_id: "request-1" });
  });
  render(<Page />);
  expect(screen.getByRole("heading", { name: "How can PEKA help?" })).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("Question"), { target: { value: "How do I install vManager?" } });
  fireEvent.click(screen.getByRole("button", { name: "Send" }));
  await screen.findByRole("heading", { name: "Installing vManager" });
  const citationButton = await screen.findByRole("button", { name: "[C1]" });
  expect(citationButton.closest(".rounded-xl")).toHaveClass("w-full", "min-w-0");
  expect(screen.getByRole("main")).toHaveClass("max-w-5xl", "min-w-0");
  expect(screen.getByLabelText("Question").parentElement).toHaveClass("shrink-0");
  fireEvent.click(citationButton);
  await screen.findByRole("dialog", { name: "Citation evidence" });
  expect(screen.getAllByText("vManager Guide")).toHaveLength(2);
  expect(screen.getByText("Installation · Page 12")).toBeInTheDocument();
  expect(screen.getByText(citation.excerpt)).toBeInTheDocument();
  expect(screen.queryByText("chunk-private-id")).not.toBeInTheDocument();
  expect(mocks.citationEvidence).toHaveBeenCalledWith(
    "acme", "conversation-1", "message-1", "C1",
  );
  expect(mocks.replace).toHaveBeenCalledWith(
    "/t/acme/ai?conversation=conversation-1",
  );
  expect(document.querySelector("button button")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Copy answer" }));
  await waitFor(() => expect(mocks.clipboardWrite).toHaveBeenCalledWith(
    "- Install the signed package. [C1]\n\n  Verify the service.",
  ));
  fireEvent.click(screen.getByRole("button", { name: "Helpful answer" }));
  fireEvent.click(screen.getByRole("button", { name: "Unhelpful answer" }));
  const history = screen.getByRole("region", { name: "Conversation history" });
  expect(history).toBeInTheDocument();
  expect(history).not.toHaveClass("bg-white");
  expect(history.closest("aside")).toHaveClass("bg-slate-950");
});

it("renders insufficient evidence without citations", async () => {
  mocks.streamAnswer.mockImplementation(async (_tenantSlug, _request, callbacks) => {
    callbacks.onToken("I could not find enough information.");
    callbacks.onCitations([]);
    callbacks.onComplete({ grounded: false, code: "INSUFFICIENT_EVIDENCE", request_id: "request-2" });
  });
  render(<Page />);
  fireEvent.click(await screen.findByRole("button", { name: "Summarize Acme handbook." }));
  await waitFor(() => expect(screen.getByText(/could not find enough indexed evidence/i)).toBeInTheDocument());
  expect(screen.queryByRole("region", { name: "Citations" })).not.toBeInTheDocument();
});

it("supports stop generation", async () => {
  mocks.streamAnswer.mockImplementation(
    (_tenantSlug, _request, _callbacks, signal: AbortSignal) =>
      new Promise((_resolve, reject) =>
        signal.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError"))),
      ),
  );
  render(<Page />);
  fireEvent.change(screen.getByLabelText("Question"), { target: { value: "How?" } });
  fireEvent.click(screen.getByRole("button", { name: "Send" }));
  const userCard = screen.getByText("How?").closest(".rounded-xl");
  expect(userCard).toHaveClass("w-fit", "max-w-[78%]");
  fireEvent.click(await screen.findByRole("button", { name: "Stop generation" }));
  await waitFor(() => expect(screen.getByText("Generation stopped.")).toBeInTheDocument());
});

it("New chat cancels an active stream and leaves a clean composer", async () => {
  let activeSignal: AbortSignal | undefined;
  mocks.streamAnswer.mockImplementation(
    (_tenantSlug, _request, _callbacks, signal: AbortSignal) =>
      new Promise((_resolve, reject) => {
        activeSignal = signal;
        signal.addEventListener("abort", () =>
          reject(new DOMException("Aborted", "AbortError")),
        );
      }),
  );
  render(<Page />);
  fireEvent.change(screen.getByLabelText("Question"), {
    target: { value: "Long-running question" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Send" }));
  await screen.findByRole("button", { name: "Stop generation" });

  fireEvent.click(screen.getByRole("button", { name: "New chat" }));
  expect(activeSignal?.aborted).toBe(true);
  expect(screen.getByRole("heading", { name: "How can PEKA help?" })).toBeInTheDocument();
  await waitFor(() => expect(screen.getByLabelText("Question")).toBeEnabled());
  expect(screen.queryByText("Generation stopped.")).not.toBeInTheDocument();
});

it("does not abort the active stream during a normal rerender", async () => {
  let activeSignal:AbortSignal | undefined;
  let finish: (() => void) | undefined;
  mocks.streamAnswer.mockImplementation(
    (_tenantSlug, _request, callbacks, signal: AbortSignal) =>
      new Promise<void>((resolve, reject) => {
        activeSignal = signal;
        finish = () => {
          callbacks.onComplete({ grounded: true, request_id: "request-rerender" });
          resolve();
        };
        signal.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")));
      }),
  );
  const view = render(<Page />);
  fireEvent.change(screen.getByLabelText("Question"), { target: { value: "How?" } });
  fireEvent.click(screen.getByRole("button", { name: "Send" }));
  await screen.findByRole("button", { name: "Stop generation" });
  view.rerender(<Page />);
  expect(activeSignal?.aborted).toBe(false);
  finish?.();
  await waitFor(() =>
    expect(screen.queryByRole("button", { name: "Stop generation" })).not.toBeInTheDocument(),
  );
  expect(screen.getByLabelText("Question")).toBeEnabled();
});

it("renders a safe provider-unavailable state", async () => {
  mocks.streamAnswer.mockRejectedValue(
    new Error("The AI service is temporarily unavailable."),
  );
  render(<Page />);
  fireEvent.change(screen.getByLabelText("Question"), { target: { value: "How?" } });
  fireEvent.click(screen.getByRole("button", { name: "Send" }));
  await waitFor(() =>
    expect(screen.getByText("The AI service is temporarily unavailable.")).toBeInTheDocument(),
  );
});

it("reopens stored messages without regenerating the answer", async () => {
  const summary = {
    id: "conversation-1", title: "Stored installation answer",
    created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z",
    last_message_at: "2026-01-01T00:00:00Z", is_archived: false,
    last_message_preview: "Install the package.",
  };
  mocks.conversations.mockResolvedValue({ items: [summary], total: 1, limit: 30, offset: 0 });
  mocks.conversation.mockResolvedValue({
    ...summary,
    messages: [{
      id: "message-1", role: "assistant", content: "Stored answer. [C1]",
      status: "completed", created_at: "2026-01-01T00:00:00Z",
      completed_at: "2026-01-01T00:00:01Z", model: "qwen3:8b",
      prompt_version: "ai-answer-v1", citations: [citation],
      retrieval_metadata: {}, failure_metadata: {}, context_message_ids: [],
    }],
  });
  render(<Page />);
  const title = await screen.findByText("Stored installation answer");
  fireEvent.click(title.closest("button")!);
  expect(mocks.closeMobile).toHaveBeenCalled();
  expect(mocks.push).toHaveBeenCalledWith(
    "/t/acme/ai?conversation=conversation-1",
  );
  await waitFor(() =>
    expect(title.closest("button")).toHaveAttribute("aria-current", "page"),
  );
  await screen.findByRole("button", { name: "[C1]" });
  expect(mocks.streamAnswer).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "[C1]" }));
  expect(await screen.findByText(/evidence used for this answer/i)).toBeInTheDocument();
  expect(mocks.citationEvidence).toHaveBeenCalledWith(
    "acme", "conversation-1", "message-1", "C1",
  );
});

it("clears conversation state when the active tenant changes", async () => {
  mocks.conversations
    .mockResolvedValueOnce({ items: [{
      id: "acme-chat", title: "Acme private chat", created_at: "2026-01-01T00:00:00Z",
      updated_at: "2026-01-01T00:00:00Z", last_message_at: "2026-01-01T00:00:00Z",
      is_archived: false, last_message_preview: null,
    }], total: 1, limit: 30, offset: 0 })
    .mockResolvedValueOnce({ items: [], total: 0, limit: 30, offset: 0 });
  const view = render(<Page />);
  await screen.findByText("Acme private chat");
  mocks.tenantSlug = "beta";
  view.rerender(<Page />);
  await waitFor(() => expect(screen.queryByText("Acme private chat")).not.toBeInTheDocument());
  expect(mocks.conversations).toHaveBeenLastCalledWith("beta");
  expect(mocks.assistantSuggestions).toHaveBeenLastCalledWith("beta");
});

it("shows onboarding guidance when this tenant has no indexed knowledge", async () => {
  mocks.assistantSuggestions.mockResolvedValue({
    has_indexed_knowledge: false,
    suggestions: [],
    onboarding_guidance: "Index tenant documents before asking PEKA questions.",
  });
  render(<Page />);
  expect(await screen.findByRole("heading", {
    name: "Local knowledge is not ready",
  })).toBeInTheDocument();
  expect(screen.getByText(
    "Index tenant documents before asking PEKA questions.",
  )).toBeInTheDocument();
  expect(screen.queryByRole("button", {
    name: "Summarize Acme handbook.",
  })).not.toBeInTheDocument();
});

it("filters private history, loads archives, and starts a clean chat", async () => {
  const installation = {
    id: "installation-chat", title: "Installing vManager",
    created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z",
    last_message_at: "2026-01-01T00:00:00Z", is_archived: false,
    last_message_preview: "Install the signed package.",
  };
  const database = {
    ...installation, id: "database-chat", title: "Database access",
    last_message_preview: "Use the approved database account.",
  };
  mocks.conversations
    .mockResolvedValueOnce({
      items: [installation, database], total: 2, limit: 30, offset: 0,
    })
    .mockResolvedValueOnce({ items: [], total: 0, limit: 30, offset: 0 });
  mocks.conversation.mockResolvedValue({ ...database, messages: [] });

  render(<Page />);
  await screen.findByText("Installing vManager");
  fireEvent.change(screen.getByPlaceholderText("Search conversations"), {
    target: { value: "database" },
  });
  expect(screen.queryByText("Installing vManager")).not.toBeInTheDocument();
  const databaseTitle = screen.getByText("Database access");
  fireEvent.click(databaseTitle.closest("button")!);
  await screen.findByRole("heading", { name: "Database access" });

  fireEvent.click(screen.getByRole("button", { name: "New chat" }));
  expect(screen.getByRole("heading", { name: "How can PEKA help?" })).toBeInTheDocument();
  expect(screen.getByPlaceholderText(
    "Ask PEKA about your organization’s knowledge…",
  )).toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", { name: "Archived" }));
  await waitFor(() =>
    expect(mocks.conversations).toHaveBeenLastCalledWith("acme", true),
  );
  expect(screen.getByText("Archived chats")).toBeInTheDocument();
});

it("opens an owned conversation from the URL and follows browser history", async () => {
  const conversation = {
    id: "conversation-1", title: "Direct private chat",
    created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z",
    last_message_at: "2026-01-01T00:00:00Z", is_archived: false,
    last_message_preview: "Stored answer.", messages: [],
  };
  mocks.conversationParam = conversation.id;
  mocks.conversation.mockResolvedValue(conversation);

  const view = render(<Page />);
  await screen.findByRole("heading", { name: "Direct private chat" });
  expect(mocks.conversation).toHaveBeenCalledWith("acme", "conversation-1");
  expect(mocks.streamAnswer).not.toHaveBeenCalled();

  mocks.conversationParam = null;
  view.rerender(<Page />);
  await screen.findByRole("heading", { name: "How can PEKA help?" });
  expect(screen.getByPlaceholderText(
    "Ask PEKA about your organization’s knowledge…",
  )).toBeInTheDocument();
});

it("lets tenant administrators collapse history independently", async () => {
  mocks.userRole = "tenant_admin";
  mocks.conversations.mockResolvedValue({
    items: [{
      id: "admin-chat", title: "Admin private chat",
      created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z",
      last_message_at: "2026-01-01T00:00:00Z", is_archived: false,
      last_message_preview: null,
    }],
    total: 1, limit: 30, offset: 0,
  });

  render(<Page />);
  await screen.findByText("Admin private chat");
  const collapse = screen.getByRole("button", { name: "Collapse chat history" });
  expect(collapse).toHaveAttribute("aria-expanded", "true");
  fireEvent.click(collapse);
  const expand = screen.getByRole("button", { name: "Expand chat history" });
  expect(expand).toHaveAttribute("aria-expanded", "false");
  expect(screen.queryByPlaceholderText("Search conversations")).not.toBeInTheDocument();
  expect(screen.queryByText("Admin private chat")).not.toBeInTheDocument();
  expect(screen.queryByText("Older")).not.toBeInTheDocument();
  expect(screen.queryByRole("button", {
    name: "Actions for Admin private chat",
  })).not.toBeInTheDocument();
  expect(screen.getByText("Chats")).toBeInTheDocument();
  expect(screen.getByRole("region", {
    name: "Conversation history",
  })).toHaveAttribute("data-expanded", "false");
  expect(screen.getByRole("region", {
    name: "Conversation history",
  })).toHaveClass("py-1");
  expect(localStorage.getItem("peka:assistant-history-expanded")).toBe("false");

  fireEvent.click(expand);
  expect(screen.getByRole("button", {
    name: "Collapse chat history",
  })).toHaveAttribute("aria-expanded", "true");
  expect(screen.getByPlaceholderText("Search conversations")).toBeInTheDocument();
  expect(screen.getByText("Admin private chat")).toBeInTheDocument();
  expect(localStorage.getItem("peka:assistant-history-expanded")).toBe("true");
});

it("restores the admin history preference after leaving Assistant", async () => {
  mocks.userRole = "tenant_admin";
  mocks.conversations.mockResolvedValue({
    items: [{
      id: "admin-chat", title: "Restored private chat",
      created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z",
      last_message_at: "2026-01-01T00:00:00Z", is_archived: false,
      last_message_preview: null,
    }],
    total: 1, limit: 30, offset: 0,
  });

  const assistant = render(<Page />);
  await screen.findByText("Restored private chat");
  fireEvent.click(screen.getByRole("button", { name: "Collapse chat history" }));
  assistant.unmount();

  render(<Page />);
  const expand = await screen.findByRole("button", { name: "Expand chat history" });
  expect(expand).toHaveAttribute("aria-expanded", "false");
  expect(screen.queryByText("Restored private chat")).not.toBeInTheDocument();
  expect(screen.queryByPlaceholderText("Search conversations")).not.toBeInTheDocument();
});
