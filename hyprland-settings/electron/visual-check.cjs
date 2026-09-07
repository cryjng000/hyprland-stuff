const fs=require('node:fs/promises');
const delay=ms=>new Promise(resolve=>setTimeout(resolve,ms));
module.exports=async(win,app)=>{
  const out='/tmp/settings-electron-qa';await fs.mkdir(out,{recursive:true});
  const errors=[];win.webContents.on('console-message',(_event,...args)=>{if(args[0]>=3)errors.push(args[1]);});
  const report=[];
  for(const [width,height] of [[1040,800],[720,800],[480,650],[360,640],[960,480]]){
    win.setContentSize(width,height);await delay(100);
    for(const page of ['overview','appearance','audio','network','waybar']){
      await win.webContents.executeJavaScript(`navigate(${JSON.stringify(page)})`);
      await delay(page==='appearance'?1200:100);
      const layout=await win.webContents.executeJavaScript(`(()=>{
        const viewport=document.querySelector('#viewport'),root=document.documentElement;
        const escapes=[...document.querySelectorAll('#page button,#page select,#page input,#page h1,#page h2,#page p,#page .row-control')].filter(el=>{
          if(!el.getClientRects().length)return false;
          const r=el.getBoundingClientRect(),v=viewport.getBoundingClientRect();return r.left<v.left-1||r.right>v.right+1;
        }).map(el=>el.id||el.className||el.tagName);
        return {width:innerWidth,height:innerHeight,bodyOverflow:root.scrollWidth>innerWidth,
          horizontalOverflow:viewport.scrollWidth>viewport.clientWidth,escapes,heading:document.querySelector('h1')?.textContent,
          error:!!document.querySelector('#retry'),nestedScrollers:[...document.querySelectorAll('#page *')].filter(el=>el.scrollHeight>el.clientHeight+2&&['auto','scroll'].includes(getComputedStyle(el).overflowY)).length};
      })()`);
      report.push({page,...layout});
      const image=await win.webContents.capturePage();await fs.writeFile(`${out}/${page}-${width}x${height}.png`,image.toPNG());
    }
  }
  await win.webContents.executeJavaScript(`dirty=false;setTheme({background:'#fbf8ff',surface:'#fbf8ff',surface_container:'#f0edf5',surface_container_low:'#f5f2fa',surface_container_high:'#eae7ef',surface_container_highest:'#e4e1e9',primary:'#535b92',primary_container:'#dfe0ff',on_primary:'#ffffff',on_surface:'#1b1b21',on_surface_variant:'#45464f',tertiary:'#75546d'});navigate('overview')`);
  win.setContentSize(1040,800);await delay(200);await fs.writeFile(`${out}/overview-light.png`,(await win.webContents.capturePage()).toPNG());
  await fs.writeFile(`${out}/report.json`,JSON.stringify({report,errors},null,2));
  const bad=report.filter(r=>r.bodyOverflow||r.horizontalOverflow||r.escapes.length||r.error||r.nestedScrollers);
  console.log(JSON.stringify({screenshots:out,cases:report.length,failures:bad,errors},null,2));
  win.destroy();app.exit(bad.length||errors.length?1:0);
};
