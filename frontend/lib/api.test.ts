import { beforeEach, expect, it, vi } from "vitest";
import { tenantApi } from "./api";

const encoder = new TextEncoder();

function streamingResponse(chunks: string[]) {
  return new Response(new ReadableStream({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(encoder.encode(chunk));
      controller.close();
    },
  }), { status: 200, headers: { "Content-Type": "text/event-stream" } });
}

beforeEach(() => {
  vi.restoreAllMocks();
});

it("parses SSE events split across arbitrary network chunks", async () => {
  vi.spyOn(globalThis, "fetch").mockResolvedValue(streamingResponse([
    "event: status\ndata: {\"status\":\"star",
    "ted\"}\n\n: keepalive\n\nevent: token\nda",
    "ta: {\"text\":\"Install \"}\n\nevent: token\ndata: {\"text\":\"vManager. [C1]\"}\n\n",
    "event: citations\ndata: {\"citations\":[]}\n\nevent: complete\ndata: {\"grounded\":true,\"request_id\":\"req-1\"}\n\n",
  ]));
  const tokens:string[] = [];
  const statuses:string[] = [];
  let completed = false;

  await tenantApi.streamAnswer("vitwo", { query: "How?" }, {
    onStatus: (value) => statuses.push(value.status),
    onToken: (value) => tokens.push(value),
    onCitations: () => undefined,
    onComplete: () => { completed = true; },
  });

  expect(statuses).toEqual(["started"]);
  expect(tokens.join("")).toBe("Install vManager. [C1]");
  expect(completed).toBe(true);
});

it("rejects an unexpected EOF without a complete event", async () => {
  vi.spyOn(globalThis, "fetch").mockResolvedValue(streamingResponse([
    "event: status\ndata: {\"status\":\"started\"}\n\n",
    "event: token\ndata: {\"text\":\"Partial answer\"}\n\n",
  ]));

  await expect(tenantApi.streamAnswer("vitwo", { query: "How?" }, {
    onToken: () => undefined,
    onCitations: () => undefined,
    onComplete: () => undefined,
  })).rejects.toThrow("stream ended unexpectedly");
});
