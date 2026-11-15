// NINA-Logo, Kurzlogo und Icon nach dem Vorbild von MIRA (Schrift Dream MMA, dafont 100% kostenlos)
// node nina-logo.js <ausgabe-ordner> <mira-icon.svg>
const fs = require('fs');
const BASIS = process.env.DREAM_BASIS || "."; // Ordner mit otjs/node_modules/opentype.js und dreammma-dl/x/Dream MMA.ttf
const ot = require(BASIS + '/otjs/node_modules/opentype.js');
const f = ot.loadSync(BASIS + '/dreammma-dl/x/Dream MMA.ttf');
const segoe = ot.loadSync('C:/Windows/Fonts/seguisb.ttf');
const out = process.argv[2], miraIcon = process.argv[3];

// ---------- Farben: Blau/Cyan statt Orange ----------
const F = {
  seele: ['#b8f0ff', '#4fd0ff', '#0d8ee0'],     // hell → mittel → dunkel (Verlauf der Seele)
  seeleTief: '#00508f',                          // Tiefe unter der Seele (bei MIRA #b54a00)
  rand: ['#c4f2ff', '#5fd2ff', '#1690e0', '#0a5a9c'], // Schild-Rand (bei MIRA randmetall)
  icon: ['#9fe8ff', '#33c3ff', '#0a84d6'],       // Seele im Icon (bei MIRA #orange)
};

// ---------- Glyphen ----------
const KORREKTUR = {
  // n: linker Strich wie das m von MIRA oben gerade abgeschnitten (keine Spitze)
  n: 'M19.3 0L-0.1 0L16.12-57L20.37-57L30.4-38.2ZM55.5-62.5L69.5-35.1L81.8-70L107.4-70L86.2 0.1L56.1 0.1L20.5-70L45.5-70Q47.3-70.2 50.35-68.2Q53.4-66.2 55.5-62.5Z',
  i: 'M29 0L0 0L20.5-70L50.4-70Z',
};
// Füller der Kerbe oben links am n (nur Rand, Seele bleibt geteilt)
const FUELLER_N = [[16.12, -57], [19.82, -70], [20.5, -70], [27.1, -57]];
{ // a gespiegelt wie bei MIRA
  const p = f.charToGlyph('a').getPath(0, 0, 100), W = 110.8;
  let d = '';
  for (const c of p.commands) {
    if (c.type === 'M') d += `M${(W - c.x).toFixed(2)} ${c.y.toFixed(2)}`;
    else if (c.type === 'L') d += `L${(W - c.x).toFixed(2)} ${c.y.toFixed(2)}`;
    else if (c.type === 'Q') d += `Q${(W - c.x1).toFixed(2)} ${c.y1.toFixed(2)} ${(W - c.x).toFixed(2)} ${c.y.toFixed(2)}`;
    else if (c.type === 'Z') d += 'Z';
  }
  KORREKTUR.a = d;
}
function glyphPfad(ch, x, y, size) {
  if (!KORREKTUR[ch]) return f.charToGlyph(ch).getPath(x, y, size);
  const p = new ot.Path(), k = size / 100;
  const t = KORREKTUR[ch].match(/[MLQZ]|-?[\d.]+/g);
  let i = 0; const n = () => parseFloat(t[i++]);
  while (i < t.length) {
    const c = t[i++];
    if (c === 'M') p.moveTo(x + n() * k, y + n() * k);
    else if (c === 'L') p.lineTo(x + n() * k, y + n() * k);
    else if (c === 'Q') { const a = x + n() * k, b = y + n() * k; p.quadTo(a, b, x + n() * k, y + n() * k); }
    else if (c === 'Z') p.close();
  }
  return p;
}
function polygone(ch) {
  const ps = []; let cur = null, last = null;
  for (const c of glyphPfad(ch, 0, 0, 100).commands) {
    if (c.type === 'M') { cur = [[c.x, c.y]]; ps.push(cur); last = [c.x, c.y]; }
    else if (c.type === 'L') { cur.push([c.x, c.y]); last = [c.x, c.y]; }
    else if (c.type === 'Q') { for (let t = .125; t <= 1; t += .125) cur.push([(1 - t) ** 2 * last[0] + 2 * (1 - t) * t * c.x1 + t * t * c.x, (1 - t) ** 2 * last[1] + 2 * (1 - t) * t * c.y1 + t * t * c.y]); last = [c.x, c.y]; }
  }
  return ps;
}
function spanne(ch, y) {
  let lo = 1e9, hi = -1e9;
  for (const p of polygone(ch)) for (let i = 0; i < p.length; i++) {
    const [ax, ay] = p[i], [bx, by] = p[(i + 1) % p.length];
    if ((ay - y) * (by - y) <= 0 && ay !== by) { const x = ax + (y - ay) / (by - ay) * (bx - ax); lo = Math.min(lo, x); hi = Math.max(hi, x); }
  }
  return [lo, hi];
}
function abstand(a, b, dx) {
  let m = 1e9;
  for (let y = -68; y <= -2; y += 1) { const r = spanne(a, y)[1], l = spanne(b, y)[0]; if (r > -1e8 && l < 1e8) m = Math.min(m, dx + l - r); }
  return m;
}
const LUECKE = 15.5;   // gleiche engste Lücke wie bei MIRA
function positionen(text, size) {
  const xs = [0];
  for (let i = 1; i < text.length; i++) xs.push(xs[i - 1] + (100 + LUECKE - abstand(text[i - 1], text[i], 100)) * size / 100);
  return xs;
}
const wort = (text, x, y, size) => { const xs = positionen(text, size); return [...text].map((ch, i) => glyphPfad(ch, x + xs[i], y, size).toPathData(2)).join(''); };
function bbox(text, x, y, size) {
  let b = { x1: 1e9, y1: 1e9, x2: -1e9, y2: -1e9 };
  const xs = positionen(text, size);
  [...text].forEach((ch, i) => { const bb = glyphPfad(ch, x + xs[i], y, size).getBoundingBox(); b = { x1: Math.min(b.x1, bb.x1), y1: Math.min(b.y1, bb.y1), x2: Math.max(b.x2, bb.x2), y2: Math.max(b.y2, bb.y2) }; });
  return b;
}
const fueller = (x, y, k) => 'M' + FUELLER_N.map(([a, c]) => (x + a * k).toFixed(2) + ' ' + (y + c * k).toFixed(2)).join('L') + 'Z';

// ---------- Logo ----------
const TEXT = 'nina', SIZE = 100, Y = 97;
const b0 = bbox(TEXT, 0, Y, SIZE);
const X = 20 - b0.x1;
const xs = positionen(TEXT, SIZE);
const d = wort(TEXT, X, Y, SIZE);
const fd = [...TEXT].map((ch, i) => ch === 'n' ? fueller(X + xs[i], Y, SIZE / 100) : '').join('');
const b = bbox(TEXT, X, Y, SIZE);
const R = 9;
const vbX = b.x1 - 26, vbW = (b.x2 - b.x1) + 52;
const mitte = (b.x1 + b.x2) / 2;

// natürliche Breite einer Zeile in Segoe UI Semibold 14 px mit letter-spacing 1.5
const natur = (s, gr = 14) => [...s].reduce((w, ch) => w + segoe.charToGlyph(ch).advanceWidth * gr / segoe.unitsPerEm + 1.5, 0);
const MIRA_ZUSATZ = (392.5 - 287.4) / 33;   // Sperrung der MIRA-Unterzeile
let HOEHE = 159;
function unterzeilen() {
  const Z1 = 'NETWORK INVENTORY', Z2 = 'ASSISTANT';
  const w1 = b.x2 - b.x1 - 6;
  // Schriftgröße so, dass die Sperrung wie bei MIRA aussieht (Zeile ist kürzer als bei MIRA)
  const GR = Math.min(18, 14 * (w1 - Z1.length * (1.5 + MIRA_ZUSATZ)) / (natur(Z1) - Z1.length * 1.5));
  const Y1 = Math.round(112.5 + .72 * GR), Y2 = Math.round(Y1 + 30 * GR / 14);
  HOEHE = Y2 + 6;
  const zusatz = (w1 - natur(Z1, GR)) / Z1.length;
  const w2 = natur(Z2, GR) + Z2.length * zusatz;
  const x1 = mitte - w1 / 2, x2 = mitte - w2 / 2;
  const lx1 = (x1 + x2) / 2, lx2 = 2 * mitte - lx1;
  const ly = (Y1 + (Y2 - .73 * GR)) / 2 + .5;
  const stil = `font-family="'Segoe UI Semibold','Segoe UI',Arial,Helvetica,sans-serif" font-size="${GR.toFixed(1)}" font-weight="600"
        fill="#ffffff" stroke="#25272c" stroke-width="${(2.8 * GR / 14).toFixed(1)}" stroke-linejoin="round" paint-order="stroke" letter-spacing="1.5" lengthAdjust="spacing"`;
  return `
  <!-- ausgeschrieben -->
  <text x="${x1.toFixed(1)}" y="${Y1}" textLength="${w1.toFixed(1)}" ${stil}>${Z1}</text>
  <!-- Trennlinie -->
  <path d="M${lx1.toFixed(1)} ${ly.toFixed(1)}H${lx2.toFixed(1)}" stroke="#25272c" stroke-width="3.6" stroke-linecap="round"/>
  <path d="M${lx1.toFixed(1)} ${ly.toFixed(1)}H${lx2.toFixed(1)}" stroke="#ffffff" stroke-width="1.2" stroke-linecap="round"/>
  <text x="${x2.toFixed(1)}" y="${Y2}" textLength="${w2.toFixed(1)}" ${stil}>${Z2}</text>
`;
}
const HELL = '.hinterschein{fill:#000;stroke:#000;opacity:.5;transform:translate(0,4px)}';
const DUNKEL = '.hinterschein{fill:#fff;stroke:#fff;opacity:.34;transform:none}';
const schattenStil = m => m === 'hell' ? `  <style>${HELL}</style>` : m === 'dunkel' ? `  <style>${DUNKEL}</style>`
  : `  <style>\n    ${HELL}\n    @media (prefers-color-scheme: dark){${DUNKEL}}\n  </style>`;
function logo(mitText, modus) {
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="${vbX.toFixed(1)} 0 ${vbW.toFixed(1)} ${mitText ? (unterzeilen(), HOEHE) : 118}" role="img" aria-label="NINA – Network Inventory Assistant">
  <defs>
    <!-- Buchstaben: Schrift Dream MMA (dafont, 100% kostenlos) als Pfade -->
    <path id="b" d="${d}"/>
    <path id="f" d="${fd}"/>
    <linearGradient id="rahmen" x1="0" y1="18" x2="0" y2="102" gradientUnits="userSpaceOnUse">
      <stop offset="0" stop-color="#4b4f58"/><stop offset=".5" stop-color="#33363c"/><stop offset="1" stop-color="#202226"/>
    </linearGradient>
    <linearGradient id="seele" x1="0" y1="26" x2="0" y2="96" gradientUnits="userSpaceOnUse">
      <stop offset="0" stop-color="${F.seele[0]}"/><stop offset=".35" stop-color="${F.seele[1]}"/><stop offset="1" stop-color="${F.seele[2]}"/>
    </linearGradient>
    <radialGradient id="sonne" cx="70" cy="10" r="190" gradientUnits="userSpaceOnUse" gradientTransform="translate(70 10) scale(1 .55) translate(-70 -10)">
      <stop offset="0" stop-color="#fff" stop-opacity=".6"/><stop offset=".35" stop-color="#fff" stop-opacity=".22"/><stop offset=".7" stop-color="#fff" stop-opacity="0"/>
    </radialGradient>
    <linearGradient id="spiegel" x1="0" y1="14" x2="0" y2="62" gradientUnits="userSpaceOnUse">
      <stop offset="0" stop-color="#fff" stop-opacity=".62"/><stop offset=".55" stop-color="#fff" stop-opacity=".3"/><stop offset="1" stop-color="#fff" stop-opacity=".14"/>
    </linearGradient>
    <filter id="bogenweich" filterUnits="userSpaceOnUse" x="-100" y="-300" width="700" height="450"><feGaussianBlur stdDeviation=".7"/></filter>
    <filter id="hinterweich" filterUnits="userSpaceOnUse" x="-50" y="-20" width="600" height="200"><feGaussianBlur stdDeviation="7"/></filter>
    <mask id="form" maskUnits="userSpaceOnUse" x="-50" y="0" width="600" height="150">
      <use href="#b" fill="#fff" stroke="#fff" stroke-width="${R}" stroke-linejoin="miter"/>
      <use href="#f" fill="#fff" stroke="#fff" stroke-width="${R}" stroke-linejoin="miter"/>
    </mask>
    <mask id="fase" maskUnits="userSpaceOnUse" x="-50" y="0" width="600" height="150">
      <use href="#b" fill="#fff" stroke="#000" stroke-width="2.4" stroke-linejoin="miter"/>
    </mask>
    <mask id="kern" maskUnits="userSpaceOnUse" x="-50" y="0" width="600" height="150">
      <use href="#b" fill="#fff" stroke="#000" stroke-width="5" stroke-linejoin="miter"/>
    </mask>
  </defs>

  <!-- ganz leichter Schatten hinter dem Schriftzug: hell auf dunklem, dunkel auf hellem Untergrund -->
${schattenStil(modus)}
  <g filter="url(#hinterweich)"><use href="#b" class="hinterschein" stroke-width="${R}" stroke-linejoin="round"/><use href="#f" class="hinterschein" stroke-width="${R}" stroke-linejoin="round"/></g>

  <!-- Rand, gleich breit an allen Seiten -->
  <use href="#b" fill="url(#rahmen)" stroke="url(#rahmen)" stroke-width="${R}" stroke-linejoin="miter"/>
  <use href="#f" fill="url(#rahmen)" stroke="url(#rahmen)" stroke-width="${R}" stroke-linejoin="miter"/>
  <!-- feine Fase innen am Rand -->
  <use href="#b" fill="#000" fill-opacity=".35" mask="url(#fase)"/>
  <!-- blaue Seele, leicht gewölbt -->
  <g mask="url(#kern)">
    <use href="#b" fill="${F.seeleTief}"/>
    <use href="#b" fill="url(#seele)" transform="translate(0 .9)"/>
  </g>
  <!-- Glanz -->
  <rect x="-50" y="0" width="600" height="110" fill="url(#sonne)" opacity=".6" mask="url(#form)"/>
  <g mask="url(#form)">
    <ellipse cx="${mitte.toFixed(0)}" cy="-110" rx="${(vbW * .85).toFixed(0)}" ry="168" transform="rotate(-5 ${mitte.toFixed(0)} -110)" fill="url(#spiegel)" filter="url(#bogenweich)"/>
  </g>
${mitText ? unterzeilen() : ''}</svg>
`;
}
fs.writeFileSync(out + '/logo.svg', logo(true));
fs.writeFileSync(out + '/logo-kurz.svg', logo(false));
for (const m of ['hell', 'dunkel']) {
  fs.writeFileSync(out + '/logo-' + m + '.svg', logo(true, m));
  fs.writeFileSync(out + '/logo-kurz-' + m + '.svg', logo(false, m));
}

// ---------- Icon: MIRA-Schild mit n, blau ----------
{
  const MB = 38;                                    // Breite des n (das m von MIRA hat 44)
  const s0 = glyphPfad('n', 0, 0, 100).getBoundingBox();
  const size = 100 * MB / (s0.x2 - s0.x1), h = (s0.y2 - s0.y1) * size / 100, k = size / 100;
  const nx = 50 - MB / 2 - s0.x1 * k, ny = 43 + h / 2;
  let ic = fs.readFileSync(miraIcon, 'utf8');
  ic = ic.replace('aria-label="MIRA"', 'aria-label="NINA"');
  ic = ic.replace(/<path id="m" transform="translate\(0 -3\)" d="[^"]*"\/>/, `<path id="m" transform="translate(0 -3)" d="${glyphPfad('n', nx, ny, size).toPathData(2)}"/>`);
  ic = ic.replace(/<path id="mf" transform="translate\(0 -3\)" d="[^"]*"\/>/, `<path id="mf" transform="translate(0 -3)" d="${fueller(nx, ny, k)}"/>`);
  // Rand des Schilds und Seele blau
  ic = ic.replace(/(<linearGradient id="randmetall"[^>]*>\s*)<stop offset="0" stop-color="#ffd27a"\/><stop offset=".3" stop-color="#ffa62b"\/>\s*<stop offset=".7" stop-color="#f07a0a"\/><stop offset="1" stop-color="#b85000"\/>/,
    `$1<stop offset="0" stop-color="${F.rand[0]}"/><stop offset=".3" stop-color="${F.rand[1]}"/>\n      <stop offset=".7" stop-color="${F.rand[2]}"/><stop offset="1" stop-color="${F.rand[3]}"/>`);
  ic = ic.replace('<stop offset="0" stop-color="#ffc04d"/>', `<stop offset="0" stop-color="${F.icon[0]}"/>`)
    .replace('<stop offset=".5" stop-color="#ff9a1a"/>', `<stop offset=".5" stop-color="${F.icon[1]}"/>`)
    .replace('<stop offset="1" stop-color="#ff7000"/>', `<stop offset="1" stop-color="${F.icon[2]}"/>`)
    .replace(/#b54a00/g, F.seeleTief)
    .replace(/oranger Rand/g, 'blauer Rand').replace(/orange Seele/g, 'blaue Seele')
    .replace(/\bM\b(?=[ -])/g, 'n').replace('m in Dream MMA', 'n in Dream MMA').replace('Bogen in der oberen Hälfte des m', 'Bogen in der oberen Hälfte des n');
  if (/#ff[0-9a-f]{4}/i.test(ic.replace(/pAcc|pRout|lRout|lAcc/g, ''))) console.log('Hinweis: noch orange Töne im Icon:', ic.match(/#ff[0-9a-f]{4}/gi));
  fs.writeFileSync(out + '/icon.svg', ic);
}
console.log('fertig, Logo-Box', b);
