import { describe, it, expect, vi } from 'vitest'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { ScreenCapture, ScreenPreferences, screenDefaults, screenAvailability, handleScreenStatus, retainScreenDecision, screenDecisionText, screenReason } from './screenCompanion'

describe('screen settings', () => {
 it.each(['quiet','balanced','lively'] as const)('renders the saved companion style %s and distinguishes it from the speech initiative switch', style => {
  const html=renderToStaticMarkup(createElement(ScreenPreferences,{settings:{...screenDefaults,screen_companion_style:style},onChange:vi.fn()}))
  expect(html).toContain(`<option value="${style}" selected="">`)
  expect(html).toContain('不是定时强制说话')
  expect(html).toContain('另一个独立开关')
  expect(screenDefaults.screen_companion_style).toBe('balanced')
  expect(screenDecisionText({status:'waiting',style,reason:'low_desire'})).not.toContain('生效风格 —')
 })
 it('keeps screen enable and request controls available with System One off', () => {
  const settings={...screenDefaults,systemone_enabled:false}
  const html=renderToStaticMarkup(createElement(ScreenPreferences,{settings,onChange:vi.fn()}))
  expect(html).toMatch(/<input type="checkbox"\/>\u542f\u7528\u5c4f\u5e55\u966a\u73a9\u914d\u7f6e/)
  expect(html).toMatch(/<input type="checkbox" checked=""\/>\u5141\u8bb8\u6309\u9700\u8bf7\u6c42\u622a\u56fe/)
  expect(html).toContain('手动屏幕查看无需开启 System One；Jev 模式的自动陪玩判断需要 System One。')
 })
 it('direct mode hides only judgment parameters and keeps shared limits and saved thresholds', () => {
  const settings = {...screenDefaults, screen_companion_mode:'direct' as const, screen_companion_speak_threshold:.7}
  const html = renderToStaticMarkup(createElement(ScreenPreferences,{settings,onChange:vi.fn()}))
  expect(html).not.toContain('<label>开口意愿阈值')
  expect(html).toContain('回复冷却（秒）')
  expect(html).toContain('每小时最多回复次数')
  expect(settings.screen_companion_speak_threshold).toBe(.7)
  expect(screenAvailability({...settings,screen_companion_enabled:true,screen_model_ready:true,systemone_enabled:false,harness_provider:'dsh',conversation_mode:'duplex'},true,false,false)).toBe('')
 })
 it.each([.5,.65,.8,.9])('allows a 0.5 minimum and renders the saved value %s without replacing it', threshold => {
  const html = renderToStaticMarkup(createElement(ScreenPreferences, {settings:{...screenDefaults,screen_companion_speak_threshold:threshold},onChange:vi.fn()}))
  const input = html.match(/<label>开口意愿阈值(<input[^>]+>)/)?.[1]
  expect(input).toBeDefined()
  expect(input).toContain('min="0.5" max="0.99" step="any"')
  expect(input).toContain(`value="${threshold}"`)
  expect(screenDefaults.screen_companion_speak_threshold).toBe(.9)
  expect(html).toContain('越低越容易触发主动评论')
  expect(html).toContain('仍受等待、冷却和次数上限约束')
 })
})

describe('screen diagnostics', () => {
 it('retains the last proactive decision across transient and requested statuses', () => {
  const decision = {status:'waiting',mode:'proactive' as const,reason:'low_desire',desire:.61,must_wait:.1,speak_threshold:.9,wait_threshold:.2,intent:'acknowledge',intent_probability:.4,non_wait_probability:.8,intent_confidence:.4,intent_confidence_threshold:.7}
  let retained = retainScreenDecision(undefined, decision)
  for (const status of [{status:'waiting',reason:'busy'}, {status:'waiting',reason:'interval'}, {status:'accepted',mode:'requested' as const,desire:.99}, {status:'waiting',reason:'request_low_intent',desire:.1}]) retained = retainScreenDecision(retained,status)
  expect(retained).toBe(decision)
  const text = screenDecisionText(retained!)
  expect(text).toContain('开口意愿未达到阈值')
  expect(text).toContain('0.610 / 生效阈值 0.900')
  expect(text).toContain('非等待概率 0.800 / 生效阈值 0.700')
  expect(text).toContain('不单独决定开口')
  expect(retainScreenDecision(retained,{status:'waiting',reason:'must_wait',desire:.95,must_wait:.3})?.reason).toBe('must_wait')
 })
 it('explains gates and handles old servers without optional numbers', () => {
  for (const reason of ['low_desire','must_wait','wait_intent','low_confidence','busy','interval','cooldown','budget']) expect(screenReason({status:'waiting',reason})).not.toBe(reason)
  expect(screenDecisionText({status:'waiting',reason:'low_desire',desire:0})).toContain('0.000 / 生效阈值 —')
  expect(retainScreenDecision(undefined,{status:'waiting',reason:'busy'})).toBeUndefined()
 })
})

describe('screen authorization', () => {
 it('keeps an explicit grant, periodic frames and fresh requested snapshots while hidden', async () => {
  vi.useFakeTimers(); vi.setSystemTime(0)
  const id='12345678-1234-4123-8123-123456789abc', req='87654321-1234-4123-8123-123456789abc'
  let grant!: (stream: MediaStream) => void
  const track={stop:vi.fn(),addEventListener:vi.fn()}, send=vi.fn(), mic=vi.fn()
  const video={videoWidth:100,videoHeight:100,play:async()=>{},pause:vi.fn(),remove:vi.fn(),srcObject:null}
  const context={drawImage:vi.fn(),getImageData:()=>({data:new Uint8ClampedArray(32*18*4)})}
  const canvas=()=>({width:0,height:0,getContext:()=>context,toBlob:(cb:(b:Blob)=>void)=>cb({type:'image/jpeg',size:1,arrayBuffer:async()=>new Uint8Array([1]).buffer} as Blob)})
  const doc={visibilityState:'visible',createElement:(type:string)=>type==='video'?video:canvas()}
  vi.stubGlobal('document',doc); vi.stubGlobal('window',globalThis); vi.stubGlobal('crypto',{randomUUID:()=>id})
  const display=vi.fn(()=>new Promise<MediaStream>(resolve=>{grant=resolve}))
  vi.stubGlobal('navigator',{mediaDevices:{getDisplayMedia:display,getUserMedia:mic}})
  const capture=new ScreenCapture(()=>{})
  capture.start({...screenDefaults,screen_request_enabled:false},send)
  doc.visibilityState='hidden' // The user selected a window, then switched tabs before the grant resolved.
  grant({getTracks:()=>[track],getVideoTracks:()=>[track]} as unknown as MediaStream)
  await vi.advanceTimersByTimeAsync(0)
  await vi.advanceTimersByTimeAsync(screenDefaults.screen_companion_refresh_ms)
  expect(send.mock.calls.filter(([type])=>type==='voice.screen.frame')).toHaveLength(2)
  capture.requestSnapshot({stream_id:id,request_id:req,purpose:'idle'}); await vi.advanceTimersByTimeAsync(0)
  expect(send).toHaveBeenCalledWith('voice.screen.snapshot',expect.objectContaining({request_id:req,seq:3}))
  vi.clearAllTimers() // Simulate the browser suppressing background interval callbacks.
  await vi.advanceTimersByTimeAsync(screenDefaults.screen_companion_refresh_ms)
  capture.sample({stream_id:'stale-stream'}); await vi.advanceTimersByTimeAsync(0)
  expect(send.mock.calls.filter(([type])=>type==='voice.screen.frame')).toHaveLength(2)
  capture.sample({stream_id:id}); capture.sample({stream_id:id}); await vi.advanceTimersByTimeAsync(0)
  expect(send.mock.calls.filter(([type])=>type==='voice.screen.frame')).toHaveLength(3)
  expect(track.stop).not.toHaveBeenCalled(); expect(display).toHaveBeenCalledOnce(); expect(mic).not.toHaveBeenCalled()
  capture.stop()
  expect(track.stop).toHaveBeenCalledOnce(); expect(vi.getTimerCount()).toBe(0)
  capture.requestSnapshot({stream_id:id,request_id:'11111111-1234-4123-8123-123456789abc'})
  await vi.advanceTimersByTimeAsync(30000)
  expect(send.mock.calls.filter(([type])=>type==='voice.screen.snapshot')).toHaveLength(1)
  vi.useRealTimers(); vi.unstubAllGlobals()
 })
 it('requires saved DSH, enabled screen, an image model, and a supported mode', () => {
  const ready = {...screenDefaults, screen_companion_enabled:true, screen_model_ready:true, systemone_enabled:true, harness_provider:'dsh', conversation_mode:'duplex'}
  expect(screenAvailability(ready,true,false,false)).toBe('')
  expect(screenAvailability(ready,true,true,false)).toBe('')
  expect(screenAvailability({...ready,harness_provider:'other'},true,false,false)).toContain('DSH')
  expect(screenAvailability({...ready,screen_companion_enabled:false},true,false,false)).not.toBe('')
  expect(screenAvailability({...ready,systemone_enabled:false},true,false,false)).toBe('')
  expect(screenAvailability({...ready,screen_model_ready:false},true,false,false)).toContain('图片输入')
  expect(screenAvailability({...ready,screen_model_ready:undefined},true,false,false)).toContain('图片输入')
  expect(screenAvailability({...ready,conversation_mode:'moss_live'},true,false,false)).toContain('MOSS-Live')
 })
 it.each(['requires_dsh_and_systemone', 'no_vision'])('stops synchronously on unavailable: %s', reason => {
  const order: string[] = []
  const status = {status:'unavailable',reason}
  handleScreenStatus(status, () => order.push('stop'), value => { expect(value).toEqual(status); order.push('report') })
  expect(order).toEqual(['stop','report'])
 })
 it('leaves an available stream running', () => {
  const stop = vi.fn(), report = vi.fn()
  handleScreenStatus({status:'ready'},stop,report)
  expect(stop).not.toHaveBeenCalled()
  expect(report).toHaveBeenCalledOnce()
 })
 it('stops an active share immediately on an unavailable status', async () => {
  vi.useFakeTimers()
  const track = {stop:vi.fn(),addEventListener:vi.fn()}
  const stream = {getTracks:() => [track],getVideoTracks:() => [track]}
  const video = {videoWidth:0,videoHeight:0,play:() => Promise.resolve(),pause:vi.fn(),remove:vi.fn(),srcObject:null}
  vi.stubGlobal('document',{visibilityState:'visible',createElement:() => video})
  vi.stubGlobal('window',globalThis)
  vi.stubGlobal('navigator',{mediaDevices:{getDisplayMedia:() => Promise.resolve(stream)}})
  vi.stubGlobal('crypto',{randomUUID:() => 'stream-id'})
  const send=vi.fn(), capture=new ScreenCapture(() => {})
  capture.start(screenDefaults,send)
  await vi.advanceTimersByTimeAsync(0)
  handleScreenStatus({status:'unavailable',reason:'no_vision'},() => capture.stop(),vi.fn())
  expect(track.stop).toHaveBeenCalledOnce()
  expect(video.remove).toHaveBeenCalledOnce()
  expect(vi.getTimerCount()).toBe(0)
  expect(send).toHaveBeenLastCalledWith('voice.screen',{active:false,stream_id:'stream-id'})
  vi.useRealTimers(); vi.unstubAllGlobals()
 })
 it('stops a stream granted after cancellation without sending', async () => {
  let grant!: (stream: MediaStream) => void
  const stop = vi.fn(), send = vi.fn()
  vi.stubGlobal('document', { visibilityState: 'visible' })
  vi.stubGlobal('navigator', { mediaDevices: { getDisplayMedia: vi.fn(() => new Promise<MediaStream>(resolve => { grant = resolve })) } })
  const capture = new ScreenCapture(() => {})
  capture.start(screenDefaults, send)
  expect(navigator.mediaDevices.getDisplayMedia).toHaveBeenCalledWith({video:true,audio:false})
  capture.stop()
  grant({getTracks: () => [{stop}]} as unknown as MediaStream)
  await Promise.resolve()
  expect(stop).toHaveBeenCalledOnce()
  expect(send).not.toHaveBeenCalled()
  vi.unstubAllGlobals()
 })
 it('sends one JPEG frame and filters unchanged thumbnails', async () => {
  vi.useFakeTimers()
  const stop = vi.fn(), send = vi.fn(), update = vi.fn()
  const track = { stop, addEventListener: vi.fn() }
  const stream = {getTracks: () => [track], getVideoTracks: () => [track]}
  const video = {videoWidth:1920, videoHeight:1080, play: () => Promise.resolve(), pause: vi.fn(), remove: vi.fn(), srcObject:null}
  const context = {drawImage:vi.fn(), getImageData: () => ({data:new Uint8ClampedArray(32*18*4)})}
  const canvas = () => ({width:0,height:0,getContext: () => context, toBlob: (cb: (blob: Blob) => void) => cb({type:'image/jpeg',size:3,arrayBuffer: async () => new Uint8Array([1,2,3]).buffer} as Blob)})
  vi.stubGlobal('document', {visibilityState:'visible', createElement:(type:string) => type === 'video' ? video : canvas()})
  vi.stubGlobal('window', globalThis)
  vi.stubGlobal('navigator', {mediaDevices:{getDisplayMedia:() => Promise.resolve(stream)}})
  vi.stubGlobal('crypto', {randomUUID:() => '12345678-1234-4123-8123-123456789abc'})
  const capture = new ScreenCapture(update)
  capture.start(screenDefaults,send)
  await vi.advanceTimersByTimeAsync(0)
  expect(send).toHaveBeenCalledWith('voice.screen',{active:true,stream_id:'12345678-1234-4123-8123-123456789abc'})
  expect(send).toHaveBeenCalledWith('voice.screen.frame',{stream_id:'12345678-1234-4123-8123-123456789abc',seq:1,width:960,height:540,mime_type:'image/jpeg',data:'AQID'})
  await vi.advanceTimersByTimeAsync(2500)
  expect(send.mock.calls.filter(([type]) => type === 'voice.screen.frame')).toHaveLength(1)
  expect(update).toHaveBeenLastCalledWith(expect.objectContaining({sent:1,filtered:1}))
  capture.stop()
  expect(stop).toHaveBeenCalledOnce()
  expect(video.pause).toHaveBeenCalledOnce()
  expect(video.remove).toHaveBeenCalledOnce()
  expect(video.srcObject).toBeNull()
  expect(vi.getTimerCount()).toBe(0)
  vi.useRealTimers(); vi.unstubAllGlobals()
 })
 it('cleans video, timer and tracks when the shared track ends', async () => {
  vi.useFakeTimers()
  let ended!: () => void
  const stop = vi.fn(), send = vi.fn()
  const track = {stop, addEventListener: (_type: string, cb: () => void) => { ended = cb }}
  const stream = {getTracks: () => [track], getVideoTracks: () => [track]}
  const video = {videoWidth:0, videoHeight:0, play: () => Promise.resolve(), pause: vi.fn(), remove: vi.fn(), srcObject:null}
  vi.stubGlobal('document', {visibilityState:'visible', createElement: () => video})
  vi.stubGlobal('window', globalThis)
  vi.stubGlobal('navigator', {mediaDevices:{getDisplayMedia:() => Promise.resolve(stream)}})
  vi.stubGlobal('crypto', {randomUUID:() => 'stream-id'})
  const capture = new ScreenCapture(() => {})
  capture.start(screenDefaults, send)
  await vi.advanceTimersByTimeAsync(0)
  expect(vi.getTimerCount()).toBe(1)
  ended()
  expect(stop).toHaveBeenCalledOnce()
  expect(video.pause).toHaveBeenCalledOnce()
  expect(video.remove).toHaveBeenCalledOnce()
  expect(video.srcObject).toBeNull()
  expect(vi.getTimerCount()).toBe(0)
  expect(send).toHaveBeenLastCalledWith('voice.screen', {active:false,stream_id:'stream-id'})
  vi.useRealTimers(); vi.unstubAllGlobals()
 })
 it('replaces a pending authorization synchronously and stops the stale grant', async () => {
  const grants: Array<(stream: MediaStream) => void> = []
  const getDisplayMedia = vi.fn(() => new Promise<MediaStream>(resolve => grants.push(resolve)))
  vi.stubGlobal('document', {visibilityState:'visible'})
  vi.stubGlobal('navigator', {mediaDevices:{getDisplayMedia}})
  const capture = new ScreenCapture(() => {})
  capture.start(screenDefaults, vi.fn())
  capture.start(screenDefaults, vi.fn())
  expect(getDisplayMedia).toHaveBeenCalledTimes(2)
  const stop = vi.fn()
  grants[0]({getTracks: () => [{stop}]} as unknown as MediaStream)
  await Promise.resolve()
  expect(stop).toHaveBeenCalledOnce()
  capture.stop()
  const stopSecond = vi.fn()
  grants[1]({getTracks: () => [{stop:stopSecond}]} as unknown as MediaStream)
  await Promise.resolve()
  expect(stopSecond).toHaveBeenCalledOnce()
  vi.unstubAllGlobals()
 })
 it('cleans the acquired track and video when playback fails', async () => {
  const stop = vi.fn(), update = vi.fn(), send = vi.fn()
  const track = {stop, addEventListener: vi.fn()}
  const stream = {getTracks: () => [track], getVideoTracks: () => [track]}
  const video = {play: () => Promise.reject(new Error('play failed')), pause: vi.fn(), remove: vi.fn(), srcObject:null}
  vi.stubGlobal('document', {visibilityState:'visible', createElement: () => video})
  vi.stubGlobal('navigator', {mediaDevices:{getDisplayMedia:() => Promise.resolve(stream)}})
  vi.stubGlobal('crypto', {randomUUID:() => 'stream-id'})
  const capture = new ScreenCapture(update)
  capture.start(screenDefaults, send)
  await vi.waitFor(() => expect(stop).toHaveBeenCalledOnce())
  expect(video.pause).toHaveBeenCalledOnce()
  expect(video.remove).toHaveBeenCalledOnce()
  expect(video.srcObject).toBeNull()
  // An idempotent stop also closes a possibly in-flight announcement.
  expect(send).toHaveBeenCalledExactlyOnceWith('voice.screen', {active:false, stream_id:'stream-id'})
  expect(update).toHaveBeenLastCalledWith(expect.objectContaining({active:false,pending:false,error:expect.stringContaining('play failed')}))
  vi.unstubAllGlobals()
 })
 it('resets pending state when permission is denied', async () => {
  const update = vi.fn()
  vi.stubGlobal('navigator', {mediaDevices:{getDisplayMedia:() => Promise.reject(new Error('denied'))}})
  const capture = new ScreenCapture(update)
  capture.start(screenDefaults, vi.fn())
  await vi.waitFor(() => expect(update).toHaveBeenLastCalledWith(expect.objectContaining({active:false,pending:false,error:expect.stringContaining('denied')})))
  vi.unstubAllGlobals()
 })
 it('keeps only one frame encoding in flight and drops it after stop', async () => {
  vi.useFakeTimers()
  let finish!: (blob: Blob) => void
  const encode = vi.fn((cb: (blob: Blob) => void) => { finish = cb })
  const track = {stop: vi.fn(), addEventListener: vi.fn()}
  const stream = {getTracks: () => [track], getVideoTracks: () => [track]}
  const video = {videoWidth:100, videoHeight:100, play: () => Promise.resolve(), pause: vi.fn(), remove: vi.fn(), srcObject:null}
  const context = {drawImage: vi.fn(), getImageData: () => ({data:new Uint8ClampedArray(32*18*4)})}
  const canvas = () => ({width:0,height:0,getContext: () => context,toBlob:encode})
  vi.stubGlobal('document', {visibilityState:'visible', createElement:(type:string) => type === 'video' ? video : canvas()})
  vi.stubGlobal('window', globalThis)
  vi.stubGlobal('navigator', {mediaDevices:{getDisplayMedia:() => Promise.resolve(stream)}})
  vi.stubGlobal('crypto', {randomUUID:() => 'stream-id'})
  const send = vi.fn(), capture = new ScreenCapture(() => {})
  capture.start(screenDefaults, send)
  await vi.advanceTimersByTimeAsync(7500)
  expect(encode).toHaveBeenCalledOnce()
  capture.stop()
  finish({type:'image/jpeg',size:1,arrayBuffer:async () => new Uint8Array([1]).buffer} as Blob)
  await vi.advanceTimersByTimeAsync(0)
  expect(send.mock.calls.filter(([type]) => type === 'voice.screen.frame')).toHaveLength(0)
  expect(vi.getTimerCount()).toBe(0)
  vi.useRealTimers(); vi.unstubAllGlobals()
 })
 it.each(['timeout','network','circuit_open','busy','unchanged','interval','cooldown','budget','low_desire','must_wait','wait_intent','low_confidence','request_not_shared','request_disabled','request_low_intent','request_snapshot_timeout','request_attached','request_cancelled','request_intent_unavailable'])('keeps sharing on nonfatal %s', reason => {
  const stop=vi.fn(), report=vi.fn()
  handleScreenStatus({status:'unavailable',reason,mode:'requested',frames:3,rejected:1},stop,report)
  expect(stop).not.toHaveBeenCalled()
  expect(report).toHaveBeenCalledWith(expect.objectContaining({mode:'requested',frames:3,rejected:1}))
 })
 it.each(['requires_image_capable_dsh_model','missing_key','unauthorized','forbidden','invalid_response','unknown_failure'])('fails closed on %s', reason => {
  const stop=vi.fn(), report=vi.fn()
  handleScreenStatus({status:'unavailable',reason,mode:'requested'},stop,report)
  expect(stop).toHaveBeenCalledOnce()
  expect(report).toHaveBeenCalledWith(expect.objectContaining({reason,mode:'requested'}))
 })
 it('refreshes static frames periodically and fulfills only valid current requests without microphone access', async () => {
  vi.useFakeTimers(); vi.setSystemTime(0)
  const id='12345678-1234-4123-8123-123456789abc', req='87654321-1234-4123-8123-123456789abc'
  const track={stop:vi.fn(),addEventListener:vi.fn()}, send=vi.fn(), mic=vi.fn()
  const video={videoWidth:100,videoHeight:100,play:async()=>{},pause:vi.fn(),remove:vi.fn(),srcObject:null}
  const context={drawImage:vi.fn(),getImageData:()=>({data:new Uint8ClampedArray(32*18*4)})}
  const canvas=()=>({width:0,height:0,getContext:()=>context,toBlob:(cb:(b:Blob)=>void)=>cb({type:'image/jpeg',size:1,arrayBuffer:async()=>new Uint8Array([1]).buffer} as Blob)})
  vi.stubGlobal('document',{visibilityState:'visible',createElement:(type:string)=>type==='video'?video:canvas()})
  vi.stubGlobal('window',globalThis); vi.stubGlobal('crypto',{randomUUID:()=>id})
  vi.stubGlobal('navigator',{mediaDevices:{getDisplayMedia:()=>Promise.resolve({getTracks:()=>[track],getVideoTracks:()=>[track]}),getUserMedia:mic}})
  const capture=new ScreenCapture(()=>{}); capture.start(screenDefaults,send); await vi.advanceTimersByTimeAsync(0)
  const ready={...screenDefaults,screen_companion_enabled:true,screen_model_ready:true,systemone_enabled:true,harness_provider:'dsh',conversation_mode:'duplex'}
  expect(screenAvailability(ready,true,true,false)).toBe(screenAvailability(ready,true,false,false))
  expect(track.stop).not.toHaveBeenCalled()
  capture.requestSnapshot({stream_id:id,request_id:'bad'})
  capture.requestSnapshot({stream_id:req,request_id:req})
  capture.requestSnapshot({stream_id:id,request_id:req}); await vi.advanceTimersByTimeAsync(0)
  expect(send.mock.calls.filter(([type])=>type==='voice.screen.snapshot')).toHaveLength(1)
  expect(send).toHaveBeenCalledWith('voice.screen.snapshot',expect.objectContaining({stream_id:id,request_id:req}))
  capture.requestSnapshot({stream_id:id,request_id:req}); await vi.advanceTimersByTimeAsync(0)
  await vi.advanceTimersByTimeAsync(12500)
  expect(send.mock.calls.filter(([type])=>type==='voice.screen.frame')).toHaveLength(1)
  await vi.advanceTimersByTimeAsync(2500)
  expect(send.mock.calls.filter(([type])=>type==='voice.screen.frame')).toHaveLength(2)
  expect(mic).not.toHaveBeenCalled(); capture.stop(); vi.useRealTimers(); vi.unstubAllGlobals()
 })
 it('allows only tool snapshots when automatic requests are disabled and a grant is active', async () => {
  vi.useFakeTimers()
  const id='12345678-1234-4123-8123-123456789abc', req='87654321-1234-4123-8123-123456789abc'
  let ended!:()=>void
  const track={stop:vi.fn(),addEventListener:(_type:string,cb:()=>void)=>{ended=cb}}, send=vi.fn()
  const display=vi.fn(()=>Promise.resolve({getTracks:()=>[track],getVideoTracks:()=>[track]}))
  const video={videoWidth:100,videoHeight:100,play:async()=>{},pause:vi.fn(),remove:vi.fn(),srcObject:null}
  const context={drawImage:vi.fn(),getImageData:()=>({data:new Uint8ClampedArray(32*18*4)})}
  const canvas=()=>({width:0,height:0,getContext:()=>context,toBlob:(cb:(b:Blob)=>void)=>cb({type:'image/jpeg',size:1,arrayBuffer:async()=>new Uint8Array([1]).buffer} as Blob)})
  vi.stubGlobal('document',{createElement:(type:string)=>type==='video'?video:canvas()})
  vi.stubGlobal('window',globalThis); vi.stubGlobal('crypto',{randomUUID:()=>id}); vi.stubGlobal('navigator',{mediaDevices:{getDisplayMedia:display}})
  const capture=new ScreenCapture(()=>{}); capture.start({...screenDefaults,screen_request_enabled:false},send); await vi.advanceTimersByTimeAsync(0)
  for (const purpose of [undefined,'intent','unknown',null]) capture.requestSnapshot({stream_id:id,request_id:req,purpose})
  capture.requestSnapshot({stream_id:req,request_id:req,purpose:'tool'})
  capture.requestSnapshot({stream_id:id,request_id:'bad',purpose:'tool'})
  await vi.advanceTimersByTimeAsync(0)
  expect(send.mock.calls.filter(([type])=>type==='voice.screen.snapshot')).toHaveLength(0)
  capture.requestSnapshot({stream_id:id,request_id:req,purpose:'tool'}); await vi.advanceTimersByTimeAsync(0)
  expect(send).toHaveBeenCalledWith('voice.screen.snapshot',{stream_id:id,request_id:req,seq:2,width:100,height:100,mime_type:'image/jpeg',data:'AQ=='})
  capture.requestSnapshot({stream_id:id,request_id:req,purpose:'tool'}); await vi.advanceTimersByTimeAsync(0)
  ended()
  capture.requestSnapshot({stream_id:id,request_id:'11111111-1234-4123-8123-123456789abc',purpose:'tool'}); await vi.advanceTimersByTimeAsync(0)
  expect(send.mock.calls.filter(([type])=>type==='voice.screen.snapshot')).toHaveLength(1)
  expect(display).toHaveBeenCalledOnce()
  vi.useRealTimers(); vi.unstubAllGlobals()
 })
 it('drops the bounded pending request when stopped during encoding', async () => {
  vi.useFakeTimers()
  const id='12345678-1234-4123-8123-123456789abc', req='87654321-1234-4123-8123-123456789abc'
  let finish!: (b:Blob)=>void
  const track={stop:vi.fn(),addEventListener:vi.fn()}, send=vi.fn()
  const video={videoWidth:100,videoHeight:100,play:async()=>{},pause:vi.fn(),remove:vi.fn(),srcObject:null}
  const context={drawImage:vi.fn(),getImageData:()=>({data:new Uint8ClampedArray(32*18*4)})}
  vi.stubGlobal('document',{visibilityState:'visible',createElement:(type:string)=>type==='video'?video:{width:0,height:0,getContext:()=>context,toBlob:(cb:(b:Blob)=>void)=>{finish=cb}}})
  vi.stubGlobal('window',globalThis); vi.stubGlobal('crypto',{randomUUID:()=>id})
  vi.stubGlobal('navigator',{mediaDevices:{getDisplayMedia:()=>Promise.resolve({getTracks:()=>[track],getVideoTracks:()=>[track]})}})
  const capture=new ScreenCapture(()=>{}); capture.start(screenDefaults,send); await vi.advanceTimersByTimeAsync(0)
  capture.requestSnapshot({stream_id:id,request_id:req}); capture.stop()
  finish({type:'image/jpeg',size:1,arrayBuffer:async()=>new Uint8Array([1]).buffer} as Blob); await vi.advanceTimersByTimeAsync(0)
  expect(send.mock.calls.filter(([type])=>type==='voice.screen.snapshot')).toHaveLength(0)
  vi.useRealTimers(); vi.unstubAllGlobals()
 })
 it('drops a snapshot whose encoding completes after its local deadline', async () => {
  vi.useFakeTimers(); vi.setSystemTime(0)
  const id='12345678-1234-4123-8123-123456789abc', req='87654321-1234-4123-8123-123456789abc'
  const finishes: Array<(b:Blob)=>void> = [], send=vi.fn()
  const track={stop:vi.fn(),addEventListener:vi.fn()}
  const video={videoWidth:100,videoHeight:100,play:async()=>{},pause:vi.fn(),remove:vi.fn(),srcObject:null}
  const context={drawImage:vi.fn(),getImageData:()=>({data:new Uint8ClampedArray(32*18*4)})}
  vi.stubGlobal('document',{visibilityState:'visible',createElement:(type:string)=>type==='video'?video:{width:0,height:0,getContext:()=>context,toBlob:(cb:(b:Blob)=>void)=>finishes.push(cb)}})
  vi.stubGlobal('window',globalThis); vi.stubGlobal('crypto',{randomUUID:()=>id})
  vi.stubGlobal('navigator',{mediaDevices:{getDisplayMedia:()=>Promise.resolve({getTracks:()=>[track],getVideoTracks:()=>[track]})}})
  const blob={type:'image/jpeg',size:1,arrayBuffer:async()=>new Uint8Array([1]).buffer} as Blob
  const capture=new ScreenCapture(()=>{}); capture.start(screenDefaults,send); await vi.advanceTimersByTimeAsync(0)
  finishes.shift()!(blob); await vi.advanceTimersByTimeAsync(0)
  capture.requestSnapshot({stream_id:id,request_id:req})
  expect(finishes).toHaveLength(1)
  await vi.advanceTimersByTimeAsync(2000)
  finishes.shift()!(blob); await vi.advanceTimersByTimeAsync(0)
  expect(send.mock.calls.filter(([type])=>type==='voice.screen.snapshot')).toHaveLength(0)
  capture.stop(); vi.useRealTimers(); vi.unstubAllGlobals()
 })
 it('keeps the newest pending request and bounds the deduplication history', async () => {
  vi.useFakeTimers(); vi.setSystemTime(0)
  const id='12345678-1234-4123-8123-123456789abc'
  const requestId=(n:number)=>`${n.toString(16).padStart(8,'0')}-1234-4123-8123-123456789abc`
  const finishes: Array<(b:Blob)=>void> = [], send=vi.fn()
  const track={stop:vi.fn(),addEventListener:vi.fn()}
  const video={videoWidth:100,videoHeight:100,play:async()=>{},pause:vi.fn(),remove:vi.fn(),srcObject:null}
  const context={drawImage:vi.fn(),getImageData:()=>({data:new Uint8ClampedArray(32*18*4)})}
  vi.stubGlobal('document',{visibilityState:'visible',createElement:(type:string)=>type==='video'?video:{width:0,height:0,getContext:()=>context,toBlob:(cb:(b:Blob)=>void)=>finishes.push(cb)}})
  vi.stubGlobal('window',globalThis); vi.stubGlobal('crypto',{randomUUID:()=>id})
  vi.stubGlobal('navigator',{mediaDevices:{getDisplayMedia:()=>Promise.resolve({getTracks:()=>[track],getVideoTracks:()=>[track]})}})
  const blob={type:'image/jpeg',size:1,arrayBuffer:async()=>new Uint8Array([1]).buffer} as Blob
  const capture=new ScreenCapture(()=>{}); capture.start(screenDefaults,send); await vi.advanceTimersByTimeAsync(0)
  for(let i=1;i<=300;i++) capture.requestSnapshot({stream_id:id,request_id:requestId(i)})
  expect((capture as any).seenRequests.size).toBe(256)
  finishes.shift()!(blob); await vi.advanceTimersByTimeAsync(0)
  expect(finishes).toHaveLength(1)
  finishes.shift()!(blob); await vi.advanceTimersByTimeAsync(0)
  const snapshots=send.mock.calls.filter(([type])=>type==='voice.screen.snapshot')
  expect(snapshots).toHaveLength(1)
  expect(snapshots[0][1]).toEqual(expect.objectContaining({request_id:requestId(300)}))
  capture.requestSnapshot({stream_id:id,request_id:requestId(300)}); await vi.advanceTimersByTimeAsync(0)
  expect(finishes).toHaveLength(0)
  capture.stop(); vi.useRealTimers(); vi.unstubAllGlobals()
 })

})
