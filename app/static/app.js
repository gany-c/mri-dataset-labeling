const $ = id => document.getElementById(id);
const state = { studies: [], targets: [], study: null, series: null, slice: 0, labels: {}, revision: 0,
  dirty: false, saving: false, image: null, imageOK: false, imageRequest: 0, studyRequest: 0, abort: null,
  center: null, width: null, zoom: 1, pan: [0,0], invert: false, reviewer: '' };
const findingTitles = {'ACL':'ACL injury','MCL':'MCL injury','Medial Meniscus':'Medial meniscus tear','Lateral Meniscus':'Lateral meniscus tear'};
const names = {'ACL':'Anterior cruciate ligament injury','MCL':'Medial collateral ligament injury','Medial Meniscus':'Medial meniscal tear',
  'Lateral Meniscus':'Lateral meniscal tear','Medial OA':'Medial compartment osteoarthritis','Lateral OA':'Lateral compartment osteoarthritis',
  'PF OA':'Patellofemoral osteoarthritis','Effusion':'Joint fluid','Synovitis':'Synovial inflammation',"Baker's":'Popliteal cyst',
  'Contusion':'Bone contusion','Fracture':'Bone fracture'};
async function api(url, options={}) {
  const response = await fetch(url, {...options, headers:{'Content-Type':'application/json','X-Knee-Review':'1',...options.headers}});
  if (!response.ok) {
    let error; try { error = await response.json(); } catch { error = {detail:response.statusText}; }
    if(response.status===401 && !url.endsWith('/login')) showLogin();
    throw new Error(typeof error.detail==='string'?error.detail:`Request failed (${response.status})`);
  }
  return response.json();
}
let toastTimer;
function toast(text) { $('toast').textContent=text; $('toast').hidden=false; clearTimeout(toastTimer); toastTimer=setTimeout(()=>$('toast').hidden=true,7000); }
function showLogin() { $('workspace').hidden=true; $('loginScreen').hidden=false; }
function confirmLeave() { return !state.dirty || confirm('You have unsaved answers. Discard them and continue?'); }
$('loginForm').onsubmit=async event=>{
  event.preventDefault(); $('loginError').textContent=''; const button=event.submitter; button.disabled=true;
  try { await api('/api/login',{method:'POST',body:JSON.stringify({name:$('name').value,password:$('password').value,register:$('register').checked})});
    $('password').value=''; await start();
  } catch(e){$('loginError').textContent=e.message;} finally {button.disabled=false;}
};
$('logoutBtn').onclick=async()=>{if(!confirmLeave())return;try{await api('/api/logout',{method:'POST'});state.dirty=false;showLogin();}catch(e){toast(e.message);}};
async function start(){
  const info=await api('/api/me'); state.reviewer=info.reviewer; state.targets=info.targets;
  $('reviewerName').textContent=info.reviewer; $('dataPath').textContent=info.scan_root;
  $('loginScreen').hidden=true; $('workspace').hidden=false;
  state.study=null;state.series=null;state.dirty=false; $('studyWorkspace').hidden=true; $('emptyState').hidden=false;
  state.labels=Object.fromEntries(state.targets.map(t=>[t,null]));buildFindings();await refresh();
}
async function refresh(){state.studies=await api('/api/studies');renderQueue();}
function filtered(){return state.studies.filter(s=>s.demo===($('datasetFilter').value==='demo')&&s.uid.includes($('search').value.trim())&&($('statusFilter').value==='all'||s.status===$('statusFilter').value));}
function renderQueue(){
  const list=$('studyList');list.replaceChildren();const all=state.studies.filter(s=>s.demo===($('datasetFilter').value==='demo'));
  $('studyCount').textContent=all.length; $('progressText').textContent=`${all.filter(s=>s.status==='complete').length} of ${all.length} complete`;
  const rows=filtered();if(!rows.length){const p=document.createElement('p');p.className='queue-empty';p.textContent=all.length?'No matching studies.':'No studies loaded yet.';list.append(p);}
  for(const s of rows){const b=document.createElement('button');b.className='study-card'+(state.study?.uid===s.uid?' active':'');
    const header=document.createElement('span');header.className='study-number';header.textContent=`${s.demo?'Practice':'Study'} ${String(all.indexOf(s)+1).padStart(3,'0')}`;
    const status=document.createElement('span');status.className=`status-tag status-${s.status}`;status.textContent={complete:'✓ Complete',draft:'In progress',unstarted:'Not started'}[s.status];header.append(status);
    const detail=document.createElement('small');detail.textContent=`${s.series_count} series · ${s.answered}/12 findings`;
    const uid=document.createElement('small');uid.textContent='…'+s.uid.slice(-19);b.append(header,detail,uid);b.onclick=()=>openStudy(s.uid);list.append(b);}
}
$('search').oninput=renderQueue;$('statusFilter').onchange=renderQueue;
$('datasetFilter').onchange=()=>{renderQueue();};
$('practiceBtn').onclick=()=>{$('datasetFilter').value='demo';renderQueue();const first=filtered()[0];if(first)openStudy(first.uid);else toast('Run python -m app.demo to create practice scans.');};
async function openStudy(uid){
  if(!confirmLeave())return;
  const request=++state.studyRequest;
  try{const s=await api('/api/studies/'+encodeURIComponent(uid));if(request!==state.studyRequest)return;state.imageOK=false;state.study=s;state.labels={...s.review.labels};state.revision=s.review.revision;state.dirty=false;
    $('notes').value=s.review.notes; $('studyTitle').textContent=s.demo?'Practice knee study':'Knee MRI';$('studyUid').textContent=s.uid;
    $('reportPanel').open=false; $('reportText').textContent=s.report?.trim()?s.report:'No original report is available for this study.';
    $('demoBadge').hidden=!s.demo;$('studyEyebrow').textContent=s.demo?'PRACTICE WORKSPACE':'STUDY REVIEW';
    $('lastEditor').textContent=s.review.editor?`Last saved by ${s.review.editor} · ${new Date(s.review.updated).toLocaleString()}`:'Shared record · no edits yet';
    $('saveStatus').textContent=s.review.status==='complete'?'Complete':s.review.revision?'Saved':'Not started';
    $('emptyState').hidden=true;$('studyWorkspace').hidden=false;buildFindings();renderQueue();renderSeries();
    if(s.series.length)selectSeries(s.series[0]);
  }catch(e){toast(e.message);}
}
function renderSeries(){
  $('seriesTabs').replaceChildren(); for(const s of state.study.series){const b=document.createElement('button');b.className='series-tab'+(state.series?.uid===s.uid?' active':'');b.textContent=s.plane;
    const sub=document.createElement('small');sub.textContent=`${s.description} · ${s.count} slices`;b.append(sub);b.onclick=()=>selectSeries(s);$('seriesTabs').append(b);}
}
function direction(v){const labels=['LR','PA','HF'];return v.map((x,i)=>({x:Math.abs(x),name:labels[i][x>=0?0:1]})).filter(x=>x.x>.2).sort((a,b)=>b.x-a.x).map(x=>x.name).join('');}
function selectSeries(s){
  state.series=s;state.slice=Math.floor(s.count/2);state.center=null;state.width=null;state.zoom=1;state.pan=[0,0];state.invert=false;
  $('zoom').value=100;$('invertBtn').setAttribute('aria-pressed','false');$('seriesTitle').textContent=s.description;$('planeLabel').textContent=s.plane;
  $('sliceMeta').textContent=state.study.demo?'SYNTHETIC · FOR PRACTICE ONLY':'Original acquired slices';$('geometryWarning').textContent=s.warnings.join(' ');
  $('sliceSlider').max=s.count-1;renderSeries();
  const ori=s.orientation;const ids=['orientationRight','orientationLeft','orientationBottom','orientationTop'];
  const vectors=ori.length===6?[ori.slice(0,3),ori.slice(0,3).map(x=>-x),ori.slice(3),ori.slice(3).map(x=>-x)]:[];
  ids.forEach((id,i)=>$(id).textContent=vectors.length?direction(vectors[i]):'');loadSlice();
}
async function loadSlice(){
  if(!state.series)return;const request=++state.imageRequest;state.abort?.abort();state.abort=new AbortController();state.imageOK=false;updateButtons();
  state.image?.close();state.image=null;draw();$('imageMessage').textContent='Loading slice…';$('imageMessage').hidden=false;
  $('sliceSlider').value=state.slice;$('sliceCount').textContent=`${state.slice+1} / ${state.series.count}`;
  const query=state.width===null?'':`?center=${state.center}&width=${state.width}`;
  try{const r=await fetch(`/api/series/${encodeURIComponent(state.series.uid)}/slices/${state.slice}${query}`,{signal:state.abort.signal});
    if(!r.ok){const e=await r.json();throw new Error(e.detail||'Could not load image');}
    const meta=JSON.parse(r.headers.get('X-Image-Meta'));const bitmap=await createImageBitmap(await r.blob());
    if(request!==state.imageRequest){bitmap.close();return;}
    state.image=bitmap;state.imageOK=true;
    if(state.width===null){state.width=meta.width;state.center=meta.center;
      $('windowWidth').max=Math.ceil(meta.width*5);$('windowWidth').value=state.width;
      $('windowCenter').min=Math.floor(meta.center-meta.width*3);$('windowCenter').max=Math.ceil(meta.center+meta.width*3);$('windowCenter').value=state.center;}
    $('imageMessage').hidden=true;draw();updateButtons();
  }catch(e){if(e.name==='AbortError')return;if(request!==state.imageRequest)return;$('imageMessage').textContent=e.message;state.imageOK=false;updateButtons();}
}
function draw(){const canvas=$('canvas'),box=$('stage').getBoundingClientRect(),dpr=devicePixelRatio||1;
  canvas.width=Math.round(box.width*dpr);canvas.height=Math.round(box.height*dpr);const ctx=canvas.getContext('2d');ctx.scale(dpr,dpr);ctx.fillStyle='#080e12';ctx.fillRect(0,0,box.width,box.height);
  if(!state.image)return;const [row,col]=state.series.spacing;const aspect=Number.isFinite(row/col)&&row/col>0?row/col:1;
  const w=state.image.width,h=state.image.height*aspect,scale=Math.min((box.width-70)/w,(box.height-50)/h)*state.zoom;
  ctx.imageSmoothingEnabled=true;ctx.filter=state.invert?'invert(1)':'none';ctx.drawImage(state.image,(box.width-w*scale)/2+state.pan[0],(box.height-h*scale)/2+state.pan[1],w*scale,h*scale);
  $('windowMeta').textContent=`W ${Math.round(state.width)} / L ${Math.round(state.center)} · ${Math.round(state.zoom*100)}%`;
}
new ResizeObserver(draw).observe($('stage'));
function step(delta){if(!state.series)return;const next=Math.max(0,Math.min(state.series.count-1,state.slice+delta));if(next!==state.slice){state.slice=next;loadSlice();}}
$('prevSlice').onclick=()=>step(-1);$('nextSlice').onclick=()=>step(1);$('sliceSlider').oninput=()=>{state.slice=+$('sliceSlider').value;loadSlice();};
$('stage').addEventListener('wheel',e=>{e.preventDefault();if(e.ctrlKey||e.metaKey){state.zoom=Math.max(.5,Math.min(4,state.zoom+(e.deltaY>0?-.1:.1)));$('zoom').value=state.zoom*100;draw();}else step(e.deltaY>0?1:-1);},{passive:false});
let drag=null;$('canvas').onpointerdown=e=>{drag=[e.clientX,e.clientY,...state.pan];$('canvas').setPointerCapture(e.pointerId);};
$('canvas').onpointermove=e=>{if(drag){state.pan=[drag[2]+e.clientX-drag[0],drag[3]+e.clientY-drag[1]];draw();}};
$('canvas').onpointerup=$('canvas').onpointercancel=()=>drag=null;
$('zoom').oninput=()=>{state.zoom=+$('zoom').value/100;draw();};
let windowTimer;for(const id of ['windowWidth','windowCenter'])$(id).oninput=()=>{state.width=+$('windowWidth').value;state.center=+$('windowCenter').value;clearTimeout(windowTimer);windowTimer=setTimeout(loadSlice,120);};
$('invertBtn').onclick=()=>{state.invert=!state.invert;$('invertBtn').setAttribute('aria-pressed',String(state.invert));draw();};
$('resetBtn').onclick=()=>{if(state.series)selectSeries(state.series);};$('fullBtn').onclick=()=>{if(document.fullscreenElement)document.exitFullscreen();else $('stage').requestFullscreen().catch(e=>toast(e.message));};
function buildFindings(){
  $('findings').replaceChildren();for(const target of state.targets){const row=document.createElement('div');row.className='finding';
    const title=document.createElement('div');title.className='finding-name';title.textContent=findingTitles[target] || target;const sub=document.createElement('small');sub.textContent=names[target];title.append(sub);
    const controls=document.createElement('div');controls.className='segmented';controls.setAttribute('role','group');controls.setAttribute('aria-label',findingTitles[target] || target);
    for(const [text,value] of [['Yes',1],['No',0],['×',null]]){const b=document.createElement('button');b.type='button';b.textContent=text;b.disabled=!state.study;
      b.className=value===null?'clear':state.labels[target]===value?value?'selected-yes':'selected-no':'';
      b.setAttribute('aria-label',value===null?`Clear ${findingTitles[target] || target}`:`${findingTitles[target] || target}: ${text}`);b.setAttribute('aria-pressed',String(state.labels[target]===value));
      b.onclick=()=>{state.labels[target]=value;markDirty();buildFindings();};controls.append(b);}
    row.append(title,controls);$('findings').append(row);
  } updateButtons();
}
function markDirty(){state.dirty=true;$('saveStatus').textContent='Unsaved changes';}
function updateButtons(){const count=Object.values(state.labels).filter(v=>v!==null).length;
  $('answerCount').textContent=`${count} of 12 answered`;$('answerProgress').value=count;
  $('completeBtn').disabled=!state.study||count!==12||state.saving||!state.imageOK;
  $('saveDraft').disabled=!state.study||state.saving;$('notes').disabled=!state.study;}
$('notes').oninput=markDirty;
async function save(status){if(!state.study||state.saving)return;state.saving=true;updateButtons();
  const uid=state.study.uid,payload={labels:{...state.labels},notes:$('notes').value,status,revision:state.revision};
  try{const r=await api(`/api/studies/${encodeURIComponent(uid)}/review`,{method:'PUT',body:JSON.stringify(payload)});
    if(state.study?.uid===uid){state.revision=r.revision;state.dirty=JSON.stringify(state.labels)!==JSON.stringify(payload.labels)||$('notes').value!==payload.notes;
      $('saveStatus').textContent=state.dirty?'Unsaved changes':status==='complete'?'Complete':'Saved';$('lastEditor').textContent=`Last saved by ${state.reviewer} · ${new Date(r.updated).toLocaleTimeString()}`;}
    await refresh();toast(status==='complete'?'Shared review completed.':'Shared draft saved.');
  }catch(e){toast(e.message);}finally{state.saving=false;updateButtons();}}
$('saveDraft').onclick=()=>save('draft');$('reviewForm').onsubmit=e=>{e.preventDefault();save('complete');};
$('nextStudy').onclick=()=>{const rows=filtered();const i=rows.findIndex(s=>s.uid===state.study?.uid);if(rows[i+1])openStudy(rows[i+1].uid);else toast('You’re at the end of this worklist.');};
window.addEventListener('beforeunload',e=>{if(state.dirty){e.preventDefault();e.returnValue='';}});
window.addEventListener('keydown',e=>{if((e.ctrlKey||e.metaKey)&&e.key==='s'){e.preventDefault();save('draft');return;}if(['INPUT','TEXTAREA','SELECT','BUTTON'].includes(e.target.tagName))return;if(e.key==='ArrowDown'){e.preventDefault();step(1);}if(e.key==='ArrowUp'){e.preventDefault();step(-1);}});
$('importBtn').onclick=async()=>{const b=$('importBtn');b.disabled=true;b.textContent='Scanning…';try{const r=await api('/api/import',{method:'POST'});await refresh();$('datasetFilter').value='real';renderQueue();toast(`Indexed ${r.studies} studies, ${r.series} series.${r.errors.length?' '+r.errors.length+' files failed to import; inspect the server import response before review.':''}`);}catch(e){toast(e.message);}finally{b.disabled=false;b.textContent='↻ Scan data folder';}};
$('exportBtn').onclick=()=>{$('exportDataset').value=$('datasetFilter').value;$('exportDialog').showModal();};
async function download(audit){try{const demo=$('exportDataset').value==='demo';const r=await fetch(`/api/export?demo=${demo}&audit=${audit}`);if(!r.ok)throw new Error('Export failed. Sign in and try again.');const blob=await r.blob(),url=URL.createObjectURL(blob);const a=document.createElement('a');a.href=url;a.download=audit?'review-status.csv':demo?'demo-labels.csv':'labels.csv';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}catch(e){toast(e.message);}}
$('downloadLabels').onclick=()=>download(false);$('downloadAudit').onclick=()=>download(true);
start().catch(()=>showLogin());
