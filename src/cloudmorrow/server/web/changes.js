/* The change feed in the browser: told what changed, instead of asking.

   `listenChanges(onChange)` keeps one connection to GET /api/changes open
   (server/changefeed.py) and calls back with each change the server sends:
   `{seq, model, id, space, owner, action, at}` — which record, never what is
   in it. A screen that hears one asks the record API for what it has not
   got, the same `?_since=` call it made on a timer before.

   The line drops now and then — a phone sleeps, a proxy times out — and
   comes back by itself, a little later each time it fails, and from where
   it left off (`?since=`). While it is down the screen's own timer is the
   fallback; `live` says which it is right now. `stop()` ends it. */

import { apiStream } from "./core.js";

const RETRY = 1000;
const RETRY_MOST = 30000;

export function listenChanges(onChange, { onState } = {}) {
  let stopped = false;
  let seq = null;
  let controller = null;
  let delay = RETRY;
  const feed = { live: false, stop() { stopped = true; if (controller) controller.abort(); } };

  const handle = (block) => {
    let id = null, name = "message", data = "";
    for (const line of block.split("\n")) {
      if (line.startsWith("id:")) id = Number(line.slice(3).trim());
      else if (line.startsWith("event:")) name = line.slice(6).trim();
      else if (line.startsWith("data:")) data += line.slice(5).trim();
    }
    if (id != null && !Number.isNaN(id)) seq = id;
    if (!data) return;
    let parsed;
    try { parsed = JSON.parse(data); } catch { return; }
    if (name === "hello" && typeof parsed.seq === "number") seq = parsed.seq;
    if (name === "change") onChange(parsed);
  };

  const run = async () => {
    while (!stopped) {
      controller = new AbortController();
      try {
        const res = await apiStream("/api/changes" + (seq != null ? `?since=${seq}` : ""), { signal: controller.signal });
        feed.live = true;
        delay = RETRY;
        if (onState) onState(true);
        const reader = res.body.pipeThrough(new TextDecoderStream()).getReader();
        let buffer = "";
        for (;;) {
          const { value, done } = await reader.read();
          if (done) break;
          buffer += value;
          let at;
          while ((at = buffer.indexOf("\n\n")) >= 0) {
            handle(buffer.slice(0, at));
            buffer = buffer.slice(at + 2);
          }
        }
      } catch (err) {
        // A session that ended has signed out already; nothing to come back to.
        if (err && err.status === 401) stopped = true;
      }
      feed.live = false;
      if (onState) onState(false);
      if (stopped) break;
      await new Promise((resolve) => setTimeout(resolve, delay));
      delay = Math.min(delay * 2, RETRY_MOST);
    }
  };
  run();
  return feed;
}
