from ..spatial_template import PROJECTION_SCRIPT

HTML_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>lyte Preview</title>
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
<header><h1 id="title">lyte Preview</h1></header>
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
__PROJECTION_SCRIPT__

function draw(time) {
  if (canvas.width === 0 || canvas.height === 0) {
    resize();
  }
  const frame = frames[Math.floor(time / 1000 * data.fps) % frames.length];
  const axes = {xy:[0,1],xz:[0,2],yz:[1,2]}[data.plane];
  const points = projectedPoints(data.coords,canvas.width,canvas.height,axes,data.zoom);
  const radius = Math.max(3, Math.min(canvas.width, canvas.height) / 140)
    * data.ledSize;
  context.fillStyle = data.background;
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
""".replace('__PROJECTION_SCRIPT__', PROJECTION_SCRIPT)
