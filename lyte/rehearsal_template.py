"""Browser controls for the shared installation playback engine."""

# ruff: noqa: E501

REHEARSAL_TEMPLATE = r"""<!doctype html>
<html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>lyte Rehearsal</title>
<style>
body{background:#111;color:#eee;font:16px system-ui;max-width:1100px;margin:2rem auto;padding:0 1rem}
button,input,select{font:inherit;margin:.3rem;padding:.3rem}label{display:inline-block}
canvas{width:100%;height:90px;background:#000}fieldset{margin:1rem 0}output{display:block;white-space:pre-wrap}
#error{color:#ffb4b4;min-height:1.5em}pre{white-space:pre-wrap}
</style>
<h1>lyte Rehearsal</h1>
<p>Software simulation only. No devices, MIDI ports, or installation services are opened.
Each step advances one delivery tick. Play advances the simulated clock; browser delays slow rehearsal without skipping ticks.</p>
<button id="play">Play</button><button id="step">Step</button>
<label>Animation <select id="animation"></select></label><button id="select">Select</button>
<label>Fade (s) <input id="fade" type="number" min="0" step="0.1" value="0"></label>
<label>Master (%) <input id="master" type="number" min="0" max="100" value="100"></label><button id="set-master">Set master</button>
<output id="fade-status"></output>
<button id="blackout">Blackout</button>
<label>Test level (%) <input id="level" type="number" min="0" max="100" value="50"></label>
<label>Test duration (s) <input id="duration" type="number" min="0.01" step="0.1" value="2"></label><button id="test">Test</button>
<fieldset id="midi"><legend>Synthetic MIDI</legend>
<label>Channel (1–16) <input id="channel" type="number" min="1" max="16" value="1"></label>
<label>Note <input id="note" type="number" min="0" max="127" value="60"></label>
<label>Velocity <input id="velocity" type="number" min="0" max="127" value="96"></label>
<button id="note-on">Note on / restart</button><button id="note-off">Note off</button>
<label>Breath <input id="breath" type="range" min="0" max="127" value="0"></label>
<label>Pitch bend <input id="pitch" type="range" min="-8192" max="8191" value="0"></label>
<button id="program">Next animation</button>
<p>Controls apply to the note-owning channel and the installation's configured channel filter.</p></fieldset>
<output id="error" role="alert"></output><output id="status"></output><pre id="bindings"></pre><section id="strings"></section>
<script>
const element=id=>document.getElementById(id), number=id=>Number(element(id).value);
let playing=false, rate=30, queue=Promise.resolve(), timer=null, initial=true, generation=0;
const canvases=new Map();
function show(data){
  rate=data.fps;
  element('fade-status').textContent=`Master ${Math.round(data.master_level*100)}% · fade ${data.transition_duration||0}s`;
  if(initial){
    element('animation').replaceChildren(...data.animations.map(name=>new Option(name,name)));
    element('animation').value=data.active;
    element('midi').disabled=data.midi===null;
    if(data.midi?.channel){element('channel').value=data.midi.channel;}
    initial=false;
  }
  element('status').textContent=`Time ${data.time.toFixed(3)}s · delivery ${rate} fps · active ${data.active} · queued ${data.queued||'none'} · blackout ${data.blackout} · test ${data.test}\nNote ${data.performance.note??'none'} · velocity ${data.performance.velocity} · breath ${data.performance.breath??'none'} · pitch ${data.performance.pitch??'none'}`;
  element('bindings').textContent=Object.entries(data.bindings).map(([output,binding])=>`${output}: ${binding}`).join('\n');
  for(const [name,count] of Object.entries(data.strings)){
    if(!canvases.has(name)){
      const title=document.createElement('h2');title.textContent=`${name} (${count} simulated lights)`;
      const canvas=document.createElement('canvas');canvas.width=1000;canvas.height=90;
      element('strings').append(title,canvas);canvases.set(name,canvas);
    }
    if(!data.frames[name]){continue;}
    const canvas=canvases.get(name),ctx=canvas.getContext('2d'),frame=atob(data.frames[name]);
    ctx.clearRect(0,0,canvas.width,canvas.height);
    for(let i=0;i<count;i++){
      ctx.fillStyle=`rgb(${frame.charCodeAt(i*3)},${frame.charCodeAt(i*3+1)},${frame.charCodeAt(i*3+2)})`;
      ctx.fillRect(i*canvas.width/count,10,Math.max(1,canvas.width/count),70);
    }
  }
}
function request(command,params={}){
  queue=queue.then(async()=>{
    const response=await fetch('/api/rehearse',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({command,params})});
    const data=await response.json();
    if(!response.ok){throw new Error(data.error);}
    show(data);
  }).catch(error=>{playing=false;element('play').textContent='Play';element('error').textContent=error.message;});
  return queue;
}
async function tick(id){if(!playing||id!==generation){return;}await request('step');if(playing&&id===generation){timer=setTimeout(()=>tick(id),1000/rate);}}
element('play').onclick=()=>{playing=!playing;generation++;element('play').textContent=playing?'Pause':'Play';clearTimeout(timer);if(playing){tick(generation);}};
element('step').onclick=()=>request('step');
element('select').onclick=()=>request('select_animation',{name:element('animation').value,duration:number('fade')});
element('set-master').onclick=()=>request('master_level',{level:number('master')/100});
element('blackout').onclick=()=>request('blackout');
element('test').onclick=()=>request('test',{level:number('level'),duration:number('duration')});
function midi(type,values){return request('midi',{type,channel:number('channel')-1,...values});}
element('note-on').onclick=()=>midi('note_on',{note:number('note'),velocity:number('velocity')});
element('note-off').onclick=()=>midi('note_off',{note:number('note'),velocity:0});
element('breath').onchange=()=>midi('control_change',{control:2,value:number('breath')});
element('pitch').onchange=()=>midi('pitchwheel',{pitch:number('pitch')});
element('program').onclick=()=>midi('program_change',{program:0});
request('step');
</script></html>"""
