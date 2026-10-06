export type SseMessage = { event: string; data: string };

// Server-sent events from a fetch body (the EventSource API can't POST or send a bearer header).
// Only complete events (ended by a blank line) are yielded; a trailing partial event is dropped.
export async function* parseSse(body: ReadableStream<Uint8Array>): AsyncGenerator<SseMessage> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let event = "message";
  let data: string[] = [];
  try {
    for (;;) {
      const { value, done } = await reader.read();
      if (done) return;
      buffer += decoder.decode(value, { stream: true });
      for (;;) {
        const end = lineEnd(buffer);
        if (end === null) break;
        const line = buffer.slice(0, end.index);
        buffer = buffer.slice(end.index + end.length);
        if (line === "") {
          if (data.length) yield { event, data: data.join("\n") };
          event = "message";
          data = [];
        } else if (!line.startsWith(":")) {
          const colon = line.indexOf(":");
          const field = colon === -1 ? line : line.slice(0, colon);
          const raw = colon === -1 ? "" : line.slice(colon + 1);
          const text = raw.startsWith(" ") ? raw.slice(1) : raw;
          if (field === "event") event = text;
          else if (field === "data") data.push(text);
        }
      }
    }
  } finally {
    // Also runs when the consumer stops early (the page unmounts): cancelling closes the connection.
    await reader.cancel().catch(() => {});
  }
}

// A lone "\r" at the end of the buffer may be the first half of "\r\n": wait for more input.
function lineEnd(buffer: string): { index: number; length: number } | null {
  const index = buffer.search(/\r\n|\r|\n/);
  if (index === -1) return null;
  if (buffer[index] === "\r") {
    if (index === buffer.length - 1) return null;
    return { index, length: buffer[index + 1] === "\n" ? 2 : 1 };
  }
  return { index, length: 1 };
}
