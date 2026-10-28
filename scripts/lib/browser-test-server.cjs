'use strict';
const assert=require('node:assert/strict');
const fs=require('node:fs'),os=require('node:os'),path=require('node:path');
const {spawn}=require('node:child_process');

const root=path.resolve(__dirname,'../..');

// Each test owns a fresh data directory and never starts against the user's database.
function createTestServer(prefix,{python=process.env.CI_PYTHON,timeout=15000}={}){
 if(!/^[A-Za-z0-9_-]+-$/.test(prefix))throw Error('Invalid temporary directory prefix');
 const temporaryRoot=path.resolve(os.tmpdir());
 const directory=fs.mkdtempSync(path.join(temporaryRoot,prefix));
 const localPython=path.join(root,'.venv','Scripts','python.exe');
 python=python||(fs.existsSync(localPython)?localPython:'python');
 let server,stopped;

 async function start(){
  assert(!server,'Test server already started');
  server=spawn(python,['-B',path.join(root,'server.py'),'--port','0','--reminder-port','0','--data-dir',directory],{cwd:root,windowsHide:true});
  stopped=new Promise(resolve=>server.once('close',resolve));
  const url=await new Promise((resolve,reject)=>{
   let stdout='',stderr='';
   const timer=setTimeout(()=>finish(Error('server startup timeout: '+stderr)),timeout);
   const onData=chunk=>{
    stdout=(stdout+chunk.toString()).slice(-16384);
    const match=stdout.match(/ready: (http:\/\/127\.0\.0\.1:\d+)/);
    if(match)finish(null,match[1]);
   };
   const onError=error=>finish(error);
   const onExit=code=>finish(Error('server exited '+code+': '+stderr));
   function finish(error,value){
    clearTimeout(timer);
    server.stdout.off('data',onData);server.off('error',onError);server.off('close',onExit);
    if(error)reject(error);else resolve(value);
   }
   // Continue draining stderr after startup so a full pipe cannot block the child.
   server.stderr.on('data',chunk=>{stderr=(stderr+chunk.toString()).slice(-16384)});
   server.stdout.on('data',onData);server.once('error',onError);server.once('close',onExit);
  });
  const bootstrap=await fetch(url+'/api/bootstrap',{signal:AbortSignal.timeout(timeout)});
  assert(bootstrap.ok,'bootstrap failed: '+bootstrap.status);
  const {token}=await bootstrap.json();
  async function api(endpoint,body,method,accessToken=token){
   const response=await fetch(url+'/api/'+endpoint,{
    method:method||(body?'POST':'GET'),
    headers:{Authorization:'Bearer '+accessToken,'Content-Type':'application/json'},
    body:body?JSON.stringify(body):undefined
   });
   assert(response.ok,response.status+': '+await response.clone().text());
   return response.json();
  }
  return {url,token,api};
 }

 async function close(){
  if(server){
   if(server.exitCode===null&&server.signalCode===null)server.kill();
   await stopped;
  }
  // Only remove the exact temporary directory created by this fixture.
  assert.equal(path.dirname(directory),temporaryRoot);
  assert(path.basename(directory).startsWith(prefix));
  fs.rmSync(directory,{recursive:true,force:true,maxRetries:3,retryDelay:100});
 }

 return {root,directory,python,start,close};
}

module.exports={createTestServer};
