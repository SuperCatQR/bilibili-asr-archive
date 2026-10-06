// Run with Bun and an installed @mstar-harness/engine 3.11.2 package directory.
// All writes are confined to a newly created temporary fixture harness.
import assert from 'node:assert/strict';
import { mkdtempSync, mkdirSync, readFileSync, writeFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
import { createHash } from 'node:crypto';

const engineDir = resolve(process.argv[2]);
const packageInfo = JSON.parse(readFileSync(join(engineDir, 'package.json'), 'utf8'));
assert.equal(packageInfo.version, '3.11.2');
const engine = await import(pathToFileURL(join(engineDir, 'dist', 'engine.js')));
const root = mkdtempSync(join(tmpdir(), 'bili-harness-concurrency-'));
process.env.MSTAR_HARNESS_DIR = root;
engine.setArtifactStore(engine.createFsStore(root));
const date = '2026-10-06T00:00:00Z';
const fixture = (id) => ({
  schema_version: 1, id, type: 'iteration', status: 'running',
  started_at: date, updated_at: date, plans: [{id: 'fixture-plan', title: 'Fixture', file: 'plans/fixture.md', status: 'Todo', progress: '0/1'}],
  branch: {base: 'main', integration: 'iteration/fixture', target: 'main'},
  integration_worktree_path: root, compass_ref: `iterations/${id}/delivery-compass.md`,
});
try {
  writeFileSync(join(root, 'status.json'), JSON.stringify({version: 2, updated_at: date, workflows: []}));
  for (const id of ['session-a', 'session-b']) {
    await engine.writeWorkflowSnapshot(fixture(id), join(root, 'workflows', id));
  }
  const entry = (id) => ({id, type: 'iteration', started_at: date, dir: `workflows/${id}`});
  await engine.registerWorkflow(join(root, 'status.json'), entry('session-b'));
  const stale = JSON.parse(readFileSync(join(root, 'status.json'), 'utf8'));
  assert.deepEqual(stale.workflows.map(row => row.id), ['session-b']);
  await Promise.all([
    engine.registerWorkflow(join(root, 'status.json'), entry('session-a')),
    engine.unregisterWorkflow(join(root, 'status.json'), 'session-b'),
  ]);
  assert.deepEqual(JSON.parse(readFileSync(join(root, 'status.json'), 'utf8')).workflows.map(row => row.id), ['session-a']);
  console.log('#192 PASS: interleaved registration/close preserves the live peer entry');

  const dir = join(root, 'workflows', 'session-a');
  const path = join(dir, 'snapshot.json');
  const old = JSON.parse(readFileSync(path, 'utf8'));
  const oldVersion = 'sha256:' + createHash('sha256').update(readFileSync(path)).digest('hex');
  const completed = structuredClone(old);
  completed.plans[0].status = 'Done';
  completed.plans[0].progress = '1/1';
  // A fixture peer's completed write establishes the interleaving, outside any live harness.
  writeFileSync(path, JSON.stringify(completed));
  await assert.rejects(engine.writeWorkflowSnapshot(old, dir, {expectedVersion: oldVersion}), error => error.code === 'coordination.version-conflict');
  assert.deepEqual(JSON.parse(readFileSync(path, 'utf8')), completed);
  console.log('#207 PASS: stale writer refuses a Done-to-Todo row regression');
  const staleLease = structuredClone(completed);
  staleLease.plans[0].status = 'InProgress';
  staleLease.plans[0].progress = '0/1';
  staleLease.plans[0].execution_lease = {holder: 'old-session', claimed_at: date, worktree_path: root, working_branch: 'codex/fixture'};
  await assert.rejects(engine.writeWorkflowSnapshot(staleLease, dir, {expectedVersion: oldVersion}), error => error.code === 'coordination.version-conflict');
  assert.equal(JSON.parse(readFileSync(path, 'utf8')).plans[0].execution_lease, undefined);
  console.log('#207 PASS: stale lease cannot be restored');
} finally {
  assert.ok(root.startsWith(join(tmpdir(), 'bili-harness-concurrency-')));
  rmSync(root, {recursive: true, force: true});
}
