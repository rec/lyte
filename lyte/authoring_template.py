"""Browser UI for animation authoring."""

# ruff: noqa: E501

AUTHOR_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>lyte Author</title>
<style>
html,body{
  height:100%;
  margin:0;
  background:#111417;
  color:#e5e7eb;
  font:14px -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif
}
main{
  height:100%;
  display:grid;
  grid-template-columns:minmax(260px,340px) 1fr
}
aside{
  border-right:1px solid #343a40;
  padding:16px;
  overflow:auto
}
canvas{
  width:100%;
  height:100%;
  display:block
}
h1{
  font-size:17px;
  margin:0 0 16px
}
h2{
  font-size:13px;
  margin:24px 0 8px;
  color:#cbd5e1
}
label{
  display:grid;
  gap:6px;
  margin:14px 0;
  color:#cbd5e1
}
select,input{
  width:100%;
  box-sizing:border-box
}
output,#status{
  font-variant-numeric:tabular-nums;
  color:#94a3b8
}
.transport{
  display:grid;
  grid-template-columns:1fr 1fr 1fr;
  gap:6px
}
.transport button:last-child{
  grid-column:span 3
}
button{
  padding:7px;
  border:1px solid #475569;
  border-radius:4px;
  background:#1e293b;
  color:#e5e7eb
}
.transport label{
  display:flex;
  align-items:center;
  gap:6px;
  margin:10px 0
}
.transport label input{
  width:auto
}
#frame{
  margin:4px 0
}
#status{
  display:block;
  min-height:20px
}
.tree{
  margin:0;
  padding-left:16px
}
.tree li{
  margin:4px 0
}
.tree button{
  width:100%;
  text-align:left;
  padding:4px 6px
}
.tree button.selected{
  background:#334155
}
pre{
  margin:8px 0;
  max-height:220px;
  overflow:auto;
  padding:8px;
  background:#0b0f14;
  border:1px solid #343a40;
  border-radius:4px;
  font-size:12px;
  white-space:pre-wrap
}
#timeline{
  display:grid;
  gap:7px
}
.timeline-summary{
  color:#94a3b8;
  font-variant-numeric:tabular-nums
}
.timeline-row{
  display:grid;
  grid-template-columns:78px 1fr;
  gap:6px;
  align-items:center
}
.timeline-label{
  overflow:hidden;
  text-overflow:ellipsis;
  white-space:nowrap
}
.timeline-track{
  height:22px;
  position:relative;
  background:#0b0f14;
  border:1px solid #343a40;
  border-radius:4px
}
.timeline-bar{
  height:100%;
  position:absolute;
  background:#2563eb;
  border-radius:3px;
  overflow:hidden;
  white-space:nowrap;
  box-sizing:border-box;
  padding:3px 5px;
  font-size:11px;
  color:#eff6ff
}
.timeline-inputs{
  display:flex;
  gap:5px;
  grid-column:2
}
.timeline-inputs label{
  display:flex;
  gap:3px;
  align-items:center;
  margin:0;
  font-size:12px
}
.timeline-inputs input{
  width:64px
}
#operation-fields{
  display:grid;
  gap:6px
}
.operation-field{
  display:grid;
  grid-template-columns:1fr 100px;
  gap:6px;
  align-items:center
}
.operation-field label{
  margin:0
}
.operation-field input{
  width:100%
}
@media(max-width:700px){
  main{
    grid-template-columns:1fr;
    grid-template-rows:auto 1fr
  }
  aside{
    border-right:0;
    border-bottom:1px solid #343a40
  }
}
</style>
</head>
<body>
<main>
<aside>
<h1>lyte Author</h1>
<p>Edits accumulate in memory and update the preview. Download every edited score to keep your work. Source files are unchanged; restarting the editor discards unsaved work.</p>
<label>Animation<select id="animation">
</select>
</label>
<p id="score-source"></p>
<h2>Session edits</h2>
<button id="undo" type="button" disabled>Undo</button>
<button id="redo" type="button" disabled>Redo</button>
<output id="history-status"></output>
<ul id="changed-scores"></ul>
<p>The ZIP contains the listed edits, not a standalone library. Replace matching files in a copy of your libraries.</p>
<button id="download-bundle" type="button" disabled>Download all edits (ZIP)</button>
<output id="bundle-status"></output>
<section id="controls">
</section>
<h2>Composition</h2>
<section id="composition">
</section>
<h2>Inspector</h2>
<pre id="inspector">Select an operation</pre>
<h2>Operation fields</h2>
<section id="operation-fields">Select an operation</section>
<button id="download-fields" type="button" disabled>Apply and download fields</button>
<output id="fields-status">
</output>
<h2>Timeline</h2>
<section id="timeline">Select a timed operation</section>
<button id="download-timing" type="button" disabled>Apply and download timing</button>
<output id="timing-status">
</output>
<label>Replace selected operation<select id="operation-template" disabled>
</select>
</label>
<button id="download-operation" type="button" disabled>Apply and download score</button>
<output id="operation-status">
</output>
<h2>Save preset</h2>
<label>Name<input id="preset-name">
</label>
<button id="save" type="button">Download TOML preset</button>
<output id="save-status">
</output>
<h2>Preview</h2>
<div class="transport">
<button id="previous" type="button" aria-label="Previous frame">Previous</button>
<button id="play" type="button">Pause</button>
<button id="next" type="button" aria-label="Next frame">Next</button>
<label>
<input id="loop" type="checkbox" checked>Loop</label>
</div>
<input id="frame" type="range" min="0" max="0" value="0" aria-label="Preview frame">
<output id="status">
</output>
</aside>
<canvas id="preview">
</canvas>
</main>
<script>
let catalog=__LYTE_AUTHOR_CATALOG__;
let history=__LYTE_AUTHOR_HISTORY__;
const offeredRevisions=new Map();
const select=document.getElementById('animation');
const controls=document.getElementById('controls');
const canvas=document.getElementById('preview');
const context=canvas.getContext('2d');
const previous=document.getElementById('previous');
const play=document.getElementById('play');
const next=document.getElementById('next');
const loop=document.getElementById('loop');
const frameControl=document.getElementById('frame');
const status=document.getElementById('status');
const composition=document.getElementById('composition');
const inspector=document.getElementById('inspector');
const operationFields=document.getElementById('operation-fields');
const downloadFields=document.getElementById('download-fields');
const fieldsStatus=document.getElementById('fields-status');
const timeline=document.getElementById('timeline');
const downloadTiming=document.getElementById('download-timing');
const timingStatus=document.getElementById('timing-status');
const operationTemplate=document.getElementById('operation-template');
const downloadOperation=document.getElementById('download-operation');
const operationStatus=document.getElementById('operation-status');
const presetName=document.getElementById('preset-name');
const save=document.getElementById('save');
const saveStatus=document.getElementById('save-status');
let preview=null;
let frames=[];
let frame=0;
let playing=true;
let lastTime=0;
let previewRequest=0;
let previewBusy=false;
let previewTimer=null;
let pendingPreview=null;
let selectedOperation=null;
for(const animation of catalog){
  const option=document.createElement('option');
  option.value=animation.selector;
  option.textContent=animation.title;
  select.append(option)
}
function active(){
  return catalog.find(animation=>animation.selector===select.value)
}
function values(){
  return Object.fromEntries([...controls.querySelectorAll('input')].map(input=>[input.name,Number(input.value)]))
}
function control(parameter){
  const label=document.createElement('label');
  label.textContent=parameter.name;
  const input=document.createElement('input');
  input.type='range';
  input.name=parameter.name;
  input.min=parameter.minimum;
  input.max=parameter.maximum;
  input.step=(parameter.maximum-parameter.minimum)/200||1;
  input.value=parameter.default;
  const output=document.createElement('output');
  output.textContent=`${parameter.default} ${parameter.unit}`;
  input.oninput=()=>{
    output.textContent=`${input.value} ${parameter.unit}`;
    requestPreview()
  }
  ;
  label.append(input,output);
  controls.append(label)
}
function defaultPresetName(){
  return `preset-${select.value.replace(/[^A-Za-z0-9_-]+/g,'-').replace(/^-+|-+$/g,'')||'animation'}`
}
function rationalNumber(value){
  const [numerator,denominator='1']=value.split('/');
  return Number(numerator)/Number(denominator)
}
function operationField(name,value){
  const row=document.createElement('div');
  row.className='operation-field';
  const label=document.createElement('label');
  label.textContent=name;
  const input=document.createElement('input');
  input.dataset.field=name;
  if(typeof value==='boolean'){
    input.type='checkbox';
    input.checked=value
  }
  else if(typeof value==='number'){
    input.type='number';
    input.step='any';
    input.value=value
  }
  else{
    input.type='text';
    input.value=value
  }
  label.append(input);
  row.append(label);
  return row
}
function rebuildOperationFields(node){
  operationFields.replaceChildren();
  fieldsStatus.textContent='';
  const fields=node.editor_fields;
  downloadFields.disabled=!node.editable||!Object.keys(fields).length;
  if(!Object.keys(fields).length){
    operationFields.textContent='This operation has no editable scalar fields.';
    return
  }
  for(const [name,value] of Object.entries(fields)){
    operationFields.append(operationField(name,value))
  }
}
function timingInput(name,value){
  const label=document.createElement('label');
  label.textContent=name;
  const input=document.createElement('input');
  input.type='text';
  input.value=value;
  input.dataset.timing=name;
  input.setAttribute('aria-label',name);
  label.append(input);
  return label
}
function rebuildTimeline(node){
  timeline.replaceChildren();
  timingStatus.textContent='';
  downloadTiming.disabled=!node.editable||!node.timeline;
  if(!node.timeline){
    timeline.textContent='This operation has no timed cues or crossfade.';
    return
  }
  const summary=document.createElement('div');
  summary.className='timeline-summary';
  summary.textContent=`${node.timeline.effect} · ${node.timeline.duration} s`;
  timeline.append(summary);
  if(node.timeline.effect==='crossfade'){
    const inputs=document.createElement('div');
    inputs.className='timeline-inputs';
    inputs.append(timingInput('duration',node.timeline.duration));
    timeline.append(inputs)
  }
  const duration=rationalNumber(node.timeline.duration);
  for(const event of node.timeline.events){
    const row=document.createElement('div');
    row.className='timeline-row';
    const label=document.createElement('div');
    label.className='timeline-label';
    label.textContent=`${event.name}:${event.output}`;
    label.title=label.textContent;
    const track=document.createElement('div');
    track.className='timeline-track';
    const bar=document.createElement('div');
    bar.className='timeline-bar';
    bar.style.left=`${rationalNumber(event.start)/duration*100}%`;
    bar.style.width=`${rationalNumber(event.duration)/duration*100}%`;
    bar.textContent=`${event.start}–${event.end} s`;
    track.append(bar);
    row.append(label,track);
    if(node.timeline.effect==='cues'){
      const inputs=document.createElement('div');
      inputs.className='timeline-inputs';
      inputs.append(timingInput('start',event.start),timingInput('duration',event.duration));
      row.append(inputs)
    }
    timeline.append(row)
  }
}
function inspect(node,button){
  selectedOperation=node;
  inspector.textContent=`${node.entry} · ${node.source_kind}\n${JSON.stringify(node.fields,null,2)}`;
  rebuildOperationFields(node);
  rebuildTimeline(node);
  operationTemplate.replaceChildren();
  operationStatus.textContent='';
  const placeholder=document.createElement('option');
  placeholder.textContent='Choose a template';
  placeholder.value='';
  operationTemplate.append(placeholder);
  for(const name of node.templates){
    const option=document.createElement('option');
    option.value=name;
    option.textContent=name;
    operationTemplate.append(option)
  }
  operationTemplate.disabled=!node.editable;
  downloadOperation.disabled=!node.editable;
  for(const item of composition.querySelectorAll('button')){
    item.classList.remove('selected')
  }
  button.classList.add('selected')
}
function compositionNode(node){
  const item=document.createElement('li');
  const button=document.createElement('button');
  button.type='button';
  button.textContent=`${node.path} · ${node.effect}`;
  button.onclick=()=>inspect(node,button);
  item.append(button);
  if(node.children.length){
    const children=document.createElement('ul');
    children.className='tree';
    for(const child of node.children){
      const branch=document.createElement('li');
      branch.textContent=`${child.source}:${child.output}`;
      const nested=document.createElement('ul');
      nested.className='tree';
      nested.append(compositionNode(child.node));
      branch.append(nested);
      children.append(branch)
    }
    item.append(children)
  }
  return item
}
function rebuildComposition(){
  composition.replaceChildren();
  const tree=active().composition;
  if(!tree){
    inspector.textContent='This animation has no uFor composition.';
    return
  }
  const nodes=document.createElement('ul');
  nodes.className='tree';
  nodes.append(compositionNode(tree));
  composition.append(nodes);
  const first=composition.querySelector('button');
  if(first){
    first.click()
  }
}
function updateHistory(value){
  history=value;
  document.getElementById('undo').disabled=!history.can_undo;
  document.getElementById('redo').disabled=!history.can_redo;
  document.getElementById('download-bundle').disabled=!(history.changed||[]).length;
  const changed=document.getElementById('changed-scores');
  changed.replaceChildren();
  for(const entry of history.changed||[]){
    const item=document.createElement('li');
    const offered=offeredRevisions.get(entry)===history.revisions[entry];
    item.textContent=`${entry} · ${offered?'Current revision offered for download':'Not yet offered for download'}`;
    changed.append(item);
  }
  if(!changed.children.length){changed.textContent='No changed scores';}
}
function hasUnofferedChanges(){
  return (history.changed||[]).some(entry=>offeredRevisions.get(entry)!==history.revisions[entry]);
}
function offerDownload(result){
  const content=result.archive?decodeFrame(result.archive):result.document;
  const type=result.archive?'application/zip':'application/toml';
  const link=document.createElement('a');
  link.href=URL.createObjectURL(new Blob([content],{type}));
  link.download=result.filename;
  link.click();
  setTimeout(()=>URL.revokeObjectURL(link.href),0);
  for(const [entry,revision] of Object.entries(result.revisions||{})){
    offeredRevisions.set(entry,revision);
  }
  updateHistory(history);
}
async function downloadBundle(){
  const message=document.getElementById('bundle-status');
  try{
    const response=await fetch('/api/bundle',{
      method:'POST',headers:{'Content-Type':'application/json'},body:'{}'
    });
    const result=await response.json();
    if(!response.ok){message.textContent=result.error;return;}
    updateHistory(result.history);
    offerDownload(result);
    message.textContent=`Offered ${result.filename} for download. Check your browser's downloads.`;
  }catch(error){message.textContent=`Could not download edits: ${error.message}`;}
}
async function changeHistory(action){
  const message=document.getElementById('history-status');
  try{
    const response=await fetch(`/api/${action}`,{
      method:'POST',headers:{'Content-Type':'application/json'},body:'{}'
    });
    const result=await response.json();
    if(!response.ok){message.textContent=result.error;return;}
    catalog=result.catalog;
    updateHistory(result.history);
    rebuildComposition();
    requestPreview();
    message.textContent=action==='undo'?'Edit undone':'Edit redone';
  }catch(error){message.textContent=`Could not ${action}: ${error.message}`;}
}
function rebuild(){
  const selected=active();
  document.getElementById('score-source').textContent=
    `${selected.source||selected.selector} · ${selected.source_kind}`;
  controls.replaceChildren();
  for(const parameter of active().parameters){
    control(parameter)
  }
  rebuildComposition();
  presetName.value=defaultPresetName();
  saveStatus.textContent='';
  requestPreview()
}
function decodeFrame(text){
  const binary=atob(text);
  const bytes=new Uint8Array(binary.length);
  for(let index=0;
  index<binary.length;
  index+=1){
    bytes[index]=binary.charCodeAt(index)
  }
  return bytes
}
async function requestPreview(){
  const request=++previewRequest;
  pendingPreview={
    request,selector:select.value,parameters:values()
  }
  ;
  clearTimeout(previewTimer);
  preview=null;
  frames=[];
  frame=0;
  frameControl.max=0;
  frameControl.value=0;
  status.textContent='Loading preview';
  previewTimer=setTimeout(sendPreview,150);
}
async function sendPreview(){
  if(previewBusy||!pendingPreview){
    return
  }
  previewBusy=true;
  const {
    request,selector,parameters
  }
  =pendingPreview;
  pendingPreview=null;
  try {
    const response=await fetch('/api/preview',{
      method:'POST',headers:{
        'Content-Type':'application/json'
      }
      ,body:JSON.stringify({
        selector,parameters
      }
      )
    }
    );
    const result=await response.json();
    if(request!==previewRequest){
      return
    }
    if(!response.ok){
      status.textContent=result.error;
      return
    }
    const decoded=result.frames.map(decodeFrame);
    preview=result;
    frames=decoded;
    frameControl.max=Math.max(0,frames.length-1);
    lastTime=performance.now();
    updateStatus();
  }
  catch(error) {
    if(request===previewRequest){
      status.textContent=`Could not load preview: ${error.message}`
    }
  }
  finally {
    previewBusy=false;
    if(pendingPreview){
      clearTimeout(previewTimer);
      previewTimer=setTimeout(sendPreview,150)
    }
  }
}
async function savePreset(){
  const response=await fetch('/api/preset',{
    method:'POST',headers:{
      'Content-Type':'application/json'
    }
    ,body:JSON.stringify({
      selector:select.value,parameters:values(),name:presetName.value
    }
    )
  }
  );
  const result=await response.json();
  if(!response.ok){
    saveStatus.textContent=result.error;
    return
  }
  if(result.catalog){
    catalog=result.catalog;
    updateHistory(result.history);
    rebuildComposition();
    requestPreview()
  }
  offerDownload(result);
  saveStatus.textContent=`Offered ${result.filename} for download`
}
async function saveOperation(){
  if(!selectedOperation||!operationTemplate.value){
    operationStatus.textContent='Choose an operation template';
    return
  }
  const response=await fetch('/api/operation',{
    method:'POST',headers:{
      'Content-Type':'application/json'
    }
    ,body:JSON.stringify({
      entry:selectedOperation.entry,output:selectedOperation.output,template:operationTemplate.value
    }
    )
  }
  );
  const result=await response.json();
  if(!response.ok){
    operationStatus.textContent=result.error;
    return
  }
  if(result.catalog){
    catalog=result.catalog;
    updateHistory(result.history);
    rebuildComposition();
    requestPreview()
  }
  offerDownload(result);
  operationStatus.textContent=`Offered ${result.filename} for download`
}
function fieldValues(){
  return Object.fromEntries([...operationFields.querySelectorAll('[data-field]')].map(input=>[input.dataset.field,input.type==='checkbox'?input.checked:input.type==='number'?Number(input.value):input.value]))
}
async function saveFields(){
  if(!selectedOperation){
    return
  }
  const response=await fetch('/api/fields',{
    method:'POST',headers:{
      'Content-Type':'application/json'
    }
    ,body:JSON.stringify({
      entry:selectedOperation.entry,output:selectedOperation.output,fields:fieldValues()
    }
    )
  }
  );
  const result=await response.json();
  if(!response.ok){
    fieldsStatus.textContent=result.error;
    return
  }
  if(result.catalog){
    catalog=result.catalog;
    updateHistory(result.history);
    rebuildComposition();
    requestPreview()
  }
  offerDownload(result);
  fieldsStatus.textContent=`Offered ${result.filename} for download`
}
function timingValues(){
  if(selectedOperation.timeline.effect==='crossfade'){
    return {
      duration:timeline.querySelector('[data-timing="duration"]').value
    }
  }
  return {
    events:[...timeline.querySelectorAll('.timeline-row')].map(row=>Object.fromEntries([...row.querySelectorAll('[data-timing]')].map(input=>[input.dataset.timing,input.value])))
  }
}
async function saveTiming(){
  if(!selectedOperation||!selectedOperation.timeline){
    return
  }
  const response=await fetch('/api/timeline',{
    method:'POST',headers:{
      'Content-Type':'application/json'
    }
    ,body:JSON.stringify({
      entry:selectedOperation.entry,output:selectedOperation.output,timing:timingValues()
    }
    )
  }
  );
  const result=await response.json();
  if(!response.ok){
    timingStatus.textContent=result.error;
    return
  }
  if(result.catalog){
    catalog=result.catalog;
    updateHistory(result.history);
    rebuildComposition();
    requestPreview()
  }
  offerDownload(result);
  timingStatus.textContent=`Offered ${result.filename} for download`
}
function updateStatus(){
  if(!preview){
    return
  }
  status.textContent=`${active().title} · frame ${frame+1} of ${frames.length} · ${preview.fps} FPS`
}
function setFrame(value){
  if(!frames.length){
    return
  }
  if(value<0){
    frame=loop.checked?frames.length-1:0
  }
  else if(value>=frames.length){
    frame=loop.checked?0:frames.length-1;
    playing=loop.checked
  }
  else{
    frame=value
  }
  frameControl.value=frame;
  updateStatus()
}
function resize(){
  const scale=devicePixelRatio||1;
  const rect=canvas.getBoundingClientRect();
  canvas.width=Math.max(1,Math.round(rect.width*scale));
  canvas.height=Math.max(1,Math.round(rect.height*scale))
}
function projectedPoints(){
  const bounds=preview.coords.reduce((value,point)=>({
    minX:Math.min(value.minX,point[0]),minY:Math.min(value.minY,point[1]),maxX:Math.max(value.maxX,point[0]),maxY:Math.max(value.maxY,point[1])
  }
  ),{
    minX:Infinity,minY:Infinity,maxX:-Infinity,maxY:-Infinity
  }
  );
  const pad=Math.max(24,Math.min(canvas.width,canvas.height)*0.08);
  const spanX=Math.max(1e-9,bounds.maxX-bounds.minX);
  const spanY=Math.max(1e-9,bounds.maxY-bounds.minY);
  const scale=Math.min((canvas.width-pad*2)/spanX,(canvas.height-pad*2)/spanY);
  const offsetX=(canvas.width-spanX*scale)/2;
  const offsetY=(canvas.height-spanY*scale)/2;
  return preview.coords.map(point=>[offsetX+(point[0]-bounds.minX)*scale,offsetY+(point[1]-bounds.minY)*scale])
}
function draw(){
  context.fillStyle='#050506';
  context.fillRect(0,0,canvas.width,canvas.height);
  if(!preview||!frames.length){
    return
  }
  const points=projectedPoints();
  const values=frames[frame];
  const radius=Math.max(3,Math.min(canvas.width,canvas.height)/140);
  for(let index=0;
  index<points.length;
  index+=1){
    const offset=index*3;
    context.fillStyle=`rgb(${values[offset]},${values[offset+1]},${values[offset+2]})`;
    context.beginPath();
    context.arc(points[index][0],points[index][1],radius,0,Math.PI*2);
    context.fill()
  }
}
function animate(time){
  if(playing&&preview&&frames.length){
    const elapsed=time-lastTime;
    const advance=Math.floor(elapsed*preview.fps/1000);
    if(advance>0){
      setFrame(frame+advance);
      lastTime=time
    }
  }
  else{
    lastTime=time
  }
  draw();
  requestAnimationFrame(animate)
}
addEventListener('beforeunload',event=>{
  if(hasUnofferedChanges()){event.preventDefault();event.returnValue='';}
});
document.getElementById('download-bundle').onclick=downloadBundle;
updateHistory(history);
document.getElementById('undo').onclick=()=>changeHistory('undo');
document.getElementById('redo').onclick=()=>changeHistory('redo');
select.onchange=rebuild;
save.onclick=savePreset;
downloadOperation.onclick=saveOperation;
downloadFields.onclick=saveFields;
downloadTiming.onclick=saveTiming;
previous.onclick=()=>{
  playing=false;
  play.textContent='Play';
  setFrame(frame-1)
}
;
next.onclick=()=>{
  playing=false;
  play.textContent='Play';
  setFrame(frame+1)
}
;
play.onclick=()=>{
  playing=!playing;
  play.textContent=playing?'Pause':'Play'
}
;
frameControl.oninput=()=>{
  playing=false;
  play.textContent='Play';
  setFrame(Number(frameControl.value))
}
;
addEventListener('resize',resize);
resize();
rebuild();
requestAnimationFrame(animate);
</script></body></html>"""
