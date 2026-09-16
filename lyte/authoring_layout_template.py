"""Orthographic layout inspection, coordinate edits, and constrained dragging."""

# ruff: noqa: E501

LAYOUT_SCRIPT = r"""
const projection=document.getElementById('projection');
const zoom=document.getElementById('zoom');
const layoutDetails=document.getElementById('layout-details');
const layoutTable=document.getElementById('layout-table');
const layoutStatus=document.getElementById('layout-status');
const applyLayout=document.getElementById('apply-layout');
const dragLights=document.getElementById('drag-lights');
let layoutDraft=null;
let layoutEditable=false;
let originalPositions='';
let selectedLight=0;
let layoutCamera=null;
let layoutDrag=null;
function viewAxes(){return projection.value.split(',').map(Number);}
function moveLayoutPoint(position,point,axes,transform){
  const result=[...position];
  if(axes[0]<result.length){result[axes[0]]=transform.minX+(point[0]-transform.offsetX)/transform.scale;}
  if(axes[1]<result.length){result[axes[1]]=transform.minY+(point[1]-transform.offsetY)/transform.scale;}
  return result;
}
function draftPositions(){return layoutDraft?layoutDraft.lights.map(light=>light.position):preview?.coords||[];}
function updateLayoutStatus(){
  const changed=layoutDraft&&JSON.stringify(draftPositions())!==originalPositions;
  applyLayout.disabled=!layoutEditable||!changed;
  const point=layoutDraft?.lights[selectedLight];
  document.getElementById('selected-light').textContent=point?
    `Index ${selectedLight}: ${point.name} (${point.position.join(', ')})${changed?' · unapplied layout draft':''}`:'';
}
function coordinateTable(){
  if(!layoutDetails.open){return;}
  layoutTable.replaceChildren();
  if(!layoutDraft){layoutTable.textContent='No declared layout for this preview';return;}
  const table=document.createElement('table');
  const header=document.createElement('tr');
  for(const text of ['Index','Light',...layoutDraft.axes]){
    const cell=document.createElement('th');cell.textContent=text;header.append(cell);
  }
  table.append(header);
  layoutDraft.lights.forEach((light,index)=>{
    const row=document.createElement('tr');
    for(const text of [String(index),light.name]){
      const cell=document.createElement('td');cell.textContent=text;row.append(cell);
    }
    light.position.forEach((value,axis)=>{
      const cell=document.createElement('td');
      const input=document.createElement('input');input.type='number';input.step='any';input.value=value;
      input.disabled=!layoutEditable;
      input.setAttribute('aria-label',`${light.name} ${layoutDraft.axes[axis]}`);
      input.onchange=()=>{
        if(!Number.isFinite(Number(input.value))){layoutStatus.textContent='Coordinates must be finite';return;}
        light.position[axis]=Number(input.value);selectedLight=index;updateLayoutStatus();
      };
      cell.append(input);row.append(cell);
    });
    row.onclick=()=>{selectedLight=index;updateLayoutStatus();};table.append(row);
  });
  layoutTable.append(table);
}
function updateAxes(){
  layoutCamera=null;
  const axes=viewAxes(),names=layoutDraft?.axes||['x','y','z'];
  document.getElementById('axis-labels').textContent=
    `Horizontal: ${names[axes[0]]||'zero (absent axis)'}, positive right. Vertical: ${names[axes[1]]||'zero (absent axis)'}, positive down. ${layoutDraft?.unit||''}`;
}
function rebuildLayout(selected){
  layoutDraft=selected?.layout?structuredClone(selected.layout):null;
  layoutEditable=selected?.source_kind==='Editable TOML'&&!selected.diagnostics.length;
  originalPositions=JSON.stringify(draftPositions());
  selectedLight=0;layoutDrag=null;layoutStatus.textContent='';
  dragLights.disabled=!layoutEditable;dragLights.checked=false;
  updateAxes();coordinateTable();updateLayoutStatus();
}
function canvasPoint(event){
  const box=canvas.getBoundingClientRect();
  return [(event.clientX-box.left)*canvas.width/box.width,(event.clientY-box.top)*canvas.height/box.height];
}
canvas.addEventListener('pointerdown',event=>{
  if(!layoutDraft||!preview){return;}
  const coords=draftPositions(),axes=viewAxes();
  const transform=layoutCamera||projectionTransform(coords,canvas.width,canvas.height,axes,Number(zoom.value));
  const points=projectedPoints(coords,canvas.width,canvas.height,axes,Number(zoom.value),transform);
  const pointer=canvasPoint(event);
  let nearest=-1,distance=15*(devicePixelRatio||1);
  points.forEach((point,index)=>{
    const delta=Math.hypot(point[0]-pointer[0],point[1]-pointer[1]);
    if(delta<distance){nearest=index;distance=delta;}
  });
  if(nearest<0){return;}
  selectedLight=nearest;updateLayoutStatus();
  if(layoutEditable&&dragLights.checked){
    layoutCamera=transform;layoutDrag={index:nearest,axes,transform};
    canvas.setPointerCapture(event.pointerId);event.preventDefault();
  }
});
canvas.addEventListener('pointermove',event=>{
  if(!layoutDrag){return;}
  const light=layoutDraft.lights[layoutDrag.index];
  light.position=moveLayoutPoint(light.position,canvasPoint(event),layoutDrag.axes,layoutDrag.transform);
  updateLayoutStatus();
});
function finishLayoutDrag(event){
  if(!layoutDrag){return;}
  layoutDrag=null;
  if(canvas.hasPointerCapture(event.pointerId)){canvas.releasePointerCapture(event.pointerId);}
  coordinateTable();
}
canvas.addEventListener('pointerup',finishLayoutDrag);
canvas.addEventListener('pointercancel',finishLayoutDrag);
async function saveLayout(){
  if(!layoutEditable){return;}
  applyLayout.disabled=true;
  try{
    const response=await fetch('/api/layout',{
      method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({
        entry:active().source,output:active().outputs[0],positions:draftPositions()
      })
    });
    const result=await response.json();
    if(!response.ok){layoutStatus.textContent=result.error;return;}
    catalog=result.catalog;updateHistory(result.history);rebuildLibrary();offerDownload(result);
    layoutStatus.textContent=`Applied and offered ${result.filename} for download`;
  }catch(error){layoutStatus.textContent=`Could not apply layout: ${error.message}`;}
  finally{updateLayoutStatus();}
}
projection.onchange=updateAxes;
zoom.oninput=()=>{layoutCamera=null;};
document.getElementById('fit-layout').onclick=()=>{zoom.value=1;layoutCamera=null;};
layoutDetails.ontoggle=coordinateTable;
applyLayout.onclick=saveLayout;
document.getElementById('download-preview').onclick=async()=>{
  const status=document.getElementById('preview-download-status');
  if(layoutDraft&&JSON.stringify(draftPositions())!==originalPositions){
    status.textContent='Apply the layout draft before downloading its preview';return;
  }
  try{
    const response=await fetch('/api/preview-download',{
      method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({
        selector:select.value,parameters:values(),view:{
          plane:{'0,1':'xy','0,2':'xz','1,2':'yz'}[projection.value],
          zoom:Number(zoom.value),led_size:Number(document.getElementById('light-size').value),
          background:document.getElementById('preview-background').value
        }
      })
    });
    const result=await response.json();
    if(!response.ok){status.textContent=result.error;return;}
    offerDownload(result);status.textContent='Offered standalone visual preview; editable sources are separate downloads';
  }catch(error){status.textContent=`Could not download preview: ${error.message}`;}
};
"""
