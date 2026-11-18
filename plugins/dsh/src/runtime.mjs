/** Owner-scoped lifecycle. Unloading DSH never terminates borrowed model services. */
import { spawn } from 'node:child_process';
import { createConnection } from 'node:net';
import { request } from 'node:http';
import { open, mkdir, readFile, writeFile, appendFile, access } from 'node:fs/promises';
import { join } from 'node:path';
import { setTimeout as delay } from 'node:timers/promises';

async function occupied(port) {
  return new Promise(resolve => {
    const socket = createConnection({host:'127.0.0.1', port});
    socket.setTimeout(700);
    socket.once('connect', () => { socket.destroy(); resolve(true); });
    socket.once('error', () => resolve(false));
    socket.once('timeout', () => { socket.destroy(); resolve(false); });
  });
}

export class SpeechRuntimeError extends Error {
  constructor(code, message) { super(message); this.name = 'SpeechRuntimeError'; this.code = code; }
}

export function createSpeechRuntime({projectRoot, homeDir = projectRoot, packaged = false, gatewayPort = 8765, speechPort = 8766, bridge, pluginToken, origin, startServices = true, pythonPath}, dependencies = {}) {
  if (![gatewayPort,speechPort].every(port=>Number.isInteger(port)&&port>=1024&&port<=65535) || gatewayPort===speechPort) throw new Error('Gateway and speech ports must be distinct integers between 1024 and 65535');
  // Optional dependency injection is for lifecycle tests, never sourced from plugin JSON configuration.
  const openLog = dependencies.openLog ?? open;
  const isOccupied = dependencies.isOccupied ?? occupied;
  const spawnChild = dependencies.spawnChild ?? spawn;
  const now = dependencies.now ?? Date.now;
  const wait = dependencies.delay ?? delay;
  const timing = {cache:1500, recovery:10_000, startup:120_000, ...dependencies.timing};
  let child, childError, pending, disposal, disposed = false;
  let healthyUntil = 0;
  const logged = new Map();
  const requireOpen = () => { if (disposed) throw new SpeechRuntimeError('plugin_disposed', 'Plugin disposed'); };
  const exited = () => !child || childError || child.exitCode !== null || child.signalCode !== null;
  const gatewayUrl = `http://127.0.0.1:${gatewayPort}`;
  const logPath = join(homeDir, 'data/logs/dsh-plugin-runner.log');
  async function report(code) {
    // Fixed codes and an owned numeric PID only. Never log exception strings,
    // response bodies, bearer tokens, settings payloads or credentials.
    if (now() - (logged.get(code) ?? -Infinity) < 5000) return;
    logged.set(code, now());
    try {
      await mkdir(join(homeDir, 'data/logs'), {recursive:true});
      await appendFile(logPath, `[${new Date().toISOString()}] runtime ${code} pid=${Number.isSafeInteger(child?.pid) ? child.pid : 'none'}\n`);
    } catch { /* Diagnostic IO must not turn a recovered gateway into a failure. */ }
  }
  async function probeHealth() {
    // node:http never applies HTTP_PROXY / NODE_USE_ENV_PROXY to this private local hop.
    return new Promise(resolve => {
      const req = request(`${gatewayUrl}/api/health`, {headers:{'X-Dafeiyu-Plugin-Token':pluginToken}, timeout:1500}, response => {
        response.resume(); resolve(response.statusCode);
      });
      req.once('timeout', () => { req.destroy(); resolve(0); });
      req.once('error', () => resolve(0));
      req.end();
    });
  }
  const health = dependencies.probeHealth ?? probeHealth;
  const authenticated = status => {
    if (status === 401 || status === 403) throw new SpeechRuntimeError('gateway_auth_mismatch', 'Speech gateway authentication does not match this plugin');
    return status === 200;
  };
  async function awaitOwnedGateway(startup) {
    const deadline = now() + (startup ? timing.startup : timing.recovery);
    let interrupted = false;
    while (now() < deadline) {
      requireOpen();
      if (exited()) throw new SpeechRuntimeError('supervisor_failed', 'Speech supervisor failed; inspect data/logs/dsh-plugin-runner.log');
      const status = await health();
      requireOpen();
      if (exited()) throw new SpeechRuntimeError('supervisor_failed', 'Speech supervisor failed; inspect data/logs/dsh-plugin-runner.log');
      if (authenticated(status)) {
        healthyUntil = now() + timing.cache;
        if (interrupted && !startup) await report('gateway_recovered');
        return;
      }
      interrupted = true;
      await wait(Math.min(300, Math.max(0, deadline - now())));
    }
    throw new SpeechRuntimeError(startup ? 'gateway_start_timeout' : 'gateway_busy',
      startup ? 'Speech gateway startup timed out' : 'Owned speech gateway is temporarily unresponsive');
  }
  async function start() {
    requireOpen();
    if (!exited()) {
      if (now() < healthyUntil) return;
      // A live owned supervisor does not become a foreign process because one
      // health probe timed out. Wait for recovery; never launch a second copy,
      // kill by port, change credentials, or retry a settings/TTS request.
      await awaitOwnedGateway(false);
      return;
    }
    if (!startServices) {
      if (!authenticated(await health())) throw new SpeechRuntimeError('external_gateway_unavailable', 'Configured external DSH speech gateway is unavailable');
      requireOpen();
      return;
    }
    const python = pythonPath ?? join(homeDir, '.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python');
    if (packaged) {
      for(const lock of ['bootstrap.lock','setup.lock']){
        if(await access(join(homeDir,'.runtime',lock)).then(()=>true,()=>false))throw new SpeechRuntimeError('setup_required','Installation is still changing this runtime; wait for it to finish before starting speech.');
      }
      try {
        await Promise.all([access(python), access(join(homeDir, '.venv-voice', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python'))]);
        if (!pythonPath) {
          const marker = JSON.parse(await readFile(join(homeDir, '.runtime', 'installation.json'), 'utf8'));
          const {version} = JSON.parse(await readFile(new URL('../package.json', import.meta.url), 'utf8'));
          if (marker.schemaVersion !== 1 || marker.status !== 'ready' || marker.version !== version) throw new Error('Installation marker is not ready');
        }
      } catch { throw new SpeechRuntimeError('setup_required', 'Runtime is not set up. Run dafeiyu setup --home <homeDir> before starting speech.'); }
      await mkdir(join(homeDir, 'cache', 'tmp'), {recursive:true});
    }
    if (await isOccupied(gatewayPort)) throw new SpeechRuntimeError('gateway_port_occupied', 'The gateway port is in use by another application; it was not stopped');
    requireOpen();
    await mkdir(join(homeDir, 'data/logs'), {recursive:true});
    const log = await openLog(logPath, 'a');
    try {
      requireOpen();
      childError = undefined;
      child = spawnChild(python,
        [join(projectRoot, 'scripts/run.py'), '--runtime-name', 'dsh', '--parent-stdin', '--no-local-llm'], {
          cwd:projectRoot, windowsHide:true, stdio:['pipe',log.fd,log.fd],
          env:{...process.env, PYTHONUTF8:'1', PYTHONUNBUFFERED:'1',
            DAFEIYU_HOME:homeDir, DAFEIYU_DATA_DIR:join(homeDir,'data'), DAFEIYU_MODELS_DIR:join(homeDir,'models'),
            DAFEIYU_RUNTIME_DIR:join(homeDir,'.runtime'), DAFEIYU_CACHE_DIR:join(homeDir,'cache'),
            DAFEIYU_GATEWAY_PORT:String(gatewayPort), DAFEIYU_SPEECH_PORT:String(speechPort),
            SPEECH_BASE_URL:`http://127.0.0.1:${speechPort}`, PYTHONDONTWRITEBYTECODE:'1',
            ...(packaged ? {TEMP:join(homeDir,'cache','tmp'), TMP:join(homeDir,'cache','tmp'), TMPDIR:join(homeDir,'cache','tmp'), XDG_CACHE_HOME:join(homeDir,'cache'), HF_HOME:join(homeDir,'cache','huggingface'), TORCH_HOME:join(homeDir,'cache','torch')} : {}),
            DAFEIYU_HARNESS:'dsh', DAFEIYU_DSH_BRIDGE_URL:bridge.url, DAFEIYU_DSH_BRIDGE_TOKEN:bridge.token,
            DAFEIYU_PLUGIN_TOKEN:pluginToken, DAFEIYU_DSH_ORIGIN:origin},
        });
      // spawn emits errors on a later tick, which may precede any awaited log close.
      const current = child;
      current.once('error', failure => { if (child === current) { childError = failure; healthyUntil = 0; } });
      current.once('exit', () => { if (child === current) healthyUntil = 0; });
      current.stdin?.on('error', () => {});
    } finally { await log.close(); }
    await awaitOwnedGateway(true);
  }
  return {
    gatewayUrl,
    ensure() {
      if (!pending) pending = start().catch(async error => {
        const failure = error instanceof SpeechRuntimeError ? error
          : new SpeechRuntimeError('supervisor_start_failed', 'Could not start speech supervisor');
        if (failure.code !== 'plugin_disposed' && failure.code !== 'setup_required') await report(failure.code);
        throw failure;
      }).finally(() => { pending = undefined; });
      return pending;
    },
    dispose() {
      return disposal ??= (async () => {
      disposed = true;
      child?.stdin?.end();
      // Cover startup suspended in filesystem IO as well as a fully published child.
      // start() rechecks disposed immediately before spawn, so it cannot publish after disposal completes.
      await pending?.catch(() => {});
      if (!child || exited()) return;
      // EOF is a second independent shutdown signal if the ownership file was not written yet.
      child.stdin?.end();
      try {
        const owner = JSON.parse(await readFile(join(homeDir, '.runtime/runner-dsh.json'), 'utf8'));
        if (owner.pid === child.pid && /^[0-9a-f]{32}$/.test(owner.token)) await writeFile(join(homeDir, `.runtime/stop-${owner.token}`), '');
      } catch {}
      const deadline = Date.now() + 25_000;
      while (!exited() && Date.now() < deadline) await delay(100);
      // Do not kill process trees by port or broad image name. The supervisor's stdin handles host crashes too.
      if (!exited()) child.kill();
      })();
    },
  };
}
