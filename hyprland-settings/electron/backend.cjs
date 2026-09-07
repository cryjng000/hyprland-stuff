const fs = require('node:fs/promises');
const path = require('node:path');
const os = require('node:os');
const crypto = require('node:crypto');
const { execFile, spawn } = require('node:child_process');
const { promisify } = require('node:util');
const jsonc = require('jsonc-parser');
const exec = promisify(execFile);
const home = os.homedir();
const conf = path.resolve(__dirname, '..');
const barDir = path.join(home, '.config/waybar');
const cache = path.join(home, '.cache/settings-panel/electron-thumbnails');
const extensions = /\.(png|jpe?g|webp|bmp|gif|mp4|mkv|webm|mov|avi)$/i;
const video = /\.(gif|mp4|mkv|webm|mov|avi)$/i;
const env = { ...process.env, LC_ALL: 'C', PATH: `${home}/.local/bin:${process.env.PATH}` };
async function read(file, fallback = '') { try { return await fs.readFile(file, 'utf8'); } catch { return fallback; } }
async function command(bin, args = [], timeout = 4000) {
  const { stdout } = await exec(bin, args, { env, timeout, maxBuffer: 4 * 1024 * 1024 });
  return stdout.trim();
}
async function optional(bin, args, fallback = '') { try { return await command(bin, args); } catch { return fallback; } }
function launch(bin, args = []) { const child = spawn(bin, args, { env, detached: true, stdio: 'ignore' }); child.on('error', () => {}); child.unref(); }
async function atomic(file, text) {
  const tmp = `${file}.${process.pid}.tmp`;
  await fs.writeFile(tmp, text, { mode: 0o600 });
  await fs.rename(tmp, file);
}
async function backup(file) {
  try { await fs.copyFile(file, `${file}.electron-settings.bak`, require('node:fs').constants.COPYFILE_EXCL); }
  catch (error) { if (error.code !== 'EEXIST') throw error; }
}
async function palette() {
  const css = await read(path.join(conf, 'colors.css'));
  return Object.fromEntries([...css.matchAll(/@define-color\s+(\w+)\s+(#[0-9a-f]{6})\s*;/gi)].map(m => [m[1], m[2]]));
}
let previousCpu = os.cpus();
let previousNetwork = { time: Date.now(), rx: 0, tx: 0 };
async function system() {
  const cpus = os.cpus();
  const cores = cpus.map((cpu, i) => {
    const prev = previousCpu[i] || cpu;
    const total = Object.values(cpu.times).reduce((a,b) => a+b,0) - Object.values(prev.times).reduce((a,b) => a+b,0);
    return total ? Math.max(0, Math.min(100, (1 - (cpu.times.idle-prev.times.idle)/total)*100)) : 0;
  });
  previousCpu = cpus;
  const [mem, net, disk, release] = await Promise.all([read('/proc/meminfo'), read('/proc/net/dev'), fs.statfs('/'), read('/etc/os-release')]);
  const available = +(mem.match(/MemAvailable:\s+(\d+)/)?.[1] || os.freemem()/1024)*1024;
  const total = os.totalmem();
  let rx=0, tx=0;
  for (const line of net.split('\n').slice(2)) {
    const [name, data] = line.split(':'); if (!data || name.trim()==='lo') continue;
    const fields = data.trim().split(/\s+/); rx+=+fields[0]; tx+=+fields[8];
  }
  const seconds = (Date.now()-previousNetwork.time)/1000 || 1;
  const network = { rx: previousNetwork.rx ? Math.max(0,(rx-previousNetwork.rx)/seconds) : 0, tx: previousNetwork.tx ? Math.max(0,(tx-previousNetwork.tx)/seconds) : 0 };
  previousNetwork={time:Date.now(),rx,tx};
  let temperature=null, gpu=null;
  try {
    for(const name of await fs.readdir('/sys/class/hwmon')) {
      const dir='/sys/class/hwmon/'+name;
      if (/k10temp|coretemp|zenpower/.test(await read(dir+'/name'))) { temperature=Number(await read(dir+'/temp1_input'))/1000 || null; break; }
    }
    for(const name of await fs.readdir('/sys/class/drm')) {
      if(!/^card\d+$/.test(name)) continue;
      const raw=await read(`/sys/class/drm/${name}/device/gpu_busy_percent`); if(raw.trim()) { gpu=Number(raw); break; }
    }
  } catch {}
  return { hostname:os.hostname(), model:cpus[0]?.model || 'Processor', threads:cpus.length, cores,
    cpu:cores.reduce((a,b)=>a+b,0)/(cores.length||1), memory:{used:total-available,total},
    disk:{used:(disk.blocks-disk.bavail)*disk.bsize,total:disk.blocks*disk.bsize},
    network, temperature, gpu, uptime:os.uptime(), release:os.release(),
    distro:release.match(/^PRETTY_NAME="?(.*?)"?$/m)?.[1] || 'Linux' };
}
function parseAudio(text) {
  const result={outputs:[],inputs:[],streams:[]}; let section='', current;
  for(const line of text.split('\n')) {
    if(line.trim()==='Video') break;
    const heading=line.match(/(?:├|└)─ (Sinks|Sources|Streams|Devices|Sink endpoints|Source endpoints):/);
    if(heading) {section=heading[1]; current=null; continue;}
    const body=line.replace(/^[\s│├─└]+/,'');
    const entry=body.match(/^(\*\s*)?(\d+)\.\s+(.+?)(?:\s+\[vol:\s*([\d.]+)([^\]]*)\])?\s*$/);
    if(!entry) continue;
    const [,def,id,name,vol,flags]=entry;
    if(section==='Streams') {
      if(/^(input_|output_|monitor_)/.test(name)) { if(current && name.startsWith('output_')) current.playback=true; }
      else {current={id,name,playback:false};result.streams.push(current);}
    } else if(section==='Sinks'||section==='Sources') {
      result[section==='Sinks'?'outputs':'inputs'].push({id,name,default:!!def,volume:vol===undefined?null:Math.round(+vol*100),muted:flags?.includes('MUTED')||false});
    }
  }
  result.streams=result.streams.filter(s=>s.playback&&!/^(cava|beatsync|speech-dispatcher)/i.test(s.name));
  return result;
}
async function audio() {
  const text=await command('wpctl',['status']); const state=parseAudio(text);
  state.streams=await Promise.all(state.streams.map(async s=> {
    const raw=await optional('wpctl',['get-volume',s.id]);
    return {...s,volume:Math.round(+(raw.match(/Volume:\s*([\d.]+)/)?.[1]||0)*100),muted:raw.includes('MUTED')};
  }));
  const [title,status]=await Promise.all([optional('playerctl',['-p','spotify,%any','metadata','--format','{{title}}\n{{artist}}']),optional('playerctl',['-p','spotify,%any','status'])]);
  state.media={title:title.split('\n')[0]||'',artist:title.split('\n')[1]||'',status}; return state;
}
function splitTerse(line) {
  const fields=['']; let escape=false;
  for(const ch of line) { if(escape){fields[fields.length-1]+=ch;escape=false;} else if(ch==='\\')escape=true; else if(ch===':')fields.push('');else fields[fields.length-1]+=ch; } return fields;
}
async function network() {
  const [radio,connections,wifi]=await Promise.all([
    command('nmcli',['radio','wifi']),command('nmcli',['-t','-f','NAME,TYPE,DEVICE,ACTIVE','connection','show']),
    command('nmcli',['-t','-f','IN-USE,SSID,SIGNAL,SECURITY','device','wifi','list','--rescan','no'])]);
  const seen=new Set();
  return {enabled:radio==='enabled',connections:connections.split('\n').filter(Boolean).map(line=>{const[name,type,device,active]=splitTerse(line);return{name,type,device,active:active==='yes'};}),
    wifi:wifi.split('\n').filter(Boolean).map(line=>{const[active,name,signal,security]=splitTerse(line);return {name,signal:+signal,security,active:active==='*'};}).filter(n=>n.name&&!seen.has(n.name)&&seen.add(n.name)).sort((a,b)=>b.signal-a.signal)};
}
const wallpaperPaths=new Map();
async function wallpapers() {
  const dirs=[path.join(home,'.config/wallpapers'),...(await read(path.join(conf,'wallpaper-dirs.txt'))).split('\n').filter(Boolean)];
  const current=(await read(path.join(home,'.cache/current_wallpaper'))).trim();
  const items=[]; const seen=new Set(); wallpaperPaths.clear();
  for(const dir of new Set(dirs)) {
    try {
      for(const item of await fs.readdir(dir,{withFileTypes:true})) {
        if(!item.isFile()||!extensions.test(item.name))continue;
        const file=path.join(dir,item.name); if(seen.has(file))continue; seen.add(file);
        const stat=await fs.stat(file); const id=crypto.createHash('sha256').update(file+'\0'+stat.mtimeMs).digest('hex');
        wallpaperPaths.set(id,file);
        items.push({id,name:item.name.replace(/\.[^.]+$/,'').replace(/[_-]+/g,' '),filename:item.name,video:video.test(item.name),current:file===current});
      }
    } catch {}
  }
  return {items:items.sort((a,b)=>a.name.localeCompare(b.name)),dirs:[...new Set(dirs)],current:path.basename(current)};
}
let thumbnailQueue=Promise.resolve(); const pendingThumbnails=new Map();
function thumbnail(id) {
  if(!wallpaperPaths.has(id))throw Error('Unknown wallpaper');
  if(pendingThumbnails.has(id))return pendingThumbnails.get(id);
  const task=thumbnailQueue.then(async()=>{
    const file=wallpaperPaths.get(id); if(!file)return null;
    const dest=path.join(cache,id+'.png'); await fs.mkdir(cache,{recursive:true});
    try {await fs.access(dest);} catch {
      try {
        if(video.test(file)) await command('ffmpeg',['-v','error','-y','-i',file,'-frames:v','1','-vf','scale=400:240:force_original_aspect_ratio=decrease',dest],15000);
        else await command('gdk-pixbuf-thumbnailer',['-s','400',file,dest],15000);
      } catch {return null;}
    }
    return 'data:image/png;base64,'+(await fs.readFile(dest)).toString('base64');
  });
  thumbnailQueue=task.catch(()=>{});pendingThumbnails.set(id,task);task.finally(()=>pendingThumbnails.delete(id)).catch(()=>{});return task;
}
let rethemeBusy=false;
async function applyWallpaper(id) {
  if(rethemeBusy)throw Error('A wallpaper is already being applied.');
  const file=wallpaperPaths.get(id); if(!file)throw Error('Wallpaper no longer available. Refresh the collection.');
  rethemeBusy=true; try{await command(path.join(home,'.local/bin/retheme'),[file],180000);return true;}finally{rethemeBusy=false;}
}
async function addDirectory(dir) {
  if(typeof dir!=='string'||!path.isAbsolute(dir))throw Error('Choose an absolute folder path.');
  if(!(await fs.stat(dir)).isDirectory())throw Error('That path is not a folder.');
  const file=path.join(conf,'wallpaper-dirs.txt'); const dirs=new Set((await read(file)).split('\n').filter(Boolean));dirs.add(dir);
  await atomic(file,[...dirs].join('\n')+'\n');return wallpapers();
}
function parseConfig(text) {
  const errors=[]; const data=jsonc.parse(text,errors,{allowTrailingComma:true});
  if(errors.length||!data||Array.isArray(data)||typeof data!=='object')throw Error('This editor needs a single valid Waybar JSONC object.');return data;
}
function editConfig(text, values) {
  parseConfig(text);
  for(const [key,value] of Object.entries(values))text=jsonc.applyEdits(text,jsonc.modify(text,[key],value,{formattingOptions:{insertSpaces:true,tabSize:2,eol:'\n'}}));
  parseConfig(text); return text;
}
const defaults={position:'top',layer:'bottom',height:36,spacing:4,'margin-top':3,'margin-bottom':0,'margin-left':8,'margin-right':8,exclusive:true,'fixed-center':true};
async function waybar() {
  const config=await fs.readFile(path.join(barDir,'config.jsonc'),'utf8'); const data=parseConfig(config);
  const css=await fs.readFile(path.join(barDir,'style.css'),'utf8');
  const font=+(css.match(/\/\* settings-electron:start \*\/[\s\S]*?font-size:\s*(\d+)%/)?.[1]||css.match(/font-size:\s*(\d+)%/)?.[1]||98);
  return {...defaults,...Object.fromEntries(Object.keys(defaults).filter(k=>k in data).map(k=>[k,data[k]])),font,
    modules:{left:data['modules-left']||[],center:data['modules-center']||[],right:data['modules-right']||[]},
    revision:crypto.createHash('sha256').update(config+css).digest('hex')};
}
function validateBar(values) {
  const limits={height:[24,80],spacing:[0,24],'margin-top':[0,48],'margin-bottom':[0,48],'margin-left':[0,80],'margin-right':[0,80]};
  const result={};
  for(const [key,value] of Object.entries(values)) {
    if(key in limits) { if(!Number.isInteger(value)||value<limits[key][0]||value>limits[key][1])throw Error('Invalid '+key); }
    else if(key==='position'){if(!['top','bottom'].includes(value))throw Error('Invalid position');}
    else if(key==='layer'){if(!['bottom','top','overlay'].includes(value))throw Error('Invalid layer');}
    else if(['exclusive','fixed-center'].includes(key)){if(typeof value!=='boolean')throw Error('Invalid toggle');}
    else throw Error('Unsupported Waybar option');result[key]=value;
  } return result;
}
async function saveWaybar({values,font,revision}) {
  values=validateBar(values);if(!Number.isInteger(font)||font<75||font>140)throw Error('Invalid font scale');
  const current=await waybar();if(current.revision!==revision)throw Error('Waybar changed outside Settings. Reload this page before saving.');
  const configFile=path.join(barDir,'config.jsonc'), cssFile=path.join(barDir,'style.css');
  const original=await fs.readFile(configFile,'utf8'), oldCss=await fs.readFile(cssFile,'utf8');
  const config=editConfig(original,values);
  const css=oldCss.replace(/\n?\/\* settings-electron:start \*\/[\s\S]*?\/\* settings-electron:end \*\//g,'')+
    `\n/* settings-electron:start */\n* { font-size: ${font}%; }\n/* settings-electron:end */\n`;
  await backup(configFile);await backup(cssFile);
  await atomic(cssFile,css);try{await atomic(configFile,config);}catch(error){await atomic(cssFile,oldCss);throw error;}
  await restartBar();return waybar();
}
async function restartBar(){await optional('pkill',['-x','waybar']);launch('waybar');return true;}
async function restoreBar(){
  const files=['config.jsonc','style.css'];
  const contents=await Promise.all(files.map(f=>fs.readFile(path.join(barDir,f)+'.electron-settings.bak','utf8')));
  parseConfig(contents[0]);for(let i=0;i<files.length;i++)await atomic(path.join(barDir,files[i]),contents[i]);
  await restartBar();return waybar();
}
async function audioAction({action,id,value}) {
  if(!/^(\d+|@DEFAULT_AUDIO_(SINK|SOURCE)@)$/.test(String(id)))throw Error('Invalid device');
  if(action==='volume'){if(!Number.isFinite(value)||value<0||value>150)throw Error('Invalid volume');await command('wpctl',['set-volume',String(id),(value/100).toFixed(2)]);}
  else if(action==='mute')await command('wpctl',['set-mute',String(id),'toggle']);
  else if(action==='default'&&/^\d+$/.test(String(id)))await command('wpctl',['set-default',String(id)]);
  else throw Error('Unknown audio action');return true;
}
async function networkAction({action,name,enabled}) {
  if(action==='radio'&&typeof enabled==='boolean')return command('nmcli',['radio','wifi',enabled?'on':'off']);
  if(action==='rescan')return command('nmcli',['device','wifi','rescan'],15000);
  if(typeof name!=='string'||!name.length||name.length>256)throw Error('Invalid connection');
  if(action==='connection'&&typeof enabled==='boolean')return command('nmcli',['connection',enabled?'up':'down','id',name],20000);
  throw Error('Unknown network action');
}
module.exports={palette,system,audio,network,wallpapers,thumbnail,applyWallpaper,addDirectory,waybar,saveWaybar,restoreBar,restartBar,audioAction,networkAction,parseAudio,splitTerse,editConfig,validateBar,
  media:async action=>{if(!['previous','play-pause','next'].includes(action))throw Error('Unknown media action');return command('playerctl',['-p','spotify,%any',action]);},
  toggleBar:()=>command('pkill',['-SIGUSR1','-x','waybar'])};
