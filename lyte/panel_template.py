"""Operator controls with fresh status polling and no command replay."""

# ruff: noqa: E501

PANEL_TEMPLATE = r"""<!doctype html>
<html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>lyte Installation</title>
<style>body{background:#111;color:#eee;font:16px system-ui;max-width:1000px;margin:2rem auto;padding:0 1rem}button,input,select{font:inherit;padding:.4rem;margin:.4rem}pre,output{white-space:pre-wrap;display:block}#error{color:#ffb4b4}td,th{text-align:left;padding:.5rem;border-bottom:1px solid #555}</style>
<h1>lyte Installation</h1><output id="connection">Connecting…</output>
<p>This controls the running installation. Commands take effect on physical outputs.</p>
<fieldset id="controls" disabled><legend>Controls</legend>
<select id="animation" aria-label="Animation"></select><button id="select">Select animation</button>
<label>Fade (s) <input id="fade" type="number" min="0" step="0.1" value="0"></label>
<label>Master (%) <input id="master" type="number" min="0" max="100" value="100"></label><button id="set-master">Set master</button>
<output id="fade-status"></output>
<output id="recording-status"></output>
<button id="blackout">Blackout</button><button id="stop">Stop installation</button>
<label>Test level (%) <input id="level" type="number" min="0" max="100" value="50"></label>
<label>Duration (s) <input id="duration" type="number" min="0.01" step="0.1" value="2"></label><button id="test">Test lights</button>
</fieldset><output id="error" role="alert"></output><button id="clear-error">Clear command error</button>
<output id="status"></output><table><thead><tr><th>String</th><th>Transport</th><th>State</th><th>Lights</th><th>Sent</th><th>Failures</th><th>Last error</th></tr></thead><tbody id="strings"></tbody></table>
<details><summary>Timing diagnostics</summary><pre id="diagnostics"></pre></details>
<script>
const element=id=>document.getElementById(id);
let connected=false,busy=false,statusRequest=0;
function displayStatus(data){
  connected=data.running===true;
  element('connection').textContent=connected?'Connected to lyte':'lyte reports stopped';
  element('controls').disabled=!connected||busy;
  element('recording-status').textContent=[data.recording?'Recording to '+data.recording_path:'Recording off',data.recording_error?'Recording failed; lighting continues: '+data.recording_error:'',data.render_error?'Render error; retrying: '+data.render_error:'',data.status_error?'Status publication error: '+data.status_error:''].filter(Boolean).join('\n');
  element('fade-status').textContent=`Master ${Math.round(data.master_level*100)}% · fade ${data.transition_duration||0}s${data.transition_from_snapshot?' from displayed snapshot':data.outgoing_animation?' from '+data.outgoing_animation:''}`;
  const selected=element('animation').value;
  element('animation').replaceChildren(...data.animations.map(name=>new Option(name,name)));
  element('animation').value=data.animations.includes(selected)?selected:data.active_animation||data.animations[0]||'';
  element('status').textContent=`Active: ${data.active_animation||'none'}\nQueued: ${data.queued_animation||'none'}\nBlackout: ${data.blackout}\nMIDI: ${data.midi_connected?'connected':'disconnected'}${data.midi_error?' ('+data.midi_error+')':''}\nTest: ${data.active_test?'active':data.queued_test?'queued':'none'}\n${(data.errors||[]).map(error=>error.message).join('\n')}`;
  element('strings').replaceChildren(...Object.entries(data.strings).map(([name,status])=>{
    const row=document.createElement('tr');
    for(const value of [name,status.transport,status.state,status.led_count??'unknown',status.frame_count,status.failure_count,status.last_error||'']){
      const cell=document.createElement('td');cell.textContent=String(value);row.append(cell);
    }
    return row;
  }));
  element('diagnostics').textContent=JSON.stringify({render_costs:data.render_costs,delivery:data.delivery},null,2);
}
async function refresh(){
  const request=++statusRequest;
  try{
    const response=await fetch('/api/status',{cache:'no-store'}),data=await response.json();
    if(request!==statusRequest){return;}
    if(!response.ok){throw new Error(data.error);}
    displayStatus(data);
  }catch(error){
    if(request!==statusRequest){return;}
    connected=false;element('controls').disabled=true;
    element('connection').textContent=`Disconnected: ${error.message}. Values below are the last received state.`;
  }
}
async function sendCommand(command,params={}){
  if(!connected||busy){return;}
  busy=true;statusRequest++;element('controls').disabled=true;
  try{
    const response=await fetch('/api/command',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({command,params})});
    const data=await response.json();
    if(!response.ok){throw new Error(data.error);}
  }catch(error){element('error').textContent=`${command}: ${error.message}. The command will not be retried automatically.`;}
  finally{busy=false;await refresh();}
}
async function poll(){if(!busy){await refresh();}setTimeout(poll,1000);}
element('select').onclick=()=>sendCommand('select_animation',{name:element('animation').value,duration:Number(element('fade').value)});
element('set-master').onclick=()=>sendCommand('master_level',{level:Number(element('master').value)/100});
element('blackout').onclick=()=>sendCommand('blackout');
element('stop').onclick=()=>sendCommand('stop');
element('test').onclick=()=>sendCommand('test',{level:Number(element('level').value),duration:Number(element('duration').value)});
element('clear-error').onclick=()=>{element('error').textContent='';};
poll();
</script></html>"""
