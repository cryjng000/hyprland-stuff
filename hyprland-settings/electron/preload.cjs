const { contextBridge, ipcRenderer } = require('electron');
const allowed=new Set(['theme','system','audio','network','wallpapers','thumbnail','applyWallpaper','waybar','saveWaybar','restoreBar','restartBar','toggleBar','audioAction','networkAction','media','chooseDirectory','close']);
contextBridge.exposeInMainWorld('settings',{
  request:async(method,arg)=>{
    if(!allowed.has(method))throw Error('Unknown request');
    const response=await ipcRenderer.invoke('settings:request',method,arg);
    if(!response.ok)throw Error(response.error);return response.data;
  },
  onTheme:callback=>{const handler=(_event,theme)=>callback(theme);ipcRenderer.on('settings:theme',handler);return()=>ipcRenderer.removeListener('settings:theme',handler);}
});
