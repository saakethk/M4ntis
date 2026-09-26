import { mkdirSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { BLOCK_DEFS } from '../src/blocks/catalog';
import { toDocument, toIR } from '../src/flow/serialize';
import { TEMPLATES } from '../src/flow/templates';

const outDir = join(dirname(fileURLToPath(import.meta.url)), '..', 'examples');
mkdirSync(outDir, { recursive: true });

const write = (file: string, value: unknown) => {
  writeFileSync(join(outDir, file), `${JSON.stringify(value, null, 2)}\n`);
  console.log(`wrote examples/${file}`);
};

write('block_catalog.json', BLOCK_DEFS);

for (const t of TEMPLATES) {
  const { nodes, edges } = t.build();
  const doc = toDocument(t.name, nodes, edges);
  write(`${t.id}.strategy.json`, { ...doc, savedAt: '2026-01-01T00:00:00.000Z' });
  write(`${t.id}.ir.json`, toIR(nodes, edges));
}
