import test from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { pathToFileURL } from 'node:url';
import { join, resolve, relative, isAbsolute } from 'node:path';
import { existsSync } from 'node:fs';
import { mkdir, mkdtemp, rm } from 'node:fs/promises';
import { screenImages, admitScreen } from '../src/screen.mjs';

const root = process.env.DSH_RUNTIME_MODULES_ROOT || 'C:/Users/Administrator/AppData/Roaming/dsh-launcher/dsh-runtime/versions/0.2.2-rc.1/node_modules';
import {jpeg} from './fixtures/screen-image.mjs';

test('real rc1 attachment admission decodes, persists and resolves a screen image without model I/O', {
  skip: !existsSync(join(root, '@deepseek-ai/dsh/package.json')),
}, async t => {
  const req = createRequire(join(root, '@deepseek-ai/dsh/package.json'));
  const load = name => import(pathToFileURL(req.resolve(name)).href);
  const [{ Context }, { LocalAttachmentStore }] = await Promise.all([
    load('@deepseek-ai/cordis'), load('@deepseek-ai/dsh-attachment-local'),
  ]);
  const parent = resolve(process.env.DAFEIYU_TEST_TMP || join(import.meta.dirname, '../../../.runtime/tests'));
  await mkdir(parent, { recursive: true });
  const home = await mkdtemp(join(parent, 'screen-native-'));
  const context = new Context();
  t.after(async () => {
    const child = relative(parent, resolve(home));
    assert(child && !child.startsWith('..') && !isAbsolute(child));
    await rm(home, { recursive: true, force: true });
  });
  const attachments = new LocalAttachmentStore(context, { dshHome: home });
  const ctx = { attachments, llm: { async resolveModelInfo() { return { inputModalities: ['text', 'image'] }; } } };
  const images = screenImages([{ mime_type: 'image/jpeg', data: jpeg, width: 1, height: 1 }], () => Error('invalid'));
  const [part] = await admitScreen(ctx, images, { provider: 'offline', model: 'fixture' }, new AbortController().signal, () => Error('unavailable'));
  assert.equal(part.type, 'image');
  assert.equal(part.attachment.width, 1);
  assert(existsSync(attachments.imageHostPath(part.attachment)));
  const stored = await attachments.readImage(part.attachment);
  assert.equal(stored.data.byteLength, part.attachment.bytes);
  await assert.rejects(admitScreen(ctx, [{ ...images[0], data: '/9j/2Q==' }], { provider: 'offline', model: 'fixture' },
    new AbortController().signal, () => Error('unavailable')));
});
