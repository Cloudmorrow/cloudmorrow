/* The service worker: the only part of the app that runs when the app does not.

   It exists for one job. A web app on a home screen is not a process most of
   the time — it is a screenshot and an icon — so nothing it could poll would
   keep the count on that icon right. A push from the browser vendor's service
   wakes this file instead, and this file shows the banner and sets the badge.

   It deliberately does not cache anything. The page already follows a deploy
   on its own (fresh.js), and a worker that also served stale copies of the
   app would be a second, slower answer to a question that is already
   answered — and the usual way a web app gets stuck on last month's code.

   Served from /app/sw.js, never from /app/<deploy>/, because a worker may
   only control pages at or below its own path. */

self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (event) => event.waitUntil(self.clients.claim()));

const APP = "/app";
const ICON = "/app/icon-192.png";

// The count on the icon. Wrapped because Safari throws rather than returning
// a rejected promise when the app is not installed, and a worker that throws
// here never gets as far as showing the notification.
async function setBadge(count) {
  try {
    if (typeof count !== "number" || !self.navigator.setAppBadge) return;
    if (count > 0) await self.navigator.setAppBadge(count);
    else await self.navigator.clearAppBadge();
  } catch { /* not installed, or no badging here */ }
}

async function windows() {
  return self.clients.matchAll({ type: "window", includeUncontrolled: true });
}

self.addEventListener("push", (event) => {
  let data = {};
  try {
    data = event.data ? event.data.json() : {};
  } catch {
    data = { body: event.data ? event.data.text() : "" };
  }
  event.waitUntil((async () => {
    // iOS requires a visible notification for every push it delivers: stay
    // silent and the permission is taken away after a few of them.
    await self.registration.showNotification(data.title || "Cloudmorrow", {
      body: data.body || "",
      // One line per channel, replaced as it goes, rather than forty
      // stacked up by morning.
      tag: data.tag || "cloudmorrow",
      renotify: true,
      icon: ICON,
      badge: ICON,
      data: { url: data.url || "#/" },
    });
    await setBadge(data.badge);
    // A page that happens to be open should not wait for its next poll.
    for (const client of await windows()) {
      client.postMessage({ type: "push", url: data.url || "", badge: data.badge });
    }
  })());
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const hash = (event.notification.data && event.notification.data.url) || "#/";
  event.waitUntil((async () => {
    // Prefer the window that is already open — on a phone there is only
    // ever one, and opening a second is how you lose what was being typed.
    for (const client of await windows()) {
      if (client.url.includes(APP)) {
        client.postMessage({ type: "go", hash });
        if ("focus" in client) return client.focus();
        return undefined;
      }
    }
    return self.clients.openWindow(APP + hash);
  })());
});

// The subscription can be rotated by the browser without anyone asking. The
// page re-subscribes on every start, so the least this can do is not leave a
// notification claiming to have arrived.
self.addEventListener("pushsubscriptionchange", (event) => {
  event.waitUntil((async () => {
    for (const client of await windows()) client.postMessage({ type: "resubscribe" });
  })());
});
