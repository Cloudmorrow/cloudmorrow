/* A QR code as an SVG, drawn from the matrix: crisp at any size, no image
   file. Dark modules on white with the quiet zone the standard asks for,
   whatever the theme, because a camera reads contrast, not a palette.

   Its own file, with no import from core.js, so the setup page — which is
   not the app — can draw one too. */

import qrcode from "./qrcode.js";

const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);

export function qrSvg(text, label = "") {
  const qr = qrcode(0, "M");
  qr.addData(text);
  qr.make();
  const n = qr.getModuleCount();
  const quiet = 4;
  let path = "";
  for (let r = 0; r < n; r += 1) {
    for (let c = 0; c < n; c += 1) {
      if (qr.isDark(r, c)) path += `M${c + quiet} ${r + quiet}h1v1h-1z`;
    }
  }
  const size = n + quiet * 2;
  return `<svg class="qr" viewBox="0 0 ${size} ${size}" role="img" aria-label="${esc(label || text)}"
    shape-rendering="crispEdges" xmlns="http://www.w3.org/2000/svg">
    <rect width="${size}" height="${size}" fill="#fff"/><path d="${path}" fill="#000"/></svg>`;
}
