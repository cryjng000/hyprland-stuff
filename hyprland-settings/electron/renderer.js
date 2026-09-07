const $ = selector => document.querySelector(selector);
const api = (method, value) => window.settings.request(method, value);
const icons = {
  settings:'M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8ZM9.5 3h5l.6 2.4 2 .9 2.2-.7 2.5 4.3-1.6 1.7v2.3l1.6 1.7-2.5 4.3-2.2-.7-2 .9-.6 2.4h-5l-.6-2.4-2-.9-2.2.7-2.5-4.3 1.6-1.7v-2.3L2.2 9.9l2.5-4.3 2.2.7 2-.9Z',
  overview:'M4 3h6v8H3V4a1 1 0 0 1 1-1Zm10 0h6a1 1 0 0 1 1 1v4h-7ZM3 15h7v6H4a1 1 0 0 1-1-1Zm11-3h7v8a1 1 0 0 1-1 1h-6Z',
  appearance:'M4 5h16a1 1 0 0 1 1 1v12a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1Zm-1 11 5-5 4 4 4-6 5 7M7 8h.01',
  audio:'M4 9h4l5-4v14l-5-4H4Zm12-1a6 6 0 0 1 0 8m3-11a10 10 0 0 1 0 14',
  network:'M3 8a15 15 0 0 1 18 0M6 12a10 10 0 0 1 12 0m-9 4a5 5 0 0 1 6 0m-3 4h.01',
  waybar:'M4 4h16a1 1 0 0 1 1 1v14a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V5a1 1 0 0 1 1-1Zm-1 5h18M6 6.5h3m8 0h1',
  search:'m16 16 5 5M10.5 3a7.5 7.5 0 1 0 0 15 7.5 7.5 0 0 0 0-15',
  close:'m6 6 12 12M6 18 18 6', arrow:'m9 5 7 7-7 7',
  cpu:'M7 7h10v10H7Zm3 3h4v4h-4ZM8 3v4m4-4v4m4-4v4M8 17v4m4-4v4m4-4v4M3 8h4m-4 4h4m-4 4h4m10-8h4m-4 4h4m-4 4h4',
  memory:'M3 7h18v10H3Zm4 3v4m5-4v4m5-4v4M6 17v3m4-3v3m4-3v3m4-3v3',
  disk:'M5 4h14l3 12v4H2v-4Zm-3 12h20M6 18h.01m4 0h.01',
  temperature:'M9 15V5a3 3 0 0 1 6 0v10a5 5 0 1 1-6 0Zm3-8v10',
  mic:'M9 5a3 3 0 0 1 6 0v7a3 3 0 0 1-6 0Zm-3 6v1a6 6 0 0 0 12 0v-1m-6 7v4m-3 0h6',
  play:'m8 4 12 8-12 8Z', pause:'M8 5v14M16 5v14',
  previous:'M5 5v14m14-14L7 12l12 7Z', next:'M19 5v14M5 5l12 7-12 7Z',
  refresh:'M20 8a8 8 0 1 0 0 8m0-13v5h-5', folder:'M3 5h6l2 3h10v12H3Z',
  check:'m5 12 4 4L19 6', shuffle:'M3 6h3c5 0 7 12 12 12h3m-4-4 4 4-4 4M3 18h3c2 0 4-3 6-6s4-6 6-6h3m-4-4 4 4-4 4',
  monitor:'M3 4h18v13H3Zm9 13v4m-4 0h8', sun:'M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8Zm0-6v2m0 16v2M2 12h2m16 0h2M5 5l1 1m12 12 1 1M5 19l1-1M18 6l1-1',
  lock:'M5 10h14v11H5Zm3 0V6a4 4 0 0 1 8 0v4m-4 5v2',
};
const icon = (name, cls='') => `<svg class="icon ${cls}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.65" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="${icons[name]||icons.settings}"/></svg>`;
const esc = value => String(value??'').replace(/[&<>"']/g,ch=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
const bytes = n => n>=1024**3 ? `${(n/1024**3).toFixed(1)} GB` : n>=1024**2 ? `${(n/1024**2).toFixed(1)} MB` : `${Math.round(n/1024)} KB`;
const percent = (used,total) => Math.round(used/total*100);
const pages = [
  {id:'overview',name:'Overview',icon:'overview',description:'A little space for everything.',terms:'system cpu memory storage disk temperature uptime'},
  {id:'appearance',name:'Appearance',icon:'appearance',description:'Make yourself at home.',terms:'wallpaper theme color palette background'},
  {id:'audio',name:'Sound',icon:'audio',description:'Everything sounds better your way.',terms:'audio microphone volume mixer music devices'},
  {id:'network',name:'Network',icon:'network',description:'Stay connected.',terms:'wifi wi-fi internet connections'},
  {id:'waybar',name:'Menu bar',icon:'waybar',description:'The details, always within reach.',terms:'waybar layout position font spacing margins'},
];
let active='overview', generation=0, pollTimer, theme={}, stats, audioState, wallState, barState, dirty=false, applying=false;
const history=[];const thumbs=new Map();let toastTimer;
function toast(message,error=false) {
  const el=$('#toast');el.textContent=message;el.classList.toggle('error',error);el.hidden=false;
  clearTimeout(toastTimer);toastTimer=setTimeout(()=>{el.hidden=true;},error?7000:3500);
}
function setTheme(colors) {
  theme=colors; for(const [name,value] of Object.entries(colors))if(/^#[0-9a-f]{6}$/i.test(value))document.documentElement.style.setProperty('--'+name,value);
  const hex=colors.background||'#18191d';const rgb=[1,3,5].map(i=>parseInt(hex.slice(i,i+2),16));
  document.documentElement.dataset.mode=(rgb[0]*.2126+rgb[1]*.7152+rgb[2]*.0722)>140?'light':'dark';
  if(active==='appearance'&&wallState)renderPalette();
}
function title(page,action='') {return `<div class="page-heading"><div><h1>${page.name}</h1><p>${page.description}</p></div>${action}</div>`;}
const button=(label,id,name='',cls='')=>`<button id="${id}" class="button ${cls}">${name?icon(name):''}<span>${label}</span></button>`;
const group=(name,description,body)=>`<section class="settings-section"><div class="section-heading"><h2>${name}</h2>${description?`<p>${description}</p>`:''}</div><div class="group">${body}</div></section>`;
const row=(name,description,control,nameIcon='')=>`<div class="setting-row">${nameIcon?`<span class="row-icon">${icon(nameIcon)}</span>`:''}<div class="row-copy"><h3>${name}</h3>${description?`<p>${description}</p>`:''}</div><div class="row-control">${control}</div></div>`;
const toggle=(id,on,label)=>`<button id="${id}" class="switch" role="switch" aria-checked="${!!on}" aria-label="${esc(label)}"><span></span></button>`;
const range=(id,value,min=0,max=100,label='Volume')=>`<input type="range" id="${id}" value="${value}" min="${min}" max="${max}" style="--fill:${(value-min)/(max-min)*100}%" aria-label="${esc(label)}">`;
function ranges() {document.querySelectorAll('input[type=range]').forEach(el=>el.addEventListener('input',()=>{el.style.setProperty('--fill',`${(el.value-el.min)/(el.max-el.min)*100}%`);}));}
function bind(id,fn) {const el=document.getElementById(id);if(el)el.onclick=async()=>{try{await fn(el);}catch(error){toast(error.message,true);}};}
function loading(page){$('#page').innerHTML=title(page)+`<div class="loading"><span class="spinner"></span>Loading ${page.name.toLowerCase()}…</div>`;}
async function navigate(id) {
  if(dirty&&active==='waybar'&&id!==active){toast('Save or discard your menu bar changes first.');return;}
  active=id;const token=++generation;clearTimeout(pollTimer);
  document.querySelectorAll('[data-page]').forEach(el=>{el.classList.toggle('selected',el.dataset.page===id);el.setAttribute('aria-current',el.dataset.page===id?'page':'false');});
  const page=pages.find(p=>p.id===id);$('#breadcrumb').textContent=page.name;$('#viewport').scrollTop=0;loading(page);
  try {
    if(id==='overview') {stats=await api('system');if(token!==generation)return;renderOverview();schedulePoll();}
    if(id==='appearance'){wallState=await api('wallpapers');if(token!==generation)return;renderAppearance();}
    if(id==='audio'){audioState=await api('audio');if(token!==generation)return;renderAudio();schedulePoll();}
    if(id==='network'){const state=await api('network');if(token!==generation)return;renderNetwork(state);}
    if(id==='waybar'){barState=await api('waybar');if(token!==generation)return;dirty=false;renderBar();}
  } catch(error) {if(token===generation){$('#page').innerHTML=title(page)+`<div class="empty-state">${icon(page.icon)}<h2>${id==='audio'?'Sound service unavailable':id==='network'?'Network service unavailable':'Unable to load settings'}</h2><p>${esc(error.message)}</p>${button('Try again','retry','refresh')}</div>`;bind('retry',()=>navigate(id));}}
}
function schedulePoll(){const token=generation;pollTimer=setTimeout(async()=>{
  try {
    if(document.hidden){schedulePoll();return;}
    if(active==='overview'){const next=await api('system');if(token!==generation)return;stats=next;updateStats();}
    if(active==='audio'&&!document.querySelector('input:focus,select:focus')&&!document.querySelector('button:active')){const next=await api('audio');if(token!==generation)return;
      const structure=s=>JSON.stringify([s.outputs.map(x=>[x.id,x.default]),s.inputs.map(x=>[x.id,x.default]),s.streams.map(x=>x.id)]);
      if(structure(next)!==structure(audioState)){audioState=next;renderAudio();}else{audioState=next;updateAudio();}}
  }catch{}
  if(token===generation)schedulePoll();
},active==='overview'?1500:3000);}
function renderOverview(){
  const metric=(id,name,ico)=>`<article class="metric"><div class="metric-top"><span>${icon(ico)}${name}</span><span class="metric-status" id="${id}-status"></span></div><div class="metric-number" id="${id}-number">—</div><div class="meter"><span id="${id}-meter"></span></div><p id="${id}-note"></p></article>`;
  $('#page').innerHTML=title(pages[0])+`
    <section class="desktop-hero"><div class="desktop-symbol">${icon('monitor')}</div><div><div class="eyebrow">YOUR WORKSPACE</div><h2>${esc(stats.hostname)}</h2><p>${esc(stats.distro)} <span class="middot">·</span> Hyprland</p></div><span class="status-pill"><i class="live-dot"></i> System online</span></section>
    <div class="metrics-grid">${metric('cpu','Processor','cpu')}${metric('memory','Memory','memory')}${metric('disk','Storage','disk')}</div>
    <div class="overview-split">${group('Activity','A live view of your workspace.',`<div class="activity"><div class="activity-head"><div><span class="eyebrow">PROCESSOR LOAD</span><strong id="activity-value">—</strong></div><span class="muted">Last 60 samples</span></div><svg class="sparkline" viewBox="0 0 600 100" preserveAspectRatio="none" aria-label="Processor usage history"><defs><linearGradient id="graph-fill" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stop-color="var(--primary)" stop-opacity=".22"/><stop offset="100%" stop-color="var(--primary)" stop-opacity="0"/></linearGradient></defs><path id="graph-area" fill="url(#graph-fill)"/><path id="graph-line" fill="none" stroke="var(--primary)" stroke-width="2" vector-effect="non-scaling-stroke"/></svg><div class="core-grid" id="cores">${stats.cores.map((_,i)=>`<div title="Thread ${i+1}"><span>${i+1}</span><i><b></b></i></div>`).join('')}</div></div>`)}
    ${group('At a glance','The everyday essentials.',row('Network','Download / upload','<span id="network-rate">—</span>','network')+row('Temperature','CPU package','<span id="temperature">—</span>','temperature')+row('Graphics','GPU activity','<span id="gpu">—</span>','monitor')+row('Uptime','Since your last restart','<span id="uptime">—</span>','refresh'))}</div>
    <div class="quick-grid"><button class="quick-card" data-go="appearance"><span class="quick-icon">${icon('appearance')}</span><span><strong>A fresh perspective</strong><small>Wallpaper & colors</small></span>${icon('arrow')}</button><button class="quick-card" data-go="waybar"><span class="quick-icon">${icon('waybar')}</span><span><strong>All in the details</strong><small>Personalize your menu bar</small></span>${icon('arrow')}</button></div>
    <p class="hardware-note">${esc(stats.model)} · ${stats.threads} threads · Kernel ${esc(stats.release)}</p>`;
  document.querySelectorAll('[data-go]').forEach(el=>el.onclick=()=>navigate(el.dataset.go));updateStats();
}
function updateStats(){
  if(!$('#cpu-number'))return;
  history.push(stats.cpu);if(history.length>60)history.shift();
  const cpu=Math.round(stats.cpu),mem=percent(stats.memory.used,stats.memory.total),disk=percent(stats.disk.used,stats.disk.total);
  for(const [id,value,note] of [['cpu',cpu,`${stats.threads} threads available`],['memory',mem,`${bytes(stats.memory.used)} of ${bytes(stats.memory.total)}`],['disk',disk,`${bytes(stats.disk.total-stats.disk.used)} available`]]){
    $(`#${id}-number`).innerHTML=`${value}<small>%</small>`;$(`#${id}-meter`).style.width=value+'%';$(`#${id}-note`).textContent=note;
    $(`#${id}-status`).textContent=value>90?'High':value>70?'In use':'Comfortable';
    $(`#${id}-meter`).classList.toggle('warning',value>90);
  }
  $('#network-rate').textContent=`↓ ${bytes(stats.network.rx)}/s · ↑ ${bytes(stats.network.tx)}/s`;
  $('#temperature').textContent=stats.temperature?`${Math.round(stats.temperature)}°C`:'Unavailable';$('#gpu').textContent=stats.gpu===null?'Unavailable':`${stats.gpu}%`;
  const hours=Math.floor(stats.uptime/3600);$('#uptime').textContent=`${hours}h ${Math.floor(stats.uptime%3600/60)}m`;
  $('#activity-value').textContent=cpu+'%';
  const pts=history.map((v,i)=>`${i*600/Math.max(1,history.length-1)},${96-v*.90}`).join(' L');
  $('#graph-line').setAttribute('d','M'+pts);$('#graph-area').setAttribute('d',`M0,100 L${pts} L600,100 Z`);
  document.querySelectorAll('#cores b').forEach((el,i)=>el.style.width=stats.cores[i]+'%');
}
function renderPalette(){
  if(!$('#palette-swatches'))return;
  $('#palette-swatches').innerHTML=['primary','secondary','tertiary','surface_container','on_surface'].map(k=>`<span title="${k.replaceAll('_',' ')} · ${theme[k]||''}" style="background:${theme[k]||'#777'}"></span>`).join('');
}
const wallImg=item=>item?`<img data-wall="${item.id}" alt="${esc(item.name)}" class="${item.video?'video-preview':''}">`:'';
function renderAppearance(){
  const current=wallState.items.find(x=>x.current);
  $('#page').innerHTML=title(pages[1])+`
    <div class="appearance-hero"><div class="wallpaper-current">${wallImg(current)}<div class="wallpaper-caption"><span class="eyebrow">CURRENT WALLPAPER</span><strong>${esc(current?.name||wallState.current||'Choose your next backdrop')}</strong></div></div><div class="palette-card"><span class="palette-icon">${icon('sun')}</span><h2>Colors in harmony</h2><p>Your desktop palette follows your wallpaper, from the menu bar to this window.</p><div id="palette-swatches"></div><span class="tiny-note">Synced with your desktop</span></div></div>
    <section class="settings-section"><div class="library-heading"><div><h2>Your collection <span class="count">${wallState.items.length}</span></h2><p>Choose a backdrop. The rest falls into place.</p></div><div class="toolbar-actions">${button('Add folder','add-folder','folder')}${button('Shuffle','shuffle','shuffle')}</div></div><div class="library-toolbar"><label class="inline-search">${icon('search')}<input id="wall-search" placeholder="Search wallpapers" aria-label="Search wallpapers"></label><button id="rescan-walls" class="icon-button" title="Refresh collection" aria-label="Refresh collection">${icon('refresh')}</button></div><div id="wall-grid" class="wall-grid"></div><div id="wall-empty" class="empty-state" hidden><h3>No matching wallpapers</h3><p>Try another name or add a folder.</p></div></section>`;
  renderPalette();renderWallGrid('');
  $('#wall-search').oninput=e=>renderWallGrid(e.target.value);
  bind('add-folder',async()=>{const state=await api('chooseDirectory');if(state&&active==='appearance'){wallState=state;renderAppearance();}});
  bind('shuffle',()=>{const choices=wallState.items.filter(x=>!x.current);if(choices.length)return applyWall(choices[Math.floor(Math.random()*choices.length)].id);});
  bind('rescan-walls',()=>navigate('appearance'));observeThumbnails();
}
let observer;
function renderWallGrid(query){
  const items=wallState.items.filter(x=>x.name.toLowerCase().includes(query.toLowerCase()));
  $('#wall-grid').innerHTML=items.map(item=>`<button class="wall-tile ${item.current?'chosen':''}" data-apply-wall="${item.id}" title="${esc(item.filename)}" aria-label="Apply ${esc(item.name)}" aria-pressed="${item.current}" ${applying?'disabled':''}><div class="wall-image">${wallImg(item)}${item.video?`<span class="video-badge">${icon('play')} Live</span>`:''}${item.current?`<span class="wall-check">${icon('check')}</span>`:''}</div><span class="wall-name">${esc(item.name)}</span></button>`).join('');
  $('#wall-empty').hidden=items.length!==0;
  document.querySelectorAll('[data-apply-wall]').forEach(el=>el.onclick=()=>applyWall(el.dataset.applyWall));observeThumbnails();
}
function observeThumbnails(){
  observer?.disconnect();observer=new IntersectionObserver(entries=>entries.forEach(async entry=>{
    if(!entry.isIntersecting)return;const el=entry.target;observer.unobserve(el);
    try {let src=thumbs.get(el.dataset.wall);if(!src){src=await api('thumbnail',el.dataset.wall);if(src)thumbs.set(el.dataset.wall,src);}if(src){el.src=src;el.classList.add('loaded');}}catch{}
  }),{root:$('#viewport'),rootMargin:'150px'});
  document.querySelectorAll('img[data-wall]:not([src])').forEach(el=>observer.observe(el));
}
async function applyWall(id){
  if(applying)return;applying=true;toast('Applying wallpaper and matching colors…');
  document.querySelectorAll('[data-apply-wall],#shuffle').forEach(el=>el.disabled=true);
  try {await api('applyWallpaper',id);wallState=await api('wallpapers');setTheme(await api('theme'));toast('Your new wallpaper and colors are ready.');}
  catch(error){toast(error.message,true);}
  finally{applying=false;if(active==='appearance')renderAppearance();}
}
function deviceCard(kind,name,ico){
  const devices=audioState[kind],selected=devices.find(d=>d.default);
  return `<section class="device-card"><div class="device-heading"><span class="device-icon">${icon(ico)}</span><div><h2>${name}</h2><p>${kind==='outputs'?'Where your sound plays':'Be heard, on your terms'}</p></div></div><label class="field-label" for="${kind}-device">${name} device</label><select id="${kind}-device" ${!devices.length?'disabled':''}>${!selected?'<option value="">Choose a device</option>':''}${devices.map(d=>`<option value="${d.id}" ${d.default?'selected':''}>${esc(d.name)}</option>`).join('')}</select><div class="volume-label"><label for="${kind}-volume">${kind==='outputs'?'Volume':'Input level'}</label><output id="${kind}-value">${selected?.volume??0}%</output></div>${range(kind+'-volume',selected?.volume||0,0,150,name+' volume')}<div class="volume-footer"><span>0%</span><span>100%</span><span>150%</span></div><div class="device-footer"><button class="button mute ${selected?.muted?'is-muted':''}" id="${kind}-mute" aria-pressed="${!!selected?.muted}" ${!selected?'disabled':''}>${icon(ico)}<span>${selected?.muted?'Unmute':'Mute '+name.toLowerCase()}</span></button><span class="tiny-note">${kind==='outputs'?'Above 100% may distort':'Mute for privacy'}</span></div></section>`;
}
function renderAudio(){
  $('#page').innerHTML=title(pages[2],button('Refresh','audio-refresh','refresh','subtle'))+`
    <div class="device-grid">${deviceCard('outputs','Output','audio')}${deviceCard('inputs','Microphone','mic')}</div>
    ${group('Application volume','Fine-tune the apps you’re listening to.',audioState.streams.length?audioState.streams.map(s=>`<div class="mixer-row"><span class="app-icon">${icon('audio')}</span><div class="mixer-name"><strong>${esc(s.name)}</strong><small>Playback</small></div><div class="mixer-level">${range('stream-'+s.id,s.volume,0,150,s.name+' volume')}<output id="stream-value-${s.id}">${s.volume}%</output></div><button id="stream-mute-${s.id}" class="icon-button mute ${s.muted?'is-muted':''}" aria-label="${s.muted?'Unmute':'Mute'} ${esc(s.name)}" aria-pressed="${s.muted}">${icon('audio')}</button></div>`).join(''):`<div class="inline-empty">${icon('audio')}<div><h3>Nothing playing yet</h3><p>Open a music player, video or call to adjust its volume here.</p></div></div>`)}
    <section class="now-playing"><div class="album-placeholder">${icon('audio')}</div><div class="track"><span class="eyebrow">NOW PLAYING</span><strong id="track-title">${esc(audioState.media.title||'A moment of quiet')}</strong><span id="track-artist">${esc(audioState.media.artist||'Your music will appear here')}</span></div><div class="transport"><button id="media-previous" class="icon-button" aria-label="Previous track">${icon('previous')}</button><button id="media-play" class="play-button" aria-label="Play or pause">${icon(audioState.media.status==='Playing'?'pause':'play')}</button><button id="media-next" class="icon-button" aria-label="Next track">${icon('next')}</button></div></section>`;
  ranges();bind('audio-refresh',()=>navigate('audio'));
  for(const kind of ['outputs','inputs']){
    const target=kind==='outputs'?'@DEFAULT_AUDIO_SINK@':'@DEFAULT_AUDIO_SOURCE@';
    $(`#${kind}-device`).onchange=async e=>{if(!e.target.value)return;await doAudio({action:'default',id:e.target.value});if(active==='audio'){audioState=await api('audio');renderAudio();}};
    volumeHandler(`${kind}-volume`,`${kind}-value`,target);
    bind(`${kind}-mute`,()=>doAudio({action:'mute',id:target},true));
  }
  for(const s of audioState.streams){volumeHandler('stream-'+s.id,'stream-value-'+s.id,s.id);bind('stream-mute-'+s.id,()=>doAudio({action:'mute',id:s.id},true));}
  for(const[action,id]of[['previous','previous'],['play-pause','play'],['next','next']])bind('media-'+id,async()=>{await api('media',action);audioState=await api('audio');updateAudio();});
}
const volumeTimers=new Map();
function volumeHandler(id,output,target){
  const el=document.getElementById(id);
  el.oninput=()=>{document.getElementById(output).textContent=el.value+'%';clearTimeout(volumeTimers.get(target));volumeTimers.set(target,setTimeout(()=>doAudio({action:'volume',id:target,value:+el.value}),90));};
}
async function doAudio(arg,refresh=false){try{await api('audioAction',arg);if(refresh){audioState=await api('audio');if(active==='audio')updateAudio();}}catch(error){toast(error.message,true);}}
function updateAudio(){
  for(const kind of ['outputs','inputs']){
    const d=audioState[kind].find(d=>d.default);if(!d)continue;
    const slider=$(`#${kind}-volume`);if(!slider)return;slider.value=d.volume;slider.style.setProperty('--fill',d.volume/150*100+'%');$(`#${kind}-value`).textContent=d.volume+'%';
    const mute=$(`#${kind}-mute`);mute.classList.toggle('is-muted',d.muted);mute.setAttribute('aria-pressed',d.muted);mute.querySelector('span').textContent=d.muted?'Unmute':'Mute '+(kind==='outputs'?'output':'microphone');
  }
  for(const s of audioState.streams){const el=$('#stream-'+s.id);if(!el)continue;el.value=s.volume;el.style.setProperty('--fill',s.volume/150*100+'%');$('#stream-value-'+s.id).textContent=s.volume+'%';$('#stream-mute-'+s.id).classList.toggle('is-muted',s.muted);}
  $('#track-title').textContent=audioState.media.title||'A moment of quiet';$('#track-artist').textContent=audioState.media.artist||'Your music will appear here';$('#media-play').innerHTML=icon(audioState.media.status==='Playing'?'pause':'play');
}
function renderNetwork(state){
  $('#page').innerHTML=title(pages[3],button('Refresh','network-refresh','refresh','subtle'))+
    group('Wireless',null,row('Wi-Fi','Discover and connect to nearby networks',toggle('wifi-toggle',state.enabled,'Wi-Fi'),'network'))+
    group('Your connections','Saved networks, ready when you are.',state.connections.length?state.connections.map((c,i)=>row(esc(c.name),c.active?`Connected${c.device?' · '+esc(c.device):''}`:'Not connected',toggle('connection-'+i,c.active,c.name),c.type.includes('wireless')?'network':'monitor')).join(''):'<div class="inline-empty"><p>No saved connections yet.</p></div>')+
    group('Nearby networks','Connect using an existing saved profile.',state.wifi.length?state.wifi.map((n,i)=>row(esc(n.name),`${n.signal}% signal · ${esc(n.security||'Open network')}`,n.active?'<span class="status-pill">Connected</span>':button('Connect','wifi-'+i,'','small'),n.security?'lock':'network')).join(''):'<div class="inline-empty"><p>No nearby networks. Turn on Wi-Fi or refresh.</p></div>');
  const change=async arg=>{await api('networkAction',arg);await navigate('network');};
  bind('wifi-toggle',()=>change({action:'radio',enabled:!state.enabled}));
  state.connections.forEach((c,i)=>bind('connection-'+i,()=>change({action:'connection',name:c.name,enabled:!c.active})));
  state.wifi.forEach((n,i)=>bind('wifi-'+i,async()=>{const known=state.connections.find(c=>c.name===n.name);if(!known){toast('Add this network in your system network manager first; it needs a saved connection.',true);return;}await change({action:'connection',name:known.name,enabled:true});}));
  bind('network-refresh',async()=>{await api('networkAction',{action:'rescan'});await navigate('network');});
}
const barLabels={height:['Height','The height of your menu bar',24,80],spacing:['Item spacing','Room between your modules',0,24],'margin-top':['Top margin','Space above the bar',0,48],'margin-bottom':['Bottom margin','Space below the bar',0,48],'margin-left':['Left margin','Inset from the left edge',0,80],'margin-right':['Right margin','Inset from the right edge',0,80],font:['Text size','Keep your current font, change its scale',75,140]};
function barRange(key){const[label,desc,min,max]=barLabels[key];return row(label,desc,`<div class="range-control">${range('bar-'+key,barState[key],min,max,label)}<output id="bar-value-${key}">${barState[key]}${key==='font'?'%':' px'}</output></div>`);}
function select(id,options,value){return `<select id="${id}">${options.map(([v,label])=>`<option value="${v}" ${v===value?'selected':''}>${label}</option>`).join('')}</select>`;}
function renderBar(){
  const modules=Object.values(barState.modules).flat().length;
  $('#page').innerHTML=title(pages[4])+`
    <section class="bar-preview-card"><div class="preview-header"><span class="eyebrow">YOUR MENU BAR</span><span>${modules} configured items</span></div><div class="mini-desktop" id="mini-desktop"><div class="mini-bar" id="mini-bar"><span>09:41</span><span class="mini-workspaces"><i></i><i></i><i></i></span><span>${icon('network')}${icon('audio')} 100%</span></div><div class="mini-window"><div></div><span></span><span></span></div></div><p>Layout preview <span>·</span> Your existing modules and colors are preserved</p></section>
    <div class="bar-settings-grid">
    ${group('Placement','Find its place on your desktop.',row('Position','Choose a screen edge',`<div class="segmented"><button id="position-top" class="${barState.position==='top'?'active':''}">Top</button><button id="position-bottom" class="${barState.position==='bottom'?'active':''}">Bottom</button></div>`)+row('Window layer','How the bar sits with your windows',select('bar-layer',[['bottom','Behind windows'],['top','Above windows'],['overlay','Overlay']],barState.layer))+row('Reserve space','Keep tiled windows clear of the bar',toggle('bar-exclusive',barState.exclusive,'Reserve space'))+row('Centered items','Keep center modules on the screen center',toggle('bar-fixed-center',barState['fixed-center'],'Centered items')))}
    ${group('Size & rhythm','A comfortable fit for your workspace.',barRange('height')+barRange('spacing')+barRange('font'))}
    </div>
    ${group('Breathing room','Fine-tune the space around the bar.',`<div class="margin-grid">${['margin-top','margin-bottom','margin-left','margin-right'].map(barRange).join('')}</div>`)}
    <div class="bar-utilities"><span class="tiny-note">Changes apply when you save.</span><div>${button('Restart','restart-bar','refresh','subtle')}${button('Hide / show','toggle-bar','waybar','subtle')}${button('Restore original','restore-bar','','subtle')}</div></div>
    <div class="save-tray" id="save-tray" hidden><div><strong>Make it yours</strong><span>You have unsaved changes</span></div><div>${button('Discard','discard-bar','','subtle')}${button('Save changes','save-bar','check','primary')}</div></div>`;
  ranges();previewBar();
  const changed=()=>{dirty=true;$('#save-tray').hidden=false;previewBar();};
  for(const key of Object.keys(barLabels)){$('#bar-'+key).oninput=e=>{barState[key]=+e.target.value;$('#bar-value-'+key).textContent=e.target.value+(key==='font'?'%':' px');changed();};}
  for(const pos of ['top','bottom'])bind('position-'+pos,()=>{barState.position=pos;document.querySelectorAll('.segmented button').forEach(el=>el.classList.toggle('active',el.id==='position-'+pos));changed();});
  $('#bar-layer').onchange=e=>{barState.layer=e.target.value;changed();};
  for(const key of ['exclusive','fixed-center'])bind('bar-'+key,el=>{barState[key]=!barState[key];el.setAttribute('aria-checked',barState[key]);changed();});
  bind('discard-bar',()=>{dirty=false;return navigate('waybar');});
  bind('save-bar',async el=>{el.disabled=true;try{const values=Object.fromEntries(['position','layer','height','spacing','margin-top','margin-bottom','margin-left','margin-right','exclusive','fixed-center'].map(k=>[k,barState[k]]));barState=await api('saveWaybar',{values,font:barState.font,revision:barState.revision});dirty=false;renderBar();toast('Menu bar updated.');}finally{el.disabled=false;}});
  bind('restart-bar',async()=>{await api('restartBar');toast('Menu bar restarted.');});bind('toggle-bar',()=>api('toggleBar'));
  bind('restore-bar',async()=>{barState=await api('restoreBar');dirty=false;renderBar();toast('Original menu bar restored.');});
}
function previewBar(){
  const el=$('#mini-bar');if(!el)return;
  el.style.top=barState.position==='top'?`${8+barState['margin-top']/2}px`:'auto';
  el.style.bottom=barState.position==='bottom'?`${8+barState['margin-bottom']/2}px`:'auto';
  el.style.left=(8+barState['margin-left']/2)+'px';el.style.right=(8+barState['margin-right']/2)+'px';
  el.style.height=(20+barState.height/3)+'px';el.style.fontSize=(barState.font/11)+'px';el.style.gap=(barState.spacing+4)+'px';
}
document.querySelectorAll('[data-icon]').forEach(el=>el.innerHTML=icon(el.dataset.icon));
$('#navigation').innerHTML=pages.map(page=>`<button data-page="${page.id}" title="${page.name}" aria-label="${page.name}"><span class="nav-icon">${icon(page.icon)}</span><span class="nav-label">${page.name}</span>${icon('arrow','nav-arrow')}</button>`).join('');
document.querySelectorAll('[data-page]').forEach(el=>el.onclick=()=>navigate(el.dataset.page));
$('#search').oninput=e=>{const q=e.target.value.toLowerCase();document.querySelectorAll('[data-page]').forEach(el=>{const p=pages.find(p=>p.id===el.dataset.page);el.hidden=!`${p.name} ${p.terms}`.toLowerCase().includes(q);});};
$('#search').onkeydown=e=>{if(e.key==='Enter')document.querySelector('[data-page]:not([hidden])')?.click();};
bind('close',()=>{if(dirty){toast('Save or discard your changes before closing.');return;}return api('close');});
document.addEventListener('keydown',e=>{if(e.key==='Escape'){if(dirty)toast('Save or discard your changes before closing.');else api('close');}if((e.ctrlKey||e.metaKey)&&e.key==='k'){e.preventDefault();$('#search').focus();}});
window.settings.onTheme(setTheme);
api('theme').then(setTheme).catch(()=>{});
navigate('overview');
