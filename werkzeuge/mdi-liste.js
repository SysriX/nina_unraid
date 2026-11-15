// Erzeugt app/web/mdi.json (alle Material Design Icons mit Pfad, Aliassen und Kategorien) aus dem npm-Paket @mdi/svg.
//   npm pack @mdi/svg@7.4.47 && tar -xzf mdi-svg-7.4.47.tgz
//   node werkzeuge/mdi-liste.js <ordner>/package app/web/mdi.json
// Material Design Icons: Apache License 2.0 (https://github.com/Templarian/MaterialDesign)
const fs = require("fs");
const [paket, ziel] = process.argv.slice(2);
const meta = JSON.parse(fs.readFileSync(paket + "/meta.json", "utf8"));
const version = JSON.parse(fs.readFileSync(paket + "/package.json", "utf8")).version;
const kategorien = [];
const kat = t => { let i = kategorien.indexOf(t); if (i < 0) { kategorien.push(t); i = kategorien.length - 1; } return i; };
const icons = [];
for (const m of meta) {
  if (m.deprecated) continue;
  const svg = fs.readFileSync(`${paket}/svg/${m.name}.svg`, "utf8");
  const d = (svg.match(/ d="([^"]+)"/) || [])[1];
  if (!d) continue;
  icons.push([m.name, d, (m.aliases || []).join(" "), (m.tags || []).map(kat)]);
}
fs.writeFileSync(ziel, JSON.stringify({ v: version, k: kategorien, i: icons }));
console.log(`${icons.length} Icons, ${kategorien.length} Kategorien, ${(fs.statSync(ziel).size / 1e6).toFixed(2)} MB`);
