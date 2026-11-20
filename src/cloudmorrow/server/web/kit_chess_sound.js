/* The chess board's sounds, made here with the Web Audio API — no files:
   a wooden tap for a move, a heavier double knock for a capture, the two
   pieces of a castle, a small bell with a check, and a little chime when
   the game is over. A browser plays nothing until the page has been
   touched, so the first press on the board wakes the sound (`wake`). It
   can be switched off with the speaker beside the moves; the choice is
   this browser's own (localStorage), like a folded list. */

const KEY = "chess.sound";
let context = null;
let noise = null;

export function soundOn() {
  try { return localStorage.getItem(KEY) !== "off"; } catch { return true; }
}

export function setSound(on) {
  try { localStorage.setItem(KEY, on ? "on" : "off"); } catch { /* private mode: for now only */ }
  if (on) wake();
}

/** The sound, started on a press: a browser lets a page play only after one. */
export function wake() {
  if (!context) {
    const Audio = window.AudioContext || window.webkitAudioContext;
    if (!Audio) return null;
    try { context = new Audio(); } catch { return null; }
  }
  if (context.state === "suspended") context.resume().catch(() => {});
  return context;
}

function noiseBuffer(c) {
  if (noise) return noise;
  noise = c.createBuffer(1, Math.floor(c.sampleRate * 0.2), c.sampleRate);
  const data = noise.getChannelData(0);
  for (let i = 0; i < data.length; i++) data[i] = Math.random() * 2 - 1;
  return noise;
}

// One knock of wood on wood: a burst of noise through a narrow band, and a low thud under it.
function knock(c, at, { pitch = 1, loud = 1 } = {}) {
  const source = c.createBufferSource();
  source.buffer = noiseBuffer(c);
  const band = c.createBiquadFilter();
  band.type = "bandpass";
  band.frequency.value = 1500 * pitch;
  band.Q.value = 1.4;
  const gain = c.createGain();
  gain.gain.setValueAtTime(0.0001, at);
  gain.gain.exponentialRampToValueAtTime(0.55 * loud, at + 0.004);
  gain.gain.exponentialRampToValueAtTime(0.0001, at + 0.07);
  source.connect(band).connect(gain).connect(c.destination);
  source.start(at);
  source.stop(at + 0.09);
  const thud = c.createOscillator();
  thud.type = "sine";
  thud.frequency.setValueAtTime(190 * pitch, at);
  thud.frequency.exponentialRampToValueAtTime(90 * pitch, at + 0.08);
  const body = c.createGain();
  body.gain.setValueAtTime(0.0001, at);
  body.gain.exponentialRampToValueAtTime(0.5 * loud, at + 0.006);
  body.gain.exponentialRampToValueAtTime(0.0001, at + 0.1);
  thud.connect(body).connect(c.destination);
  thud.start(at);
  thud.stop(at + 0.12);
}

function bell(c, at, freq, { length = 0.35, loud = 0.18 } = {}) {
  const tone = c.createOscillator();
  tone.type = "sine";
  tone.frequency.value = freq;
  const gain = c.createGain();
  gain.gain.setValueAtTime(0.0001, at);
  gain.gain.exponentialRampToValueAtTime(loud, at + 0.01);
  gain.gain.exponentialRampToValueAtTime(0.0001, at + length);
  tone.connect(gain).connect(c.destination);
  tone.start(at);
  tone.stop(at + length + 0.02);
}

/** What a move sounds like, from how it is written: O-O, Nxe5, Qh7+, e8=Q#. */
export function kindOf(san) {
  if (!san) return "move";
  if (san.startsWith("O-O")) return "castle";
  if (san.includes("x")) return san.endsWith("+") || san.endsWith("#") ? "capture-check" : "capture";
  return san.endsWith("+") || san.endsWith("#") ? "check" : "move";
}

/** Play one: move, capture, castle, check, capture-check, or end. */
export function play(kind) {
  if (!soundOn() || !context || context.state !== "running") return;
  const c = context;
  const at = c.currentTime + 0.01;
  if (kind === "end") {
    [523.25, 659.25, 783.99].forEach((f, i) => bell(c, at + i * 0.13, f, { length: 0.5, loud: 0.14 }));
    return;
  }
  if (kind === "castle") { knock(c, at); knock(c, at + 0.12, { pitch: 0.9 }); return; }
  if (kind.startsWith("capture")) { knock(c, at, { pitch: 0.8, loud: 1.2 }); knock(c, at + 0.05, { pitch: 0.7, loud: 0.9 }); }
  else knock(c, at);
  if (kind.endsWith("check")) bell(c, at + 0.06, 880);
}
