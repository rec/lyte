"""Search, diagnostics, metadata and on-demand thumbnails for the editor."""

# ruff: noqa: E501

BROWSER_SCRIPT = r"""
const librarySearch=document.getElementById('library-search');
const libraryFilter=document.getElementById('library-filter');
const familyFilter=document.getElementById('family-filter');
let lastSelected='';
let thumbnailRequest=0;
function matchingScores(items,query,library,family){
  const words=query.toLowerCase().trim().split(/\s+/).filter(Boolean);
  return items.filter(item=>(!library||item.library===library)&&(!family||item.family===family)&&
    words.every(word=>`${item.title} ${item.name} ${item.selector} ${(item.tags||[]).join(' ')}`.toLowerCase().includes(word)));
}
function filterChoices(control,values){
  const previous=control.value;
  control.replaceChildren();
  for(const value of ['',...new Set(values.sort())]){
    const option=document.createElement('option');
    option.value=value;option.textContent=value||'All';control.append(option);
  }
  control.value=values.includes(previous)?previous:'';
}
function rebuildLibrary(){
  const previous=select.value;
  filterChoices(libraryFilter,catalog.map(item=>item.library));
  filterChoices(familyFilter,catalog.map(item=>item.family));
  const matches=matchingScores(catalog,librarySearch.value,libraryFilter.value,familyFilter.value);
  select.replaceChildren();
  for(const item of matches){
    const option=document.createElement('option');
    option.value=item.selector;
    option.textContent=`${item.title} (${item.selector})${item.diagnostics.length?' [unavailable]':''}`;
    select.append(option);
  }
  select.value=matches.some(item=>item.selector===previous)?previous:(matches[0]?.selector||'');
  document.getElementById('library-count').textContent=`${matches.length} of ${catalog.length} entries`;
  rebuild();
}
function libraryDetails(selected){
  thumbnailRequest++;
  const details=document.getElementById('library-details');
  const thumbnail=document.getElementById('thumbnail');
  thumbnail.hidden=true;
  document.getElementById('thumbnail-status').textContent='';
  document.getElementById('make-thumbnail').disabled=!selected||selected.renderer!=='ufor'||selected.diagnostics.length>0;
  details.replaceChildren();
  if(!selected){details.textContent='No matching scores';return;}
  const text=document.createElement('p');
  text.textContent=`${selected.family} · ${selected.rate||'unknown'} FPS · ${selected.light_count||'unknown'} lights · Outputs: ${selected.outputs.join(', ')||'preview'} · ${(selected.tags||[]).join(' ')}`;
  details.append(text);
  for(const message of selected.diagnostics){
    const error=document.createElement('p');error.textContent=message;details.append(error);
  }
  for(const [label,entries] of [['Dependencies',selected.dependencies],['Used by',selected.used_by]]){
    const heading=document.createElement('p');heading.textContent=label;details.append(heading);
    for(const entry of entries){
      const button=document.createElement('button');button.type='button';button.textContent=entry;
      button.disabled=!catalog.some(item=>item.selector===entry);
      button.onclick=()=>{
        librarySearch.value='';libraryFilter.value='';familyFilter.value='';
        rebuildLibrary();select.value=entry;rebuild();
      };
      details.append(button);
    }
  }
}
async function requestThumbnail(){
  const request=++thumbnailRequest;
  const selector=select.value;
  const message=document.getElementById('thumbnail-status');
  message.textContent='Rendering thumbnail';
  try{
    const response=await fetch('/api/thumbnail',{
      method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({selector})
    });
    const result=await response.json();
    if(request!==thumbnailRequest||selector!==select.value){return;}
    if(!response.ok){message.textContent=result.error;return;}
    const target=document.getElementById('thumbnail');target.hidden=false;
    drawFrame(target,result.coords,decodeFrame(result.frame));
    message.textContent='Initial frame at 0 seconds, using the score’s existing seed';
  }catch(error){if(request===thumbnailRequest&&selector===select.value){message.textContent=error.message;}}
}
librarySearch.oninput=rebuildLibrary;
libraryFilter.onchange=rebuildLibrary;
familyFilter.onchange=rebuildLibrary;
document.getElementById('make-thumbnail').onclick=requestThumbnail;
"""
