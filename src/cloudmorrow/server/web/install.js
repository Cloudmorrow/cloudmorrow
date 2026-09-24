/* The card that offers to put the app on the home screen.

   Chrome and Edge, on Android and the desktop, hand the page an install
   prompt it may show from a button of its own. iOS hands out nothing: there
   the card can only say which two taps do it. Neither shows once installed.
   A screen that wants the card puts an `.install-slot` where it should go. */

import { app, onShell, store, wordmark } from "./core.js";

const shareIcon = '<svg width="16" height="20" viewBox="0 0 16 20" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M8 1.5v12M4.5 5 8 1.5 11.5 5M3 8.5H1.5v10h13v-10H13"/></svg>';

let installPrompt = null;
addEventListener("beforeinstallprompt", (event) => {
  event.preventDefault();
  installPrompt = event;
  refreshInstallCard();
});
addEventListener("appinstalled", () => {
  installPrompt = null;
  store.set("install-answered", String(Date.now()));
  refreshInstallCard();
});

const isStandalone = () => matchMedia("(display-mode: standalone)").matches || navigator.standalone === true;
const isIOS = () => /iPhone|iPad|iPod/.test(navigator.userAgent)
  || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);

export function installCard() {
  if (isStandalone()) return "";
  const answered = Number(store.get("install-answered") || 0);
  if (Date.now() - answered < 30 * 86400000) return "";
  const brand = `<div class="brand">${wordmark()}</div>`;
  if (installPrompt) {
    return `<div class="install">${brand}<div class="text"><b>Install as an app</b>
      Put Cloudmorrow on your home screen: an icon of its own, no browser bar.</div>
      <div class="actions"><button class="install-go strong">Install</button><button class="install-no">Not now</button></div></div>`;
  }
  if (isIOS()) {
    return `<div class="install">${brand}<div class="text"><b>Add to your home screen</b>
      Tap <span class="key">${shareIcon} Share</span> below, then <span class="key">Add to Home Screen</span>.</div>
      <div class="actions"><button class="install-no">Got it</button></div></div>`;
  }
  return "";
}

function wireInstall() {
  const go = app.querySelector(".install-go");
  if (go) go.addEventListener("click", async () => {
    const prompt = installPrompt;
    installPrompt = null;
    try {
      prompt.prompt();
      const { outcome } = await prompt.userChoice;
      if (outcome !== "accepted") store.set("install-answered", String(Date.now()));
    } catch { /* the browser declined to ask; the card goes away either way */ }
    refreshInstallCard();
  });
  const no = app.querySelector(".install-no");
  if (no) no.addEventListener("click", () => {
    store.set("install-answered", String(Date.now()));
    refreshInstallCard();
  });
}

function refreshInstallCard() {
  const slot = app.querySelector(".install-slot");
  if (!slot) return;
  slot.innerHTML = installCard();
  wireInstall();
}

onShell(wireInstall);
