/* DSH's documented closure-factory format. React is the DSH module-table singleton.
 * The existing application remains a separate, isolated React root, never an iframe. */
window.__ModuleLoader__.load({
  id: '@dafeiyu/dsh-live2d',
  factory(require) {
    const React = require('react');
    const {createPortal} = require('react-dom');
    const PANEL = 'dafeiyu-live2d';
    const h = React.createElement;
    // DSH's keyed main slot unmounts a page when another panel wins. The
    // plugin, not that transient slot, owns this single retained application.
    function retainPanel({subscribeActive, isActive, nativeConversation}) {
      let target, host, app, entry, loading, disposed = false, error = '', attachment = 0;
      const listeners = new Set();
      const publish = value => { error = value; for (const listener of listeners) listener(error); };
      // setActive is visual visibility, not interaction ownership. Detach must
      // not interrupt speech or revoke already granted capture permissions.
      const sync = () => app?.setActive?.(!!target && isActive());
      const unsubscribe = subscribeActive(sync);
      const ensure = () => {
        if (disposed || !target || app) return;
        if (entry) {
          try {
            app = entry.mountDafeiyu(host, {apiBase: '/dafeiyu', assetBase: '/dafeiyu', harnessProvider: 'dsh', active: isActive(), nativeConversation});
            sync();
          } catch { publish('数字人资源加载失败，请检查插件构建与本地语音服务。'); }
          return;
        }
        if (!loading) {
          publish('');
          loading = import('/dafeiyu/panel-entry.js').then(module => {
            loading = undefined;
            if (disposed) return;
            entry = module; ensure();
          }).catch(() => {
            loading = undefined;
            if (!disposed) publish('数字人资源加载失败，请检查插件构建与本地语音服务。');
          });
        }
      };
      return {
        subscribe(listener) { listeners.add(listener); listener(error); return () => listeners.delete(listener); },
        attach(container) {
          if (disposed) return () => {};
          const lease = ++attachment;
          if (!host) { host = document.createElement('div'); Object.assign(host.style, {width: '100%', height: '100%', minHeight: '0'}); }
          target = container; container.appendChild(host); sync(); ensure();
          return () => {
            if (target !== container || lease !== attachment) return;
            target = undefined; sync(); host.remove();
          };
        },
        dispose() {
          if (disposed) return;
          disposed = true; target = undefined; unsubscribe(); listeners.clear();
          app?.dispose(); host?.remove(); app = undefined; entry = undefined; host = undefined;
        },
      };
    }
    // Native CSS stays in its own shadow scopes, never resetting the Live2D
    // application's styles. Mirror runtime-owned styles (including late plugin
    // styles) rather than vendoring a fork of DSH's renderer or CSS modules.
    function nativeSurface(container, target) {
      const host = document.createElement('div');
      host.className = 'dafeiyu-native-host';
      host.style.cssText = `width:100%;height:${target === 'composer' ? 'auto' : '100%'};min-height:0;align-self:flex-end`;
      const shadow = host.attachShadow({mode:'open'});
      const styles = document.createElement('div');
      const content = document.createElement('div');
      content.className = `dafeiyu-native-${target}`;
      const theme = document.createElement('style');
      theme.textContent = `
        :host {
          color:var(--ink); font-family:inherit; --dsh-chat-reading-width:100%;
          --dsw-alias-label-primary:var(--ink); --dsw-alias-label-primary-bluish:var(--ink);
          --dsw-alias-label-primary-dimmed:var(--dim); --dsw-alias-label-secondary:var(--dim);
          --dsw-alias-label-tertiary:var(--faint); --dsw-alias-label-caption:var(--dim);
          --dsw-alias-bg-base:var(--bg); --dsw-alias-bg-layer-1:var(--field);
          --dsw-alias-bg-layer-2:var(--field); --dsw-alias-bg-module-platform:var(--field);
          --dsw-alias-markdown-code-block:var(--field); --dsw-specific-input-major:var(--field);
          --dsw-alias-border-l1:var(--line); --dsw-alias-border-l2:var(--line);
          --dsw-alias-border-l3:var(--line); --dsw-alias-border-l4:var(--line-strong);
          --dsw-alias-state-business-primary:var(--accent); --dsw-alias-brand-primary:var(--accent);
          --dsw-alias-interactive-bg-hover:color-mix(in srgb,var(--ink) 9%,transparent);
          --dsh-font-family-text:var(--font-cjk); --dsw-font-family:var(--font-cjk);
          --dsw-radius-panel:var(--radius); --dsw-radius-lg:var(--radius); --dsw-radius-xl:var(--radius);
          --dsh-composer-card-max-width:100%; --dsh-composer-side-clearance:0px;
          --dsh-composer-text-max-height:180px;
        }
        *,*::before,*::after { box-sizing:border-box; }
        .dafeiyu-native-messages { height:100%; min-height:0; overflow:auto; scrollbar-width:thin; }
        .dafeiyu-native-composer { min-width:0; }
        [data-conversation-content] { background:transparent!important; min-height:0!important; height:auto!important; }
        [data-conversation-scroll] { padding:0!important; overflow:visible!important; min-height:0!important; }
        [data-composer-seat] { position:relative!important; padding:0!important; margin:0!important; }
        .dafeiyu-native-messages > * { min-height:0; }
        /* Keep the native editor, attachments, menus and submission; only its
           visual seat adopts the original 40px cinematic console. rc1's data
           hooks scope the few structural CSS-module suffixes, never hashes. */
        .dafeiyu-native-composer { position:relative; z-index:0; font:14px/22px var(--font-cjk); }
        .dafeiyu-native-composer [data-conversation-content],
        .dafeiyu-native-composer [data-conversation-scroll],
        .dafeiyu-native-composer [data-composer-seat],
        .dafeiyu-native-composer [class$="_composerStack"] {
          width:100%!important; min-width:0!important; border:0!important; gap:0!important;
        }
        .dafeiyu-native-composer [class$="_root"]:has(> [data-composer-card]) {
          display:flex!important; flex-direction:column-reverse; padding:0!important; margin:0!important; gap:0!important;
        }
        .dafeiyu-native-composer [data-composer-card] {
          position:relative; display:grid!important; grid-template-columns:minmax(0,1fr) 32px 32px 46px;
          grid-template-rows:auto auto auto minmax(40px,auto); width:100%!important; min-width:0!important;
          min-height:40px!important; margin:0!important; padding:0!important; gap:0!important;
          border:0!important; border-radius:0!important; background:transparent!important; box-shadow:none!important;
        }
        .dafeiyu-native-composer [data-composer-card] > [class$="_row"],
        .dafeiyu-native-composer [data-composer-card] [class$="_tools"],
        .dafeiyu-native-composer [data-composer-card] [class$="_trailing"] { display:contents!important; }
        .dafeiyu-native-composer [data-input-scroll] {
          grid-area:4 / 1; min-width:0; min-height:40px!important; max-height:min(180px,40vh)!important;
          margin:0!important; padding:0!important; scrollbar-width:thin;
        }
        .dafeiyu-native-composer [data-input-scroll] > div { min-height:40px!important; }
        .dafeiyu-native-composer [data-composer-input] {
          min-height:40px!important; padding:9px 14px!important; font:14px/22px var(--font-cjk)!important;
          color:var(--ink-strong)!important; outline:none!important; overflow-wrap:anywhere;
        }
        .dafeiyu-native-composer [data-composer-input] p { margin:0!important; }
        .dafeiyu-native-composer [data-composer-placeholder] {
          top:9px!important; left:14px!important; right:6px!important; padding:0!important;
          font:14px/22px var(--font-cjk)!important; color:var(--faint)!important;
          white-space:nowrap; overflow:hidden; text-overflow:ellipsis;
        }
        .dafeiyu-native-composer [data-composer-card]:has([data-phase="plain"]) [data-composer-placeholder] { font-size:0!important; }
        .dafeiyu-native-composer [data-composer-card]:has([data-phase="plain"]) [data-composer-placeholder]::after {
          content:'说点什么，或开启语音…'; font:14px/22px var(--font-cjk);
        }
        .dafeiyu-native-composer [data-slot="conversation.input.attachments"] { grid-area:2 / 1 / 3 / -1; min-width:0; }
        .dafeiyu-native-composer [data-composer-overlay] { grid-column:1 / -1; }
        .dafeiyu-native-composer button { font-family:var(--font-cjk); }
        .dafeiyu-native-composer [data-composer-card] button[class$="_add"] {
          grid-area:4 / 2; align-self:end; width:32px!important; height:40px!important;
          border:0!important; border-radius:0!important; background:transparent!important; color:var(--dim)!important;
        }
        .dafeiyu-native-composer [data-composer-card] button[class$="_primary"] {
          grid-area:4 / 4; align-self:end; width:46px!important; height:40px!important; margin:0!important;
          border:0!important; border-left:1px solid var(--line)!important; border-radius:0!important;
          background:var(--accent)!important; color:var(--accent-ink)!important; box-shadow:none!important;
        }
        .dafeiyu-native-composer [data-composer-card] button[class$="_primary"]:disabled {
          background:transparent!important; color:var(--faint)!important; opacity:1!important;
        }
        .dafeiyu-native-composer [data-composer-card] [class$="_modes"],
        .dafeiyu-native-composer [data-composer-card] [class$="_standardControls"],
        .dafeiyu-native-composer [data-composer-dock] { display:none!important; }
        .dafeiyu-native-composer[data-options-open="true"] [data-composer-card] {
          background:var(--panel-solid)!important; box-shadow:0 -1px 0 var(--line),1px 0 0 var(--line),-1px 0 0 var(--line)!important;
        }
        .dafeiyu-native-composer[data-options-open="true"] [data-composer-card] [class$="_modes"] {
          display:flex!important; grid-area:1 / 1 / 2 / -1; justify-self:start; align-self:center; z-index:1;
          padding:4px; min-height:36px;
        }
        .dafeiyu-native-composer[data-options-open="true"] [data-composer-card] [class$="_standardControls"] {
          display:flex!important; grid-area:1 / 1 / 2 / -1; justify-content:flex-end; flex-wrap:wrap;
          min-width:0; min-height:36px; margin-left:50px; padding:4px 8px; gap:4px;
        }
        .dafeiyu-native-composer[data-options-open="true"] [data-composer-card] [class$="_standardControls"] button {
          max-width:100%; color:var(--dim)!important; font:12px/20px var(--font-cjk)!important;
        }
        .dafeiyu-native-composer[data-options-open="true"] [data-composer-dock] {
          display:flex!important; min-height:0!important; padding:4px 8px; background:var(--panel-solid);
          border:1px solid var(--line); border-bottom:0; font:11px/18px var(--font-mono); color:var(--faint);
        }
        .dafeiyu-native-composer [data-composer-card] [class$="_activity"] {
          grid-area:3 / 1 / 4 / -1; justify-self:end; font:12px/20px var(--font-cjk);
        }
        .dafeiyu-composer-options {
          position:absolute; right:46px; bottom:0; z-index:2; width:32px; height:40px; padding:0;
          border:0; border-radius:0; background:transparent; color:var(--dim); cursor:pointer;
          font:600 18px/1 var(--font-mono); letter-spacing:1px;
        }
        .dafeiyu-composer-options:hover, .dafeiyu-composer-options[aria-expanded="true"],
        .dafeiyu-native-composer [data-composer-card] button[class$="_add"]:hover {
          background:color-mix(in srgb,var(--ink) 9%,transparent)!important; color:var(--ink-strong)!important;
        }
        .dafeiyu-composer-options:focus-visible { outline:2px solid var(--accent); outline-offset:-3px; }
        .dafeiyu-native-composer [hidden] { display:none!important; }
      `;
      // SVG <use> cannot resolve document-level symbols across a ShadowRoot.
      // Mirror only referenced native icons, including those added by plugins.
      const sprite = document.createElementNS('http://www.w3.org/2000/svg','svg');
      sprite.style.cssText='position:absolute;width:0;height:0;overflow:hidden;pointer-events:none';
      sprite.setAttribute('aria-hidden','true');
      const icons = new Set();
      const mirrorIcon = use => {
        const ref = use.getAttribute('href') || use.getAttribute('xlink:href');
        if (!ref?.startsWith('#') || icons.has(ref)) return;
        const symbol = document.getElementById(ref.slice(1));
        if (symbol?.localName !== 'symbol') return;
        sprite.appendChild(symbol.cloneNode(true)); icons.add(ref);
      };
      const syncIcons = records => {
        // Text streaming must not rescan an entire conversation on every token.
        for (const record of records) {
          if (record.type === 'attributes') { mirrorIcon(record.target); continue; }
          for (const node of record.addedNodes) {
            if (node.nodeType !== 1) continue;
            if (node.localName === 'use') mirrorIcon(node);
            for (const use of node.querySelectorAll('use')) mirrorIcon(use);
          }
        }
      };
      const syncStyles = () => {
        const clones = [...document.head.querySelectorAll('style,link[rel="stylesheet"]')].map(node => node.cloneNode(true));
        styles.replaceChildren(...clones);
      };
      syncStyles(); shadow.append(styles, theme, sprite, content); container.appendChild(host);
      if (target === 'composer') {
        const toggle = document.createElement('button');
        toggle.className = 'dafeiyu-composer-options'; toggle.type = 'button'; toggle.textContent = '···';
        toggle.setAttribute('aria-label','更多聊天选项'); toggle.setAttribute('aria-expanded','false');
        toggle.title = '模型、权限与聊天选项';
        toggle.addEventListener('click', () => {
          const open = toggle.getAttribute('aria-expanded') !== 'true';
          toggle.setAttribute('aria-expanded',String(open)); content.dataset.optionsOpen = String(open);
        });
        // Outside the portal's owned content; React can reconcile its editor
        // normally. This is a visual disclosure, never a second composer.
        const shell = document.createElement('div'); shell.style.cssText='position:relative;width:100%;min-width:0';
        shadow.appendChild(shell); shell.append(content,toggle);
        shell.addEventListener('keydown', event => {
          if (!event.defaultPrevented && event.key === 'Escape' && toggle.getAttribute('aria-expanded') === 'true') {
            toggle.setAttribute('aria-expanded','false'); content.dataset.optionsOpen='false'; toggle.focus();
          }
        });
      }
      const observer = new MutationObserver(syncStyles);
      observer.observe(document.head, {childList:true, subtree:true, characterData:true, attributes:true, attributeFilter:['href','media','disabled']});
      const iconObserver = new MutationObserver(syncIcons);
      iconObserver.observe(content, {childList:true, subtree:true, attributes:true, attributeFilter:['href','xlink:href']});
      return {content, dispose() { observer.disconnect(); iconObserver.disconnect(); host.remove(); }};
    }
    function nativeBridge(sessions) {
      let snapshot = {}, reference, serial = 0, disposed = false;
      const surfaces = new Set();
      const listeners = new Set(), seats = new Map();
      const publish = patch => { snapshot = {...snapshot,...patch}; for (const fn of listeners) fn(); };
      const retain = sessionId => {
        const generation = ++serial;
        reference?.release(); reference = undefined;
        publish({sessionId, binding:undefined, error:''});
        try {
          reference = sessions.retain(sessionId, {source:'dafeiyuConversation'});
          const ownedReference = reference;
          reference.ready.then(() => {
            if (!disposed && generation === serial) publish({binding:ownedReference});
          }, () => { if (!disposed && generation === serial) publish({error:'DSH 会话加载失败，请重试。'}); });
        } catch { publish({error:'DSH 会话加载失败，请重试。'}); }
      };
      return {
        subscribe(fn) { listeners.add(fn); return () => listeners.delete(fn); },
        getSnapshot:() => snapshot,
        retry() { if (!disposed && snapshot.sessionId && snapshot.error) retain(snapshot.sessionId); },
        mount(container, sessionId, target) {
          if (disposed) return () => {};
          if (snapshot.sessionId !== sessionId || snapshot.error) retain(sessionId);
          const surface = nativeSurface(container,target), lease = {};
          surfaces.add(surface);
          seats.set(target, lease); publish({[target]:surface.content});
          return () => {
            surface.dispose();
            surfaces.delete(surface);
            if (seats.get(target) === lease) { seats.delete(target); publish({[target]:undefined}); }
          };
        },
        dispose() {
          if (disposed) return;
          disposed = true; ++serial; reference?.release(); reference = undefined; listeners.clear(); seats.clear();
          for (const surface of surfaces) surface.dispose(); surfaces.clear();
        },
      };
    }
    const MessageSeat = React.createContext(null);
    function NativeMessages({renderSlot}) {
      const target = React.useContext(MessageSeat);
      return target ? createPortal(renderSlot('conversation.session', {}), target) : null;
    }
    function NativeSessionContent({messageTarget, composerTarget, renderFactorySlot}) {
      return h(MessageSeat.Provider, {value:messageTarget}, createPortal(
        renderFactorySlot('conversation.content', {variant:'embedded', hero:false, phase:'active'}, {slots:{views:NativeMessages}}), composerTarget));
    }
    function NativeConversation({nativeConversation, SessionProvider, renderSlot}) {
      const state = React.useSyncExternalStore(nativeConversation.subscribe, nativeConversation.getSnapshot);
      if (state.error && state.messages) return createPortal(h('div',{role:'alert'},state.error,
        h('button',{type:'button',onClick:() => nativeConversation.retry()},'重试')), state.messages);
      if (!state.binding || !state.messages || !state.composer) return null;
      // Complete native content Factory: history, plugin renderers, attachments,
      // approvals, interactions, queue dock, editor and submission all stay native.
      // Only the two visual seats differ; no copied ChatView or content switch.
      return h(SessionProvider, {session:state.binding},
        renderSlot('dafeiyu.native.session', {messageTarget:state.messages, composerTarget:state.composer}));
    }
    function DafeiyuPage({panel, nativeConversation, SessionProvider, renderSlot}) {
      const host = React.useRef(null);
      const [error, setError] = React.useState('');
      React.useEffect(() => {
        const unsubscribe = panel.subscribe(setError), detach = panel.attach(host.current);
        return () => { unsubscribe(); detach(); };
      }, [panel]);
      return h('section', {style: {position: 'relative', width: '100%', height: '100%', minHeight: 0, overflow: 'hidden'}, 'aria-label': '大肥鱼数字人'},
        error ? h('div', {role: 'alert', style: {padding: 24}}, error) : null,
        h('div', {ref: host, style: {width: '100%', height: '100%', minHeight: 0}}),
        h(NativeConversation, {nativeConversation, SessionProvider, renderSlot}));
    }
    function FishIcon() {
      return h('svg', {viewBox: '0 0 24 24', width: 20, height: 20, fill: 'none', stroke: 'currentColor', strokeWidth: 1.7, 'aria-hidden': true},
        h('path', {d: 'M3 12c5-8 12-8 16 0-4 8-11 8-16 0zm0 0L1 7v10l2-5M14 9v.1'}));
    }
    return {
      name: 'dafeiyu-live2d-client',
      inject: ['slots', 'layout', 'sessions', 'uiConversation'],
      apply(ctx) {
        const subscribeActive = listener => ctx.layout.panelInfo.subscribe(listener);
        const isActive = () => ctx.layout.panelInfo.getSnapshot().activePanelId === PANEL;
        const nativeConversation = nativeBridge(ctx.sessions);
        const panel = retainPanel({subscribeActive, isActive, nativeConversation});
        ctx.on('dispose', () => { panel.dispose(); nativeConversation.dispose(); });
        ctx.effect(function* () {
          yield ctx.slots.inject('main', () => ctx.slots.register({name: 'main', key: PANEL,
            children:{'dafeiyu.native.session':{kind:'single',scope:'session'}},
            inject: () => ({panel,nativeConversation})}, DafeiyuPage));
          yield ctx.slots.register({name:'dafeiyu.native.session'}, NativeSessionContent);
          yield ctx.slots.inject('sidebar.panellist', () => ctx.slots.register({name: 'sidebar.panellist', id: PANEL, order: 15, label: () => '大肥鱼'}, FishIcon));
        });
      },
    };
  },
});
