/* Signing in. The API speaks bearer tokens, so this is one POST and the
   token goes into the session; signing out lives in core.js because every
   feature may need it when a token stops working. */

import { CLOUD_NAME, VERSION, api, app, esc, registerScreen, session, signIn, wordmark } from "./core.js";

function renderLogin(message = "", bad = false) {
  app.innerHTML = `
    <form class="login" autocomplete="on">
      <div class="brand"><span class="hedgehog" aria-hidden="true"></span>${wordmark()}</div>
      <h1>${esc(CLOUD_NAME === "Cloudmorrow" ? "Sign in" : CLOUD_NAME)}</h1>
      <div class="fields">
        <input name="username" placeholder="Username" autocapitalize="none" autocorrect="off" autocomplete="username" required value="${esc(session.user)}">
        <input name="password" type="password" placeholder="Password" autocomplete="current-password" required>
      </div>
      <p class="error${bad ? " bad" : ""}">${esc(message)}</p>
      <button class="submit" type="submit">Sign in</button>
      <p class="foot">Cloudmorrow ${esc(VERSION)} · <a href="/">install on a machine</a></p>
    </form>`;
  const form = app.querySelector("form");
  const error = form.querySelector(".error");
  form.querySelector(session.user ? "[name=password]" : "[name=username]").focus();
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const submit = form.querySelector(".submit");
    submit.disabled = true;
    error.textContent = "";
    try {
      signIn(await api("POST", "/api/auth/login", {
        username: form.username.value.trim(),
        password: form.password.value,
      }));
    } catch (err) {
      error.textContent = err.status === 401 ? "Wrong username or password." : err.message;
      error.classList.add("bad");
      submit.disabled = false;
    }
  });
}

registerScreen("login", (arg, { message = "", bad = false } = {}) => renderLogin(message, bad));
