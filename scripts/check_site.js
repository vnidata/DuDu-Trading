/* Kiểm tra chéo giao diện: id trong HTML <-> el() trong JS, canvas <-> makeChart. */
const fs = require("fs");
const path = require("path");

const root = path.resolve(__dirname, "..");
const html = fs.readFileSync(path.join(root, "site/index.html"), "utf8");
const js = fs.readFileSync(path.join(root, "site/assets/app.js"), "utf8");
const css = fs.readFileSync(path.join(root, "site/assets/styles.css"), "utf8");

const ids = new Set([...html.matchAll(/id="([^"]+)"/g)].map((m) => m[1]));
const used = new Set([...js.matchAll(/el\("([^"]+)"\)/g)].map((m) => m[1]));
const missingIds = [...used].filter((x) => !ids.has(x));

const canvases = [...html.matchAll(/canvas id="([^"]+)"/g)].map((m) => m[1]);
const charts = [
  ...js.matchAll(/makeChart\("([^"]+)"\s*,/g),
  ...js.matchAll(/histogramChart\("([^"]+)"\s*,/g),
].map((m) => m[1]);
const unusedCanvas = canvases.filter((c) => !charts.includes(c));
const orphanChart = charts.filter((c) => !canvases.includes(c));

const dataFiles = [...js.matchAll(/loadJSON\("(data\/[^"]+)"\)/g)].map((m) => m[1]);
const missingData = dataFiles.filter((f) => !fs.existsSync(path.join(root, "site", f)));

const chartsInHtml = [...html.matchAll(/new Chart/g)].length;

let fail = 0;
const report = (label, list) => {
  const bad = list.length > 0;
  if (bad) fail++;
  console.log(`${bad ? "LỖI " : "OK  "} ${label}${bad ? ": " + JSON.stringify(list) : ""}`);
};

console.log(`index.html  ${(html.length / 1024).toFixed(1)} KB`);
console.log(`app.js      ${(js.length / 1024).toFixed(1)} KB`);
console.log(`styles.css  ${(css.length / 1024).toFixed(1)} KB`);
console.log(`id trong HTML: ${ids.size} | el() gọi: ${used.size}`);
console.log(`canvas: ${canvases.length} | makeChart: ${charts.length} | loadJSON: ${dataFiles.length}`);
console.log("---");

report("Mọi el(id) đều tồn tại trong HTML", missingIds);
report("Mọi canvas đều được vẽ", unusedCanvas);
report("Mọi makeChart đều có canvas", orphanChart);
report("Mọi tệp dữ liệu loadJSON đều tồn tại", missingData);
report("Không còn thẻ <script> nội tuyến lạc hậu", chartsInHtml ? ["new Chart trong HTML"] : []);

if (missingData.length === 0) {
  for (const f of dataFiles) {
    const size = fs.statSync(path.join(root, "site", f)).size;
    let ok = true;
    try {
      JSON.parse(fs.readFileSync(path.join(root, "site", f), "utf8"));
    } catch (e) {
      ok = false;
    }
    console.log(`     ${ok ? "JSON hợp lệ" : "JSON LỖI  "} ${f.padEnd(28)} ${(size / 1024).toFixed(1)} KB`);
  }
}

console.log("---");
console.log(fail === 0 ? "TẤT CẢ KIỂM TRA GIAO DIỆN ĐỀU ĐẠT" : `CÓ ${fail} LỖI`);
process.exit(fail === 0 ? 0 : 1);
