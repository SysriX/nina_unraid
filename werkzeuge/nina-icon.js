// NINA-Icon: quadratischer Rahmen (wie das erste Icon) mit Nodes; Variante A mit n, Variante B mit Router
// node nina-icon.js <ausgabe-ordner>
const fs = require('fs');
const out = process.argv[2];
// n aus Dream MMA (korrigiert wie im Logo), Koordinaten bei Größe 100, Grundlinie 0
const N = 'M19.3 0L-0.1 0L16.12-57L20.37-57L30.4-38.2ZM55.5-62.5L69.5-35.1L81.8-70L107.4-70L86.2 0.1L56.1 0.1L20.5-70L45.5-70Q47.3-70.2 50.35-68.2Q53.4-66.2 55.5-62.5Z';
const NF = [[16.12, -57], [19.82, -70], [20.5, -70], [27.1, -57]];   // Kerben-Füller (nur Rand)
function transform(d, x, y, k) {
  const t = d.match(/[MLQZ]|-?[\d.]+/g); let i = 0, s = '';
  const p = () => (x + parseFloat(t[i++]) * k).toFixed(2) + ' ' + (y + parseFloat(t[i++]) * k).toFixed(2);
  while (i < t.length) { const c = t[i++]; if (c === 'Z') s += 'Z'; else if (c === 'Q') s += 'Q' + p() + ' ' + p(); else s += c + p(); }
  return s;
}

const DEFS = `
    <linearGradient id="rand" x1="10" y1="8" x2="90" y2="92" gradientUnits="userSpaceOnUse">
      <stop offset="0" stop-color="#c4f2ff"/><stop offset=".35" stop-color="#5fd2ff"/>
      <stop offset=".75" stop-color="#1690e0"/><stop offset="1" stop-color="#0a5a9c"/>
    </linearGradient>
    <linearGradient id="feld" x1="20" y1="14" x2="80" y2="86" gradientUnits="userSpaceOnUse">
      <stop offset="0" stop-color="#4a4e57"/><stop offset=".5" stop-color="#2a2c32"/><stop offset="1" stop-color="#16171a"/>
    </linearGradient>
    <radialGradient id="licht" cx="34" cy="24" r="40" gradientUnits="userSpaceOnUse">
      <stop offset="0" stop-color="#fff" stop-opacity=".2"/><stop offset="1" stop-color="#fff" stop-opacity="0"/>
    </radialGradient>
    <radialGradient id="led" cx="50%" cy="40%" r="60%">
      <stop offset="0" stop-color="#e6fbff"/><stop offset=".45" stop-color="#4fd0ff"/><stop offset="1" stop-color="#0a78c8"/>
    </radialGradient>
    <filter id="glow" x="-50%" y="-50%" width="200%" height="200%">
      <feGaussianBlur stdDeviation="1.6" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge>
    </filter>`;
const RAHMEN = `
  <!-- Gehäuse: dunkle Kante, blauer Metallrand, dunkles Feld -->
  <rect x="7" y="7" width="86" height="86" rx="20" fill="#0b0c0e"/>
  <rect x="9" y="9" width="82" height="82" rx="18.5" fill="url(#rand)"/>
  <rect x="13" y="13" width="74" height="74" rx="15" fill="url(#feld)"/>
  <rect x="13" y="13" width="74" height="74" rx="15" fill="url(#licht)"/>`;
const GERAETE = `
  <!-- Geräte unten -->
  <g fill="#1a1b1f" stroke="#c9ccd2" stroke-width="1.5">
    <rect x="20" y="63" width="20" height="13" rx="2.5"/>
    <rect x="42" y="66" width="16" height="12" rx="2.5"/>
    <rect x="60" y="63" width="20" height="13" rx="2.5"/>
  </g>
  <g stroke="#4fd0ff" stroke-width="1.6" stroke-linecap="round">
    <path d="M24 68.5h8M24 71.5h12M46 70.5h8M46 73.5h5M64 68.5h12M64 71.5h7"/>
  </g>`;
const kopf = label => `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100" role="img" aria-label="${label}">`;

// ---------- A: n oben, von dort gehen die Nodes ab ----------
{
  const B = 36, k = B / 107.5, h = 70 * k, x0 = 50 - B / 2 + 0.1 * k, y0 = 17.5 + h;
  const n = transform(N, x0, y0, k);
  const nf = 'M' + NF.map(([a, c]) => (x0 + a * k).toFixed(2) + ' ' + (y0 + c * k).toFixed(2)).join('L') + 'Z';
  const svg = `${kopf('NINA')}
  <defs>${DEFS}
    <linearGradient id="anthrazit" x1="0" y1="0" x2="0" y2="100" gradientUnits="userSpaceOnUse">
      <stop offset="0" stop-color="#555962"/><stop offset="1" stop-color="#25272c"/>
    </linearGradient>
    <linearGradient id="seele" x1="0" y1="17" x2="0" y2="${y0.toFixed(0)}" gradientUnits="userSpaceOnUse">
      <stop offset="0" stop-color="#b8f0ff"/><stop offset=".45" stop-color="#4fd0ff"/><stop offset="1" stop-color="#0d8ee0"/>
    </linearGradient>
    <linearGradient id="nspiegel" x1="0" y1="17" x2="0" y2="31" gradientUnits="userSpaceOnUse">
      <stop offset="0" stop-color="#fff" stop-opacity=".6"/><stop offset="1" stop-color="#fff" stop-opacity=".1"/>
    </linearGradient>
    <path id="n" d="${n}"/>
    <path id="nf" d="${nf}"/>
    <mask id="nkern" maskUnits="userSpaceOnUse" x="0" y="0" width="100" height="100"><use href="#n" fill="#fff" stroke="#000" stroke-width="2" stroke-linejoin="miter"/></mask>
    <mask id="nform" maskUnits="userSpaceOnUse" x="0" y="0" width="100" height="100"><use href="#n" fill="#fff" stroke="#fff" stroke-width="3" stroke-linejoin="miter"/><use href="#nf" fill="#fff" stroke="#fff" stroke-width="3"/></mask>
    <filter id="nschatten" filterUnits="userSpaceOnUse" x="0" y="0" width="100" height="100"><feGaussianBlur stdDeviation="1.3"/></filter>
  </defs>${RAHMEN}
  <!-- Verbindungen: vom n über den Knoten zu den Geräten -->
  <g stroke="#4fd0ff" stroke-width="2.6" stroke-linecap="round" fill="none" opacity=".9">
    <path d="M50 ${(y0 + 1.5).toFixed(1)}V52M50 52L30 64M50 52L50 66M50 52L70 64"/>
  </g>
  <circle cx="50" cy="52" r="4.2" fill="url(#led)" filter="url(#glow)"/>
  <!-- n in Dream MMA: Schatten, dunkler Rand, blaue Seele, Glanz -->
  <use href="#n" fill="#000" stroke="#000" stroke-width="3" stroke-linejoin="round" opacity=".6" transform="translate(1.2 2.4)" filter="url(#nschatten)"/>
  <use href="#n" fill="url(#anthrazit)" stroke="url(#anthrazit)" stroke-width="3" stroke-linejoin="miter"/>
  <use href="#nf" fill="url(#anthrazit)" stroke="url(#anthrazit)" stroke-width="3" stroke-linejoin="miter"/>
  <g mask="url(#nkern)"><use href="#n" fill="#00508f"/><use href="#n" fill="url(#seele)" transform="translate(0 .4)"/></g>
  <g mask="url(#nform)"><ellipse cx="48" cy="-10" rx="40" ry="38" transform="rotate(-8 48 -10)" fill="url(#nspiegel)"/></g>
${GERAETE}
</svg>
`;
  fs.writeFileSync(out + '/icon-a.svg', svg);
}

// ---------- C: n als zentraler Knoten, alle Leitungen laufen hinein ----------
{
  const B = 36, k = B / 107.5, h = 70 * k, x0 = 50 - B / 2 + 0.1 * k, y0 = 40 + h / 2;   // n mittig bei y≈40
  const n = transform(N, x0, y0, k);
  const nf = 'M' + NF.map(([a, c]) => (x0 + a * k).toFixed(2) + ' ' + (y0 + c * k).toFixed(2)).join('L') + 'Z';
  const svg = `${kopf('NINA')}
  <defs>${DEFS}
    <linearGradient id="anthrazit" x1="0" y1="0" x2="0" y2="100" gradientUnits="userSpaceOnUse">
      <stop offset="0" stop-color="#555962"/><stop offset="1" stop-color="#25272c"/>
    </linearGradient>
    <linearGradient id="seele" x1="0" y1="${(y0 - h).toFixed(0)}" x2="0" y2="${y0.toFixed(0)}" gradientUnits="userSpaceOnUse">
      <stop offset="0" stop-color="#b8f0ff"/><stop offset=".45" stop-color="#4fd0ff"/><stop offset="1" stop-color="#0d8ee0"/>
    </linearGradient>
    <linearGradient id="nspiegel" x1="0" y1="${(y0 - h).toFixed(0)}" x2="0" y2="${(y0 - h / 2).toFixed(0)}" gradientUnits="userSpaceOnUse">
      <stop offset="0" stop-color="#fff" stop-opacity=".6"/><stop offset="1" stop-color="#fff" stop-opacity=".1"/>
    </linearGradient>
    <radialGradient id="halo" cx="50" cy="40" r="22" gradientUnits="userSpaceOnUse">
      <stop offset="0" stop-color="#4fd0ff" stop-opacity=".55"/><stop offset=".55" stop-color="#4fd0ff" stop-opacity=".15"/><stop offset="1" stop-color="#4fd0ff" stop-opacity="0"/>
    </radialGradient>
    <path id="n" d="${n}"/>
    <path id="nf" d="${nf}"/>
    <mask id="nkern" maskUnits="userSpaceOnUse" x="0" y="0" width="100" height="100"><use href="#n" fill="#fff" stroke="#000" stroke-width="2" stroke-linejoin="miter"/></mask>
    <mask id="nform" maskUnits="userSpaceOnUse" x="0" y="0" width="100" height="100"><use href="#n" fill="#fff" stroke="#fff" stroke-width="3" stroke-linejoin="miter"/><use href="#nf" fill="#fff" stroke="#fff" stroke-width="3"/></mask>
    <filter id="nschatten" filterUnits="userSpaceOnUse" x="0" y="0" width="100" height="100"><feGaussianBlur stdDeviation="1.3"/></filter>
  </defs>${RAHMEN}
  <!-- Leuchten hinter dem Knoten -->
  <circle cx="50" cy="40" r="22" fill="url(#halo)"/>
  <!-- Leitungen: alle laufen im n zusammen -->
  <g stroke="#4fd0ff" stroke-width="2.6" stroke-linecap="round" fill="none" opacity=".9">
    <path d="M50 40L30 64M50 40L50 66M50 40L70 64M50 40L25.5 24.5M50 40L74.5 24.5"/>
  </g>
  <!-- Netz-Knoten oben -->
  <circle cx="25" cy="24" r="3.6" fill="#1a1b1f" stroke="#c9ccd2" stroke-width="1.4"/>
  <circle cx="25" cy="24" r="1.6" fill="url(#led)" filter="url(#glow)"/>
  <circle cx="75" cy="24" r="3.6" fill="#1a1b1f" stroke="#c9ccd2" stroke-width="1.4"/>
  <circle cx="75" cy="24" r="1.6" fill="url(#led)" filter="url(#glow)"/>
  <!-- n in Dream MMA als Knoten: Schatten, dunkler Rand, blaue Seele, Glanz -->
  <use href="#n" fill="#000" stroke="#000" stroke-width="3" stroke-linejoin="round" opacity=".6" transform="translate(1.2 2.4)" filter="url(#nschatten)"/>
  <use href="#n" fill="url(#anthrazit)" stroke="url(#anthrazit)" stroke-width="3" stroke-linejoin="miter"/>
  <use href="#nf" fill="url(#anthrazit)" stroke="url(#anthrazit)" stroke-width="3" stroke-linejoin="miter"/>
  <g mask="url(#nkern)"><use href="#n" fill="#00508f"/><use href="#n" fill="url(#seele)" transform="translate(0 .4)"/></g>
  <g mask="url(#nform)"><ellipse cx="48" cy="${(y0 - h - 26).toFixed(1)}" rx="40" ry="38" transform="rotate(-8 48 ${(y0 - h - 26).toFixed(1)})" fill="url(#nspiegel)"/></g>
${GERAETE}
</svg>
`;
  fs.writeFileSync(out + '/icon-c.svg', svg);
}

// ---------- B: wie das erste Icon (Router oben), blau ----------
{
  const svg = `${kopf('NINA')}
  <defs>${DEFS}
  </defs>${RAHMEN}
  <!-- Verbindungen -->
  <g stroke="#4fd0ff" stroke-width="2.6" stroke-linecap="round" fill="none" opacity=".9">
    <path d="M50 36V50M50 50L30 64M50 50L50 66M50 50L70 64"/>
  </g>
  <!-- Router oben -->
  <rect x="35" y="23" width="30" height="13" rx="4" fill="#1a1b1f" stroke="#7fdcff" stroke-width="1.6"/>
  <circle cx="42" cy="29.5" r="1.8" fill="#3ddc84" filter="url(#glow)"/>
  <circle cx="48" cy="29.5" r="1.8" fill="#3ddc84" filter="url(#glow)"/>
  <circle cx="54" cy="29.5" r="1.8" fill="#4fd0ff" filter="url(#glow)"/>
  <circle cx="50" cy="50" r="4.2" fill="url(#led)" filter="url(#glow)"/>
${GERAETE}
</svg>
`;
  fs.writeFileSync(out + '/icon-b.svg', svg);
}
console.log('ok');

// ---------- D (eingesetzt): wie C, ohne Rahmen, Ausschnitt angepasst ----------
{
  let s = fs.readFileSync(out + '/icon-c.svg', 'utf8');
  s = s.replace(/\n  <!-- Gehäuse:[\s\S]*?url\(#licht\)"\/>/, '').replace('viewBox="0 0 100 100"', 'viewBox="15 13 70 70"').replace(/stroke="#c9ccd2"/g, 'stroke="#9aa0a8"');
  fs.writeFileSync(out + '/icon-d.svg', s);
}
