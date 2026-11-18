/** Opt-in, isolated DSH acceptance fixture. Never install in a user profile. */
import {createRequire} from 'node:module';
import {pathToFileURL} from 'node:url';
import {join} from 'node:path';
import {ownerRejection} from '../../plugins/dsh/src/proxy.mjs';
import {json} from '../../plugins/dsh/src/bridge.mjs';
export const name = 'dafeiyu-native-acceptance-fixture';
export const inject = ['webServer','connection','sessionController','sessions','sessionPersistence','attachments'];
export async function apply(ctx, config) {
  if (process.env.DAFEIYU_NATIVE_ACCEPTANCE !== '1') throw Error('Isolated acceptance opt-in required');
  const require = createRequire(join(config.runtimeModulesRoot,'@deepseek-ai/dsh/package.json'));
  const {createUserMessage,createAssistantMessage} = await import(pathToFileURL(require.resolve('@deepseek-ai/dsh-llm/message')).href);
  const {assembleContextFor} = await import(pathToFileURL(require.resolve('@deepseek-ai/dsh-agent')).href);
  const {renderPrompt,PERSONA_PREFIX_SECTION,PERSONA_SUFFIX_SECTION} = await import(pathToFileURL(require.resolve('@deepseek-ai/dsh-system-prompt')).href);
  const release = ctx.webServer.register({kind:'prefix',path:'/dafeiyu-fixture',handler:async (req,res) => {
    if (ownerRejection(ctx.connection,req)) return json(res,403,{});
    const id = new URL(req.url,'http://127.0.0.1').searchParams.get('session_id');
    if (!id?.startsWith('dafeiyu-')) return json(res,400,{});
    const {agent} = await ctx.sessionController.resolveAgent(id);
    if (!agent || agent.status !== 'idle') return json(res,409,{});
    const assembly = await agent.ctx.systemPrompt.assemble(assembleContextFor(agent));
    const persona = renderPrompt({...assembly,sections:assembly.sections.filter(section =>
      [PERSONA_PREFIX_SECTION,PERSONA_SUFFIX_SECTION,'soul:persona'].includes(section.name))});
    if (typeof persona !== 'string') throw Error('Native persona assembly unavailable');
    const images = config.fixtureJpeg ? await ctx.attachments.admitPromptContent([
      {type:'image',mediaType:'image/jpeg',data:config.fixtureJpeg,name:'offline-screen-observation.jpg'},
    ]) : [];
    const notice = createUserMessage({source:{kind:'dafeiyu-voice',form:'notice',externalEventId:'offline-observation',playedChars:7,ending:'completed',interrupted:false,
      summary:'屏幕主动评论：离线通知验收'},content:[{type:'text',text:'离线通知验收（不是新的用户指令）；发生时间：2026-11-15T06:13:28.000Z；场景：离线屏幕；所附图片为历史画面。'},...images]});
    agent.inject(notice);
    if (agent.status !== 'idle' || !agent.inbox.nextStep.some(message => message.id === notice.id)) throw Error('Native notice must not wake model');
    await ctx.sessions.flush(agent.session);
    const reader = await ctx.sessionPersistence.open(id,'read');
    let durable, observationDurable;
    try {
      const encoded=JSON.stringify((await reader.read()).events);
      durable=encoded.includes(notice.id);
      observationDurable=images.length===1 && encoded.includes(images[0].attachment.attachmentId) && encoded.includes('offline-observation');
    } finally { await reader.close(); }
    if (!durable) throw Error('Native notice inbox did not persist');
    if (config.fixtureJpeg && !observationDurable) throw Error('Historical screenshot notice did not persist');
    agent.inbox.remove(notice.id);
    const turn=1,step=1,session=agent.session;
    session.append('turn/start',{turn});
    // Exercise standard notice presentation separately from real driver claims.
    session.append('user/message',notice,{surfaceOp:'append'});
    session.append('user/message',createUserMessage({content:[{type:'text',text:'离线原生聊天验收'}],source:{kind:'user'}}),{surfaceOp:'append'});
    session.append('step/start',{turn,step});
    session.append('assistant/message',{turn,step,stream:[],message:createAssistantMessage({source:{provider:'fixture',model:'offline'},content:[
      {type:'text',text:'## 原生富内容验收\n\n**粗体**与列表：\n- 第一项\n- 第二项\n\n```python\nprint("native renderer")\n```\n\n| 项目 | 状态 |\n| --- | --- |\n| 原生聊天 | 已挂载 |'},
    ]})},{surfaceOp:'append'});
    session.append('step/end',{turn,step});session.append('turn/end',{turn,reason:{kind:'completed'}});
    await ctx.sessions.flush(session);
    return json(res,200,{seeded:true,nativeNoticeDurable:true,nativeNoticeDidNotWake:true,nativePersonaAssembly:true,nativeScreenObservationDurable:observationDurable});
  }});
  ctx.on('dispose',release);
}
