import { describe, expect, it } from "vitest";

import { parseSse, type SseMessage } from "./sse";

function streamOf(chunks: string[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  return new ReadableStream({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(encoder.encode(chunk));
      controller.close();
    },
  });
}

async function collect(chunks: string[]): Promise<SseMessage[]> {
  const messages: SseMessage[] = [];
  for await (const message of parseSse(streamOf(chunks))) messages.push(message);
  return messages;
}

describe("parseSse", () => {
  it("joins events split across chunks and accepts \\r\\n line endings", async () => {
    expect(await collect(['event: delta\ndata: {"te', 'xt":"a"}\n\nevent: done\r\ndata: {}\r\n\r\n'])).toEqual([
      { event: "delta", data: '{"text":"a"}' },
      { event: "done", data: "{}" },
    ]);
  });

  it("ignores comment lines and a trailing event without a blank line", async () => {
    expect(await collect([": keep-alive\n\nevent: delta\ndata: x\n\nevent: done\ndata: {}"])).toEqual([
      { event: "delta", data: "x" },
    ]);
  });

  it("joins multiple data lines with a newline", async () => {
    expect(await collect(["event: delta\ndata: one\ndata: two\n\n"])).toEqual([{ event: "delta", data: "one\ntwo" }]);
  });

  it("handles a \\r\\n split between chunks", async () => {
    expect(await collect(["event: done\r", "\ndata: {}\r\n\r", "\n"])).toEqual([{ event: "done", data: "{}" }]);
  });
});
