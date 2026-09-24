/* The count on the home-screen icon, and what it takes to get one.

   Two halves. While the app is open this asks the server what is waiting and
   sets the badge itself. While it is closed the service worker does it, woken
   by a push — which needs the browser's permission, a subscription, and the
   server's public key to subscribe with.

   On iOS none of that is available until the app is on the home screen: in
   Safari's own tab there is no service worker registration to push and
   `setAppBadge` does nothing. So the card below says which of those two
   situations you are in rather than offering a button that cannot work.

   Everything here fails quietly. A phone with notifications turned off is a
   phone that reads its messages when it opens the app, which is what the app
   did before any of this. */

import { api, esc, onSignOut, session, toast } from "./core.js";

// How often the badge is checked while the app is up. The push is what makes
// it prompt; this is only so a count cleared on the laptop does not sit on
// the phone's icon until something else happens.
const EVERY = 60 * 1000;

export const supported = () =>
  "serviceWorker" in navigator && "PushManager" in window && "Notification" in window;

// An app on the home screen, rather than a tab. iOS grants neither push nor
// badging to a tab, and says so only by silently doing nothing.
export const installed = () =>
  window.matchMedia("(display-mode: standalone)").matches || navigator.standalone === true;

const badgeHooks = [];
const pushHooks = [];
/** Told the counts whenever they are looked up: {messages, notifications, badge}. */
export function onBadge(fn) { badgeHooks.push(fn); }
/** Told when a push arrives while the app is open. */
export function onPush(fn) { pushHooks.push(fn); }

let counts = { messages: 0, notifications: 0, badge: 0 };
export const lastCounts = () => counts;

// -- the badge ------------------------------------------------------------------
async function paint(n) {
  try {
    if (!navigator.setAppBadge) return;
    if (n > 0) await navigator.setAppBadge(n);
    else await navigator.clearAppBadge();
  } catch { /* not installed, or the browser has no badges */ }
}

export async function refreshBadge() {
  if (!session.token) return counts;
  try {
    counts = await api("GET", "/api/push/badge");
  } catch {
    return counts;   // offline: leave the icon saying what it last knew
  }
  await paint(counts.badge);
  for (const fn of badgeHooks) fn(counts);
  return counts;
}

// -- the worker -------------------------------------------------------------------
let registration = null;

async function worker() {
  if (registration) return registration;
  if (!supported()) return null;
  try {
    registration = await navigator.serviceWorker.register("/app/sw.js", { scope: "/app/" });
    return registration;
  } catch (err) {
    console.warn("no service worker:", err);
    return null;
  }
}

// The key comes as base64url and `subscribe` wants bytes.
function keyBytes(text) {
  const padded = (text + "=".repeat((4 - (text.length % 4)) % 4)).replace(/-/g, "+").replace(/_/g, "/");
  const raw = atob(padded);
  return Uint8Array.from([...raw].map((c) => c.charCodeAt(0)));
}

export function state() {
  if (!supported()) return "unsupported";
  if (!installed()) return "not-installed";
  return Notification.permission;   // "default" | "granted" | "denied"
}

/** Ask for permission and register this device. Must be called from a tap. */
export async function enable() {
  if (!supported()) throw new Error("This browser cannot do push notifications.");
  const permission = await Notification.requestPermission();
  if (permission !== "granted") throw new Error("Notifications are turned off for this app.");
  await subscribe();
}

/** Register with the push service and tell the server, if we may. */
export async function subscribe() {
  if (!supported() || Notification.permission !== "granted") return null;
  const reg = await worker();
  if (!reg) return null;
  const { public_key: key } = await api("GET", "/api/push/key");
  let subscription = await reg.pushManager.getSubscription();
  // A subscription made under a different server key is a subscription the
  // server cannot push. That happens when vapid.key is replaced.
  if (subscription && !sameKey(subscription, key)) {
    await subscription.unsubscribe();
    subscription = null;
  }
  if (!subscription) {
    subscription = await reg.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: keyBytes(key),
    });
  }
  const body = subscription.toJSON();
  await api("POST", "/api/push/subscribe", {
    endpoint: body.endpoint,
    keys: { p256dh: body.keys.p256dh, auth: body.keys.auth },
    label: deviceLabel(),
  });
  return subscription;
}

function sameKey(subscription, key) {
  const mine = subscription.options && subscription.options.applicationServerKey;
  if (!mine) return true;   // nothing to compare; let the server decide
  const bytes = new Uint8Array(mine);
  const wanted = keyBytes(key);
  return bytes.length === wanted.length && bytes.every((b, i) => b === wanted[i]);
}

export async function disable() {
  const reg = await worker();
  const subscription = reg && (await reg.pushManager.getSubscription());
  if (!subscription) return;
  try { await api("POST", "/api/push/unsubscribe", { endpoint: subscription.endpoint }); }
  catch { /* the row may already be gone; the browser's side still matters */ }
  await subscription.unsubscribe();
}

// Something short and recognisable in a list of devices. Not a fingerprint:
// it is only there so you can tell the phone from the laptop.
function deviceLabel() {
  const ua = navigator.userAgent || "";
  if (/iPad/.test(ua)) return "iPad";
  if (/iPhone/.test(ua)) return "iPhone";
  if (/Android/.test(ua)) return "Android";
  if (/Mac OS X/.test(ua)) return "Mac";
  if (/Windows/.test(ua)) return "Windows";
  return "This browser";
}

// -- the card in Me ------------------------------------------------------------------
const WORDS = {
  unsupported: ["Notifications", "This browser cannot show them."],
  "not-installed": ["Notifications", "Add Cloudmorrow to your Home Screen first, then turn them on here."],
  default: ["Notifications", "Get a banner and a count on the icon when somebody writes."],
  denied: ["Notifications", "Turned off in Settings › Notifications › Cloudmorrow."],
  granted: ["Notifications are on", "This device gets a banner and the count on its icon."],
};

export function pushCard() {
  const where = state();
  const [title, line] = WORDS[where] || WORDS.default;
  const button =
    where === "default" ? `<button class="push-on">Turn on</button>` :
    where === "granted" ? `<button class="push-test">Send a test</button>` : "";
  return `<div class="group push-card"><div class="row">
    <span class="main"><span class="title">${esc(title)}</span>
    <span class="meta"><span class="preview">${esc(line)}</span></span></span>${button}</div></div>`;
}

/** Wire whatever `pushCard` put on the page. Safe to call when it did not. */
export function wirePushCard(root = document) {
  const on = root.querySelector(".push-card .push-on");
  if (on) {
    on.addEventListener("click", async () => {
      on.disabled = true;
      try {
        await enable();
        toast("Notifications are on");
        // The card's words change with the permission.
        const card = root.querySelector(".push-card");
        if (card) card.outerHTML = pushCard();
        wirePushCard(root);
        refreshBadge();
      } catch (err) {
        toast(err.message);
        on.disabled = false;
      }
    });
  }
  const test = root.querySelector(".push-card .push-test");
  if (test) {
    test.addEventListener("click", async () => {
      test.disabled = true;
      try {
        await subscribe();
        await api("POST", "/api/push/test");
        toast("Sent — it should arrive in a moment");
      } catch (err) {
        toast(err.message);
      }
      test.disabled = false;
    });
  }
}

// -- keeping up ---------------------------------------------------------------------------
navigator.serviceWorker?.addEventListener("message", (event) => {
  const data = event.data || {};
  if (data.type === "go" && data.hash) {
    location.hash = data.hash;
  } else if (data.type === "push") {
    refreshBadge();
    for (const fn of pushHooks) fn(data);
  } else if (data.type === "resubscribe") {
    subscribe().catch(() => {});
  }
});

addEventListener("visibilitychange", () => {
  if (document.visibilityState === "visible") refreshBadge();
});
setInterval(() => {
  if (document.visibilityState === "visible") refreshBadge();
}, EVERY);

onSignOut(() => {
  counts = { messages: 0, notifications: 0, badge: 0 };
  paint(0);
  // The device stays subscribed on purpose: signing out of the phone app and
  // back in is routine, and asking iOS for permission again each time is the
  // quickest way to have it refused for good. `disable()` is the way out.
});

// On start: register the worker, pick up a subscription the browser may have
// rotated, and put the right number on the icon.
if (session.token) {
  worker().then(() => subscribe()).catch(() => {});
  refreshBadge();
}
