"""RGB colour and palette controls with explicit numeric units."""

# ruff: noqa: E501

COLORS_SCRIPT = r"""
let colorDraft={};
let colorNode=null;
const colorPanel=document.getElementById('color-fields');
const colorStatus=document.getElementById('color-status');
const applyColors=document.getElementById('apply-colors');
function colorHex(values,scale){
  return '#'+values.map(value=>Math.round(Math.max(0,Math.min(1,value/scale))*255).toString(16).padStart(2,'0')).join('');
}
function hexColor(value,scale){
  return [1,3,5].map(index=>parseInt(value.slice(index,index+2),16)*scale/255);
}
function drawColors(){
  colorPanel.replaceChildren();
  colorPanel.disabled=!colorNode.editable;
  applyColors.disabled=!colorNode.editable||!Object.keys(colorDraft).length;
  if(!Object.keys(colorDraft).length){
    colorPanel.textContent='No supported RGB fields. Other nested fields remain read-only.';return;
  }
  for(const [name,field] of Object.entries(colorDraft)){
    const heading=document.createElement('p');
    heading.textContent=`${name}: ${field.scale===255?'RGB bytes (0–255)':'Normalized RGB drive (1 = full scale; swatch clips to 0–1)'}`;
    colorPanel.append(heading);
    const colors=field.kind==='palette'?field.values:[field.values];
    colors.forEach((values,index)=>{
      const row=document.createElement('fieldset');
      const label=document.createElement('legend');label.textContent=`${name} ${index+1}`;row.append(label);
      const swatch=document.createElement('input');swatch.type='color';
      swatch.setAttribute('aria-label',`${name} ${index+1} colour`);
      swatch.value=colorHex(values,field.scale);row.append(swatch);
      const inputs=[];
      ['Red','Green','Blue'].forEach((component,channel)=>{
        const input=structureInput(row,component,values[channel],value=>{
          values[channel]=value;swatch.value=colorHex(values,field.scale);
        },'number');
        input.step=field.scale===255?'1':'any';inputs.push(input);
      });
      swatch.oninput=()=>{
        const next=hexColor(swatch.value,field.scale);
        next.forEach((value,channel)=>{values[channel]=value;inputs[channel].value=value;});
      };
      if(field.kind==='palette'){
        for(const [text,offset] of [['Earlier',-1],['Later',1]]){
          const button=document.createElement('button');button.type='button';button.textContent=text;
          button.disabled=index+offset<0||index+offset>=colors.length;
          button.onclick=()=>{
            [colors[index],colors[index+offset]]=[colors[index+offset],colors[index]];drawColors();
          };
          row.append(button);
        }
        const remove=document.createElement('button');remove.type='button';remove.textContent='Remove colour';
        remove.onclick=()=>{colors.splice(index,1);drawColors();};row.append(remove);
      }
      colorPanel.append(row);
    });
    if(field.kind==='palette'){
      const add=document.createElement('button');add.type='button';add.textContent='Add colour';
      add.onclick=()=>{colors.push([...(colors.at(-1)||[0,0,0])]);drawColors();};colorPanel.append(add);
    }
  }
}
function rebuildColors(node){
  colorNode=node;colorDraft=structuredClone(node.color_fields||{});
  colorStatus.textContent='';drawColors();
}
async function saveColors(){
  if(!colorNode.editable){return;}
  applyColors.disabled=true;
  try{
    const response=await fetch('/api/colors',{
      method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({
        entry:colorNode.entry,output:colorNode.output,
        fields:Object.fromEntries(Object.entries(colorDraft).map(([name,field])=>[name,field.values]))
      })
    });
    const result=await response.json();
    if(!response.ok){colorStatus.textContent=result.error;return;}
    catalog=result.catalog;updateHistory(result.history);rebuildLibrary();offerDownload(result);
    colorStatus.textContent=`Applied and offered ${result.filename} for download`;
  }catch(error){colorStatus.textContent=`Could not apply colours: ${error.message}`;}
  finally{applyColors.disabled=!colorNode.editable||!Object.keys(colorDraft).length;}
}
applyColors.onclick=saveColors;
"""
