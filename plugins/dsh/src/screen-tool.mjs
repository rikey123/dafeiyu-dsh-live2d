/** DSH capability adapter: fresh browser-authorized screen -> native tool image. */
import {request} from 'node:http';
import {createRequire} from 'node:module';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
import {admitScreen, screenImages} from './screen.mjs';

export const SCREEN_TOOL = 'view_current_screen';
const reasons = {
  not_shared:'当前没有共享屏幕，请用户在数字人界面开启屏幕共享。',
  no_connection:'本会话的数字人连接尚未就绪。',
  timeout:'本次没有及时收到新截图，可以稍后再查看。',
  disabled:'屏幕共享功能尚未启用。',
  busy:'另一次屏幕查看正在进行。',
  unsupported_mode:'当前语音模式不支持共享屏幕。',
  sharing_changed:'共享已停止或切换，本次没有取得画面。',
  invalid_frame:'本次截图未通过校验。',
  image_model_required:'当前调用模型未确认支持图片，请切换到支持图片的模型。',
  gateway_unavailable:'本地数字人服务暂时不可用。',
};
const unavailable = reason => ({available:false, reason:Object.hasOwn(reasons,reason) ? reason : 'gateway_unavailable'});
const validId = value => typeof value === 'string' && value.length > 0 && value.length <= 200 && !/[\u0000-\u001f]/u.test(value);
const get = (ctx, name) => typeof ctx.get === 'function' ? ctx.get(name) : ctx[name];

/** Only immutable DSH delegation ancestry can select another session's stream. */
export async function screenSession(ctx, agent, signal) {
  if (!validId(agent?.id) || agent.session?.id !== agent.id) return undefined;
  let id = agent.id, header = agent.session.header;
  const seen = new Set();
  for (let depth = 0; depth < 16; depth++) {
    signal?.throwIfAborted();
    if (seen.has(id)) return undefined;
    seen.add(id);
    if (!header) header = (await ctx.sessionPersistence.stat(id, {signal}))?.header;
    if (!header || header.origin !== 'subagent') return id;
    if (!validId(header.parentSession)) return undefined;
    id = header.parentSession;
    header = ctx.agents.get(id)?.session.header ?? get(ctx,'sessions')?.get?.(id)?.header;
  }
  return undefined;
}

/** Fixed loopback transport: no browser credentials, environment proxy, redirects or logs. */
export function requestScreenSnapshot({gatewayUrl, token}, sessionId, signal) {
  const url = new URL(gatewayUrl);
  if (url.protocol !== 'http:' || url.hostname !== '127.0.0.1' || url.username || url.password || url.search || url.hash || !['','/'].includes(url.pathname)) throw Error('Screen gateway must use IPv4 loopback HTTP');
  signal?.throwIfAborted();
  return new Promise((resolve, reject) => {
    const body = JSON.stringify({session_id:sessionId});
    const req = request(new URL('/api/voice/screen/snapshot',url), {method:'POST', signal, timeout:12_000,
      headers:{'content-type':'application/json', 'content-length':Buffer.byteLength(body), 'x-dafeiyu-plugin-token':token}}, res => {
      const parts=[]; let size=0;
      res.on('data', part => { size+=part.length; if (size > 384*1024) req.destroy(Error('Screen response too large')); else parts.push(part); });
      res.on('error', reject);
      res.on('end', () => {
        if (res.statusCode !== 200) return resolve(unavailable('gateway_unavailable'));
        try { resolve(JSON.parse(Buffer.concat(parts).toString('utf8'))); }
        catch { resolve(unavailable('gateway_unavailable')); }
      });
    });
    req.once('timeout', () => req.destroy(Error('Screen gateway timeout')));
    req.once('error', error => { if (signal?.aborted) reject(signal.reason ?? error); else resolve(unavailable('gateway_unavailable')); });
    req.end(body);
  });
}

export function screenToolDefinition(ctx, {snapshot}) {
  return {
    name:SCREEN_TOOL,
    description:'查看用户在当前数字人会话中正在共享的屏幕，返回一张新截图。用户说“看这个”、询问眼前内容、或需要确认画面变化时可使用。无需 System One 判断；只能查看已开启的共享画面，不能点击或操作桌面。',
    parameters:{},
    output:{
      schema:{type:'object',additionalProperties:false,properties:{
        available:{type:'boolean',required:true}, reason:{type:'string',enum:Object.keys(reasons)},
        captured_at:{type:'string'},
        image:{type:'object',additionalProperties:false,properties:{
          attachmentId:{type:'string',required:true}, mediaType:{type:'string',required:true},
          bytes:{type:'integer',required:true}, width:{type:'integer',required:true}, height:{type:'integer',required:true},
          name:{type:'string'}, originalDimensions:{type:'object',additionalProperties:false,properties:{width:{type:'integer',required:true},height:{type:'integer',required:true}}},
        }},
      }},
      render:(_args,value) => value.available ? [
        {type:'text',text:`当前共享屏幕的新截图，采集时间：${value.captured_at}。这是本次查看时的画面。`},
        {type:'image',attachment:value.image},
      ] : [{type:'text',text:`未取得屏幕画面（${value.reason}）：${reasons[value.reason]}`}],
    },
    isConcurrencySafe:() => true,
    async execute(_args,exec) {
      if (Object.keys(_args).length) throw Error('view_current_screen does not accept arguments');
      const signal=exec.signal;
      signal?.throwIfAborted();
      const sessionId=await screenSession(ctx,exec.agent,signal);
      if (!sessionId) return unavailable('no_connection');
      const selection=exec.agent.session.requestHeader?.()?.config ?? exec.agent.model?.current?.() ?? exec.agent.options;
      const llm=get(ctx,'llm');
      if (!selection?.provider || !selection.model || !llm?.resolveModelInfo || !get(ctx,'attachments')?.admitPromptContent) return unavailable('image_model_required');
      const model=await llm.resolveModelInfo(selection.provider,selection.model,signal);
      if (!model?.inputModalities?.includes('image')) return unavailable('image_model_required');
      const result=await snapshot(sessionId,signal);
      signal?.throwIfAborted();
      if (result?.available !== true) return unavailable(result?.reason);
      if (typeof result.captured_at !== 'string' || !Number.isFinite(Date.parse(result.captured_at))) return unavailable('invalid_frame');
      let images;
      try { images=screenImages([result.image], () => Error('Invalid screen image')); }
      catch { return unavailable('invalid_frame'); }
      const parts=await admitScreen(ctx,images,selection,signal,() => Error('Screen attachment unavailable'));
      return {available:true,captured_at:result.captured_at,image:parts[0].attachment};
    },
    presentCall:() => ({card:'generic',title:'查看当前共享屏幕',kind:'read'}),
  };
}

export async function registerScreenTool(ctx, config) {
  const require=createRequire(join(config.runtimeModulesRoot,'@deepseek-ai/dsh/package.json'));
  const {defineTool}=await import(pathToFileURL(require.resolve('@deepseek-ai/dsh-tools')).href);
  const releases=[];
  try {
    releases.push(ctx.tools.register(defineTool(screenToolDefinition(ctx,{snapshot:(id,signal) => requestScreenSnapshot(config,id,signal)}))));
    releases.push(ctx.systemPrompt.section({name:'dafeiyu_screen_tool',order:10001,interpolate:false,
      text:({scope}) => ctx.tools.get(SCREEN_TOOL,scope) ? '用户可能正在数字人界面共享屏幕。需要理解“看这个”等指向当前画面的表达，或确认画面变化时，可使用 view_current_screen 获取本次的新截图；用户消息已附有所需画面时无需重复查看。截图查看与实际操作是不同能力，其他查询和操作继续使用相应工具。' : ''}));
  } catch (error) { for (const release of releases.reverse()) release(); throw error; }
  return () => { for (const release of releases.splice(0).reverse()) release(); };
}
