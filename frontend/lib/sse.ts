export type ServerSentEvent = {
  event: string;
  data: string;
};

export function consumeSseFrames(
  input: string,
  final = false,
): { events: ServerSentEvent[]; remainder: string } {
  const normalized = input.replace(/\r\n/g, "\n");
  const blocks = normalized.split("\n\n");
  const remainder = final ? "" : (blocks.pop() ?? "");

  const events: ServerSentEvent[] = [];
  for (const frame of blocks) {
    let event = "message";
    const data: string[] = [];
    for (const line of frame.split("\n")) {
      if (line.startsWith(":")) {
        continue;
      }
      const separator = line.indexOf(":");
      const field = separator === -1 ? line : line.slice(0, separator);
      let value = separator === -1 ? "" : line.slice(separator + 1);
      if (value.startsWith(" ")) {
        value = value.slice(1);
      }
      if (field === "event") {
        event = value;
      } else if (field === "data") {
        data.push(value);
      }
    }
    if (data.length > 0) {
      events.push({ event, data: data.join("\n") });
    }
  }
  return { events, remainder };
}
