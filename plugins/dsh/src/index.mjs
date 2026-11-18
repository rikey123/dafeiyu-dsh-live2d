import { randomBytes } from 'node:crypto';
import { resolve, dirname, join } from 'node:path';
import { createRequire } from 'node:module';
import { createBridge, json, readJson } from './bridge.mjs';
import { createGatewayProxy, serveStatic, ownerRejection } from './proxy.mjs';
import { createSpeechRuntime } from './runtime.mjs';
import { createNativeAdapter } from './native.mjs';
import { registerScreenTool } from './screen-tool.mjs';
import { resolveLayout, staticRoots } from './layout.mjs';
import {createInstallationController} from './install.mjs';
import {openInstallationStorage} from './install-storage.mjs';

export const name = 'dafeiyu-live2d';
// Adapter services belong to the existing DSH runtime, not a second application loop.
export const inject = ['webServer', 'connection', 'sessionController', 'agents', 'sessions', 'sessionPersistence', 'agentDefaultModel', 'systemPrompt', 'workspaceRegistry', 'storageDomain', 'tools'];

export async function apply(ctx, config = {}) {
  const layout = resolveLayout(config);
  const {codeRoot:projectRoot} = layout;
  const origin = ctx.webServer.getOrigin();
  const pluginToken = randomBytes(32).toString('base64url');
  const runtimeModulesRoot = config.runtimeModulesRoot ?? resolve(dirname(createRequire(resolve(process.argv[1])).resolve('@deepseek-ai/dsh/package.json')), '../..');
  let adapter, bridge, runtime, proxy, installation, preferences;
  const registrations = [];
  const authorize = req => ownerRejection(ctx.connection, req);
  try {
    preferences=await openInstallationStorage(ctx,runtimeModulesRoot);
    const saved=preferences.read();
    const selectedHome=config.homeDir||process.env.DAFEIYU_HOME||saved?.homeDir;
    if(selectedHome)Object.assign(layout,resolveLayout({...config,homeDir:selectedHome}));
    installation=createInstallationController({layout,homeConfigured:!!selectedHome,continued:!!saved?.continued&&resolve(saved.homeDir)===layout.homeDir,config,
      save:preferences.save,selectHome:home=>{
        if(runtime)throw Object.assign(Error('请先关闭已经运行的语音服务，再安装资源。'),{code:'runtime_running'});
        layout.homeDir=home;
      }});
    adapter=await createNativeAdapter(ctx, {...config, runtimeModulesRoot, workspacePath:config.workspacePath ?? (layout.packaged ? process.cwd() : projectRoot)});
    bridge = await createBridge(adapter);
    const gatewayUrl=`http://127.0.0.1:${config.gatewayPort??8765}`;
    registrations.push(await registerScreenTool(ctx,{runtimeModulesRoot,gatewayUrl,token:pluginToken}));
    proxy = createGatewayProxy({gatewayUrl, token:pluginToken, ensure:async() => {
      const state=await installation.status();
      if(!state.ready)throw Object.assign(Error('Setup required'),{code:'setup_required'});
      runtime??=createSpeechRuntime({projectRoot, homeDir:layout.homeDir, packaged:layout.packaged, gatewayPort:config.gatewayPort, speechPort:config.speechPort, bridge, pluginToken, origin, startServices:config.startServices !== false, pythonPath:config.pythonPath});
      return runtime.ensure();
    }});
    registrations.push(ctx.webServer.register({kind:'prefix', path:'/dafeiyu', handler:async (req,res) => {
      const rejection = authorize(req);
      if (rejection) return json(res, rejection, {detail:'DSH authentication required'});
      let url;
      try { url = new URL(req.url, origin); } catch { return json(res,400,{detail:'Bad path'}); }
      const path = url.pathname.slice('/dafeiyu'.length);
      if(path==='/install'||path==='/install/continue'||path==='/install/cancel'){
        try{
          if(path==='/install'&&req.method==='GET'){await installation.autoStart();return json(res,200,await installation.status());}
          if(req.method!=='POST')return json(res,405,{detail:'Method not allowed'});
          const body=await readJson(req,16*1024);
          if(path==='/install')return json(res,202,await installation.start(body));
          if(Object.keys(body).length)return json(res,400,{detail:'此操作不接受安装选项。'});
          return json(res,200,path.endsWith('/continue')?await installation.continueWithoutAssets():await installation.cancel());
        }catch(error){
          const known=['installation_busy','runtime_running','home_change'].includes(error.code);
          const safe=known||['disposed','source_checkout','invalid_options','invalid_home','invalid_source','invalid_models','invalid_avatar','avatar_authorization','incomplete_installation'].includes(error.code);
          return json(res,error.status??(known?409:400),{code:safe?error.code:'installation_request_failed',detail:safe?error.message:'安装请求未完成，请检查配置后重试。'});
        }
      }
      // Native chat does not depend on the speech supervisor being available.
      if (path === '/api/sessions') {
        try {
          if (req.method === 'GET') return json(res,200,await adapter.sessions());
          if (req.method === 'POST') return json(res,201,await adapter.session());
        } catch (error) { return json(res,error.status ?? 503,{detail:'DSH session operation failed'}); }
      }
      const sessionRoute = /^\/api\/sessions\/([^/]+)(\/messages)?$/.exec(path);
      if (sessionRoute) {
        let id;
        try { id = decodeURIComponent(sessionRoute[1]); } catch { return json(res,400,{detail:'Invalid session'}); }
        try {
          if (req.method === 'GET' && sessionRoute[2]) return json(res,200,await adapter.messages(id));
          if (req.method === 'DELETE' && !sessionRoute[2]) return json(res,200,{deleted:await adapter.deleteSession(id)});
        } catch (error) { return json(res,error.status ?? 503,{detail:'DSH session operation failed'}); }
      }
      if (path === '/api' || path.startsWith('/api/')) return proxy.http(req,res,path+url.search);
      if (!path || path === '/') return json(res,200,{plugin:'@dafeiyu/dsh-live2d', ui:'DSH 侧栏 → 大肥鱼', harness:'dsh', memory_owner:'dsh'});
      let resource;
      try { resource = decodeURIComponent(path.slice(1)); } catch { return json(res,400,{detail:'Bad asset path'}); }
      if(['panel-entry.js','install-view.js','avatar-presets.mjs'].includes(resource))return serveStatic(req,res,[{directory:join(layout.packageRoot,'src')}],resource);
      return serveStatic(req,res,staticRoots(layout),resource);
    }}));
    registrations.push(ctx.webServer.registerUpgrade({path:'/dafeiyu/ws/voice', handler:async (req,socket,head) => {
      const rejection = authorize(req);
      if (rejection) { socket.end(`HTTP/1.1 ${rejection} Rejected\r\nConnection: close\r\n\r\n`); return; }
      const url = new URL(req.url, origin);
      return proxy.upgrade(req,socket,head,`/ws/voice${url.search}`);
    }}));
  } catch (error) {
    for (const dispose of registrations.reverse()) dispose();
    proxy?.dispose();await installation?.dispose();await runtime?.dispose();await bridge?.dispose();await adapter?.dispose();await preferences?.dispose();
    throw error;
  }
  ctx.on('dispose', async () => {
    for (const dispose of registrations.reverse()) dispose();
    proxy.dispose();await installation.dispose();await runtime?.dispose();await bridge.dispose();await adapter.dispose();await preferences.dispose();
  });
}
