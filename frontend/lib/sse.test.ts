import { describe, expect, it } from "vitest";

import { consumeSseFrames } from "@/lib/sse";

describe("consumeSseFrames", () => {
  it("parses complete frames and keeps partial frames for the next chunk", () => {
    const first = consumeSseFrames(
      'event: delta\r\ndata: {"delta":"hello"}\r\n\r\nevent: do',
    );
    expect(first.events).toEqual([
      { event: "delta", data: '{"delta":"hello"}' },
    ]);
    expect(first.remainder).toBe("event: do");

    const second = consumeSseFrames(`${first.remainder}ne\ndata: {}\n\n`);
    expect(second.events).toEqual([{ event: "done", data: "{}" }]);
  });

  it("joins multiple data lines and ignores comments", () => {
    const result = consumeSseFrames(": keep-alive\nevent: message\ndata: one\ndata: two\n\n");

    expect(result.events).toEqual([{ event: "message", data: "one\ntwo" }]);
  });

  it("flushes a final frame without a trailing blank line", () => {
    const result = consumeSseFrames("event: done\ndata: complete", true);

    expect(result.events).toEqual([{ event: "done", data: "complete" }]);
  });
});
