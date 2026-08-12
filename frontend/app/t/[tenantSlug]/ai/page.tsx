"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import * as DropdownMenu from "@radix-ui/react-dropdown-menu";
import {
  ChevronDown,
  ChevronUp,
  Copy,
  MessageSquarePlus,
  MoreHorizontal,
  ThumbsDown,
  ThumbsUp,
  X,
} from "lucide-react";
import { Alert } from "@/components/alert";
import { AssistantMarkdown } from "@/components/assistant-markdown";
import { TenantShell } from "@/components/tenant-shell";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { useTenantUser } from "@/hooks/use-tenant-user";
import { tenantApi } from "@/lib/api";
import type {
  AIAnswerCitation,
  AIConversation,
  AIConversationMessage,
  AIConversationSummary,
  AIPromptSuggestions,
} from "@/lib/types";

function citationLocation(citation: AIAnswerCitation) {
  return [
    citation.section_title,
    citation.page_number == null ? null : `Page ${citation.page_number}`,
    citation.sheet_name == null ? null : `Sheet ${citation.sheet_name}`,
    citation.row_start == null ? null : `Rows ${citation.row_start}${citation.row_end && citation.row_end !== citation.row_start ? `–${citation.row_end}` : ""}`,
  ].filter(Boolean).join(" · ");
}

function MessageActions({ content }: {content:string}) {
  const [copied, setCopied] = useState(false);
  return <div className="flex items-center gap-1 text-slate-500">
    <button type="button" aria-label="Copy answer" className="rounded p-1 hover:bg-slate-100" onClick={async () => {
      await navigator.clipboard.writeText(content); setCopied(true);
      window.setTimeout(() => setCopied(false), 1200);
    }}><Copy className="h-4 w-4"/></button>
    <span className="text-[11px]">{copied ? "Copied" : ""}</span>
    <button type="button" aria-label="Helpful answer" title="Feedback coming soon" className="rounded p-1 hover:bg-slate-100"><ThumbsUp className="h-4 w-4"/></button>
    <button type="button" aria-label="Unhelpful answer" title="Feedback coming soon" className="rounded p-1 hover:bg-slate-100"><ThumbsDown className="h-4 w-4"/></button>
  </div>;
}

function StoredMessage({ message, onCitation }: {
  message:AIConversationMessage;onCitation:(message:AIConversationMessage,citation:AIAnswerCitation)=>void;
}) {
  return <div className={`flex ${message.role === "user" ? "justify-end" : "justify-start"}`}>
    <Card className={message.role === "user" ? "w-fit max-w-[78%] bg-slate-100 sm:max-w-[70%]" : "min-w-0 w-full border-blue-100"}>
      <CardContent className="min-w-0 space-y-3 pt-5">
        <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">{message.role === "user" ? "You" : "PEKA"}</div>
        {message.content
          ? message.role === "assistant"
            ? <AssistantMarkdown content={message.content} citations={message.citations} onCitation={(citation) => onCitation(message, citation)}/>
            : <div className="whitespace-pre-wrap text-sm leading-7">{message.content}</div>
          : <div className="text-sm text-slate-500">{message.status === "cancelled" ? "Generation stopped before answer text was available." : message.status === "failed" ? "No answer was saved." : "Preparing a grounded answer…"}</div>}
        {message.status !== "completed" && <div className={`text-xs ${message.status === "failed" ? "text-red-700" : "text-amber-700"}`}>{message.status === "cancelled" ? "Cancelled" : message.status === "failed" ? "Generation failed" : "Generating"}</div>}
        {message.role === "assistant" && message.content && <MessageActions content={message.content}/>}
        {message.model && <div className="text-[11px] text-slate-400">Generated with {message.model}{message.prompt_version ? ` · ${message.prompt_version}` : ""}</div>}
      </CardContent>
    </Card>
  </div>;
}

function historyGroup(value:string) {
  const date = new Date(value);
  const today = new Date(); today.setHours(0, 0, 0, 0);
  const day = new Date(date); day.setHours(0, 0, 0, 0);
  const difference = Math.round((today.getTime() - day.getTime()) / 86_400_000);
  if (difference <= 0) return "Today";
  if (difference === 1) return "Yesterday";
  if (difference <= 7) return "Previous 7 days";
  return "Older";
}

function EvidenceDrawer({ citation, related, loading, onSelect, onClose }: {
  citation:AIAnswerCitation|null;related:AIAnswerCitation[];loading:boolean;
  onSelect:(citation:AIAnswerCitation)=>void;onClose:()=>void;
}) {
  if (!citation && !loading) return null;
  const grouped = related.reduce<Record<string,AIAnswerCitation[]>>((values, item) => {
    (values[item.title] ??= []).push(item); return values;
  }, {});
  return <div className="fixed inset-0 z-50 flex justify-end bg-slate-950/30" role="dialog" aria-modal="true" aria-label="Citation evidence">
    <button type="button" aria-label="Close evidence" className="min-w-0 flex-1" onClick={onClose}/>
    <aside className="h-full w-full max-w-xl overflow-y-auto bg-white p-5 shadow-xl">
      <div className="flex items-center justify-between"><h2 className="text-lg font-semibold">Evidence used for this answer</h2><button type="button" aria-label="Close evidence panel" onClick={onClose}><X className="h-5 w-5"/></button></div>
      {loading && <p className="mt-6 text-sm text-slate-500">Loading stored evidence…</p>}
      {citation && <div className="mt-5 space-y-5">
        <div className="rounded-lg border border-blue-200 bg-blue-50 p-4">
          <div className="text-xs font-semibold text-blue-700">[{citation.citation_id}]</div>
          <h3 className="mt-1 font-semibold">{citation.title}</h3>
          {citationLocation(citation) && <p className="mt-1 text-xs text-slate-600">{citationLocation(citation)}</p>}
          <blockquote className="mt-4 border-l-4 border-blue-400 bg-white p-3 text-sm leading-6">{citation.excerpt || "The stored evidence excerpt is unavailable for this older answer."}</blockquote>
          {citation.sensitive_content_redacted && <Alert tone="warning">Credential information in this evidence was redacted. Retrieve approved credentials from the organization&apos;s password manager or controlled document.</Alert>}
          <dl className="mt-4 grid gap-2 text-xs sm:grid-cols-2">
            <div><dt className="font-semibold text-slate-500">Document type</dt><dd>{citation.document_type || "Not recorded"}</dd></div>
            <div><dt className="font-semibold text-slate-500">Source system</dt><dd>{citation.source_system || citation.source_type}</dd></div>
            <div><dt className="font-semibold text-slate-500">Evidence revision</dt><dd className="break-all">{citation.revision || "Not recorded"}</dd></div>
            <div><dt className="font-semibold text-slate-500">Ingested</dt><dd>{citation.ingested_at ? new Date(citation.ingested_at).toLocaleString() : "Not recorded"}</dd></div>
            <div><dt className="font-semibold text-slate-500">Retrieval score</dt><dd>{citation.score.toFixed(3)}</dd></div>
            <div><dt className="font-semibold text-slate-500">Redaction</dt><dd>{citation.sensitive_content_redacted ? "Sensitive content redacted" : "None detected"}</dd></div>
          </dl>
          <p className="mt-3 text-xs text-slate-500">This is the evidence snapshot used when the answer was generated, not a live document lookup.</p>
        </div>
        <div>{Object.entries(grouped).map(([title, items]) => <div key={title} className="mb-4">
          <h3 className="text-sm font-semibold">{title}</h3>
          <div className="mt-2 space-y-1">{items.map((item) => <button key={item.citation_id} type="button" onClick={() => onSelect(item)} className={`block w-full rounded border px-3 py-2 text-left text-xs ${item.citation_id === citation.citation_id ? "border-blue-500 bg-blue-50" : "hover:bg-slate-50"}`}>[{item.citation_id}] — {citationLocation(item) || "Supporting excerpt"}</button>)}</div>
        </div>)}</div>
      </div>}
    </aside>
  </div>;
}

export default function AIPage() {
  const { tenantSlug } = useParams<{ tenantSlug: string }>();
  const router = useRouter();
  const searchParams = useSearchParams();
  const requestedConversationId = searchParams.get("conversation");
  const { user, error: userError } = useTenantUser(tenantSlug);
  const [query, setQuery] = useState("");
  const [answer, setAnswer] = useState("");
  const [citations, setCitations] = useState<AIAnswerCitation[]>([]);
  const [history, setHistory] = useState<AIConversationSummary[]>([]);
  const [promptSuggestions, setPromptSuggestions] =
    useState<AIPromptSuggestions | null>(null);
  const [historyLoading, setHistoryLoading] = useState(true);
  const [historySearch, setHistorySearch] = useState("");
  const [showArchived, setShowArchived] = useState(false);
  const [historyExpanded, setHistoryExpanded] = useState(true);
  const [active, setActive] = useState<AIConversation | null>(null);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [pendingQuestion, setPendingQuestion] = useState("");
  const [streamMessageId, setStreamMessageId] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [insufficient, setInsufficient] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [evidence, setEvidence] = useState<AIAnswerCitation | null>(null);
  const [evidenceRelated, setEvidenceRelated] = useState<AIAnswerCitation[]>([]);
  const [evidenceLoading, setEvidenceLoading] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
  const activeIdRef = useRef<string | null>(null);
  const chatRef = useRef<HTMLDivElement | null>(null);
  const shouldAutoScroll = useRef(true);
  const tenantRef = useRef(tenantSlug);
  const newChatRequestedRef = useRef(false);
  tenantRef.current = tenantSlug;
  activeIdRef.current = activeId;

  const filteredHistory = useMemo(() => history.filter((item) =>
    item.title.toLowerCase().includes(historySearch.trim().toLowerCase())
    || (item.last_message_preview || "").toLowerCase().includes(historySearch.trim().toLowerCase())
  ), [history, historySearch]);
  const groupedHistory = useMemo(() => filteredHistory.reduce<Record<string,AIConversationSummary[]>>((groups, item) => {
    const group = showArchived ? "Archived" : historyGroup(item.last_message_at);
    (groups[group] ??= []).push(item); return groups;
  }, {}), [filteredHistory, showArchived]);

  async function refreshHistory(slug = tenantSlug) {
    const value = await tenantApi.conversations(slug, showArchived);
    setHistory(value.items); setHistoryLoading(false);
  }

  useEffect(() => {
    let disposed = false;
    abortRef.current?.abort();
    setHistory([]); setActive(null); setActiveId(null); setHistorySearch("");
    setPromptSuggestions(null);
    setShowArchived(false); setAnswer(""); setCitations([]); setError("");
    setPendingQuestion(""); setEvidence(null); setHistoryLoading(true);
    setGenerating(false); setStreamMessageId(null);
    void tenantApi.conversations(tenantSlug).then((value) => {
      if (!disposed) { setHistory(value.items); setHistoryLoading(false); }
    }).catch((caught) => {
      if (!disposed) {
        setError(caught instanceof Error ? caught.message : "Conversation history could not be loaded.");
        setHistoryLoading(false);
      }
    });
    void tenantApi.assistantSuggestions(tenantSlug).then((value) => {
      if (!disposed && tenantRef.current === tenantSlug) {
        setPromptSuggestions(value);
      }
    }).catch(() => {
      if (!disposed && tenantRef.current === tenantSlug) {
        setPromptSuggestions({
          has_indexed_knowledge: false,
          suggestions: [],
          onboarding_guidance:
            "Tenant knowledge is not available yet. Ask a tenant administrator "
            + "to index documents or connect a knowledge source.",
        });
      }
    });
    return () => { disposed = true; abortRef.current?.abort(); };
  }, [tenantSlug]);

  useEffect(() => {
    if (user?.role !== "tenant_admin") {
      setHistoryExpanded(true);
      return;
    }
    setHistoryExpanded(
      typeof localStorage === "undefined"
        || localStorage.getItem("peka:assistant-history-expanded") !== "false",
    );
  }, [user?.role]);

  useEffect(() => {
    if (!requestedConversationId) {
      if (activeIdRef.current) {
        abortRef.current?.abort();
        setActive(null); setActiveId(null); setQuery(""); setAnswer("");
        setCitations([]); setPendingQuestion(""); setError("");
        setInsufficient(false); setEvidence(null);
      }
      return;
    }
    if (requestedConversationId === activeIdRef.current) return;

    let disposed = false;
    abortRef.current?.abort();
    setError(""); setAnswer(""); setCitations([]); setInsufficient(false);
    setActive(null); setActiveId(requestedConversationId);
    shouldAutoScroll.current = true;
    void tenantApi.conversation(tenantSlug, requestedConversationId)
      .then((value) => {
        if (!disposed && tenantRef.current === tenantSlug) setActive(value);
      })
      .catch((caught) => {
        if (!disposed && tenantRef.current === tenantSlug) {
          setError(caught instanceof Error
            ? caught.message
            : "Conversation could not be loaded.");
        }
      });
    return () => { disposed = true; };
  }, [requestedConversationId, tenantSlug]);

  useEffect(() => {
    if (!shouldAutoScroll.current || !chatRef.current) return;
    if (typeof chatRef.current.scrollTo === "function") {
      chatRef.current.scrollTo({
        top: chatRef.current.scrollHeight, behavior: "smooth",
      });
    } else {
      chatRef.current.scrollTop = chatRef.current.scrollHeight;
    }
  }, [answer, pendingQuestion, active?.messages.length]);

  if (userError) return <main className="p-8"><Alert>{userError}</Alert></main>;
  if (!user) return <main className="p-8">Loading…</main>;

  async function openConversation(id:string) {
    if (generating) return;
    setError(""); setAnswer(""); setCitations([]); setInsufficient(false);
    setActiveId(id); shouldAutoScroll.current = true;
    router.push(`/t/${tenantSlug}/ai?conversation=${encodeURIComponent(id)}`);
    try { setActive(await tenantApi.conversation(tenantSlug, id)); }
    catch (caught) { setError(caught instanceof Error ? caught.message : "Conversation could not be loaded."); }
  }

  function newChat() {
    newChatRequestedRef.current = generating;
    abortRef.current?.abort();
    setActive(null); setActiveId(null); setQuery(""); setAnswer("");
    setCitations([]); setPendingQuestion(""); setError(""); setInsufficient(false);
    setEvidence(null); shouldAutoScroll.current = true;
    router.push(`/t/${tenantSlug}/ai`);
  }

  async function send(question=query) {
    const value = question.trim();
    if (!value || generating) return;
    setQuery(""); setAnswer(""); setCitations([]); setError(""); setInsufficient(false);
    setPendingQuestion(value); setGenerating(true); shouldAutoScroll.current = true;
    const controller = new AbortController(); abortRef.current = controller;
    const requestTenant = tenantSlug;
    newChatRequestedRef.current = false;
    let conversationId = activeId;
    try {
      await tenantApi.streamAnswer(tenantSlug, { query:value, conversation_id:activeId }, {
        onStatus: (status) => {
          if (status.conversation_id) {
            conversationId = status.conversation_id;
            setActiveId(status.conversation_id);
            router.replace(
              `/t/${tenantSlug}/ai?conversation=${encodeURIComponent(status.conversation_id)}`,
            );
          }
          if (status.assistant_message_id) setStreamMessageId(status.assistant_message_id);
        },
        onToken: (text) => setAnswer((current) => current + text),
        onCitations: setCitations,
        onComplete: (result) => setInsufficient(!result.grounded),
      }, controller.signal);
      if (tenantRef.current !== requestTenant || newChatRequestedRef.current) return;
      if (conversationId) setActive(await tenantApi.conversation(tenantSlug, conversationId));
      setPendingQuestion(""); setAnswer(""); setCitations([]); await refreshHistory();
    } catch (caught) {
      if (tenantRef.current !== requestTenant || newChatRequestedRef.current) return;
      setError(controller.signal.aborted ? "Generation stopped." : caught instanceof Error ? caught.message : "The AI service is temporarily unavailable.");
      if (conversationId) {
        try { setActive(await tenantApi.conversation(tenantSlug, conversationId)); } catch {}
        try { await refreshHistory(); } catch {}
      }
      setPendingQuestion(""); setAnswer(""); setCitations([]);
    } finally {
      if (tenantRef.current === requestTenant) {
        setGenerating(false); setStreamMessageId(null);
        newChatRequestedRef.current = false;
      }
      if (abortRef.current === controller) abortRef.current = null;
    }
  }

  async function showEvidence(message:AIConversationMessage|null, citation:AIAnswerCitation) {
    const messageId = message?.id || streamMessageId;
    setEvidenceRelated(message?.citations || citations); setEvidence(citation);
    if (!activeId || !messageId || generating) return;
    setEvidenceLoading(true);
    try {
      const snapshot = await tenantApi.citationEvidence(tenantSlug, activeId, messageId, citation.citation_id);
      setEvidence(snapshot.citation);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Stored evidence could not be loaded.");
    } finally { setEvidenceLoading(false); }
  }

  async function rename(item:AIConversationSummary) {
    const title = window.prompt("Rename conversation", item.title)?.trim();
    if (!title) return;
    try {
      const updated = await tenantApi.renameConversation(tenantSlug, item.id, title);
      if (activeId === item.id) setActive(updated); await refreshHistory();
    } catch (caught) { setError(caught instanceof Error ? caught.message : "Conversation could not be renamed."); }
  }
  async function archive(item:AIConversationSummary) {
    try {
      await tenantApi.archiveConversation(tenantSlug, item.id, !item.is_archived);
      if (activeId === item.id) newChat(); await refreshHistory();
    } catch (caught) { setError(caught instanceof Error ? caught.message : "Conversation could not be archived."); }
  }
  async function remove(item:AIConversationSummary) {
    if (!window.confirm(`Delete “${item.title}”? This removes it from your history.`)) return;
    try {
      await tenantApi.deleteConversation(tenantSlug, item.id);
      if (activeId === item.id) newChat(); await refreshHistory();
    } catch (caught) { setError(caught instanceof Error ? caught.message : "Conversation could not be deleted."); }
  }
  async function toggleArchived() {
    const next = !showArchived; setShowArchived(next); setHistoryLoading(true);
    try { setHistory((await tenantApi.conversations(tenantSlug, next)).items); }
    catch (caught) { setError(caught instanceof Error ? caught.message : "Conversation history could not be loaded."); }
    finally { setHistoryLoading(false); }
  }

  function toggleHistoryExpanded() {
    const next = !historyExpanded;
    setHistoryExpanded(next);
    if (typeof localStorage !== "undefined") {
      localStorage.setItem("peka:assistant-history-expanded", String(next));
    }
  }

  const historyPanel = (closeMobile: () => void) => (
    <section
      aria-label="Conversation history"
      data-ai-history-sidebar
      data-expanded={historyExpanded}
      className={`border-t border-slate-800 text-slate-200 ${
        historyExpanded ? "pt-4" : "py-1"
      }`}
    >
      <div className="flex items-center justify-between gap-2 px-1">
        <div className="text-xs font-semibold uppercase tracking-wide text-slate-400">
          {user.role === "tenant_admin" && !historyExpanded
            ? "Chats"
            : showArchived
              ? "Archived chats"
              : "Private history"}
        </div>
        <div className="flex items-center gap-1">
          {historyExpanded && (
            <button
              type="button"
              className="rounded px-2 py-1 text-xs text-blue-300 hover:bg-slate-800 hover:text-blue-200"
              onClick={() => void toggleArchived()}
            >
              {showArchived ? "Active" : "Archived"}
            </button>
          )}
          {user.role === "tenant_admin" && (
            <button
              type="button"
              aria-expanded={historyExpanded}
              aria-label={
                historyExpanded ? "Collapse chat history" : "Expand chat history"
              }
              className="flex h-10 w-10 shrink-0 items-center justify-center rounded text-slate-300 hover:bg-slate-800 hover:text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-400"
              onClick={toggleHistoryExpanded}
            >
              {historyExpanded
                ? <ChevronUp className="h-5 w-5" />
                : <ChevronDown className="h-5 w-5" />}
            </button>
          )}
        </div>
      </div>
      {historyExpanded && <><label className="mt-3 block">
        <span className="sr-only">Search conversations</span>
        <input
          value={historySearch}
          onChange={(event) => setHistorySearch(event.target.value)}
          placeholder="Search conversations"
          className="h-9 w-full rounded-md border border-slate-700 bg-slate-900 px-3 text-sm text-white placeholder:text-slate-500 focus:border-blue-500 focus:outline-none"
        />
      </label>
      {historyLoading && (
        <p className="mt-3 px-1 text-sm text-slate-400">Loading conversations…</p>
      )}
      {!historyLoading && filteredHistory.length === 0 && (
        <p className="mt-3 px-1 text-sm text-slate-400">
          {historySearch ? "No matching conversations." : "No conversations yet."}
        </p>
      )}
      <div className="mt-4 space-y-5">
        {Object.entries(groupedHistory).map(([group, items]) => (
          <section key={group}>
            <h3 className="mb-1 px-2 text-xs font-semibold text-slate-500">
              {group}
            </h3>
            <div className="space-y-1">
              {items.map((item) => (
                <div
                  key={item.id}
                  className={`group flex items-start rounded-md ${
                    activeId === item.id
                      ? "bg-blue-600 text-white"
                      : "text-slate-300 hover:bg-slate-800"
                  }`}
                >
                  <button
                    type="button"
                    aria-current={activeId === item.id ? "page" : undefined}
                    className="min-w-0 flex-1 px-3 py-2 text-left"
                    onClick={() => {
                      closeMobile();
                      void openConversation(item.id);
                    }}
                  >
                    <div className="truncate text-sm font-medium">{item.title}</div>
                    {item.last_message_preview && (
                      <div
                        className={`mt-1 truncate text-xs ${
                          activeId === item.id ? "text-blue-100" : "text-slate-500"
                        }`}
                      >
                        {item.last_message_preview}
                      </div>
                    )}
                  </button>
                  <DropdownMenu.Root>
                    <DropdownMenu.Trigger asChild>
                      <button
                        type="button"
                        aria-label={`Actions for ${item.title}`}
                        className="m-1 rounded p-1.5 text-slate-400 hover:bg-slate-700 hover:text-white"
                      >
                        <MoreHorizontal className="h-4 w-4" />
                      </button>
                    </DropdownMenu.Trigger>
                    <DropdownMenu.Portal>
                      <DropdownMenu.Content
                        align="end"
                        className="z-50 min-w-32 rounded-md border bg-white p-1 text-sm text-slate-900 shadow-lg"
                      >
                        <DropdownMenu.Item
                          className="cursor-pointer rounded px-3 py-2 outline-none hover:bg-slate-100"
                          onSelect={() => void rename(item)}
                        >
                          Rename
                        </DropdownMenu.Item>
                        <DropdownMenu.Item
                          className="cursor-pointer rounded px-3 py-2 outline-none hover:bg-slate-100"
                          onSelect={() => void archive(item)}
                        >
                          {item.is_archived ? "Unarchive" : "Archive"}
                        </DropdownMenu.Item>
                        <DropdownMenu.Item
                          className="cursor-pointer rounded px-3 py-2 text-red-700 outline-none hover:bg-red-50"
                          onSelect={() => void remove(item)}
                        >
                          Delete
                        </DropdownMenu.Item>
                      </DropdownMenu.Content>
                    </DropdownMenu.Portal>
                  </DropdownMenu.Root>
                </div>
              ))}
            </div>
          </section>
        ))}
      </div></>}
    </section>
  );

  return <TenantShell
    slug={tenantSlug}
    user={user}
    title="Assistant"
    aiSidebarTop={({ closeMobile }) => (
      <Button
        type="button"
        className="w-full justify-start gap-2"
        onClick={() => {
          closeMobile();
          newChat();
        }}
      >
        <MessageSquarePlus className="h-4 w-4" />
        New chat
      </Button>
    )}
    aiCollapsedSidebarTop={({ closeMobile }) => (
      <button
        type="button"
        aria-label="New chat"
        aria-describedby="new-chat-tooltip"
        className="group relative flex w-full justify-center rounded-md bg-blue-600 p-2.5 text-white hover:bg-blue-700"
        onClick={() => {
          closeMobile();
          newChat();
        }}
      >
        <MessageSquarePlus className="h-5 w-5" />
        <span
          id="new-chat-tooltip"
          role="tooltip"
          className="pointer-events-none absolute left-full top-1/2 z-50 ml-3 -translate-y-1/2 whitespace-nowrap rounded bg-slate-800 px-2 py-1 text-xs opacity-0 shadow-lg transition-opacity group-hover:opacity-100 group-focus-visible:opacity-100"
        >
          New chat
        </span>
      </button>
    )}
    aiSidebarContent={({ closeMobile }) => historyPanel(closeMobile)}
  >
    <main className="mx-auto flex h-[calc(100dvh-6rem)] w-full max-w-5xl min-w-0 flex-col sm:h-[calc(100vh-7rem)] lg:h-[calc(100vh-8rem)]">
        <div className="mb-3 min-w-0"><h1 className="truncate text-2xl font-semibold">{active?.title ?? "How can PEKA help?"}</h1><p className="text-xs text-slate-500">Private to {user.full_name} in {user.tenant_name}</p></div>
        <div ref={chatRef} onScroll={() => {
          const element = chatRef.current;
          if (element) shouldAutoScroll.current = element.scrollHeight - element.scrollTop - element.clientHeight < 100;
        }} className="min-h-0 min-w-0 flex-1 space-y-4 overflow-x-hidden overflow-y-auto px-1 pb-6">
          {!activeId && !pendingQuestion && promptSuggestions?.has_indexed_knowledge && (
            <div className="flex flex-wrap justify-center gap-2 pt-8">
              {promptSuggestions.suggestions.map((suggestion) => (
                <button
                  key={suggestion}
                  type="button"
                  disabled={generating}
                  onClick={() => void send(suggestion)}
                  className="rounded-full border bg-white px-3 py-2 text-sm hover:bg-slate-50"
                >
                  {suggestion}
                </button>
              ))}
            </div>
          )}
          {!activeId && !pendingQuestion && promptSuggestions && !promptSuggestions.has_indexed_knowledge && (
            <Card className="mx-auto mt-8 max-w-2xl border-dashed">
              <CardContent className="pt-5 text-center">
                <h2 className="font-semibold">Local knowledge is not ready</h2>
                <p className="mt-2 text-sm text-slate-500">
                  {promptSuggestions.onboarding_guidance}
                </p>
                {user.role === "tenant_admin" && (
                  <Button className="mt-4" variant="outline" asChild>
                    <a href={`/t/${tenantSlug}/connectors`}>
                      View Connector
                    </a>
                  </Button>
                )}
              </CardContent>
            </Card>
          )}
          {active?.messages.map((message) => <StoredMessage key={message.id} message={message} onCitation={(stored, citation) => void showEvidence(stored, citation)}/>)}
          {pendingQuestion && <div className="flex justify-end"><Card className="w-fit max-w-[78%] bg-slate-100 sm:max-w-[70%]"><CardContent className="pt-5"><div className="mb-2 text-xs font-semibold uppercase text-slate-500">You</div><div className="whitespace-pre-wrap text-sm">{pendingQuestion}</div></CardContent></Card></div>}
          {(answer || generating) && <div className="flex min-w-0 justify-start"><Card className="min-w-0 w-full border-blue-100"><CardContent className="min-w-0 pt-5"><div className="mb-2 text-xs font-semibold uppercase text-slate-500">PEKA</div>{answer ? <AssistantMarkdown content={answer} citations={citations} onCitation={(citation) => void showEvidence(null, citation)}/> : <div className="text-sm text-slate-500">Preparing a grounded answer…</div>}</CardContent></Card></div>}
          {insufficient && <Alert tone="warning">PEKA could not find enough indexed evidence to answer this question.</Alert>}
          {error && <Alert>{error}</Alert>}
        </div>
        <div className="shrink-0 border-t bg-white pb-[max(0.75rem,env(safe-area-inset-bottom))] pt-3">
          <label htmlFor="ai-question" className="sr-only">Question</label>
          <textarea id="ai-question" value={query} disabled={generating} maxLength={2000} onChange={(event) => setQuery(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); void send(); } }} placeholder={activeId ? "Continue this conversation…" : "Ask PEKA about your organization’s knowledge…"} className="min-h-20 w-full resize-none rounded-lg border p-3 text-sm outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100"/>
          <div className="mt-2 flex justify-end gap-2">{generating && <Button type="button" variant="outline" onClick={() => abortRef.current?.abort()}>Stop generation</Button>}<Button type="button" disabled={generating || !query.trim()} onClick={() => void send()}>{generating ? "Generating…" : "Send"}</Button></div>
        </div>
    </main>
    <EvidenceDrawer citation={evidence} related={evidenceRelated} loading={evidenceLoading} onSelect={(citation) => setEvidence(citation)} onClose={() => setEvidence(null)}/>
  </TenantShell>;
}
