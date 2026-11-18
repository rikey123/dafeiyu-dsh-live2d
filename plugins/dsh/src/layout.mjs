import {existsSync} from 'node:fs';
import {homedir} from 'node:os';
import {dirname, join, resolve, relative, isAbsolute} from 'node:path';
import {fileURLToPath} from 'node:url';

const defaultPackageRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const inside = (root, path) => { const rel = relative(root, path); return !rel || (rel !== '..' && !rel.startsWith(`..${process.platform === 'win32' ? '\\' : '/'}`) && !isAbsolute(rel)); };

export function resolveLayout(config = {}, {packageRoot = defaultPackageRoot, env = process.env} = {}) {
  packageRoot = resolve(packageRoot);
  const payload = join(packageRoot, 'app');
  const packaged = !config.projectRoot && existsSync(join(payload, 'scripts', 'run.py'));
  const codeRoot = resolve(config.projectRoot || (packaged ? payload : join(packageRoot, '../..')));
  const defaultHome = packaged ? join(env.LOCALAPPDATA || env.XDG_DATA_HOME || join(homedir(), '.local', 'share'), 'dafeiyu') : codeRoot;
  const homeDir = resolve(config.homeDir || env.DAFEIYU_HOME || defaultHome);
  if (packaged && inside(packageRoot, homeDir)) throw new Error('DAFEIYU_HOME must be outside the installed package directory');
  return {packageRoot, codeRoot, homeDir, packaged};
}

export function staticRoots({codeRoot, homeDir}) {
  return [
    {directory:join(codeRoot, 'web/dist-dsh')},
    ...['models', 'cubism', 'vad'].map(prefix => ({directory:join(homeDir, 'public', prefix), prefix})),
    {directory:join(codeRoot, 'web/public')},
  ];
}
