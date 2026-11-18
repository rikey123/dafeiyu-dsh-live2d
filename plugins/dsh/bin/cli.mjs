#!/usr/bin/env node
/** Repeatable provisioning, also used by the authenticated first-run installer. */
import {readFile,writeFile,mkdir,access,rename,open,unlink} from 'node:fs/promises';
import {dirname,resolve,join,isAbsolute} from 'node:path';
import {fileURLToPath} from 'node:url';
import {createHash,randomUUID} from 'node:crypto';
import {spawn,execFile} from 'node:child_process';
import {resolveLayout} from '../src/layout.mjs';

const digest=bytes=>createHash('sha256').update(bytes).digest('hex');
const py=home=>join(home,'.venv',process.platform==='win32'?'Scripts/python.exe':'bin/python');
const voicePy=home=>join(home,'.venv-voice',process.platform==='win32'?'Scripts/python.exe':'bin/python');
const exists=async path=>access(path).then(()=>true,()=>false);
const requirementNames=['requirements.txt','requirements-speech.txt','requirements-lock.txt','requirements-voice-lock.txt'];
const commands=new Set(['install','setup','models','avatar','core','doctor','verify']);
const valueFlags=new Set(['home','uv','kind','archive','file','index-url','source','models','avatar-url','avatar-sha256','avatar-preset']);
const booleanFlags=new Set(['plan','offline','download','accept-live2d-license','accept-avatar-license','help','json']);

export function parseArgs(args) {
  if(!args.length || args[0]==='--help' || args[0]==='-h') return {help:true};
  const command=args[0]; if(!commands.has(command))throw Error(`Unknown command: ${command}`);
  const options={command};
  for(let i=1;i<args.length;i++){
    if(!args[i].startsWith('--'))throw Error(`Unexpected argument: ${args[i]}`);
    const key=args[i].slice(2);
    if(Object.hasOwn(options,key))throw Error(`Repeated argument: --${key}`);
    if(booleanFlags.has(key))options[key]=true;
    else if(valueFlags.has(key) && args[i+1] && !args[i+1].startsWith('--'))options[key]=args[++i];
    else throw Error(`Unknown or missing argument: --${key}`);
  }
  if(options.help)return options;
  if(!options.home && !process.env.DAFEIYU_HOME)throw Error('Choose an external writable directory with --home <path> (or DAFEIYU_HOME). No system-disk installation is performed implicitly.');
  options.home=resolve(options.home||process.env.DAFEIYU_HOME);
  if(command==='models' && !['sensevoice','speaker','streaming-asr','moss','index','gpt-sovits'].includes(options.kind))throw Error('models requires --kind sensevoice|speaker|streaming-asr|moss|index|gpt-sovits');
  if(command==='avatar' && !options.archive)throw Error('avatar requires --archive <your lawfully obtained character.zip>');
  if(command==='core' && !(Boolean(options.file) !== Boolean(options.download)))throw Error('core requires exactly one of --file <core.js> or --download');
  if(command==='core' && options.download && !options['accept-live2d-license'])throw Error('Read the Live2D terms and pass --accept-live2d-license before downloading Core');
  if(options.offline && (command==='models'||options.download))throw Error('Model/Core downloads are unavailable with --offline');
  if(options['index-url']){
    const url=new URL(options['index-url']);
    if(url.protocol!=='https:'||url.username||url.password||url.hash)throw Error('--index-url must be HTTPS without embedded credentials');
  }
  if(options.source&&!['official','china'].includes(options.source))throw Error('--source must be official or china');
  if(options['avatar-url']&&(!options['avatar-sha256']||!options['accept-avatar-license']))throw Error('Remote character import requires --avatar-sha256 and --accept-avatar-license');
  if(options['avatar-preset']&&(command!=='install'||!options['accept-avatar-license']))throw Error('--avatar-preset requires install and --accept-avatar-license');
  return options;
}

export function installationEnv(home, inherited=process.env) {
  const cache=join(home,'cache');
  return {...inherited,DAFEIYU_HOME:home,DAFEIYU_DATA_DIR:join(home,'data'),DAFEIYU_MODELS_DIR:join(home,'models'),
    DAFEIYU_RUNTIME_DIR:join(home,'.runtime'),DAFEIYU_CACHE_DIR:cache,
    UV_CACHE_DIR:join(cache,'uv'),UV_PYTHON_INSTALL_DIR:join(home,'runtimes/python'),PIP_CACHE_DIR:join(cache,'pip'),
    TEMP:join(cache,'tmp'),TMP:join(cache,'tmp'),TMPDIR:join(cache,'tmp'),XDG_CACHE_HOME:cache,
    HF_HOME:join(cache,'huggingface'),HF_HUB_CACHE:join(cache,'huggingface/hub'),HUGGINGFACE_HUB_CACHE:join(cache,'huggingface/hub'),
    MODELSCOPE_CACHE:join(cache,'modelscope'),TORCH_HOME:join(cache,'torch'),NLTK_DATA:join(cache,'nltk'),
    MPLCONFIGDIR:join(cache,'matplotlib'),NUMBA_CACHE_DIR:join(cache,'numba'),
    PYTHONUTF8:'1',PYTHONUNBUFFERED:'1',PYTHONDONTWRITEBYTECODE:'1',UV_LINK_MODE:'copy',UV_NO_PROGRESS:'1',
    // New installations must not reserve a GPU or download a TTS model implicitly.
    DAFEIYU_VOICE_MODE:inherited.DAFEIYU_VOICE_MODE||'api'};
}

export function setupPlan(options, layout) {
  const uv=options.uv||process.env.DAFEIYU_UV||'uv';
  const extra=options.offline?['--offline']:[];
  const index=options['index-url']?['--index-url',options['index-url']]:[];
  const home=layout.homeDir,root=layout.codeRoot;
  return [
    {exe:uv,args:['venv',join(home,'.venv'),'--python','3.12','--managed-python',...extra]},
    {exe:uv,args:['pip','install','--python',py(home),'--link-mode','copy',...extra,...index,
      '-r',join(root,'requirements.txt'),'-r',join(root,'requirements-speech.txt'),'-c',join(root,'requirements-lock.txt')]},
    {exe:uv,args:['venv',join(home,'.venv-voice'),'--python','3.12','--managed-python',...extra]},
    {exe:uv,args:['pip','install','--python',voicePy(home),'--link-mode','copy',...extra,...index,'-r',join(root,'requirements-voice-lock.txt')]},
    {exe:py(home),args:['-c','import fastapi, uvicorn, numpy, sherpa_onnx; print("Speech dependencies imported")']},
    {exe:voicePy(home),args:['-c','import fastapi, uvicorn, pipecat; print("Voice dependencies imported")']},
  ];
}

export async function run(step,env,cwd,{signal,onLine}={}) {
  signal?.throwIfAborted();
  await new Promise((accept,reject)=>{
    const child=spawn(step.exe,step.args,{cwd,env,stdio:onLine?['ignore','pipe','pipe']:'inherit',windowsHide:true,shell:false});
    let ended=false;
    const abort=()=>{
      if(ended||!child.pid)return;
      // Kill only the process tree created by this installation step. uv and
      // Python may own build helpers; never leave one changing an unlocked env.
      if(process.platform==='win32')execFile('taskkill.exe',['/PID',String(child.pid),'/T','/F'],{windowsHide:true},()=>{});
      else child.kill('SIGTERM');
    };
    signal?.addEventListener('abort',abort,{once:true});
    if(onLine)for(const stream of [child.stdout,child.stderr]){
      let pending='';stream.setEncoding('utf8');
      stream.on('data',chunk=>{pending+=chunk;const lines=pending.split(/[\r\n]+/u);pending=lines.pop().slice(-4096);for(const line of lines)onLine(line.slice(0,4096));});
      stream.once('end',()=>{if(pending)onLine(pending);});
    }
    child.once('spawn',()=>{if(signal?.aborted)abort();});
    const cleanup=()=>{ended=true;signal?.removeEventListener('abort',abort);};
    child.once('error',error=>{cleanup();reject(Error(`Cannot start installation command (${error.code}); check the selected uv/Python executable.`));});
    child.once('close',(code,reason)=>{cleanup();if(signal?.aborted)reject(signal.reason);else if(code===0)accept();else reject(Error(`Installation command failed (${reason||code}); see the installation log and retry.`));});
  });
}

async function atomicJson(path,value) {
  await mkdir(dirname(path),{recursive:true});const staging=`${path}.${randomUUID()}.tmp`;
  try{await writeFile(staging,JSON.stringify(value,null,2)+'\n',{mode:0o600});await rename(staging,path);}
  finally{await unlink(staging).catch(()=>{});}
}

export async function verifyPayload(layout) {
  if(!layout.packaged)return {ok:true,kind:'source-checkout'};
  const manifest=JSON.parse(await readFile(join(layout.codeRoot,'release-manifest.json'),'utf8'));
  if(manifest.schemaVersion!==1||!Array.isArray(manifest.files))throw Error('Unsupported release manifest');
  for(const [root,records] of [[layout.codeRoot,manifest.files],[layout.packageRoot,manifest.packageFiles||[]]]){
    const seen=new Set();
    for(const item of records){
      const path=resolve(root,item.path);
      if(!path.startsWith(root+ (process.platform==='win32'?'\\':'/'))||seen.has(path))throw Error('Payload manifest path escapes application or is duplicated');
      seen.add(path);
      const bytes=await readFile(path);
      if(bytes.length!==item.size||digest(bytes)!==item.sha256)throw Error(`Installed payload is incomplete or modified: ${item.path}`);
    }
  }
  return {ok:true,kind:'installed-package',version:manifest.version,files:manifest.files.length};
}

export async function doctor(layout) {
  const home=layout.homeDir;
  let marker;try{marker=JSON.parse(await readFile(join(home,'.runtime/installation.json'),'utf8'));}catch{}
  const version=JSON.parse(await readFile(join(layout.packageRoot,'package.json'),'utf8')).version;
  let dependenciesCurrent=marker?.version===version;
  for(const name of requirementNames){
    if(!marker?.requirements?.[name]||marker.requirements[name]!==digest(await readFile(join(layout.codeRoot,name))))dependenciesCurrent=false;
  }
  const checks={speechRuntime:await exists(py(home)),voiceRuntime:await exists(voicePy(home)),
    installationReady:marker?.schemaVersion===1&&marker.status==='ready',
    dependenciesCurrent,
    avatar:await exists(join(home,'public/models/deepseek/avatar.model3.json')),
    cubismCore:await exists(join(home,'public/cubism/live2dcubismcore.min.js')),
    vadModel:await exists(join(home,'public/vad/silero_vad_v5.onnx')),
    sensevoiceModel:await exists(join(home,'models/sensevoice/model.int8.onnx'))};
  return {homeDir:home,packaged:layout.packaged,checks,ready:checks.speechRuntime&&checks.voiceRuntime&&checks.installationReady&&checks.dependenciesCurrent,
    note:'Readiness checks files only. They do not prove microphone permission, GPU inference or a paid TTS/model connection.'};
}

export async function provision(options,layout,{runStep=run}={}) {
  const home=layout.homeDir,env=installationEnv(home);
  if(options.uv)env.DAFEIYU_UV=resolve(options.uv);
  const version=JSON.parse(await readFile(join(layout.packageRoot,'package.json'),'utf8')).version;
  await verifyPayload(layout);
  const plan=setupPlan(options,layout);
  if(options.plan)return {command:'setup',homeDir:home,steps:plan};
  // No writes until the user explicitly selected a home. Do not race a live
  // voice process or overwrite another installer in that home.
  await mkdir(join(home,'.runtime'),{recursive:true});
  const lockPath=join(home,'.runtime/setup.lock');let lock;
  try{lock=await open(lockPath,'wx',0o600);}catch{throw Error('Another setup owns this home (setup.lock exists). Finish it before retrying.');}
  try{
    for(const name of ['runner.json','runner-dsh.json'])if(await exists(join(home,'.runtime',name)))throw Error('Stop the existing voice service before updating this installation home.');
    await mkdir(join(home,'cache/tmp'),{recursive:true});
    const markerPath=join(home,'.runtime/installation.json');
    await atomicJson(markerPath,{schemaVersion:1,status:'installing',version});
    for(let i=0;i<plan.length;i++){
      // uv venv is deliberately not rerun over an existing environment: doing
      // so would discard installed packages and makes interrupted installs slow.
      if((i===0&&await exists(py(home)))||(i===2&&await exists(voicePy(home))))continue;
      await runStep(plan[i],env,layout.codeRoot);
    }
    const hashes={};for(const name of requirementNames)hashes[name]=digest(await readFile(join(layout.codeRoot,name)));
    // Keep this default separate from secrets; existing .env is never replaced.
    const envPath=join(home,'.env');
    try{await writeFile(envPath,'# Local speech settings; keep this file private.\nDAFEIYU_VOICE_MODE=api\n',{flag:'wx',mode:0o600});}catch(error){if(error.code!=='EEXIST')throw error;}
    await atomicJson(markerPath,{schemaVersion:1,status:'ready',version,pythonVersion:'3.12',
      completedAt:new Date().toISOString(),requirements:hashes,runtimes:{speech:py(home),voice:voicePy(home)}});
    return {ok:true,homeDir:home,message:'Dependencies ready. Import character/Core assets, prepare ASR models explicitly, then configure TTS in DSH. No inference was started.'};
  } finally{await lock.close();await unlink(lockPath);}
}

export async function perform(options,layout,dependencies={}) {
  if(options.command==='verify')return verifyPayload(layout);
  if(options.command==='doctor')return doctor(layout);
  if(options.command==='setup')return provision(options,layout,dependencies);
  if(options.command==='install'){
    const {install}=await import('../src/install.mjs');
    return install(options,layout,dependencies);
  }
  await verifyPayload(layout);
  const env=installationEnv(layout.homeDir);if(options.uv)env.DAFEIYU_UV=resolve(options.uv);
  let step;
  if(options.command==='models'){
    step=['moss','index'].includes(options.kind)
      ? {exe:py(layout.homeDir),args:[join(layout.codeRoot,'scripts/prepare_tts_models.py'),'--kind',options.kind]}
      : options.kind==='gpt-sovits'
        ? {exe:py(layout.homeDir),args:[join(layout.codeRoot,'scripts/prepare_gpt_sovits.py')]}
        : {exe:py(layout.homeDir),args:['-m','speech.prepare',options.kind]};
  }else if(options.command==='avatar'){
    step={exe:py(layout.homeDir),args:[join(layout.codeRoot,'scripts/import_avatar.py'),resolve(options.archive),'--output',join(layout.homeDir,'public/models/deepseek')]};
  }else if(options.command==='core'){
    const target=join(layout.homeDir,'public/cubism/live2dcubismcore.min.js');
    if(options.plan)return {command:'core',target,source:options.file?resolve(options.file):'https://cubism.live2d.com/sdk-web/cubismcore/live2dcubismcore.min.js'};
    let bytes;
    if(options.file)bytes=await readFile(resolve(options.file));
    else{
      if(options.offline)throw Error('Core download is unavailable offline');
      const signal=AbortSignal.any([AbortSignal.timeout(60000),...dependencies.signal?[dependencies.signal]:[]]);
      const response=await fetch('https://cubism.live2d.com/sdk-web/cubismcore/live2dcubismcore.min.js',{signal});
      if(!response.ok)throw Error(`Cubism Core download failed: HTTP ${response.status}`);
      const parts=[];let size=0;
      for await(const chunk of response.body){size+=chunk.length;if(size>8*1024*1024)throw Error('Cubism Core response exceeds its size limit');parts.push(chunk);}
      bytes=Buffer.concat(parts);
    }
    if(bytes.length<1000||bytes.length>8*1024*1024||!bytes.toString('utf8').includes('Live2DCubismCore'))throw Error('The supplied file is not the expected Cubism Core JavaScript runtime');
    await mkdir(dirname(target),{recursive:true});
    const staging=`${target}.${randomUUID()}.tmp`;
    try{await writeFile(staging,bytes);await rename(staging,target);}finally{await unlink(staging).catch(()=>{});}
    await atomicJson(join(layout.homeDir,'.runtime/cubism-core.json'),{sha256:digest(bytes),source:options.file?'local-import':'live2d-official',importedAt:new Date().toISOString()});
    return {ok:true,target,sha256:digest(bytes)};
  }
  if(options.plan)return {command:options.command,homeDir:layout.homeDir,steps:[step]};
  if(!(await doctor(layout)).ready)throw Error('Run dafeiyu setup --home <path> before preparing models or importing a character.');
  await (dependencies.runStep??run)(step,env,layout.codeRoot);return {ok:true,command:options.command,homeDir:layout.homeDir};
}

export async function main(args=process.argv.slice(2)) {
  const options=parseArgs(args);
  if(options.help){
    console.log('Dafeiyu DSH plugin — explicit installation, no automatic GPU use\n\n'+
      'dafeiyu setup --home <directory> [--uv <uv.exe>] [--offline] [--plan]\n'+
      'dafeiyu install --home <directory> [--source china|official] [--uv <uv.exe>] [--accept-live2d-license] [--avatar-preset deepseek-chan --accept-avatar-license | --archive <character.zip>] [--models speaker,streaming-asr,moss] [--plan]\n'+
      'dafeiyu models --home <directory> --kind sensevoice|speaker|streaming-asr|moss|index|gpt-sovits [--uv <uv.exe>] [--plan]\n'+
      'dafeiyu avatar --home <directory> --archive <character.zip> [--plan]\n'+
      'dafeiyu core --home <directory> --file <core.js>\n'+
      'dafeiyu core --home <directory> --download --accept-live2d-license\n'+
      'dafeiyu doctor|verify --home <directory>\n\n'+
      'Set the same DAFEIYU_HOME when launching DSH. Read docs/DSH_RELEASE.md.');return;
  }
  if(process.platform!=='win32' && options.command!=='verify' && options.command!=='doctor' && !options.plan)throw Error('This release supports Windows only. Other platforms have not been validated.');
  const layout=resolveLayout({homeDir:options.home});
  let lastStep;
  const cancellation=new AbortController(),stop=()=>cancellation.abort();
  if(options.command==='install'){process.on('SIGINT',stop);process.on('SIGTERM',stop);}
  try{
    const report=await perform(options,layout,{signal:cancellation.signal,onProgress:value=>{
      if(value.step!==lastStep){lastStep=value.step;console.error(`[${value.step}] ${value.message}`);}
    }});console.log(JSON.stringify(report,null,2));
    if(options.command==='doctor'&&!report.ready)process.exitCode=2;
  }finally{process.removeListener('SIGINT',stop);process.removeListener('SIGTERM',stop);}
}
if(process.argv[1]&&resolve(process.argv[1])===fileURLToPath(import.meta.url))main().catch(error=>{console.error(error.message);process.exitCode=1;});
