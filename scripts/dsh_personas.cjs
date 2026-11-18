'use strict';

const fs = require('node:fs');
const path = require('node:path');
const { createHash } = require('node:crypto');

// Persona text is an attributed upstream asset, not another system prompt or
// memory store. Import it into the native soul-md card through native settings.
function loadBlueWhale() {
  const directory = path.resolve(__dirname, '../personas/blue-whale');
  const source = JSON.parse(fs.readFileSync(path.join(directory, 'source.json'), 'utf8'));
  const bytes = fs.readFileSync(path.join(directory, 'persona.md'));
  if (createHash('sha256').update(bytes).digest('hex') !== source.sha256) {
    throw Error('Blue whale upstream persona integrity check failed');
  }
  return { name: source.name, content: bytes.toString('utf8'), source };
}

module.exports = { loadBlueWhale };
