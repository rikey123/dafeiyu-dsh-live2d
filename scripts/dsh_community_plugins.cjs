const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const { spawnSync } = require('node:child_process');
const ROOT = 'E:/Dafeiyu/research/dsh-community-plugins/2026-11-14';
const WORK = 'E:/Dafeiyu/dsh-community-installer';
const BEGIN = '# BEGIN DAFEIYU COMMUNITY PLUGINS';
const END = '# END DAFEIYU COMMUNITY PLUGINS';
const DATA = 'E:/Dafeiyu/dsh-community/data';
const NAMES = ['fish-memory','fish-memory-backup','bili-duty','soul-md','attachments'];
const PACKAGES = [
 ['dsh-soul-md','0.12.3','dsh-soul-md-0.12.3.tgz','6218c987e1326ac372a70bc2cf6d19e6646b1ae87577ba46777ec93e1755912d','sha512-qsTPgLN+uJmKeMuRtgu3QJ6bKk/hi2LmdrrRfHyW2PSmjT1zypoMAS0URBPlc/Dm6F2ibmc3bvFLv6OD2cWONA==','index.js'],
 ['dsh-fish-memory','1.6.1','dsh-fish-memory-1.6.1.tgz','edeb3ce059a4738b765f5d172733ba3ad84901c5758da4d95eb8f2d6f0a3d9a3','sha512-iZG/ZCCwYOxfbuAAZKcAIpSqZ8tneWrPn9pTLIR6qOrWKD4WvdAHfPUjSaZydFqUBPyCjHcvhn21m/3uhfinzA==','lib/index.js'],
 ['dsh-bili-subagent','1.0.1','dsh-bili-subagent-1.0.1.tgz','89efd05fb0a1d117d4ebc42531e9de4dfc2a9e512b2b6a9af11e8589ed0b9d4b','sha512-FuhQ11kMVPx2UL7xJWje8eTcExkDzMBTlaEyrLzW/pMIm2ftXxwoTj5Nmi4ArAhHKQBVw3xUXJvoIKJ/OTsTAA==','index.js'],
 ['@tencent-connect/dsh-qqbot','0.5.5','@tencent-connect--dsh-qqbot-0.5.5.tgz','f9442c91e29d1dcae47eca8dba84beb214b310fe5d067ddfb98b4bd47bae1048','sha512-E15Du9xWfWk7CffRba8/ADHV9l6t9kDQ+U3ImLmB5Ffpnbwsm5ovYtHlhiENlILaqx0r+46cSxBiqhmu9Lz+IA==','lib/index.js']
];
function verify(dir, packages = PACKAGES) {
 return packages.map(([name,version,file,sha,sri,entry]) => {
  const p = path.join(dir,file), b = fs.readFileSync(p);
  if (crypto.createHash('sha256').update(b).digest('hex') !== sha || 'sha512-'+crypto.createHash('sha512').update(b).digest('base64') !== sri) throw Error(`Artifact mismatch: ${name}@${version}`);
  return {name,version,file:p,entry};
 });
}
function positions(s) {
 const a=s.indexOf(BEGIN), b=s.indexOf(END);
 if ((a<0)!==(b<0) || (a>=0 && (b<a || s.indexOf(BEGIN,a+1)>=0 || s.indexOf(END,b+1)>=0))) throw Error('Invalid or duplicate community markers');
 return [a,b];
}
function addBlock(original, entries) {
 if (positions(original)[0]>=0) throw Error('Community block already exists');
 // Do not claim a sequence can be appended to an unknown YAML shape.
 if (!/^\s*(?:#.*(?:\r?\n|$)\s*)*(?:\[\]\s*)?$/.test(original) && !/^(?:[ \t]*(?:#.*)?\r?\n)*-\s/.test(original)) throw Error('Unsupported patch format; inspect manually');
 const empty = /^\s*(?:#.*(?:\r?\n|$)\s*)*\[\]\s*$/.test(original);
 const prefix = original;
 const separator = prefix && !prefix.endsWith('\n') ? '\n' : '';
 // Commented entries are intentionally inert, independent of loader condition semantics.
 const lines = entries.map(e => `# inactive ${e.name}@${e.version}: ${path.join(e.installDir,'node_modules',e.name,e.entry).replace(/\\/g,'/')}`);
 const meta = Buffer.from(JSON.stringify({empty:null, separator, entriesHash:crypto.createHash('sha256').update(lines.join('\n')).digest('hex')})).toString('base64');
 return prefix+separator+BEGIN+'\n# metadata '+meta+'\n'+lines.join('\n')+'\n'+END+'\n';
}
function removeBlock(s) {
 const [a,b]=positions(s); if(a<0) return s;
 const endLine=b+END.length; if(s.slice(endLine,endLine+1)!=='\n') throw Error('Modified community block');
 const block=s.slice(a,endLine+1), m=block.match(/^# metadata ([A-Za-z0-9+/=]+)$/m);
 if(!m || !/^# BEGIN DAFEIYU COMMUNITY PLUGINS\n# metadata [A-Za-z0-9+/=]+\n(?:# inactive [^\n]+\n)*# END DAFEIYU COMMUNITY PLUGINS\n$/.test(block)) throw Error('Modified community block; inspect manually');
 const meta=JSON.parse(Buffer.from(m[1],'base64').toString());
 const entryLines=block.split('\n').filter(line=>line.startsWith('# inactive ')).join('\n');
 if (crypto.createHash('sha256').update(entryLines).digest('hex')!==meta.entriesHash) throw Error('Modified community block; inspect manually');
 let prefix=s.slice(0,a), suffix=s.slice(endLine+1);
 if(meta.separator) { if(!prefix.endsWith(meta.separator)) throw Error('Separator changed'); if(!suffix) prefix=prefix.slice(0,-meta.separator.length); }
 if(meta.empty!==null) { if(prefix || suffix) throw Error('Originally empty patch has since changed; inspect manually'); return meta.empty; }
 return prefix+suffix;
}
function writePatch(file, before, after, backupDir) {
 if(before===after) return null;
 fs.mkdirSync(backupDir,{recursive:true});
 const backup=path.join(backupDir,`patch-${Date.now()}-${crypto.randomBytes(6).toString('hex')}.yml`);
 fs.writeFileSync(backup,before,{flag:'wx',mode:0o600});
 if(fs.readFileSync(file,'utf8')!==before) throw Error('Patch changed concurrently; backup retained');
 const tmp=file+'.community-'+crypto.randomBytes(6).toString('hex')+'.tmp';
 try {fs.writeFileSync(tmp,after,{flag:'wx',mode:0o600}); fs.renameSync(tmp,file);} finally {if(fs.existsSync(tmp)) fs.unlinkSync(tmp);}
 return backup;
}
function inspectLinks(home, data) {
 return NAMES.map(name => {
  const source=path.join(home,name), target=path.join(data,name);
  let stat; try { stat=fs.lstatSync(source); } catch(e) { if(e.code!=='ENOENT') throw e; }
  let resolved=null, kind=stat ? (stat.isSymbolicLink()?'link':'existing') : 'absent';
  if(kind==='link') { try { resolved=fs.realpathSync(source); } catch(e) { kind='broken-link'; } }
  let targetExists; try { fs.lstatSync(target); targetExists=true; } catch(e) { if(e.code!=='ENOENT') throw e; targetExists=false; }
  let matches=false; if(resolved && targetExists) { try { matches=resolved.toLowerCase()===fs.realpathSync(target).toLowerCase(); } catch(e) {} }
  return {name,source,target,kind,resolved,targetExists,matches};
 });
}
function makeLinks(home,data,journal) {
 const plan=inspectLinks(home,data);
 if(plan.some(x=>x.kind!=='absent'||x.targetExists)) throw Error('Junction source or target exists; inspect manually, nothing moved');
 if(fs.existsSync(journal)) throw Error('Junction journal exists; inspect manually');
 fs.mkdirSync(data,{recursive:true});
 const root=fs.realpathSync(data);
 if(path.parse(path.resolve(data)).root.toLowerCase()!==path.parse(root).root.toLowerCase()) throw Error('Data root resolves to another volume');
 fs.mkdirSync(path.dirname(journal),{recursive:true});
 let made=[];
 fs.writeFileSync(journal,JSON.stringify({version:1,home,links:made},null,2),{flag:'wx'});
 try {
  for(const x of plan) {
   fs.mkdirSync(x.target);
   // Journal target before linking so an interrupted operation remains inspectable.
   made.push({source:x.source,target:x.target});
   fs.writeFileSync(journal,JSON.stringify({version:1,home,links:made},null,2));
   fs.symlinkSync(x.target,x.source,'junction');
   if(fs.realpathSync(x.source).toLowerCase()!==fs.realpathSync(x.target).toLowerCase()) throw Error('Junction target mismatch');
  }
 } catch(e) { throw Error('Junction creation incomplete; journal retained for manual inspection: '+e.message); }
 return plan;
}
function removeLinks(journal,home,data) {
 if(!fs.existsSync(journal)) return {removed:[],retained:[]};
 const record=JSON.parse(fs.readFileSync(journal,'utf8'));
 if(record.version!==1 || !Array.isArray(record.links)) throw Error('Invalid junction journal');
 const removed=[],retained=[];
 for(const x of record.links) {
  // Never accept paths supplied by an altered journal.
  if(!NAMES.some(n=>path.resolve(x.source)===path.resolve(path.join(home,n)) && path.resolve(x.target)===path.resolve(path.join(data,n)))) { retained.push(x); continue; }
  try {
   const st=fs.lstatSync(x.source);
   if(!st.isSymbolicLink() || fs.realpathSync(x.source).toLowerCase()!==fs.realpathSync(x.target).toLowerCase() || fs.readdirSync(x.target).length) {retained.push(x);continue;}
   if(process.platform==='win32') fs.rmdirSync(x.source); else fs.unlinkSync(x.source); fs.rmdirSync(x.target); removed.push(x.source);
  } catch(e) {retained.push(x);}
 }
 record.links=retained;
 if(retained.length) fs.writeFileSync(journal,JSON.stringify(record,null,2)); else fs.unlinkSync(journal);
 return {removed,retained:retained.map(x=>x.source)};
}
function main(argv) {
 const action=argv[0] || 'plan'; if(!['plan','apply','uninstall','status'].includes(action) || argv.length>1) throw Error('Usage: node scripts/dsh_community_plugins.cjs [plan|apply|uninstall|status]');
 const home=process.env.DSH_HOME || path.join(process.env.USERPROFILE || '', '.dsh');
 const patch=path.join(home,'profiles','web','cordis.patch.yml');
 if(!fs.existsSync(patch)) throw Error('Existing web profile patch required');
 const original=fs.readFileSync(patch,'utf8'); positions(original);
 const journal=path.join(WORK,'junctions.json');
 const links=inspectLinks(home,DATA);
 if(action==='status') { console.log(JSON.stringify({block:positions(original)[0]>=0?'present':'absent',activation:original.includes('# BEGIN DAFEIYU COMMUNITY COMPOSITION')?'native-composition-present':'inactive-record-only',environment:WORK,links},null,2)); return; }
 if(action==='uninstall') {if(original.includes('# BEGIN DAFEIYU COMMUNITY COMPOSITION')) throw Error('Deactivate native composition first: node scripts/configure_dsh_community.cjs uninstall'); const changed=removeBlock(original); const backup=writePatch(patch,original,changed,path.join(WORK,'backups')); const junctions=removeLinks(journal,home,DATA); console.log(JSON.stringify({action,changed:changed!==original,backup,dependenciesRetained:true,junctions})); return;}
 const artifacts=verify(path.join(ROOT,'npm-tarballs'));
 const installDir=path.join(WORK,'environment');
 const entries=artifacts.map(x=>({...x,installDir}));
 const updated=addBlock(original,entries);
 if(links.some(x=>x.kind!=='absent'||x.targetExists)) { console.log(JSON.stringify({action,links},null,2)); throw Error('Junction source or target exists; inspect manually, nothing moved'); }
 if(action==='plan') {console.log(JSON.stringify({action,verified:artifacts.map(({name,version})=>({name,version})),installDir,activation:'inactive-record-only',patch,links},null,2)); return;}
 if(fs.existsSync(installDir)) throw Error('Environment already exists; inspect it before retrying');
 const npmCli=path.join(path.dirname(process.execPath),'node_modules','npm','bin','npm-cli.js');
 if(!fs.existsSync(npmCli)) throw Error('npm-cli.js not found beside Node');
 fs.mkdirSync(installDir,{recursive:true});
 const cache=path.join(WORK,'npm-cache'); fs.mkdirSync(cache,{recursive:true});
 const env={...process.env};
 for (const key of Object.keys(env)) if (/^npm_config_/i.test(key) || key === 'NODE_OPTIONS') delete env[key];
 Object.assign(env,{npm_config_userconfig:path.join(WORK,'empty-user.npmrc'),npm_config_globalconfig:path.join(WORK,'empty-global.npmrc'),npm_config_cache:cache,npm_config_ignore_scripts:'true',npm_config_update_notifier:'false',npm_config_audit:'false',npm_config_fund:'false',TEMP:path.join(WORK,'tmp'),TMP:path.join(WORK,'tmp')});
 fs.mkdirSync(env.TEMP,{recursive:true});
 const result=spawnSync(process.execPath,[npmCli,'install','--prefix',installDir,'--ignore-scripts','--no-audit','--no-fund','--legacy-peer-deps',...artifacts.map(x=>x.file)],{shell:false,stdio:'inherit',cwd:installDir,env});
 if(result.error || result.status!==0) throw Error('npm failed; E-drive environment retained for inspection');
 for(const e of entries) {const p=path.join(installDir,'node_modules',e.name,'package.json'); const pkg=JSON.parse(fs.readFileSync(p,'utf8')); if(pkg.name!==e.name || pkg.version!==e.version || !fs.existsSync(path.join(installDir,'node_modules',e.name,e.entry))) throw Error('Installed package mismatch');}
 makeLinks(home,DATA,journal);
 const backup=writePatch(patch,original,updated,path.join(WORK,'backups'));
 console.log(JSON.stringify({action,backup,environment:installDir,activation:'inactive'}));
}
if(require.main===module) try {main(process.argv.slice(2));} catch(e) {console.error(e.message); process.exitCode=1;}
module.exports={verify,addBlock,removeBlock,writePatch,positions,inspectLinks,makeLinks,removeLinks,PACKAGES};
