import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { act } from "react";
import { hydrateRoot } from "react-dom/client";
import { renderToString } from "react-dom/server";
import { beforeEach, expect, it, vi } from "vitest";
import {
  AssistantMarkdown,
  codeTextFromReactNode,
} from "@/components/assistant-markdown";

const citation = {
  citation_id: "C1",
  source_type: "document",
  document_id: "document-1",
  version_id: "version-1",
  chunk_id: "chunk-1",
  title: "Runbook",
  page_number: 2,
  section_title: "Install",
  sheet_name: null,
  row_start: null,
  row_end: null,
  score: 0.9,
  excerpt: "Install it.",
  document_type: "application/pdf",
  source_system: "Knowledge",
  source_id: "source-1",
  ingested_at: "2026-01-01T00:00:00Z",
  revision: "sha256:value",
  sensitive_content_redacted: false,
  redaction_categories: [],
};

const writeText = vi.fn();

beforeEach(() => {
  writeText.mockReset();
  writeText.mockResolvedValue(undefined);
  Object.defineProperty(navigator, "clipboard", {
    configurable: true,
    value: { writeText },
  });
});

it("renders structured Markdown and copies fenced code", async () => {
  render(
    <AssistantMarkdown
      content={[
        "## Overview",
        "",
        "Use **approved settings** on `host-1`.",
        "",
        "- First bullet",
        "- Second bullet",
        "",
        "1. Prepare",
        "2. Verify",
        "",
        "```bash",
        "peka verify --host host-1",
        "```",
        "",
        "> Keep credentials in the password manager.",
      ].join("\n")}
      citations={[]}
      onCitation={vi.fn()}
    />,
  );

  expect(screen.getByRole("heading", { name: "Overview", level: 2 })).toBeInTheDocument();
  expect(screen.getByText("approved settings").tagName).toBe("STRONG");
  expect(screen.getByText("host-1", { selector: "code" })).toBeInTheDocument();
  expect(screen.getAllByRole("list")).toHaveLength(2);
  expect(screen.getByText("Prepare").closest("ol")).toBeInTheDocument();
  expect(screen.getByText(/Keep credentials/).closest("blockquote")).toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", { name: "Copy code" }));
  await waitFor(() =>
    expect(writeText).toHaveBeenCalledWith("peka verify --host host-1"),
  );
  expect(screen.getByRole("button", { name: "Copied" })).toBeInTheDocument();
});

it.each([
  ["bash", "useradd -g dba \\\n  -d /home/kohlerdba \\\n  -m kohlerdba"],
  ["shell", "printf '%s\\n' first\nprintf '%s\\n' second"],
  ["text", "literal <code> text\n  with indentation"],
  ["json", '{\n  "enabled": true\n}'],
  ["yaml", "service:\n  enabled: true"],
  ["made-up-language", "unknown --language\n  stays plain"],
])("renders and copies an exact %s fenced block", async (language, code) => {
  const view = render(
    <AssistantMarkdown
      content={`\`\`\`${language}\n${code}\n\`\`\``}
      citations={[]}
      onCitation={vi.fn()}
    />,
  );

  expect(view.container.querySelector("pre code")?.textContent).toBe(code);
  expect(view.container).not.toHaveTextContent("[object Object]");
  fireEvent.click(screen.getByRole("button", { name: "Copy code" }));
  await waitFor(() => expect(writeText).toHaveBeenCalledWith(code));
});

it("extracts exact code from nested React children without serializing objects", () => {
  const nested = (
    <>
      <span>first line{"\n"}</span>
      <span><strong>{"  indented"}</strong></span>
      {{"internal": "not renderable"} as unknown as React.ReactNode}
    </>
  );

  expect(codeTextFromReactNode(nested)).toBe("first line\n  indented");
  expect(codeTextFromReactNode(nested)).not.toContain("[object Object]");
});

it("keeps citations interactive in bullets and after inline code", () => {
  const onCitation = vi.fn();
  render(
    <AssistantMarkdown
      content={"- Configure `host-1` securely. [C1]"}
      citations={[citation]}
      onCitation={onCitation}
    />,
  );

  expect(screen.getByText("host-1", { selector: "code" })).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "[C1]" }));
  expect(onCitation).toHaveBeenCalledWith(citation);
});

it("ignores raw HTML and rejects unsafe link protocols", () => {
  const { container } = render(
    <AssistantMarkdown
      content={'<img src=x onerror="alert(1)"> [unsafe](javascript:alert(1))'}
      citations={[]}
      onCitation={vi.fn()}
    />,
  );

  expect(container.querySelector("img")).not.toBeInTheDocument();
  expect(screen.getByText("unsafe")).toBeInTheDocument();
  expect(screen.queryByRole("link", { name: "unsafe" })).not.toBeInTheDocument();
});

it("renders connector-owned Zammad links with safe external navigation", () => {
  render(
    <AssistantMarkdown
      content={"[#11004 — Reboot required](http://zammad.example.test/#ticket/zoom/123)"}
      citations={[]}
      onCitation={vi.fn()}
    />,
  );
  const link = screen.getByRole("link", { name: "#11004 — Reboot required" });
  expect(link).toHaveAttribute("href", "http://zammad.example.test/#ticket/zoom/123");
  expect(link).toHaveAttribute("target", "_blank");
  expect(link).toHaveAttribute("rel", expect.stringContaining("noopener"));
  expect(link).toHaveAttribute("rel", expect.stringContaining("noreferrer"));
});

it("renders old plain text and incomplete streamed code fences safely", () => {
  const { rerender } = render(
    <AssistantMarkdown
      content={"Previously stored plain-text answer."}
      citations={[]}
      onCitation={vi.fn()}
    />,
  );
  expect(screen.getByText("Previously stored plain-text answer.")).toBeInTheDocument();

  rerender(
    <AssistantMarkdown
      content={"## Running\n\n```bash\npeka verify"}
      citations={[]}
      onCitation={vi.fn()}
    />,
  );
  expect(screen.getByRole("heading", { name: "Running" })).toBeInTheDocument();
  expect(screen.getByText("peka verify", { selector: "code" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Copy code" })).toBeInTheDocument();
});

it("upgrades streamed citation text to an evidence button when citations arrive", () => {
  const onCitation = vi.fn();
  const view = render(
    <AssistantMarkdown
      content={"- Configure `host-1`. [C1]"}
      citations={[]}
      onCitation={onCitation}
    />,
  );
  expect(screen.queryByRole("button", { name: "[C1]" })).not.toBeInTheDocument();
  expect(screen.getByRole("listitem")).toHaveTextContent("[C1]");

  view.rerender(
    <AssistantMarkdown
      content={"- Configure `host-1`. [C1]"}
      citations={[citation]}
      onCitation={onCitation}
    />,
  );
  fireEvent.click(screen.getByRole("button", { name: "[C1]" }));
  expect(onCitation).toHaveBeenCalledWith(citation);
});

it("never nests citation actions inside buttons or links", () => {
  const { container } = render(
    <AssistantMarkdown
      content={[
        "- First paragraph with evidence. [C1]",
        "",
        "  Continued list content.",
        "",
        "[Linked evidence [C1]](https://example.test)",
      ].join("\n")}
      citations={[citation]}
      onCitation={vi.fn()}
    />,
  );

  const citations = screen.getAllByRole("button", { name: "[C1]" });
  expect(citations).toHaveLength(2);
  expect(citations[0].tabIndex).toBe(0);
  expect(container.querySelector("button button")).toBeNull();
  expect(container.querySelector("a button")).toBeNull();
});

it("server markup hydrates without nested-button or mismatch warnings", async () => {
  const props = {
    content: "- Hydrated evidence. [C1]",
    citations: [citation],
    onCitation: vi.fn(),
  };
  const markup = renderToString(<AssistantMarkdown {...props} />);
  const container = document.createElement("div");
  container.innerHTML = markup;
  document.body.appendChild(container);
  const consoleError = vi.spyOn(console, "error").mockImplementation(() => {});

  let root: ReturnType<typeof hydrateRoot> | undefined;
  await act(async () => {
    root = hydrateRoot(container, <AssistantMarkdown {...props} />);
  });

  expect(container.querySelector("button button")).toBeNull();
  expect(consoleError.mock.calls.flat().join(" ")).not.toMatch(
    /hydration|cannot be a descendant|did not match/i,
  );
  await act(async () => root?.unmount());
  consoleError.mockRestore();
  container.remove();
});
