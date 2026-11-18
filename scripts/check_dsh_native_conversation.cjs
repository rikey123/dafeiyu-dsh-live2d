/* Isolated real-DSH browser acceptance. Native history and UI are real;
 * speech/settings are fixtures. No model, microphone or desktop capture. */
const fs=require('node:fs'), path=require('node:path'), assert=require('node:assert/strict');
const {chromium}=require(process.env.DAFEIYU_QA_MODULES || 'G:/dafeiyu/qa/node_modules/playwright');
(async()=>{
  const dir=process.env.DAFEIYU_NATIVE_QA_DIR || 'E:/Dafeiyu/qa/dsh-native-20261115';
  const temporary=path.join(dir,'tmp');fs.mkdirSync(temporary,{recursive:true});process.env.TEMP=temporary;process.env.TMP=temporary;
  const entry=fs.readFileSync(path.join(dir,'host.log'),'utf8').match(/http:\/\/127\.0\.0\.1:3081\/\?token=[^\s]+/)?.[0];
  assert(entry,'owned isolated host entry missing (never printed)');
  const browser=await chromium.launch({channel:'msedge',headless:true});
  const page=await browser.newPage({viewport:{width:1600,height:1000}}), errors=[],consoleErrors=[];
  page.on('pageerror',error=>errors.push(error.message));
  page.on('console',m=>{if(m.type()==='error')consoleErrors.push(m.text());});
  await page.addInitScript(()=>{
    window.__captures=0;
    for(const method of ['getUserMedia','getDisplayMedia'])if(navigator.mediaDevices)navigator.mediaDevices[method]=async()=>{window.__captures++;throw Error('capture forbidden in fixture');};
  });
  await page.route('**/dafeiyu/api/settings',route=>route.fulfill({status:200,contentType:'application/json',body:fs.readFileSync(path.join(dir,'settings.json'),'utf8')}));
  await page.route('**/dafeiyu/api/models',route=>route.fulfill({status:200,contentType:'application/json',body:'[]'}));
  try {
    await page.goto(entry,{waitUntil:'domcontentloaded'});await page.waitForTimeout(1200);
    for(const name of ['我知道了','开始使用','继续使用','继续','Got it']){
      const button=page.getByRole('button',{name,exact:true});if(await button.count()&&await button.first().isVisible())await button.first().click();
    }
    await page.keyboard.press('Escape');
    await page.getByText('大肥鱼',{exact:true}).first().click({timeout:30000});
    const panel=page.locator('section[aria-label="大肥鱼数字人"]');await panel.waitFor();
    const editor=panel.locator('[contenteditable="true"]').first();await editor.waitFor({timeout:30000});
    const composer=panel.locator('[data-native-conversation="composer"]');
    const options=composer.getByRole('button',{name:'更多聊天选项',exact:true});
    const measure=()=>composer.evaluate(slot=>{
      const shadow=slot.firstElementChild.shadowRoot, input=shadow.querySelector('[data-composer-input]');
      const box=input.getBoundingClientRect(), seat=slot.getBoundingClientRect();
      return {height:seat.height,inputHeight:box.height,fontSize:getComputedStyle(input).fontSize,
        width:seat.width,x:seat.x,right:seat.right,
        symbols:[...shadow.querySelectorAll('use')].every(use=>{
          const ref=use.getAttribute('href')||use.getAttribute('xlink:href');
          return !ref?.startsWith('#')||!!shadow.getElementById(ref.slice(1));
        })};
    });
    const compact=await measure();assert.equal(compact.height,40,'native toolbar must not inflate the original console');
    assert.equal(compact.fontSize,'14px');assert(compact.symbols,'native SVG symbols must work across shadow boundaries');
    await options.click();assert.equal(await options.getAttribute('aria-expanded'),'true');
    const permission=composer.getByRole('button',{name:/访问模式/});assert(await permission.isVisible(),'native permission controls must remain reachable');
    await permission.click();await page.keyboard.press('Escape');
    await options.focus();await page.keyboard.press('Escape');assert.equal(await options.getAttribute('aria-expanded'),'false');
    await composer.getByRole('button',{name:'添加文件或调用指令',exact:true}).click();
    // The original native menu, not a replacement file/command implementation.
    await page.getByRole('listbox').waitFor({timeout:5000});
    await page.keyboard.press('Escape');
    await editor.fill('第一行\n第二行\n第三行');await page.waitForTimeout(100);
    const multiline=await measure();assert(multiline.inputHeight>40&&multiline.inputHeight<=180,'native multiline editor must grow without replacing the console');
    await editor.fill('');
    const session=await panel.locator('[data-conversation-session]').getAttribute('data-conversation-session');assert(session);
    const response=await page.request.get(new URL(`/dafeiyu-fixture?session_id=${encodeURIComponent(session)}`,entry).href);assert.equal(response.status(),200);
    const seeded=await response.json();assert.equal(seeded.nativeNoticeDurable,true);assert.equal(seeded.nativeNoticeDidNotWake,true);assert.equal(seeded.nativePersonaAssembly,true);
    if(process.env.DAFEIYU_QA_SCREEN_OBSERVATION==='1')assert.equal(seeded.nativeScreenObservationDurable,true);
    await panel.getByRole('heading',{name:'原生富内容验收'}).waitFor();
    assert(await panel.locator('pre').count(),'native code renderer missing');assert(await panel.locator('table').count(),'native table renderer missing');
    await editor.fill('保留在 DSH 的草稿');
    await page.getByRole('button',{name:'插件',exact:true}).click();
    await page.getByText('大肥鱼',{exact:true}).first().click();
    await editor.waitFor();assert.equal(await editor.innerText(),'保留在 DSH 的草稿');
    await panel.getByRole('heading',{name:'原生富内容验收'}).waitFor();
    await page.setViewportSize({width:1040,height:768});
    await page.waitForTimeout(300);
    const composerBounds=await editor.boundingBox();assert(composerBounds && composerBounds.x>=0 && composerBounds.x+composerBounds.width<=1041,'native composer overflows narrow viewport');
    assert.equal(await editor.innerText(),'保留在 DSH 的草稿');
    await page.screenshot({path:path.join(dir,'native-conversation-narrow.png'),fullPage:true});
    await page.setViewportSize({width:640,height:800});await page.waitForTimeout(200);
    const mobile=await measure();assert(mobile.x>=0&&mobile.right<=641&&mobile.width>=140,'mobile console must fit and remain usable');
    await options.click();assert(await permission.isVisible());await options.click();
    await page.screenshot({path:path.join(dir,'native-conversation-mobile.png'),fullPage:true});
    await page.setViewportSize({width:1600,height:1000});await page.waitForTimeout(100);
    assert.equal(await page.evaluate(()=>window.__captures),0);
    await page.screenshot({path:path.join(dir,'native-conversation.png'),fullPage:true});
    await panel.getByRole('button',{name:/切换主题/}).click();await page.waitForTimeout(150);
    assert.equal((await measure()).height,40);
    await page.screenshot({path:path.join(dir,'native-conversation-replicant.png'),fullPage:true});
    const report={nativeDSH:true,richMarkdown:true,code:true,table:true,nativeComposer:true,compactConsole:true,nativeOptionsReachable:true,nativeIcons:true,mobileComposerFits:true,bothThemes:true,draftSurvivesPanelSwitch:true,narrowComposerFits:true,nativeNoticeDurable:seeded.nativeNoticeDurable,nativeNoticeDidNotWake:seeded.nativeNoticeDidNotWake,nativePersonaAssembly:seeded.nativePersonaAssembly,nativeScreenObservationDurable:seeded.nativeScreenObservationDurable,captures:0,modelRequests:0,pageErrors:errors,consoleErrors};
    fs.writeFileSync(path.join(dir,'browser-report.json'),JSON.stringify(report,null,2));
    console.log(JSON.stringify(report,null,2));assert.equal(errors.length,0);
  }catch(error){
    await page.screenshot({path:path.join(dir,'failure.png'),fullPage:true}).catch(()=>{});
    const text=await page.locator('body').innerText();
    fs.writeFileSync(path.join(dir,'browser-failure.json'),JSON.stringify({message:error.message,errors,consoleErrors,text},null,2));
    // URLs and query parameters may contain the owner token, never echo them.
    throw Error(error.message.replace(/https?:\/\/[^\s)]+/g,'[URL redacted]'));
  }finally{await browser.close();}
})().catch(error=>{console.error(error.message);process.exitCode=1;});
