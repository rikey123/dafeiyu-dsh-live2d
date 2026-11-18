/** First-run gate only. The existing application's styles and renderer are unchanged. */
export function createPanelMount({loadInstaller=()=>import('/dafeiyu/install-view.js'),loadApp=()=>import('/dafeiyu/entry.js')}={}) {
  return function mountDafeiyu(host,options={}) {
    let disposed=false,installer,app,ready=false,active=options.active;
    const controller=new AbortController(),doc=host.ownerDocument||document;
    const seat=doc.createElement('div');seat.style.cssText='width:100%;height:100%;min-height:0';host.appendChild(seat);
    const fail=()=>{
      if(disposed)return;
      const message=doc.createElement('p');message.textContent='资源加载失败，请重新打开面板或重启插件。';seat.replaceChildren(message);
    };
    const onReady=()=>{
      if(disposed||ready)return;ready=true;
      // The installer has its own shadow host; never reuse it as the app root.
      installer?.dispose();seat.remove();
      Promise.resolve().then(loadApp).then(module=>{
        if(!disposed){app=module.mountDafeiyu(host,{...options,active});app?.setActive?.(active);}
      }).catch(()=>{if(!disposed){host.appendChild(seat);fail();}});
    };
    Promise.resolve().then(loadInstaller).then(module=>{
      if(disposed)return;
      return module.mountInstallView(seat,{onReady,signal:controller.signal});
    }).then(value=>{installer=value;if(disposed||ready)installer?.dispose();}).catch(fail);
    return {
      setActive(value){active=value;app?.setActive?.(value);},
      dispose(){if(disposed)return;disposed=true;controller.abort();installer?.dispose();app?.dispose();seat.remove();},
    };
  };
}
export const mountDafeiyu=createPanelMount();
