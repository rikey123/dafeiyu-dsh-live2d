/* Equal-RMS TTS vowels, real official PCM player, wLipSync and DeepSeek moc. */
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict')
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'../qa/node_modules/playwright')
const out=path.resolve(__dirname,'../artifacts/vowel-acceptance'),base='http://127.0.0.1:8895'
;(async()=>{
  const sequence=JSON.parse(fs.readFileSync(path.join(out,'sequence.json'),'utf8'))
  assert(Math.max(...sequence.map(x=>x.rms))-Math.min(...sequence.map(x=>x.rms))<1)
  const browser=await chromium.launch({channel:'msedge',headless:true})
  const context=await browser.newContext({viewport:{width:1440,height:1000}})
  await context.addInitScript(()=>{
    window.__qaNodes=[];window.__lipFrames=[];window.__offset=0
    const Native=window.AudioWorkletNode
    window.AudioWorkletNode=class extends Native{
      constructor(...args){super(...args);window.__qaNodes.push({name:args[1],node:this})
        this.port.addEventListener('message',event=>{
          const data=event.data
          if(args[1]==='wlipsync-processor')window.__lipFrames.push({at:performance.now(),offset:window.__offset,...data})
          if(data?.event==='offset')window.__offset=data.offset/this.context.sampleRate
        })
      }
    }
    navigator.mediaDevices.getUserMedia=async()=>{throw Error('vowel QA must not capture a microphone')}
  })
  const page=await context.newPage(),errors=[];let session
  page.on('pageerror',error=>errors.push(error.message))
  page.on('response',async response=>{if(response.url().endsWith('/api/sessions')&&response.request().method()==='POST')session=(await response.json()).id})
  try{
    await page.goto(base,{waitUntil:'networkidle'})
    await page.locator('.avatar-canvas[data-model-loaded="true"]').waitFor({timeout:90000})
    await page.evaluate(()=>{
      window.__shapes=[]
      const proto=window.PIXI.utils.EventEmitter.prototype,original=proto.emit
      proto.emit=function(...args){const result=original.apply(this,args)
        if(args[0]==='beforeModelUpdate'&&this.coreModel){const get=id=>this.coreModel.getParameterValueById(id)
          window.__shapes.push({at:performance.now(),offset:window.__offset,open:get('ParamMouthOpenY'),form:get('ParamMouthForm'),pucker:get('Mouthpucker'),funnel:get('MouthFunnel'),wide:get('MouthPuckerWiden')})}
        return result
      }
      window.__sampleClock=setInterval(()=>{for(const item of window.__qaNodes)if(item.name==='stream_processor')item.node.port.postMessage({event:'offset',requestId:'vowel-qa'})},40)
    })
    await page.getByPlaceholder('说点什么，或开启语音...').fill('请发声检查口型。')
    await page.getByRole('button',{name:'发送',exact:true}).click()
    await page.waitForFunction(()=>window.__offset>9.2,null,{timeout:60000})
    const data=await page.evaluate(()=>({shapes:window.__shapes,frames:window.__lipFrames,nodes:window.__qaNodes.map(x=>x.name)}))
    assert(data.nodes.includes('wlipsync-processor'),'wLipSync did not initialize')
    const means=sequence.map(segment=>{
      const samples=data.shapes.filter(x=>x.offset>segment.start+.35&&x.offset<segment.end-.1)
      assert(samples.length>=3,`missing actual playback window ${segment.label}`)
      const average=key=>samples.reduce((sum,x)=>sum+x[key],0)/samples.length
      const counts={};for(const frame of data.frames.filter(x=>x.offset>segment.start+.35&&x.offset<segment.end-.1))counts[frame.name]=(counts[frame.name]||0)+1
      return {...segment,samples:samples.length,open:average('open'),form:average('form'),pucker:average('pucker'),funnel:average('funnel'),wide:average('wide'),classifications:counts}
    })
    const range=key=>Math.max(...means.map(x=>x[key]))-Math.min(...means.map(x=>x[key]))
    assert(range('form')>.015||range('funnel')>.015||range('pucker')>.015,'equal loudness vowels produce identical mouth shapes')
    assert(new Set(means.flatMap(x=>Object.keys(x.classifications))).size>=2,'classifier reduced all vowels to one class')
    assert(means.find(x=>x.label==='U').pucker>.04,'local VITS calibration did not drive U lip pucker')
    assert(means.find(x=>x.label==='I').form>means.find(x=>x.label==='A').form+.04,'I did not widen compared with A at equal RMS')
    await page.getByRole('button',{name:'停止',exact:true}).click()
    await page.waitForTimeout(700)
    const tail=await page.evaluate(()=>window.__shapes.slice(-3))
    assert(tail.every(x=>x.open<.01&&Math.abs(x.form)<.01&&Math.abs(x.pucker)<.01&&Math.abs(x.funnel)<.01),'interruption left vowel pose active')
    assert.deepEqual(errors,[])
    const result={passed:true,method:'Five local VITS vowel fixtures normalized to identical RMS; paced through production Pipecat/official 24k PCM worklet/wLipSync/DeepSeek mouth. Windows sampled by player offset. Tests acoustic shape dependence; does not measure phoneme accuracy or physical AV delay.',means,ranges:{form:range('form'),funnel:range('funnel'),pucker:range('pucker')},errors}
    fs.writeFileSync(path.join(out,'results.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result,null,2))
  }catch(error){await page.screenshot({path:path.join(out,'failure.png')}).catch(()=>{});fs.writeFileSync(path.join(out,'failure.json'),JSON.stringify(await page.evaluate(()=>({nodes:window.__qaNodes.map(x=>x.name),shapes:window.__shapes,frames:window.__lipFrames})),null,2));throw error}
  finally{await context.close();if(session)await fetch(base+'/api/sessions/'+session,{method:'DELETE'}).catch(()=>{});await browser.close()}
})().catch(error=>{console.error(error);process.exitCode=1})
