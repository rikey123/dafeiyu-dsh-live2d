import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import vm from 'node:vm';

const source = await readFile(new URL('../src/client.js', import.meta.url), 'utf8');
const tick = () => new Promise(resolve => setImmediate(resolve));
function fixture() {
  const state = {loads:0,mounts:[],active:[],disposals:0,retains:0,releases:0,subscribers:new Set(),activePanelId:'dafeiyu-live2d',observers:[],symbols:new Map()};
  let definition, panel, nativeConversation, dispose, resolve, reject;
  const node = () => ({style:{},dataset:{},attributes:{},events:{},children:[],parentNode:null,
    setAttribute(key,value){this.attributes[key]=value;},getAttribute(key){return this.attributes[key]??null;},
    addEventListener(key,fn){this.events[key]=fn;},focus(){this.focused=true;},querySelectorAll(){return [];},
    append(...children){for(const child of children)this.appendChild(child);},replaceChildren(){this.children=[];},
    attachShadow(){return this.shadowRoot=node();},appendChild(child) {child.remove();child.parentNode=this;this.child=child;this.children.push(child);},
    remove() {if(this.parentNode){this.parentNode.children=this.parentNode.children.filter(child=>child!==this);if(this.parentNode.child===this)this.parentNode.child=null;}this.parentNode=null;}});
  const entry = {mountDafeiyu(host, options) {state.mounts.push({host,options});return {setActive:value=>state.active.push(value),dispose:()=>state.disposals++};}};
  const context = {
    window:{__ModuleLoader__:{load:value=>{definition=value;}}},document:{createElement:node,createElementNS:node,getElementById:id=>state.symbols.get(id),head:{querySelectorAll:()=>[]}},
    MutationObserver:class {constructor(callback){this.callback=callback;state.observers.push(this);}observe(target){this.target=target;}disconnect(){this.disconnected=true;}},
    __loadEntry:()=>{state.loads++;return new Promise((yes,no)=>{resolve=yes;reject=no;});},
  };
  // Replace only the ESM transport seam. All retention/ownership logic is real.
  vm.runInNewContext(source.replace("import('/dafeiyu/panel-entry.js')", '__loadEntry()'),context);
  definition.factory(()=>({createElement(){},createContext(){return {};}})).apply({
    sessions:{retain(){state.retains++;if(state.failRetain)throw Error('offline');return {ready:state.rejectReady ? Promise.reject(Error('offline')) : Promise.resolve(),release(){state.releases++;}};}},
    layout:{panelInfo:{subscribe(fn){state.subscribers.add(fn);return()=>state.subscribers.delete(fn);},getSnapshot:()=>state}},
    on(name,fn){assert.equal(name,'dispose');dispose=fn;},
    effect(factory){for(const unused of factory())void unused;},
    slots:{inject(_name,callback){return callback();},register(options){if(options.key==='dafeiyu-live2d')({panel,nativeConversation}=options.inject());return()=>{};}},
  });
  return {state,node,panel,nativeConversation,dispose,loaded:()=>resolve(entry),failed:()=>reject(Error('offline')),setActive(value){state.activePanelId=value?'dafeiyu-live2d':null;for(const fn of state.subscribers)fn();}};
}

test('keyed DSH page unmount/remount reattaches the same host and application exactly once', async () => {
  const f=fixture(), first=f.node(), second=f.node();
  const detach=f.panel.attach(first);f.loaded();await tick();
  const host=first.child;
  f.setActive(false);detach();
  assert.equal(host.parentNode,null);assert.equal(f.state.active.at(-1),false);assert.equal(f.state.disposals,0);
  f.setActive(true);const detachAgain=f.panel.attach(second);
  assert.equal(second.child,host);assert.equal(f.state.mounts.length,1);assert.equal(f.state.loads,1);assert.equal(f.state.active.at(-1),true);
  detach();assert.equal(second.child,host,'stale cleanup cannot detach the current page');
  detachAgain();f.dispose();f.dispose();
  assert.equal(f.state.disposals,1);assert.equal(f.state.subscribers.size,0);
});

test('late import while away waits for a new page and does not start a hidden application', async () => {
  const f=fixture();f.panel.attach(f.node())();f.loaded();await tick();
  assert.equal(f.state.mounts.length,0);
  f.panel.attach(f.node());assert.equal(f.state.mounts.length,1);f.dispose();
});

test('plugin disposal during import never publishes a late app or listener', async () => {
  const f=fixture();f.panel.attach(f.node());f.dispose();f.loaded();await tick();
  assert.equal(f.state.mounts.length,0);assert.equal(f.state.subscribers.size,0);
  f.panel.attach(f.node());assert.equal(f.state.loads,1);
});

test('load failures are visible and a later page retries without duplicate ownership', async () => {
  const f=fixture(), errors=[];const unsubscribe=f.panel.subscribe(value=>errors.push(value));
  const detach=f.panel.attach(f.node());f.failed();await tick();
  assert(errors.at(-1));detach();f.panel.attach(f.node());f.loaded();await tick();
  assert.equal(errors.at(-1),'');assert.equal(f.state.mounts.length,1);
  unsubscribe();f.dispose();
});

for (const mode of ['failRetain','rejectReady']) test(`same native session can retry after ${mode}`, async () => {
  const f=fixture();f.state[mode]=true;
  const first=f.nativeConversation.mount(f.node(),'session','messages');await tick();
  assert(f.nativeConversation.getSnapshot().error);
  f.state[mode]=false;
  f.nativeConversation.retry();await tick();
  assert.equal(f.state.retains,2);assert(f.nativeConversation.getSnapshot().binding);
  assert.equal(f.nativeConversation.getSnapshot().error,'');first();f.dispose();
});

test('native composer keeps one editor and reveals native options without changing the session', async () => {
  const f=fixture(), container=f.node();
  const detach=f.nativeConversation.mount(container,'session','composer');await tick();
  const shadow=container.child.shadowRoot;
  const theme=shadow.children.find(child=>child.textContent?.includes('[data-composer-card]'));
  const shell=shadow.children.at(-1), [content,toggle]=shell.children;
  assert.match(theme.textContent,/grid-template-columns:minmax\(0,1fr\) 32px 32px 46px/);
  assert.match(theme.textContent,/font:14px\/22px/);
  assert.match(theme.textContent,/data-options-open="true"/);
  assert.equal(toggle.getAttribute('aria-expanded'),'false');
  toggle.events.click();
  assert.equal(toggle.getAttribute('aria-expanded'),'true');
  assert.equal(content.dataset.optionsOpen,'true');
  shell.events.keydown({key:'Escape'});
  assert.equal(toggle.getAttribute('aria-expanded'),'false');assert.equal(toggle.focused,true);
  assert.equal(f.state.retains,1,'a style disclosure cannot replace or submit the native session');
  assert.equal(f.nativeConversation.getSnapshot().composer,content);
  detach();f.dispose();
  assert(f.state.observers.every(observer=>observer.disconnected));
});

test('native icon references are mirrored once, without rescanning text-stream mutations', async () => {
  const f=fixture(), container=f.node();
  const detach=f.nativeConversation.mount(container,'session','messages');await tick();
  const shadow=container.child.shadowRoot, content=f.nativeConversation.getSnapshot().messages;
  const observer=f.state.observers.find(observer=>observer.target===content);
  const clone=f.node(), symbol={localName:'symbol',cloneNode:()=>clone};f.state.symbols.set('native-plus',symbol);
  const use=f.node();use.nodeType=1;use.localName='use';use.setAttribute('href','#native-plus');
  observer.callback([{type:'childList',addedNodes:[use]}]);
  const sprite=shadow.children.find(child=>child.children.includes(clone));assert(sprite);
  observer.callback([{type:'attributes',target:use}]);assert.equal(sprite.children.length,1);
  observer.callback([{type:'childList',addedNodes:[{nodeType:3}]}]);
  assert.equal(sprite.children.length,1,'streamed text does not touch icon state');
  detach();f.dispose();assert(f.state.observers.every(observer=>observer.disconnected));
});
