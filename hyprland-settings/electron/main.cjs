const { app, BrowserWindow, ipcMain, dialog, Menu } = require('electron');
const path = require('node:path');
const fs = require('node:fs');
const { pathToFileURL } = require('node:url');
const backend = require('./backend.cjs');
const qa = process.argv.includes('--qa');
const started = performance.now();
app.setName('settings-panel');
app.commandLine.appendSwitch('class','settings-panel');
if(qa) app.setPath('userData','/tmp/hypr-settings-electron-qa');
const ownLock=qa||app.requestSingleInstanceLock();
let win;
if(!ownLock)app.quit();
else {
  app.on('second-instance',()=>{if(win){win.show();if(win.isMinimized())win.restore();win.focus();}});
  app.whenReady().then(async()=>{
    Menu.setApplicationMenu(null);
    win = new BrowserWindow({width:1040,height:760,minWidth:320,minHeight:280,show:false,frame:false,
      transparent:true,backgroundColor:'#00000000',roundedCorners:true,title:'Settings',
      webPreferences:{preload:path.join(__dirname,'preload.cjs'),contextIsolation:true,nodeIntegration:false,sandbox:true,offscreen:qa}});
    const url=pathToFileURL(path.join(__dirname,'index.html')).href;
    win.webContents.setWindowOpenHandler(()=>({action:'deny'}));
    win.webContents.on('will-navigate',(event,target)=>{if(target!==url)event.preventDefault();});
    win.webContents.session.setPermissionRequestHandler((_wc,_permission,callback)=>callback(false));
    const methods={theme:backend.palette,system:backend.system,audio:backend.audio,network:backend.network,wallpapers:backend.wallpapers,
      thumbnail:backend.thumbnail,applyWallpaper:backend.applyWallpaper,waybar:backend.waybar,saveWaybar:backend.saveWaybar,
      restoreBar:backend.restoreBar,restartBar:backend.restartBar,toggleBar:backend.toggleBar,audioAction:backend.audioAction,
      networkAction:backend.networkAction,media:backend.media,
      chooseDirectory:async()=>{const result=await dialog.showOpenDialog(win,{properties:['openDirectory'],title:'Add wallpaper folder'});return result.canceled?null:backend.addDirectory(result.filePaths[0]);},
      close:()=>win.close()};
    ipcMain.handle('settings:request',async(event,method,arg)=>{
      if(event.sender!==win.webContents||event.senderFrame!==win.webContents.mainFrame||!Object.hasOwn(methods,method))return {ok:false,error:'Unknown request'};
      try{return {ok:true,data:await methods[method](arg)};}catch(error){return {ok:false,error:error.message.replace(/Command failed:.*\n?/,'').slice(0,300)};}
    });
    let timer;
    const watcher=fs.watch(path.resolve(__dirname,'..'),(_event,file)=>{if(file==='colors.css'){clearTimeout(timer);timer=setTimeout(async()=>{if(!win.isDestroyed())win.webContents.send('settings:theme',await backend.palette());},120);}});
    process.on('SIGUSR1',async()=>{if(!win.isDestroyed())win.webContents.send('settings:theme',await backend.palette());});
    win.on('closed',()=>{watcher.close();clearTimeout(timer);});
    win.once('ready-to-show',()=>{console.log(`Settings first frame: ${Math.round(performance.now()-started)} ms`);if(!qa)win.show();});
    await win.loadURL(url);
    if(qa)await require('./visual-check.cjs')(win,app);
    if(process.argv.includes('--native-check')) {
      setTimeout(async()=>{
        try {
          const {execFile}=require('node:child_process');
          const {promisify}=require('node:util');
          const {stdout}=await promisify(execFile)('hyprctl',['clients','-j']);
          console.log(JSON.stringify(JSON.parse(stdout).filter(client=>client.pid===process.pid),null,2));
          fs.writeFileSync('/tmp/settings-electron-native.png',(await win.webContents.capturePage()).toPNG());
        } finally {win.destroy();app.quit();}
      },1800);
    }
  }).catch(error=>{console.error(error);app.exit(1);});
  app.on('window-all-closed',()=>app.quit());
}
