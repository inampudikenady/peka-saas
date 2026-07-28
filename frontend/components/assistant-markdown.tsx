"use client";

import {
  Children,
  cloneElement,
  isValidElement,
  useState,
  type ReactNode,
} from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";
import type { AIAnswerCitation } from "@/lib/types";

function safeLinkUrl(url: string) {
  if (url.startsWith("/") || url.startsWith("#")) return url;
  try {
    const protocol = new URL(url).protocol;
    return ["http:", "https:", "mailto:"].includes(protocol) ? url : "";
  } catch {
    return "";
  }
}

function citationChildren(
  children: ReactNode,
  citations: Map<string, AIAnswerCitation>,
  onCitation: (citation: AIAnswerCitation) => void,
): ReactNode {
  return Children.map(children, (child) => {
    if (typeof child === "string") {
      return child.split(/(\[C[1-9]\d*\])/g).map((part, index) => {
        const citation = citations.get(part.slice(1, -1));
        return citation ? (
          <button
            key={`${part}-${index}`}
            type="button"
            onClick={() => onCitation(citation)}
            className="mx-0.5 inline rounded bg-blue-50 px-1 font-semibold text-blue-700 underline decoration-blue-300 hover:bg-blue-100"
          >
            {part}
          </button>
        ) : part;
      });
    }
    if (!isValidElement<{ children?: ReactNode }>(child)) return child;
    if (
      child.type === "button"
      || child.type === "a"
      || child.type === "code"
      || child.type === "pre"
    ) return child;
    return cloneElement(child, {
      children: citationChildren(child.props.children, citations, onCitation),
    });
  });
}

function containsCitation(
  children: ReactNode,
  citations: Map<string, AIAnswerCitation>,
): boolean {
  return Children.toArray(children).some((child) => {
    if (typeof child === "string") {
      return child.split(/(\[C[1-9]\d*\])/g).some(
        (part) => citations.has(part.slice(1, -1)),
      );
    }
    return isValidElement<{ children?: ReactNode }>(child)
      && containsCitation(child.props.children, citations);
  });
}

function CodeBlock({
  children,
  language,
}: {
  children: ReactNode;
  language?: string;
}) {
  const [copied, setCopied] = useState(false);
  const value = String(children).replace(/\n$/, "");

  return (
    <div className="my-4 overflow-hidden rounded-lg border border-slate-700 bg-slate-950 text-slate-100">
      <div className="flex min-h-9 items-center justify-between border-b border-slate-700 px-3 text-xs text-slate-400">
        <span>{language || "text"}</span>
        <button
          type="button"
          className="rounded px-2 py-1 hover:bg-slate-800 hover:text-white"
          onClick={async () => {
            await navigator.clipboard.writeText(value);
            setCopied(true);
            window.setTimeout(() => setCopied(false), 1200);
          }}
        >
          {copied ? "Copied" : "Copy code"}
        </button>
      </div>
      <pre className="overflow-x-auto p-4 text-sm leading-6">
        <code className="font-mono">{value}</code>
      </pre>
    </div>
  );
}

export function AssistantMarkdown({
  content,
  citations,
  onCitation,
}: {
  content: string;
  citations: AIAnswerCitation[];
  onCitation: (citation: AIAnswerCitation) => void;
}) {
  const citationMap = new Map(
    citations.map((citation) => [citation.citation_id, citation]),
  );
  const withCitations = (children: ReactNode) =>
    citationChildren(children, citationMap, onCitation);

  const components: Components = {
    h2: ({ children }) => (
      <h2 className="mb-2 mt-6 text-lg font-semibold first:mt-0">
        {withCitations(children)}
      </h2>
    ),
    h3: ({ children }) => (
      <h3 className="mb-2 mt-5 text-base font-semibold">
        {withCitations(children)}
      </h3>
    ),
    p: ({ children }) => (
      <p className="my-3 whitespace-pre-wrap first:mt-0 last:mb-0">
        {withCitations(children)}
      </p>
    ),
    ul: ({ children }) => (
      <ul className="my-3 list-disc space-y-1 pl-6">{children}</ul>
    ),
    ol: ({ children }) => (
      <ol className="my-3 list-decimal space-y-1 pl-6">{children}</ol>
    ),
    li: ({ children }) => <li>{withCitations(children)}</li>,
    blockquote: ({ children }) => (
      <blockquote className="my-4 border-l-4 border-amber-400 bg-amber-50 px-4 py-2 text-slate-700">
        {withCitations(children)}
      </blockquote>
    ),
    a: ({ children, href }) => href && !containsCitation(children, citationMap) ? (
        <a
          href={href}
          target="_blank"
          rel="noreferrer noopener"
          className="text-blue-700 underline decoration-blue-300 hover:text-blue-900"
        >
          {withCitations(children)}
        </a>
      ) : <span>{withCitations(children)}</span>,
    code: ({ children, className }) => (
      <code
        className={`${className || ""} rounded bg-slate-100 px-1.5 py-0.5 font-mono text-[0.9em] text-slate-800`}
      >
        {children}
      </code>
    ),
    pre: ({ children }) => {
      const child = isValidElement<{ children?: ReactNode; className?: string }>(
        children,
      )
        ? children
        : null;
      const language = child?.props.className?.match(/language-([\w-]+)/)?.[1];
      return (
        <CodeBlock language={language}>
          {child?.props.children ?? children}
        </CodeBlock>
      );
    },
    table: ({ children }) => (
      <div className="my-4 overflow-x-auto">
        <table className="w-full border-collapse text-left text-sm">{children}</table>
      </div>
    ),
    th: ({ children }) => (
      <th className="border bg-slate-100 px-3 py-2 font-semibold">
        {withCitations(children)}
      </th>
    ),
    td: ({ children }) => (
      <td className="border px-3 py-2 align-top">{withCitations(children)}</td>
    ),
  };

  return (
    <div className="text-sm leading-7 text-slate-800">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={components}
        skipHtml
        urlTransform={safeLinkUrl}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}
