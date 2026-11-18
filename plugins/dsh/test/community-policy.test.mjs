import test from 'node:test';
import assert from 'node:assert/strict';
import { apply, rejection } from '../src/community-policy.mjs';

test('composition avoids duplicate memory but leaves all Bilibili permissions to DSH', () => {
  for (const name of ['memory_append', 'memory_digest'])
    assert.equal(typeof rejection({ name }), 'string');
  for (const name of ['remember', 'soul_read', 'soul_update', 'bili_search', 'bili_subtitle', 'bili_comments', 'bili_send_dynamic', 'bili_reply', 'bili_config', 'bili_login_start', 'bili_login_poll', 'bili_setup'])
    assert.equal(rejection({ name }), undefined);
  assert.equal(rejection({ name: 'memory_append' }, { soulMemory: true }), undefined);
  assert.equal(rejection({ name: 'bili_reply' }, { allowBilibiliActions: true }), undefined);
  assert.equal(rejection({ name: 'bili_login_start' }, { allowBilibiliActions: false }), undefined, 'old installed config cannot retain a blanket tool ban');
  let guard;
  apply({ tools: { guard(value) { guard = value; } } });
  assert.equal(guard({ name: 'bili_reply', arguments: { force: true } }), undefined);
});
