HTML_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Lyte Preview</title>
<style>
html, body {
  height: 100%;
  margin: 0;
  background: #050506;
  color: #f3f4f6;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
}
main {
  height: 100%;
  display: grid;
  grid-template-rows: auto 1fr;
}
header {
  padding: 12px 16px;
  border-bottom: 1px solid #25262b;
}
h1 {
  margin: 0;
  font-size: 16px;
  font-weight: 600;
}
canvas {
  width: 100%;
  height: 100%;
  display: block;
}
</style>
</head>
<body>
<main>
<header><h1 id="title">Lyte Preview</h1></header>
<canvas id="preview"></canvas>
</main>
<script>
const data = __LYTE_PREVIEW_DATA__;
const canvas = document.getElementById("preview");
const context = canvas.getContext("2d");
document.getElementById("title").textContent = data.name;

function resize() {
  const scale = window.devicePixelRatio || 1;
  const rect = canvas.getBoundingClientRect();
  canvas.width = Math.max(1, Math.round(rect.width * scale));
  canvas.height = Math.max(1, Math.round(rect.height * scale));
}

function decodeFrame(text) {
  const binary = atob(text);
  const values = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i += 1) {
    values[i] = binary.charCodeAt(i);
  }
  return values;
}

const frames = data.frames.map(decodeFrame);
const bounds = data.coords.reduce((acc, point) => ({
  minX: Math.min(acc.minX, point[0]),
  minY: Math.min(acc.minY, point[1]),
  maxX: Math.max(acc.maxX, point[0]),
  maxY: Math.max(acc.maxY, point[1]),
}), {
  minX: Infinity,
  minY: Infinity,
  maxX: -Infinity,
  maxY: -Infinity,
});

function projectedPoints() {
  const width = canvas.width;
  const height = canvas.height;
  const pad = Math.max(24, Math.min(width, height) * 0.08);
  const spanX = Math.max(1e-9, bounds.maxX - bounds.minX);
  const spanY = Math.max(1e-9, bounds.maxY - bounds.minY);
  const scale = Math.min((width - pad * 2) / spanX, (height - pad * 2) / spanY);
  const offsetX = (width - spanX * scale) / 2;
  const offsetY = (height - spanY * scale) / 2;
  return data.coords.map(point => [
    offsetX + (point[0] - bounds.minX) * scale,
    offsetY + (point[1] - bounds.minY) * scale,
  ]);
}

function draw(time) {
  if (canvas.width === 0 || canvas.height === 0) {
    resize();
  }
  const frame = frames[Math.floor(time / 1000 * data.fps) % frames.length];
  const points = projectedPoints();
  const radius = Math.max(3, Math.min(canvas.width, canvas.height) / 140)
    * data.ledSize;
  context.fillStyle = "#050506";
  context.fillRect(0, 0, canvas.width, canvas.height);
  for (let i = 0; i < points.length; i += 1) {
    const offset = i * 3;
    context.fillStyle =
      `rgb(${frame[offset]}, ${frame[offset + 1]}, ${frame[offset + 2]})`;
    context.beginPath();
    context.arc(points[i][0], points[i][1], radius, 0, Math.PI * 2);
    context.fill();
  }
  requestAnimationFrame(draw);
}

window.addEventListener("resize", resize);
resize();
requestAnimationFrame(draw);
</script>
</body>
</html>
"""
