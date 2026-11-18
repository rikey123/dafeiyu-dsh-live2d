/** Build a self-contained npm/DSH bundle from a strict, audited allowlist.
 * User state and separately licensed model/Core assets are never release inputs.
 */
import {readFile, writeFile, mkdir, mkdtemp, readdir, lstat, copyFile, realpath} from 'node:fs/promises';
import {existsSync} from 'node:fs';
import {resolve, dirname, join, relative, isAbsolute, basename} from 'node:path';
import {fileURLToPath} from 'node:url';
import {createHash} from 'node:crypto';
import {spawnSync} from 'node:child_process';

export const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const hash = bytes => createHash('sha256').update(bytes).digest('hex');
const slash = path => path.replaceAll('\\', '/');
const contained = (root, path) => {
  const rel = relative(root, path);
  return rel === '' || (!isAbsolute(rel) && rel !== '..' && !rel.startsWith('..\\') && !rel.startsWith('../'));
};
const runtimeScripts = ['run.py','voice_services.py','voice_mode.py','optional_voice.py',
  'native_voice_service.py','wsl_voice_service.py','windows_process.py',
  'prepare_tts_models.py','prepare_gpt_sovits.py','import_avatar.py'];
const requirements = ['requirements.txt','requirements-lock.txt','requirements-speech.txt',
  'requirements-voice.txt','requirements-voice-lock.txt','requirements-tts-moss.txt',
  'requirements-tts-gpt-sovits.txt','requirements-device-audio.txt'];
const frontendPackages = ['react','react-dom','scheduler','pixi.js','@pixi','pixi-live2d-display',
  'lucide-react','es-toolkit','@pipecat-ai/client-js','@pipecat-ai/websocket-transport','wlipsync',
  'protobufjs','long','loglevel','eventemitter3','earcut','@pixi/utils','@pixi/core'];

export function npmCommand(args, {env = process.env} = {}) {
  const candidates = [env.npm_execpath, env.NPM_CLI_JS,
    resolve(dirname(process.execPath), 'node_modules/npm/bin/npm-cli.js')].filter(Boolean);
  const cli = candidates.find(path => existsSync(path) && /npm-cli\.js$/u.test(path));
  if (!cli) throw Error('Cannot locate npm-cli.js. Install Node.js with npm or set NPM_CLI_JS.');
  return [process.execPath, [cli, ...args]];
}

function runNpm(args, cwd, env = process.env) {
  const [exe, argv] = npmCommand(args, {env});
  const result = spawnSync(exe, argv, {cwd, env, encoding:'utf8', windowsHide:true, maxBuffer:16*1024*1024});
  if (result.status !== 0) throw Error(`npm ${args[0]} failed (${result.status ?? 'spawn'}): ${result.stderr || result.error?.message || result.stdout}`);
  return result.stdout;
}

async function filesUnder(directory, filter = () => true, skipState = true) {
  const out = [];
  for (const entry of await readdir(directory, {withFileTypes:true})) {
    const path = join(directory, entry.name);
    const stat = await lstat(path);
    if (stat.isSymbolicLink()) throw Error(`Release input is a symlink: ${path}`);
    if (stat.isDirectory()) {
      if (skipState && ['__pycache__','node_modules','.cache','.pytest_cache','.git','data','models'].includes(entry.name)) continue;
      out.push(...await filesUnder(path, filter, skipState));
    } else if (stat.isFile() && filter(path)) out.push(path);
  }
  return out.sort();
}

async function copy(root, source, destination) {
  const actual = await realpath(source);
  if (!contained(await realpath(root), actual)) throw Error(`Release input escapes source: ${source}`);
  if ((await lstat(source)).isSymbolicLink()) throw Error(`Release input is a symlink: ${source}`);
  await mkdir(dirname(destination), {recursive:true});
  await copyFile(source, destination);
}

async function copyTree(root, source, dest, filter) {
  for (const path of await filesUnder(source, filter)) await copy(root, path, join(dest, relative(source,path)));
}

async function collectFrontendNotices(root, app) {
  const nodeModules = join(root,'web/node_modules');
  const dependencies = [];
  const visited = new Set();
  async function one(spec) {
    const location = join(nodeModules, spec);
    if (!existsSync(join(location,'package.json'))) return;
    const actual = await realpath(location);
    if (visited.has(actual)) return;
    visited.add(actual);
    const manifest = JSON.parse(await readFile(join(location,'package.json'),'utf8'));
    dependencies.push({name:manifest.name,version:manifest.version,license:manifest.license ?? 'SEE UPSTREAM LICENSE'});
    const notices = (await readdir(location)).filter(name => /^(license|licence|copying|notice)(\.|$)/iu.test(name));
    for (const name of notices) {
      const from = join(location,name);
      if (!(await lstat(from)).isFile()) continue;
      const dest = join(app,'notices/frontend',manifest.name.replaceAll('/','__'),name);
      await mkdir(dirname(dest),{recursive:true});
      await copyFile(from,dest);
    }
    for (const child of Object.keys(manifest.dependencies ?? {})) await one(child);
  }
  for (const name of frontendPackages) {
    if (name === '@pixi' && existsSync(join(nodeModules,name))) {
      for (const child of await readdir(join(nodeModules,name))) await one(`${name}/${child}`);
    } else await one(name);
  }
  if (!dependencies.some(row=>row.name==='react') || !dependencies.some(row=>row.name==='wlipsync')) {
    throw Error('Install frontend dependencies before staging a release; licenses cannot be omitted.');
  }
  await writeFile(join(app,'notices/frontend-dependencies.json'),JSON.stringify(dependencies.sort((a,b)=>a.name.localeCompare(b.name)),null,2)+'\n');
}

export async function stageRelease({root = ROOT, out, collectNotices = true} = {}) {
  if (!out) throw Error('A release output directory is required');
  root = resolve(root); out = resolve(out);
  if (contained(join(root,'plugins/dsh'),out) || out === root) throw Error('Output must not overwrite plugin source');
  await mkdir(out,{recursive:true});
  const stage = await mkdtemp(join(out,'.stage-'));
  const packageRoot = join(stage,'package');
  const app = join(packageRoot,'app');
  await mkdir(app,{recursive:true});
  for (const name of ['package.json','cordis.patch.yml','icon.svg','README.md']) {
    await copy(root,join(root,'plugins/dsh',name),join(packageRoot,name));
  }
  const manifest = JSON.parse(await readFile(join(packageRoot,'package.json'),'utf8'));
  if (manifest.private || !manifest.dsh?.bundle?.patch || !manifest.engines?.dsh) throw Error('Package is not a versioned DSH bundle');
  await copyTree(root,join(root,'plugins/dsh/src'),join(packageRoot,'src'),path=>/\.(mjs|js|json|svg)$/u.test(path));
  await copyTree(root,join(root,'plugins/dsh/bin'),join(packageRoot,'bin'),path=>/\.mjs$/u.test(path));
  for (const directory of ['server','speech']) {
    await copyTree(root,join(root,directory),join(app,directory),path=>path.endsWith('.py') && !basename(path).startsWith('test_'));
  }
  for (const name of runtimeScripts) await copy(root,join(root,'scripts',name),join(app,'scripts',name));
  for (const name of ['dafeiyu_paths.py',...requirements]) await copy(root,join(root,name),join(app,name));
  if (!existsSync(join(root,'web/dist-dsh/entry.js'))) throw Error('Missing compiled frontend. Build web with build:dsh first.');
  await copyTree(root,join(root,'web/dist-dsh'),join(app,'web/dist-dsh'));
  await mkdir(join(app,'web/public'),{recursive:true});
  // No copy of web/public: it may contain the user's non-redistributable model.
  for (const name of ['LICENSE','persona.md','source.json']) await copy(root,join(root,'personas/blue-whale',name),join(app,'personas/blue-whale',name));
  for (const name of ['DSH_RELEASE.md','DEEPSEEK_SKIN.md']) await copy(root,join(root,'docs',name),join(packageRoot,'docs',name));
  for (const name of ['DSH_PLUGIN.md','DSH_NATIVE_CONVERSATION.md','PROTOCOL.md','TTS_MODES.md','SYSTEMONE.md','COMPANION_PRESENCE.md','REALTIME_LIPSYNC.md']) {
    if (existsSync(join(root,'docs',name))) await copy(root,join(root,'docs',name),join(packageRoot,'docs',name));
  }
  await copy(root,join(root,'THIRD_PARTY_NOTICES.md'),join(packageRoot,'THIRD_PARTY_NOTICES.md'));
  await copy(root,join(root,'web/LIVE2D-LICENSE.md'),join(app,'notices/LIVE2D-LICENSE.md'));
  await copy(root,join(root,'web/patches/README.md'),join(app,'notices/renderer-patches.md'));
  if (collectNotices) await collectFrontendNotices(root,app);
  const files = [];
  for (const path of await filesUnder(app)) {
    const data = await readFile(path);
    files.push({path:slash(relative(app,path)),sha256:hash(data),size:data.length});
  }
  const packageFiles=[];
  for (const path of await filesUnder(packageRoot)) {
    if(contained(app,path))continue;
    const data=await readFile(path);
    packageFiles.push({path:slash(relative(packageRoot,path)),sha256:hash(data),size:data.length});
  }
  await writeFile(join(app,'release-manifest.json'),JSON.stringify({schemaVersion:1,version:manifest.version,files,packageFiles},null,2)+'\n');
  await auditRelease(packageRoot);
  return {packageRoot,version:manifest.version,out};
}

export async function auditRelease(packageRoot) {
  packageRoot = resolve(packageRoot);
  const files = await filesUnder(packageRoot,()=>true,false);
  if (files.length < 10) throw Error('Incomplete release');
  const forbidden = /(?:^|\/)(?:\.env(?:\..*)?|\.credentials(?:\..*)?|\.venv[^/]*|__pycache__|node_modules|\.git|data|cache|models)(?:\/|$)|\.(?:sqlite3?|db|pyc|onnx|safetensors|ckpt|pth|moc3|zip)$/iu;
  for (const path of files) {
    const name = slash(relative(packageRoot,path));
    if (forbidden.test(name)) throw Error(`Forbidden release entry: ${name}`);
    if (/(?:^|\/)live2dcubismcore(?:\.min)?\.js$/iu.test(name)) throw Error('Cubism Core requires a separate installation');
    if ((await lstat(path)).size > 64*1024*1024) throw Error(`Unexpected oversized release entry: ${name}`);
    if (/\.(?:mjs|js|py|json|yml|yaml)$/u.test(path) && !name.startsWith('app/web/dist-dsh/')) {
      const text = await readFile(path,'utf8');
      if (/[A-Z]:[\\/]dafeiyu[\\/](?:\.venv|\.runtime|web|scripts|models)/iu.test(text)) throw Error(`Machine-specific runtime path in ${name}`);
      if (/(?:sk-relay_|sk-live-|sk-proj-)[a-zA-Z0-9_-]{20,}/u.test(text)) throw Error(`Credential-like content in ${name}`);
    }
  }
  const app = join(packageRoot,'app');
  const manifest = JSON.parse(await readFile(join(app,'release-manifest.json'),'utf8'));
  const seen = new Set();
  for (const record of manifest.files) {
    const path = resolve(app,record.path);
    if (!contained(app,path) || seen.has(record.path)) throw Error('Invalid release manifest path');
    seen.add(record.path);
    const data = await readFile(path);
    if (hash(data)!==record.sha256 || data.length!==record.size) throw Error(`Release manifest mismatch: ${record.path}`);
  }
  const actual = (await filesUnder(app,()=>true,false)).filter(path=>basename(path)!=='release-manifest.json');
  if (actual.length!==seen.size) throw Error('Release manifest has missing or extra files');
  for (const record of manifest.packageFiles) {
    const path=resolve(packageRoot,record.path);
    if(!contained(packageRoot,path)||contained(app,path))throw Error('Invalid package manifest path');
    const data=await readFile(path);
    if(hash(data)!==record.sha256||data.length!==record.size)throw Error(`Release manifest mismatch: ${record.path}`);
  }
  return {files:files.length,bytes:(await Promise.all(files.map(async path=>(await lstat(path)).size))).reduce((a,b)=>a+b,0)};
}

export async function packRelease(staged) {
  const stdout = runNpm(['pack','--json','--ignore-scripts','--pack-destination',staged.out],staged.packageRoot);
  const packed = JSON.parse(stdout)[0];
  const archive = join(staged.out,packed.filename);
  const declared = new Set(packed.files.map(file=>file.path));
  for (const needed of ['src/index.mjs','src/client.js','bin/cli.mjs','cordis.patch.yml',
    'app/server/main.py','app/speech/server.py','app/scripts/run.py','app/web/dist-dsh/entry.js','app/release-manifest.json']) {
    if (!declared.has(needed)) throw Error(`npm files allowlist omitted ${needed}`);
  }
  const sha256 = hash(await readFile(archive));
  await writeFile(join(staged.out,'SHA256SUMS'),`${sha256}  ${packed.filename}\n`);
  const report = {name:packed.name,version:packed.version,filename:packed.filename,sha256,
    compressedBytes:packed.size,unpackedBytes:packed.unpackedSize,fileCount:packed.files.length,
    format:'npm-tgz/dsh.bundle',codeLicense:'UNLICENSED',containsUserState:false,
    includesModelWeights:false,includesCubismCore:false,includesUserAvatar:false};
  await writeFile(join(staged.out,'release-report.json'),JSON.stringify(report,null,2)+'\n');
  return {...report,archive};
}

async function main() {
  const args = process.argv.slice(2); let out = join(ROOT,'artifacts/release'); let skipBuild=false,stageOnly=false;
  for (let i=0;i<args.length;i++) {
    if(args[i]==='--out' && args[i+1]) out=resolve(args[++i]);
    else if(args[i]==='--skip-build') skipBuild=true;
    else if(args[i]==='--stage-only') stageOnly=true;
    else throw Error(`Unknown release argument: ${args[i]}`);
  }
  if (!skipBuild) process.stdout.write(runNpm(['--prefix','web','run','build:dsh'],ROOT));
  const staged = await stageRelease({out});
  console.log(JSON.stringify(stageOnly ? staged : await packRelease(staged),null,2));
}
if (process.argv[1] && resolve(process.argv[1])===fileURLToPath(import.meta.url)) main().catch(error=>{console.error(error.message);process.exitCode=1;});
