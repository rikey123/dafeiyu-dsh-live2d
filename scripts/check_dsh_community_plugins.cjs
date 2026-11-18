const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const crypto = require('node:crypto');
const {verify,addBlock,removeBlock,writePatch,inspectLinks,makeLinks,removeLinks} = require('./dsh_community_plugins.cjs');
const root=fs.mkdtempSync(path.join(os.tmpdir(),'dsh-community-fixture-'));
try {
 const bytes=Buffer.from('fixture archive'); fs.writeFileSync(path.join(root,'x.tgz'),bytes);
 const pkg=[['fixture','1','x.tgz',crypto.createHash('sha256').update(bytes).digest('hex'),'sha512-'+crypto.createHash('sha512').update(bytes).digest('base64'),'index.js']];
 assert.equal(verify(root,pkg).length,1);
 fs.writeFileSync(path.join(root,'x.tgz'),'tampered'); assert.throws(()=>verify(root,pkg),/mismatch/);
 const entry=[{name:'fixture',version:'1',installDir:root,entry:'index.js'}];
 for(const original of ['[]\r\n','# comment\n[]\n','- insert:\n    - id: other\n      name: other\n# BEGIN DAFEIYU DSH PLUGIN\n# END DAFEIYU DSH PLUGIN\n','- insert: []']) {
  const added=addBlock(original,entry); assert.equal(removeBlock(added),original); assert.throws(()=>addBlock(added,entry),/already/);
  if(!original.includes('[]\r') && !original.startsWith('# comment')) assert.equal(removeBlock(added+'# later\n'),original+'\n'.slice(original.endsWith('\n')?1:0)+'# later\n');
 }
 const added=addBlock('[]\n',entry); assert.equal(removeBlock(added+'# later\n'),'[]\n# later\n');
 assert.throws(()=>removeBlock(added.replace('# inactive','# edited')),/Modified/);
 assert.throws(()=>addBlock('key: value\n',entry),/Unsupported/);
 const file=path.join(root,'patch.yml'); fs.writeFileSync(file,'[]\n');
 const backup=writePatch(file,'[]\n',added,path.join(root,'backups')); assert.equal(fs.readFileSync(backup,'utf8'),'[]\n'); assert.equal(fs.readFileSync(file,'utf8'),added);
 assert.throws(()=>writePatch(file,'stale','x',path.join(root,'backups')),/concurrently/); assert.equal(fs.readFileSync(file,'utf8'),added);
 const home=path.join(root,'home'), data=path.join(root,'data'), journal=path.join(root,'state','links.json'); fs.mkdirSync(home);
 assert.ok(inspectLinks(home,data).every(x=>x.kind==='absent' && !x.targetExists));
 fs.mkdirSync(path.join(home,'bili-duty')); assert.throws(()=>makeLinks(home,data,journal),/exists/); fs.rmdirSync(path.join(home,'bili-duty'));
 makeLinks(home,data,journal); assert.ok(inspectLinks(home,data).every(x=>x.kind==='link' && x.resolved));
 assert.throws(()=>makeLinks(home,data,journal),/exists/);
 fs.writeFileSync(path.join(data,'fish-memory','keep'),'data');
 const result=removeLinks(journal,home,data); assert.equal(result.removed.length,4); assert.equal(result.retained.length,1);
 assert.equal(fs.readFileSync(path.join(home,'fish-memory','keep'),'utf8'),'data');
 console.log('PASS: artifact hashes, isolated patch preservation, conflicts, backups and rollback');
} finally { const link=path.join(root,'home','fish-memory'); try { if(fs.lstatSync(link).isSymbolicLink()) { if(process.platform==='win32') fs.rmdirSync(link); else fs.unlinkSync(link); } } catch(e) { if(e.code!=='ENOENT') throw e; } fs.rmSync(root,{recursive:true,force:true}); }
