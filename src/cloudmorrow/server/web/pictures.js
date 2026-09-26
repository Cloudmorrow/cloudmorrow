/* Pictures in a page of Markdown — shown in the page, where they are.

   The kit's editor draws its body with these. A picture is an attachment
   of the page's datamodel, kept by its backend (a note's are its pictures,
   in the notes folder): the editor hands over `ed.attachments`, the
   address they are kept at, and without one a page has no photo button.

   A picture goes up as itself — the body is the file, not a form around
   it — and comes back down through fetch, because an <img src> cannot
   carry the token. What comes back is kept as a blob URL for the page's
   life; the name says when it arrived, so it never means another picture.

   In the file a picture is a `![alt](img/name)` line, and that is what the
   TUI reads. On the page it is the picture itself: the body is a run of
   text boxes with the pictures between them, so you write above and below
   a picture and never see the line that stands for it. Saving joins the
   boxes and the lines back into the one body. */

import { ApiError, authHeaders, esc, fileStem, setStatus, toast } from "./core.js";

const photoIcon = '<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="4" width="18" height="16" rx="2"/><circle cx="9" cy="10" r="2"/><path d="m21 16-5-5-8 8"/></svg>';
const closeIcon = '<svg width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="m2 2 8 8M10 2l-8 8"/></svg>';

async function uploadImage(base, file) {
  const headers = { ...authHeaders(), "Content-Type": file.type || "application/octet-stream" };
  let res;
  try {
    res = await fetch(base + "?filename=" + encodeURIComponent(file.name || ""), {
      method: "POST", headers, body: file,
    });
  } catch {
    throw new ApiError(0, "Could not reach the server");
  }
  const data = await res.json().catch(() => null);
  if (!res.ok) throw new ApiError(res.status, data && data.detail !== undefined ? data.detail : "upload failed");
  return data;
}

const imageURLs = new Map();
async function imageURL(base, name) {
  const key = base + "/" + name;
  if (imageURLs.has(key)) return imageURLs.get(key);
  if (!base) throw new ApiError(404, "no such image");
  const res = await fetch(base + "/" + encodeURIComponent(name), { headers: authHeaders() });
  if (!res.ok) throw new ApiError(res.status, "no such image");
  const url = URL.createObjectURL(await res.blob());
  imageURLs.set(key, url);
  return url;
}

const isImage = (file) => file && /^image\//.test(file.type);

// -- the body as blocks ----------------------------------------------------------
// A line that is a picture and nothing else. A picture in the middle of a
// sentence stays text: it is not ours to move.
const IMAGE_LINE = /^\s*!\[([^\]]*)\]\(img\/([^)\s]+)\)\s*$/;
const isBlank = (line) => line.trim() === "";

// Text, then picture and text in turns — so there is always a box to write
// in before, between and after the pictures, even when it is empty.
export function parseBlocks(body) {
  const runs = [[]];
  const blocks = [];
  for (const line of body.split("\n")) {
    const match = IMAGE_LINE.exec(line);
    if (match) {
      blocks.push({ kind: "text", lines: runs[runs.length - 1] });
      blocks.push({ kind: "image", name: match[2], alt: match[1] });
      runs.push([]);
    } else {
      runs[runs.length - 1].push(line);
    }
  }
  blocks.push({ kind: "text", lines: runs[runs.length - 1] });
  return blocks.map((block, index) => {
    if (block.kind === "image") return block;
    // The blank lines around a picture are the separator, not the text.
    let lines = block.lines;
    if (index > 0) { while (lines.length && isBlank(lines[0])) lines = lines.slice(1); }
    if (index < blocks.length - 1) { while (lines.length && isBlank(lines[lines.length - 1])) lines = lines.slice(0, -1); }
    return { kind: "text", text: lines.join("\n") };
  });
}

export function composeBlocks(blocks) {
  const parts = [];
  for (const block of blocks) {
    if (block.kind === "image") parts.push(`![${block.alt}](img/${block.name})`);
    else if (block.text.trim()) parts.push(block.text);
  }
  return parts.join("\n\n");
}

// -- the editor's body ------------------------------------------------------------
// The editor supplies `changed`, called on every edit. In return it gets
// `bodyText(ed)`, `setBody(ed, text)`, `focusBody(ed)` and `ed.grow()`.
export const photoButton = `<button class="photo" aria-label="Add a photo">${photoIcon}</button>`;
export const bodyMarkup = `<div class="blocks"></div><input class="photo-input" type="file" accept="image/*" multiple hidden>`;

export function mountBody(ed, box, text) {
  ed.blocksEl = box.querySelector(".blocks");
  ed.grow = () => { for (const area of ed.blocksEl.querySelectorAll("textarea")) grow(area); };
  setBody(ed, text);
  wirePictures(ed, box);
  wireGaps(ed);
}

// A tap that lands beside the boxes — in the space under a picture, on the
// picture's own margin, below the last line — is a tap on the nearest box
// below it, at its start: that is where "under the picture" is. Below
// everything, it is the end of the last box.
function wireGaps(ed) {
  ed.blocksEl.addEventListener("click", (event) => {
    const target = event.target;
    if (target.tagName === "TEXTAREA" || target.tagName === "IMG" || target.closest("button")) return;
    const areas = [...ed.blocksEl.querySelectorAll("textarea")];
    if (!areas.length) return;
    const below = areas.find((area) => area.getBoundingClientRect().top >= event.clientY);
    const area = below || areas[areas.length - 1];
    const at = below ? 0 : area.value.length;
    area.focus();
    area.setSelectionRange(at, at);
  });
}

export function setBody(ed, text) {
  ed.blocksEl.replaceChildren(...parseBlocks(text).map((block) =>
    block.kind === "image" ? figureFor(ed, block.name, block.alt) : textareaFor(ed, block.text)));
  placeholders(ed);
  ed.grow();
}

export function bodyText(ed) {
  return composeBlocks([...ed.blocksEl.children].map((el) =>
    el.tagName === "FIGURE"
      ? { kind: "image", name: el.dataset.name, alt: el.dataset.alt }
      : { kind: "text", text: el.value }));
}

// The caret into the first box, or at the very end of the last.
export function focusBody(ed, { end = false } = {}) {
  const areas = ed.blocksEl.querySelectorAll("textarea");
  const area = end ? areas[areas.length - 1] : areas[0];
  if (!area) return;
  area.focus();
  const at = end ? area.value.length : 0;
  area.setSelectionRange(at, at);
}

function grow(area) {
  area.style.height = "auto";
  area.style.height = area.scrollHeight + "px";
}

// The first box invites writing; an empty box under a picture says, more
// quietly, that it is there to be written in — without it the space would
// look like nothing, and there would be nothing to tap.
function placeholders(ed) {
  const areas = ed.blocksEl.querySelectorAll("textarea");
  areas.forEach((area, index) => { area.placeholder = index === 0 ? "Write something…" : "Write here…"; });
}

function textareaFor(ed, text) {
  const area = document.createElement("textarea");
  area.className = "body";
  area.rows = 1;
  area.value = text;
  area.addEventListener("input", () => { grow(area); ed.changed(); });
  area.addEventListener("keydown", (event) => {
    // Backspace at the top of the box under a picture takes the picture.
    if (event.key === "Backspace" && area.selectionStart === 0 && area.selectionEnd === 0) {
      const above = area.previousElementSibling;
      if (above && above.tagName === "FIGURE") { event.preventDefault(); removePicture(ed, above); }
    }
  });
  return area;
}

function figureFor(ed, name, alt) {
  const figure = document.createElement("figure");
  figure.className = "picture";
  figure.dataset.name = name;
  figure.dataset.alt = alt;
  figure.innerHTML = `<img alt="${esc(alt)}"><button class="remove" type="button" aria-label="Remove picture">${closeIcon}</button>`;
  const img = figure.querySelector("img");
  imageURL(ed.attachments || "", name)
    .then((url) => { img.src = url; })
    .catch(() => { figure.classList.add("missing"); figure.insertAdjacentHTML("beforeend", `<figcaption>missing: ${esc(name)}</figcaption>`); });
  img.addEventListener("click", () => { if (img.src) openLightbox(img.src, alt); });
  figure.querySelector(".remove").addEventListener("click", () => removePicture(ed, figure));
  return figure;
}

// A picture goes where the caret is: the box splits around it. With no box
// focused, it goes at the end.
function insertPicture(ed, name, alt) {
  const areas = [...ed.blocksEl.querySelectorAll("textarea")];
  let area = areas.find((a) => a === document.activeElement) || areas[areas.length - 1];
  let at = area === document.activeElement ? area.selectionStart : area.value.length;
  const before = area.value.slice(0, at);
  const after = area.value.slice(at);
  area.value = before;
  const figure = figureFor(ed, name, alt);
  const next = textareaFor(ed, after);
  area.after(figure, next);
  placeholders(ed);
  ed.grow();
  next.focus();
  next.setSelectionRange(0, 0);
  ed.changed();
}

// The line goes; the file stays on the server, as it would for any other
// client. The boxes either side become one.
function removePicture(ed, figure) {
  const above = figure.previousElementSibling;
  const below = figure.nextElementSibling;
  const caret = above.value.length;
  above.value = [above.value, below.value].filter((t) => t.trim()).join("\n\n");
  figure.remove();
  below.remove();
  placeholders(ed);
  ed.grow();
  above.focus();
  above.setSelectionRange(caret, caret);
  ed.changed();
}

// Hook pictures up to an editor that is on the page: the button, a
// paste, or a drop each end as a picture at the caret. `box` is the
// `.editor` element and the button is in the bar above it.
function wirePictures(ed, box) {
  if (!ed.attachments) return;
  const photo = document.querySelector(".nav .photo");
  const photoInput = box.querySelector(".photo-input");
  if (photo) photo.addEventListener("click", () => photoInput.click());
  photoInput.addEventListener("change", () => {
    addPictures(ed, [...photoInput.files]);
    photoInput.value = "";
  });
  ed.blocksEl.addEventListener("paste", (event) => {
    const files = [...((event.clipboardData && event.clipboardData.files) || [])].filter(isImage);
    if (!files.length) return;
    event.preventDefault();
    addPictures(ed, files);
  });
  box.addEventListener("dragover", (event) => {
    if (event.dataTransfer && [...event.dataTransfer.types].includes("Files")) {
      event.preventDefault();
      box.classList.add("dropping");
    }
  });
  box.addEventListener("dragleave", () => box.classList.remove("dropping"));
  box.addEventListener("drop", (event) => {
    box.classList.remove("dropping");
    const files = [...((event.dataTransfer && event.dataTransfer.files) || [])].filter(isImage);
    if (!files.length) return;
    event.preventDefault();
    addPictures(ed, files);
  });
}

async function addPictures(ed, files) {
  for (const file of files) {
    setStatus(ed, "Adding photo…");
    let info;
    try { info = await uploadImage(ed.attachments, file); }
    catch (err) {
      setStatus(ed, "");
      toast(err.status === 413 ? "That photo is too big" : err.message);
      return;
    }
    const alt = fileStem((file.name || "").replace(/\.[^.]+$/, "")) || "photo";
    const name = String(info.path || "").replace(/^img\//, "");
    insertPicture(ed, name, alt);
  }
}

function openLightbox(src, alt) {
  const box = document.createElement("div");
  box.className = "lightbox";
  box.innerHTML = `<img src="${esc(src)}" alt="${esc(alt)}">`;
  box.addEventListener("click", () => box.remove());
  document.body.appendChild(box);
}
