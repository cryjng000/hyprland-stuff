#!/usr/bin/env node
const { spawn } = require('node:child_process');
const path = require('node:path');
const fs = require('node:fs');
const binary=path.join(__dirname,'node_modules/electron/dist/electron');
if(!fs.existsSync(binary)){console.error('Electron is missing. Run npm install, then node_modules/node/bin/node node_modules/electron/install.js');process.exit(1);}
const child=spawn(binary,[__dirname,'--ozone-platform=wayland',...process.argv.slice(2)],{stdio:'inherit',env:{...process.env,ELECTRON_RUN_AS_NODE:undefined}});
child.on('error',error=>{console.error(error.message);process.exitCode=1;});
child.on('exit',code=>{process.exitCode=code||0;});
for(const signal of ['SIGTERM','SIGINT'])process.on(signal,()=>child.kill(signal));
