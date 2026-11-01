// Public browser simulation. This adapter never calls a server or model.
// The Python/SQLite recorder remains the authoritative full implementation.
(()=>{
 const runs=new Map();
 const clone=value=>structuredClone(value);
 const canonical=value=>JSON.stringify(value&&typeof value==='object'?Array.isArray(value)?value.map(v=>JSON.parse(canonical(v))):Object.fromEntries(Object.keys(value).sort().map(k=>[k,JSON.parse(canonical(value[k]))])):value);
 async function hash(previous,payload){const bytes=new TextEncoder().encode(previous+canonical(payload));return [...new Uint8Array(await crypto.subtle.digest('SHA-256',bytes))].map(n=>n.toString(16).padStart(2,'0')).join('');}
 const policies=new Set(['speed-first','evidence-first']);
 async function append(run,kind,label,state,inputs=null,output=null){const payload={kind,label,state:clone(state),inputs,output,at:new Date().toISOString()},previous=run.events.at(-1)?.hash||'';run.events.push({seq:run.events.length,...payload,hash:await hash(previous,payload)});}
 async function verify(run){let previous='';for(const event of run.events){const {seq,hash:recorded,...payload}=event;if(seq!==run.events.indexOf(event)||recorded!==await hash(previous,payload))throw Error('Browser trajectory integrity check failed');previous=recorded;}return clone(run);}
 function create(policy,parent=null,seq=null){if(runs.size>=100)throw Error('Reset the simulation to create more runs.');const run={id:crypto.randomUUID().replaceAll('-',''),name:'Checkout latency alert'+(parent?' · fork':''),policy,parent_id:parent,fork_at:seq,created_at:new Date().toISOString(),events:[],integrity:'valid'};runs.set(run.id,run);return run;}
 async function resume(run){let state=clone(run.events.at(-1).state);
  if(state.phase==='inspect'){Object.assign(state,{phase:'decide',tool_calls:state.tool_calls+1,observation:'Alert window is stale; current latency is normal.'});await append(run,'observation','Inspect current service health',state,null,{p95_ms:118,threshold_ms:500,alert_age_minutes:24});}
  if(state.phase==='decide'){const action=run.policy==='speed-first'?'restart':'close-stale-alert';Object.assign(state,{phase:'execute',action});await append(run,'decision','Policy selected: '+action,state,{policy:run.policy},{action});}
  if(state.phase==='execute'){state.tool_calls++;if(state.action==='restart'){Object.assign(state,{phase:'done',outcome:'blocked',reason:"Restart is outside the agent's permitted actions."});await append(run,'tool','Restart rejected by permission boundary',state,null,{allowed:false,side_effect:false});}else{Object.assign(state,{phase:'done',outcome:'resolved',reason:'Current health verified; stale alert closed in simulation.'});await append(run,'tool','Close stale alert',state,null,{closed:true,side_effect:'synthetic record only'});}await append(run,'finish','Workflow finished',state);}
 }
 async function demo(policy='speed-first'){if(!policies.has(policy))throw Error('Unknown policy');const run=create(policy);await append(run,'start','Incident received',{phase:'inspect',alert:'checkout latency',service:'checkout',restart_allowed:false,deployment_healthy:true,outcome:'pending',tool_calls:0,scenario:'checkout-v1'},{environment:'synthetic browser demo'});await resume(run);return run.id;}
 const initial=demo();
 window.rewindDemo={initialId:null,async request(path,data){await initial.then(id=>{this.initialId=id;});
  const url=new URL(path,'https://demo.invalid');
  if(url.pathname==='/api/runs')return [...runs.values()].reverse().map(({events,...run})=>clone(run));
  if(url.pathname.startsWith('/api/run/')){const run=runs.get(url.pathname.slice(9));if(!run)throw Error('Run not found');return verify(run);}
  if(url.pathname==='/api/demo')return {id:await demo(data.policy)};
  if(url.pathname==='/api/fork'){const parent=runs.get(data.run_id);if(!parent)throw Error('Run not found');await verify(parent);const event=parent.events[data.seq];if(!Number.isInteger(data.seq)||!event||!['inspect','decide'].includes(event.state.phase)||!policies.has(data.policy))throw Error('Choose a checkpoint before the decision.');const child=create(data.policy,parent.id,data.seq);child.events=clone(parent.events.slice(0,data.seq+1));await resume(child);return {id:child.id};}
  if(url.pathname==='/api/compare'){const left=runs.get(url.searchParams.get('left')),right=runs.get(url.searchParams.get('right'));if(!left||!right)throw Error('Run not found');await verify(left);await verify(right);let shared=0;while(left.events[shared]&&right.events[shared]&&left.events[shared].hash===right.events[shared].hash)shared++;const summary=run=>({id:run.id,policy:run.policy,steps:run.events.length,state:clone(run.events.at(-1).state)});return {shared_steps:shared,left:summary(left),right:summary(right)};}
  throw Error('Unsupported demo action');
 }};
})();
