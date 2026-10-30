/** Prepare immutable, checksum-verified benchmark downloads for static hosting. */
import { createHash } from 'node:crypto';
import { promises as fs } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { execFileSync } from 'node:child_process';
import { gzipSync } from 'node:zlib';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const output = path.join(root, 'web/public/data');
const release = 'https://github.com/aadithya2112/freshness-benchmark/releases/download/v0.5.0/';
const inventory = await fs.readFile(path.join(root, 'web/release/SHA256SUMS'), 'utf8');
const hashes = new Map(inventory.trim().split('\n').map(line => {
  const [, digest, name] = line.match(/^([a-f0-9]{64})\s+(.+)$/) || [];
  if (!digest || !name) throw new Error('Invalid release checksum inventory');
  return [name, digest];
}));
const sha = bytes => createHash('sha256').update(bytes).digest('hex');
const downloads = [
  ['benchmark-evidence-v2.tar.gz', 'benchmark-evidence.tar.gz'],
  ['benchmark-source-v0.5.0.zip', 'benchmark-source.zip'],
  ['results.json', 'results.json'],
  ['results.csv', 'results.csv'],
  ['verification.json', 'verification.json'],
];
await fs.mkdir(output, { recursive: true });
await Promise.all(downloads.map(async ([asset, destination]) => {
  const target = path.join(output, destination);
  try {
    if (sha(await fs.readFile(target)) === hashes.get(asset)) return;
  } catch (error) {
    if (error.code !== 'ENOENT') throw error;
  }
  const response = await fetch(release + asset, { signal: AbortSignal.timeout(120000) });
  if (!response.ok) throw new Error(`Release download failed: ${asset} (${response.status})`);
  const bytes = Buffer.from(await response.arrayBuffer());
  if (sha(bytes) !== hashes.get(asset)) throw new Error(`Release checksum mismatch: ${asset}`);
  await fs.writeFile(target, bytes);
  console.log(`Verified ${asset}`);
}));
const temporary = await fs.mkdtemp(path.join(os.tmpdir(), 'freshness-evidence-'));
try {
  execFileSync('tar', ['-xzf', path.join(output, 'benchmark-evidence.tar.gz'), '-C', temporary]);
  const evidence = path.join(temporary, 'publication-v2');
  const experiment = JSON.parse(await fs.readFile(path.join(evidence, 'experiment.json'), 'utf8'));
  const progress = (await fs.readFile(path.join(evidence, 'progress.jsonl'), 'utf8')).trim().split('\n').map(JSON.parse);
  const results = JSON.parse(await fs.readFile(path.join(output, 'results.json'), 'utf8'));
  if (progress.length !== 60 || results.completed !== 60 || results.status !== 'complete') {
    throw new Error('Reference release is incomplete');
  }
  const traces = path.join(output, 'evidence');
  await fs.mkdir(traces, { recursive: true });
  for (const run of progress) {
    for (const name of ['summary.json', 'failure.json', 'reference.json', 'events.jsonl', 'queries.jsonl', 'probes.jsonl']) {
      const source = path.join(evidence, 'runs', run.run, name);
      try {
        const bytes = await fs.readFile(source);
        await fs.writeFile(path.join(traces, `${run.run}-${name}.gz`), gzipSync(bytes));
      } catch (error) {
        if (error.code !== 'ENOENT') throw error;
      }
    }
  }
  await fs.copyFile(path.join(evidence, 'source.tar.gz'), path.join(output, 'experiment-source.tar.gz'));
  for (const [name, manifest] of Object.entries(experiment.datasets)) {
    const license = await fs.readFile(path.join(root, 'web/release', `${name}-LICENSE.md`));
    if (sha(license) !== manifest.files['UPSTREAM-LICENSE.md']) throw new Error(`License checksum mismatch: ${name}`);
    await fs.writeFile(path.join(output, `${name}-LICENSE.md`), license);
    await fs.writeFile(path.join(output, `${name}-manifest.json`), JSON.stringify(manifest, null, 2) + '\n');
  }
  const checksums = {};
  async function walk(directory) {
    for (const entry of (await fs.readdir(directory, { withFileTypes: true })).sort((a, b) => a.name.localeCompare(b.name))) {
      const filename = path.join(directory, entry.name);
      if (entry.isDirectory()) await walk(filename);
      else if (filename !== path.join(output, 'checksums.json')) {
        checksums[path.relative(output, filename).split(path.sep).join('/')] = sha(await fs.readFile(filename));
      }
    }
  }
  await walk(output);
  await fs.writeFile(path.join(output, 'checksums.json'), JSON.stringify(checksums, null, 2) + '\n');
  console.log(`Prepared ${progress.length} trials and ${Object.keys(checksums).length} verified downloads`);
} finally {
  await fs.rm(temporary, { recursive: true, force: true });
}
