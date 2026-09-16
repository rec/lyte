"""Controls for editing declared composition parts and operations."""

# ruff: noqa: E501

STRUCTURE_SCRIPT = r"""
let structureDraft=null;
let structureNode=null;
let reviewedStructure=null;
let structureBusy=false;
const structurePanel=document.getElementById('structure-editor');
const structureStatus=document.getElementById('structure-status');
const structureDiff=document.getElementById('structure-diff');
const applyStructure=document.getElementById('apply-structure');
function invalidateStructure(){
  reviewedStructure=null;
  applyStructure.disabled=true;
  structureDiff.textContent='Review the draft before applying it.';
  structureStatus.textContent='';
}
function structureInput(parent,label,value,change,type='text'){
  const wrapper=document.createElement('label');
  wrapper.textContent=label;
  const input=document.createElement('input');
  input.type=type;
  if(type==='number'){input.step='any';}
  input.value=value;
  input.onchange=()=>{change(type==='number'?Number(input.value):input.value);invalidateStructure();};
  wrapper.append(input);parent.append(wrapper);
  return input;
}
function structureSelect(parent,label,value,options,change){
  const wrapper=document.createElement('label');
  wrapper.textContent=label;
  const input=document.createElement('select');
  if(!options.some(option=>option.value===value)){
    options=[{value,label:value||'Choose a value'},...options];
  }
  for(const choice of options){
    const option=document.createElement('option');
    option.value=choice.value;option.textContent=choice.label;input.append(option);
  }
  input.value=value;
  input.onchange=()=>{change(input.value);invalidateStructure();};
  wrapper.append(input);parent.append(wrapper);
}
function structureButton(parent,label,action,disabled=false){
  const button=document.createElement('button');
  button.type='button';button.textContent=label;button.disabled=disabled;
  button.onclick=()=>{
    try{action();invalidateStructure();drawStructure();}
    catch(error){structureStatus.textContent=error.message;}
  };
  parent.append(button);
}
function partTarget(part){
  const reference=part.score;
  return reference.selector||structureNode.dependencies[reference.path]||'';
}
function sourceControls(parent,source){
  structureSelect(parent,'Part',source.name,structureDraft.parts.map(part=>({
    value:part.name,label:part.name
  })),value=>{source.name=value;drawStructure();});
  const part=structureDraft.parts.find(part=>part.name===source.name);
  const score=part&&catalog.find(score=>score.source===partTarget(part));
  structureSelect(parent,'Light output',source.output,(score?.outputs||[]).map(name=>({
    value:name,label:name
  })),value=>{source.output=value;});
}
function newSource(){
  const part=structureDraft.parts[0];
  const score=part&&catalog.find(score=>score.source===partTarget(part));
  return {name:part?.name||'',output:score?.outputs[0]||'light'};
}
function rationalPair(value){
  const text=String(value);
  if(text.includes('/')){return text.split('/').map(BigInt);}
  if(!/^[+-]?\d+(\.\d+)?$/.test(text)){
    throw new Error('Use integer, decimal, or fraction times before adding a time slot');
  }
  const [whole,decimal='']=text.split('.');
  return [BigInt(whole+decimal),10n**BigInt(decimal.length)];
}
function addRational(left,right){
  const [a,b]=rationalPair(left),[c,d]=rationalPair(right);
  if(!b||!d){throw new Error('Time denominator must not be zero');}
  return `${a*d+c*b}/${b*d}`;
}
function moveStructureRow(rows,index,offset){
  const other=index+offset;
  if(other<0||other>=rows.length){return;}
  if(structureDraft.operation.effect==='cues'){
    [rows[index].source,rows[other].source]=[rows[other].source,rows[index].source];
  }else{
    [rows[index],rows[other]]=[rows[other],rows[index]];
  }
}
function structureRows(parent,key){
  const rows=structureDraft.operation[key];
  rows.forEach((row,index)=>{
    const box=document.createElement('fieldset');
    const legend=document.createElement('legend');
    legend.textContent=`${key==='cues'?'Time slot':'Source'} ${index+1}`;
    box.append(legend);sourceControls(box,row.source);
    if(key==='cues'){
      const timing=document.createElement('p');
      timing.textContent=`Start ${row.start} s; duration ${row.duration} s. Moving contents preserves these times.`;
      box.append(timing);
      structureInput(box,'Start (seconds or fraction)',row.start,value=>{row.start=value;});
      structureInput(box,'Duration (seconds or fraction)',row.duration,value=>{row.duration=value;});
    }else if(key==='sources'){
      structureInput(box,'Weight',row.weight,value=>{row.weight=value;},'number');
    }else{
      structureInput(box,'Output light names (space separated)',row.lights.join(' '),value=>{
        row.lights=value.trim().split(/\s+/).filter(Boolean);
      });
    }
    structureButton(box,'Move contents earlier',()=>moveStructureRow(rows,index,-1),index===0);
    structureButton(box,'Move contents later',()=>moveStructureRow(rows,index,1),index===rows.length-1);
    structureButton(box,'Remove',()=>rows.splice(index,1));
    parent.append(box);
  });
  structureButton(parent,key==='cues'?'Add time slot':'Add source',()=>{
    const source=newSource();
    if(key==='cues'){
      const last=rows.at(-1);
      rows.push({source,start:last?addRational(last.start,last.duration):'0',duration:last?.duration||'1'});
    }else if(key==='sources'){rows.push({source,weight:1});}
    else{rows.push({source,lights:[]});}
  });
}
function drawStructure(){
  structurePanel.replaceChildren();
  if(!structureDraft){return;}
  const parts=document.createElement('fieldset');
  const legend=document.createElement('legend');legend.textContent='Named parts';parts.append(legend);
  structureDraft.parts.forEach((part,index)=>{
    const box=document.createElement('fieldset');
    structureInput(box,'Part name',part.name,value=>{part.name=value;drawStructure();});
    structureSelect(box,'Referenced score',partTarget(part),catalog.filter(score=>score.source).map(score=>({
      value:score.source,label:`${score.title} (${score.source})`
    })),value=>{part.score={selector:value};drawStructure();});
    structureButton(box,'Remove part',()=>structureDraft.parts.splice(index,1));
    parts.append(box);
  });
  structureButton(parts,'Add part',()=>{
    let index=1;
    while(structureDraft.parts.some(part=>part.name===`part_${index}`)){index++;}
    const score=catalog.find(score=>score.source&&score.source!==structureNode.entry);
    structureDraft.parts.push({name:`part_${index}`,score:{selector:score?.source||''},parameters:{}});
  });
  structurePanel.append(parts);
  const operation=structureDraft.operation;
  const effects=['cues','mix','place','gain','reverse','crossfade'];
  structureSelect(structurePanel,'Composition operation',operation.effect,[
    {value:structureNode.fields.effect,label:`Original: ${structureNode.fields.effect}`},
    ...effects.filter(effect=>effect!==structureNode.fields.effect).map(effect=>({value:effect,label:effect}))
  ],effect=>{
    if(effect===structureNode.fields.effect){structureDraft.operation=structuredClone(structureNode.fields);}
    else{
      const source=newSource();
      const defaults={
        cues:{cues:[{source,start:'0',duration:'1'}],easing:'linear'},
        mix:{sources:[{source,weight:1}]},place:{placements:[{source,lights:[]}]},
        gain:{source,amount:1},reverse:{source},
        crossfade:{outgoing:source,incoming:{...source},fade:{duration:'1',easing:'linear'}}
      };
      structureDraft.operation={effect,...defaults[effect]};
    }
    drawStructure();
  });
  if(operation.effect==='cues'){structureRows(structurePanel,'cues');}
  else if(operation.effect==='mix'){structureRows(structurePanel,'sources');}
  else if(operation.effect==='place'){
    const names=document.createElement('details');
    const title=document.createElement('summary');title.textContent='Available output light names';
    const text=document.createElement('p');text.textContent=structureNode.lights.join(' ');
    names.append(title,text);structurePanel.append(names);structureRows(structurePanel,'placements');
  }else if(['gain','reverse'].includes(operation.effect)){
    sourceControls(structurePanel,operation.source);
    if(operation.effect==='gain'){
      structureInput(structurePanel,'Gain',operation.amount,value=>{operation.amount=value;},'number');
    }
  }else if(operation.effect==='crossfade'){
    for(const name of ['outgoing','incoming']){
      const box=document.createElement('fieldset');
      const legend=document.createElement('legend');legend.textContent=name;
      box.append(legend);sourceControls(box,operation[name]);structurePanel.append(box);
    }
    structureInput(structurePanel,'Fade duration',operation.fade.duration,value=>{operation.fade.duration=value;});
  }
}
function rebuildStructure(node){
  structureNode=node;
  structureDraft=node.editable?structuredClone({parts:node.parts,operation:node.fields}):null;
  invalidateStructure();
  document.getElementById('review-structure').disabled=!structureDraft;
  document.getElementById('structure-references').textContent=
    `Editing ${node.entry} changes every use of this score. Referenced by: ${node.used_by.join(', ')||'no other library scores'}.`;
  drawStructure();
}
async function submitStructure(apply){
  if(structureBusy||!structureDraft||(apply&&!reviewedStructure)){return;}
  structureBusy=true;
  structurePanel.inert=true;
  document.getElementById('review-structure').disabled=true;
  applyStructure.disabled=true;
  const draft=JSON.stringify({entry:structureNode.entry,output:structureNode.output,structure:structureDraft});
  try{
    const response=await fetch('/api/structure',{
      method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({...JSON.parse(draft),apply})
    });
    const result=await response.json();
    if(!apply&&draft!==JSON.stringify({entry:structureNode.entry,output:structureNode.output,structure:structureDraft})){
      return;
    }
    if(!response.ok){structureStatus.textContent=result.error;return;}
    if(!apply){
      reviewedStructure=draft;
      structureDiff.textContent=result.diff||'No document changes';
      applyStructure.disabled=false;
      structureStatus.textContent='Valid draft. Review the changes below, then apply.';
      return;
    }
    catalog=result.catalog;updateHistory(result.history);rebuildComposition();requestPreview();
    offerDownload(result);
    structureStatus.textContent=`Applied and offered ${result.filename} for download`;
  }catch(error){structureStatus.textContent=`Could not ${apply?'apply':'review'} composition: ${error.message}`;}
  finally{
    structureBusy=false;structurePanel.inert=false;
    document.getElementById('review-structure').disabled=!structureDraft;
    applyStructure.disabled=!reviewedStructure;
  }
}
document.getElementById('review-structure').onclick=()=>submitStructure(false);
applyStructure.onclick=()=>submitStructure(true);
"""
