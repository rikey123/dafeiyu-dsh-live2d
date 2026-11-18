/** First-run provisioning, not a second application runtime or agent harness. */
import {mkdir,writeFile,rename,unlink,open,access,appendFile} from 'node:fs/promises';
import {resolve,join,relative,isAbsolute,dirname} from 'node:path';
import {randomUUID} from 'node:crypto';
import {DEFAULT_AVATAR} from './avatar-presets.mjs';
import {provision,perform,doctor,verifyPayload,run} from '../bin/cli.mjs';

const exists=path=>access(path).then(()=>true,()=>false);
const optionalModels=new Set(['speaker','streaming-asr','moss','index','gpt-sovits']);
const within=(root,target)=>{const r=relative(root,target);return !r||(!isAbsolute(r)&&r!=='..'&&!r.startsWith('../')&&!r.startsWith('..\\'));};
const fail=(code,message)=>Object.assign(Error(message),{code});

export function installationOptions(value={},layout){
  const allowed=new Set(['homeDir','source','acceptCoreLicense','avatarArchive','avatarUrl','avatarSha256','acceptAvatarLicense','avatarPreset','models']);
  if(!value||typeof value!=='object'||Array.isArray(value)||Object.keys(value).some(key=>!allowed.has(key)))throw fail('invalid_options','安装选项无效。');
  const home=value.homeDir??layout.homeDir;
  if(typeof home!=='string'||!isAbsolute(home)||/[\u0000-\u001f]/u.test(home)||home.length>500)throw fail('invalid_home','请选择有效的绝对安装路径，例如 E:/DafeiyuCompanion。');
  const homeDir=resolve(home);
  if(within(layout.packageRoot,homeDir)||homeDir===dirname(homeDir))throw fail('invalid_home','安装目录必须在插件目录之外，且不能是磁盘根目录。');
  const source=value.source??'china';
  if(!['official','china'].includes(source))throw fail('invalid_source','请选择官方源或国内镜像。');
  for(const key of ['acceptCoreLicense','acceptAvatarLicense'])if(value[key]!==undefined&&typeof value[key]!=='boolean')throw fail('invalid_options','授权选项必须为布尔值。');
  const models=value.models??[];
  if(!Array.isArray(models)||models.length>5||models.some(kind=>!optionalModels.has(kind))||new Set(models).size!==models.length)throw fail('invalid_models','可选模型列表无效。');
  for(const key of ['avatarArchive','avatarUrl','avatarSha256'])if(value[key]!==undefined&&typeof value[key]!=='string')throw fail('invalid_avatar','角色资源选项必须是文字。');
  const avatarArchive=value.avatarArchive?.trim()||undefined,avatarUrl=value.avatarUrl?.trim()||undefined;
  if(avatarArchive&&(typeof avatarArchive!=='string'||!isAbsolute(avatarArchive)||/[\u0000-\u001f]/u.test(avatarArchive)))throw fail('invalid_avatar','角色文件必须为本机绝对路径。');
  if(avatarArchive&&avatarUrl)throw fail('invalid_avatar','角色文件和远端下载只能选择一种。');
  const avatarPreset=value.avatarPreset;
  if(avatarPreset!==undefined){
    if(avatarPreset!==DEFAULT_AVATAR.id)throw fail('invalid_avatar','预设角色无效。');
    if(avatarArchive||avatarUrl||value.avatarSha256)throw fail('invalid_avatar','自动角色与手动导入只能选择一种。');
    if(value.acceptAvatarLicense!==true)throw fail('avatar_authorization','请先阅读角色使用须知，并确认自动下载。');
  }
  if(avatarUrl){
    let url;try{url=new URL(avatarUrl);}catch{throw fail('invalid_avatar','角色下载地址无效。');}
    if(url.protocol!=='https:'||url.username||url.password||url.hash||url.search||!/^\w[\w.-]*$/u.test(url.hostname))throw fail('invalid_avatar','角色下载请使用不含凭证、查询参数的 HTTPS 地址。');
    if(value.acceptAvatarLicense!==true||!/^[a-f0-9]{64}$/iu.test(value.avatarSha256??''))throw fail('avatar_authorization','请确认角色下载授权，并提供发布者公布的 SHA-256。');
  }
  return {homeDir,source,models,acceptCoreLicense:value.acceptCoreLicense===true,avatarArchive,avatarUrl,avatarPreset,
    avatarSha256:value.avatarSha256?.toLowerCase(),acceptAvatarLicense:value.acceptAvatarLicense===true};
}

async function atomicJson(file,value){
  await mkdir(dirname(file),{recursive:true});const temporary=`${file}.${randomUUID()}.tmp`;
  try{await writeFile(temporary,JSON.stringify(value,null,2)+'\n',{mode:0o600});await rename(temporary,file);}finally{await unlink(temporary).catch(()=>{});}
}

export async function install(options,layout,dependencies={}){
  const selected=installationOptions({homeDir:layout.homeDir,source:options.source,
    acceptCoreLicense:options['accept-live2d-license'],avatarArchive:options.archive,
    avatarUrl:options['avatar-url'],avatarSha256:options['avatar-sha256'],acceptAvatarLicense:options['accept-avatar-license'],avatarPreset:options['avatar-preset'],
    models:typeof options.models==='string'?options.models.split(',').filter(Boolean):options.models},layout);
  const {signal,onProgress=()=>{}}=dependencies;
  const home=selected.homeDir;
  const preset=selected.avatarPreset?DEFAULT_AVATAR:undefined;
  const jobs=[{step:'uv',message:'准备下载管理器'},
    {step:'dependencies',message:'安装独立 Python 与语音依赖'},
    {step:'sensevoice',message:'下载语音识别与人声检测模型'},
    ...selected.models.map(kind=>({step:kind,message:`准备可选模型 ${kind}`})),
    ...(selected.acceptCoreLicense?[{step:'core',message:'从官方获取 Cubism Core'}]:[]),
    ...(preset||selected.avatarArchive||selected.avatarUrl?[{step:'avatar',message:preset?'检查并自动安装大肥鱼形象':'导入已授权角色资源'}]:[])];
  if(options.plan)return {command:'install',homeDir:home,source:selected.source,steps:jobs,
    ...(preset?{avatar:{id:preset.id,revision:preset.revision,url:preset.url,sha256:preset.sha256}}:{}),
    note:'No downloads, inference, paid requests, microphone or screen capture are performed by --plan.'};
  signal?.throwIfAborted();
  await (dependencies.verifyPayload??verifyPayload)(layout);
  await mkdir(join(home,'.runtime'),{recursive:true});
  let lock;
  try{lock=await open(join(home,'.runtime/bootstrap.lock'),'wx',0o600);}catch{throw fail('installation_busy','这个目录有安装任务正在进行，请等待完成。');}
  let logging=Promise.resolve();
  const logPath=join(home,'data/logs/installation.log');
  const log=value=>{logging=logging.then(async()=>{
    await mkdir(dirname(logPath),{recursive:true});
    await appendFile(logPath,`[${new Date().toISOString()}] ${String(value).replace(/https?:\/\/[^\s<>"']+/giu,'[remote]').replace(/(?:sk-|Bearer\s+)[\w.-]+/giu,'[redacted]').replace(/\x1b\[[0-9;]*m/gu,'').slice(0,4096)}\n`);
  }).catch(()=>{});};
  try{
    for(const name of ['runner.json','runner-dsh.json'])if(await exists(join(home,'.runtime',name)))throw fail('runtime_running','请先关闭此目录运行的语音服务，再更新依赖。');
    const before=await (dependencies.doctor??doctor)(layout);
    if(options.offline&&(selected.models.length||!before.checks.sensevoiceModel||!before.checks.vadModel||(selected.acceptCoreLicense&&!before.checks.cubismCore)))throw fail('offline_assets','离线安装需要已缓存完整的 ASR、VAD 与 Core；可选模型请联网安装。');
    let lastPersist=0;
    const update=async value=>{
      signal?.throwIfAborted();onProgress(value);if(!value.progress)log(`${value.step}: ${value.message}`);
      // Download ticks are transient. Only persist durable phase checkpoints.
      if(!value.progress||Date.now()-lastPersist>2000){lastPersist=Date.now();await atomicJson(join(home,'.runtime/bootstrap.json'),{schemaVersion:1,...value,updatedAt:new Date().toISOString()});}
    };
    const executable=async()=>{
      if(options.uv||process.env.DAFEIYU_UV)return resolve(options.uv||process.env.DAFEIYU_UV);
      const ensureUv=dependencies.ensureUv??(await import('./install-download.mjs')).ensureUv;
      return ensureUv({homeDir:home,offline:!!options.offline,signal,
        onProgress:progress=>onProgress({stage:'running',step:'uv',message:'下载并校验 uv',progress})});
    };
    await update({stage:'running',step:'uv',message:jobs[0].message});
    const uv=await executable();
    const sourceOptions={...options,uv,'index-url':options['index-url']??(selected.source==='china'?'https://pypi.tuna.tsinghua.edu.cn/simple':undefined)};
    const runStep=(step,env,cwd)=>{
      const selectedEnv={...env,DAFEIYU_UV:uv,HF_ENDPOINT:selected.source==='china'?'https://hf-mirror.com':'https://huggingface.co',
        ...(sourceOptions['index-url']?{UV_DEFAULT_INDEX:sourceOptions['index-url'],PIP_INDEX_URL:sourceOptions['index-url']}:{})};
      return (dependencies.runStep??run)(step,selectedEnv,cwd,{signal,onLine:line=>{log(line);dependencies.onLine?.(line);}});
    };
    await update({stage:'running',step:'dependencies',message:'安装独立 Python 3.12 与两套语音环境'});
    await (dependencies.provision??provision)(sourceOptions,layout,{runStep});
    const execute=dependencies.perform??perform;
    for(const kind of ['sensevoice',...selected.models]){
      if(kind==='sensevoice'&&before.checks.sensevoiceModel&&before.checks.vadModel)continue;
      await update({stage:'running',step:kind,message:kind==='sensevoice'?'下载并准备 ASR / VAD 模型':`准备可选模型 ${kind}`});
      await execute({...sourceOptions,command:'models',kind,plan:false},layout,{runStep});
    }
    if(selected.acceptCoreLicense&&!before.checks.cubismCore){
      await update({stage:'running',step:'core',message:'从 Live2D 官方获取已授权的 Core'});
      await execute({...sourceOptions,command:'core',download:true,'accept-live2d-license':true,file:undefined,plan:false},layout,{runStep,signal});
    }
    let archive=selected.avatarArchive;
    // An opt-in default must not overwrite an existing/customized character.
    // Local ZIP and custom URL imports remain explicit replacement operations.
    const downloadUrl=preset?(before.checks.avatar?undefined:preset.url):selected.avatarUrl;
    const archiveSha256=preset?.sha256??selected.avatarSha256;
    if(preset&&before.checks.avatar)await update({stage:'running',step:'avatar',message:'已有角色，保留现有形象；无需重复下载'});
    if(downloadUrl){
      await update({stage:'running',step:'avatar',message:preset?'自动下载大肥鱼并校验完整性':'下载并校验你指定的已授权角色'});
      const downloadFile=dependencies.downloadFile??(await import('./install-download.mjs')).downloadFile;
      const result=await downloadFile({url:downloadUrl,destination:join(home,'cache/downloads',`${archiveSha256}.zip`),
        sha256:archiveSha256,maxBytes:preset?.maxBytes??512*1024*1024,signal,offline:!!options.offline,
        onProgress:progress=>onProgress({stage:'running',step:'avatar',message:preset?'自动下载大肥鱼':'下载已授权角色',progress})});
      archive=result.path;
    }
    if(archive){
      await update({stage:'running',step:'avatar',message:'自动导入角色纹理、表情与动作'});
      await execute({...sourceOptions,command:'avatar',archive,plan:false},layout,{runStep});
    }
    const state=await (dependencies.doctor??doctor)(layout);
    if(!state.ready||!state.checks.sensevoiceModel||!state.checks.vadModel)throw fail('incomplete_installation','依赖或 ASR/VAD 模型未完整准备，请重试安装。');
    if((preset||selected.avatarUrl||selected.avatarArchive)&&!state.checks.avatar)throw fail('incomplete_installation','角色导入未完成，请重试安装。');
    if(preset&&archive)await atomicJson(join(home,'.runtime/avatar-installation.json'),{
      schemaVersion:1,preset:preset.id,revision:preset.revision,sha256:preset.sha256,
      repositoryUrl:preset.repositoryUrl,licenseUrl:preset.licenseUrl,
      licenseAccepted:true,installedAt:new Date().toISOString(),
    });
    await update({stage:'complete',step:'complete',message:'环境和所选资源准备完成；尚未启动推理或调用付费接口。'});
    await logging;
    return {ok:true,homeDir:home,checks:state.checks};
  }catch(error){
    log(`failed: ${error?.message??'installation failed'}`);await logging;
    await atomicJson(join(home,'.runtime/bootstrap.json'),{schemaVersion:1,stage:'failed',step:'failed',
      message:signal?.aborted?'安装已暂停，可以原地重试。':'安装未完成，已保留下载缓存，可重试。',updatedAt:new Date().toISOString()}).catch(()=>{});
    throw error;
  }finally{await lock.close();await unlink(join(home,'.runtime/bootstrap.lock')).catch(()=>{});}
}

/** Same-origin, authenticated host endpoints call this bounded controller. */
export function createInstallationController({layout,homeConfigured=false,selectHome=()=>{},save=async()=>{},continued=false,
  config={},dependencies={}}){
  let disposed=false,starting=false,initializing,job,aborter,state={stage:homeConfigured?'idle':'needs_directory',step:'',message:''},allowMissing=continued;
  let options={homeDir:layout.homeDir,source:config.installSource??'china',acceptCoreLicense:config.acceptCoreLicense===true,models:[]};
  const inspect=dependencies.doctor??doctor;
  const status=async()=>{
    if(!layout.packaged)return {available:false,ready:true,stage:'complete',homeDir:layout.homeDir,homeConfigured:true,assets:{}};
    const result=homeConfigured?await inspect(layout):{ready:false,checks:{}};
    const checks=result.checks;
    const baseReady=result.ready&&checks.sensevoiceModel&&checks.vadModel;
    const ready=!!(!job&&!starting&&state.stage!=='failed'&&baseReady&&((checks.avatar&&checks.cubismCore)||allowMissing));
    return {available:true,...state,homeDir:homeConfigured?layout.homeDir:'E:/DafeiyuCompanion',homeConfigured,ready,
      stage:job||starting?'running':state.stage==='failed'?'failed':baseReady?'complete':state.stage,
      assets:{avatar:!!checks.avatar,cubismCore:!!checks.cubismCore,sensevoiceModel:!!checks.sensevoiceModel,vadModel:!!checks.vadModel}};
  };
  const start=async input=>{
    if(disposed)throw fail('disposed','插件已关闭。');
    if(!layout.packaged)throw fail('source_checkout','源码模式请使用命令行安装流程。');
    if(job||starting)throw fail('installation_busy','安装正在后台进行，请等待。');
    if(!homeConfigured&&(!input||typeof input.homeDir!=='string'||!input.homeDir.trim()))throw fail('invalid_home','请先明确选择资源存储目录。');
    const selected=installationOptions(input,layout);
    if(homeConfigured&&selected.homeDir!==layout.homeDir)throw fail('home_change','此插件已选择安装目录；迁移目录请在关闭插件后修改 homeDir 配置。');
    starting=true;
    let finishStarting;initializing=new Promise(done=>{finishStarting=done;});
    aborter=new AbortController();
    try{
    await selectHome(selected.homeDir);
    if(disposed)throw fail('disposed','插件已关闭。');
    layout.homeDir=selected.homeDir;homeConfigured=true;options=selected;allowMissing=false;
    await save({homeDir:layout.homeDir,continued:false});
    if(disposed||aborter.signal.aborted)throw fail('disposed','安装已停止。');
    state={stage:'running',step:'starting',message:'正在开始自动安装'};
    const command={source:selected.source,'accept-live2d-license':selected.acceptCoreLicense,archive:selected.avatarArchive,
      'avatar-url':selected.avatarUrl,'avatar-sha256':selected.avatarSha256,'accept-avatar-license':selected.acceptAvatarLicense,'avatar-preset':selected.avatarPreset,models:selected.models};
    job=Promise.resolve().then(()=>(dependencies.install??install)(command,layout,{...dependencies,signal:aborter.signal,
      onProgress:value=>{state={...state,progress:undefined,...value};},onLine:line=>{
        // Show fixed, concise steps only; child output can contain URLs or
        // environment-specific paths. Retain numeric download progress only.
        const match=/(\d+(?:\.\d+)?)\s*(KiB|MiB|GiB)\/(\d+(?:\.\d+)?)\s*(KiB|MiB|GiB)/u.exec(line);
        if(match)state.message=`${state.step}：下载中`;
      }})).then(()=>{state={stage:'complete',step:'complete',message:'环境准备完成'};})
      .catch(()=>{state={stage:'failed',step:state.step,message:aborter.signal.aborted?'安装已停止，缓存已保留。':'此步骤未完成，请查看所选目录的 data/logs/installation.log 后重试。',error:'安装未完成，已保留下载缓存。'};})
      .finally(()=>{job=undefined;aborter=undefined;});
    }finally{starting=false;finishStarting();initializing=undefined;}
    return status();
  };
  return {status,start,
    async autoStart(){if(layout.packaged&&homeConfigured&&config.autoInstall!==false){const current=await status();if(!current.ready&&current.stage!=='complete'&&!job&&!starting&&state.stage==='idle')await start(options);}},
    async continueWithoutAssets(){const current=await status();if(current.stage!=='complete')throw fail('incomplete_installation','请先完成依赖与识别模型安装。');await save({homeDir:layout.homeDir,continued:true});allowMissing=true;return status();},
    async cancel(){aborter?.abort();await initializing;await job;return status();},
    async dispose(){disposed=true;aborter?.abort();await initializing;await job;},
  };
}
