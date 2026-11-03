'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const { applyHook, NAMES } = require('./peg-parent-hook.cjs');

const CHILD = 'yFYPbnopMWJisvld';
function graph() {
  const nodes = Array.from({ length: 96 }, (_, i) => ({ name: `Existing ${i}`, type: 'n8n-nodes-base.code', typeVersion: 2, parameters: {}, position: [i, 0] }));
  nodes.push({ name: NAMES.terminal, type: 'n8n-nodes-base.code', typeVersion: 2, parameters: { jsCode: 'return $input.all();' }, position: [100, 720] });
  return { id: 'parent-workflow', name: 'Stockscreener', active: false, nodes,
    connections: { 'Existing 0': { main: [[{ node: 'Existing 1', type: 'main', index: 0 }]] } },
    settings: { executionTimeout: 3600, executionOrder: 'v1' }, credentials: { githubApi: { id: 'credential-ref' } } };
}
function freezeDeep(value) {
  if (!value || typeof value !== 'object' || Object.isFrozen(value)) return value;
  Object.freeze(value);
  Object.values(value).forEach(freezeDeep);
  return value;
}
function nodeByName(value, name) { return value.nodes.find(item => item.name === name); }
function edgeCount(value, from, output, to) {
  return (value.connections[from]?.main?.[output] || []).filter(item => item.node === to).length;
}

test('adds exactly three native nodes after durable terminal while preserving original frozen graph', () => {
  const original = freezeDeep(graph());
  const updated = applyHook(original);
  assert.equal(original.nodes.length, 97);
  assert.equal(updated.nodes.length, 100);
  assert.deepEqual(updated.nodes.slice(0, 97), original.nodes);
  assert.deepEqual(updated.settings, original.settings);
  assert.deepEqual(updated.credentials, original.credentials);
  assert.notEqual(updated.nodes, original.nodes);
  assert.notEqual(updated.connections, original.connections);
  assert.equal(edgeCount(updated, NAMES.terminal, 0, NAMES.gate), 1);
  assert.equal(edgeCount(updated, NAMES.gate, 0, NAMES.execute), 1);
  assert.equal(edgeCount(updated, NAMES.gate, 1, NAMES.preserve), 1);
  assert.equal(edgeCount(updated, NAMES.execute, 0, NAMES.preserve), 1);
});

test('gate checks allowed outcomes, verified publication, and a real exact calendar date', () => {
  const updated = applyHook(graph());
  const params = nodeByName(updated, NAMES.gate).parameters;
  assert.equal(nodeByName(updated, NAMES.gate).typeVersion, 2.2);
  const expression = params.conditions.conditions[0].leftValue.slice(3, -2).trim();
  const accepts = new Function('$json', `return (${expression});`);
  for (const outcome of ['complete', 'already_complete', 'published_with_warnings']) {
    assert.equal(accepts({ outcome, publicationStatus: 'verified', marketDate: '2026-11-04' }), true);
  }
  for (const value of [
    { outcome: 'failed', publicationStatus: 'verified', marketDate: '2026-11-04' },
    { outcome: 'in_progress', publicationStatus: 'verified', marketDate: '2026-11-04' },
    { outcome: 'complete', publicationStatus: 'pending', marketDate: '2026-11-04' },
    { outcome: 'complete', publicationStatus: 'verified', marketDate: '2026-02-30' },
    { outcome: 'complete', publicationStatus: 'verified', marketDate: 'yesterday' },
  ]) assert.equal(accepts(value), false);
});

test('child workflow is asynchronous, receives original input, and soft-fails to the original terminal item', async () => {
  const updated = applyHook(graph());
  const execute = nodeByName(updated, NAMES.execute);
  assert.equal(execute.type, 'n8n-nodes-base.executeWorkflow');
  assert.equal(execute.typeVersion, 1.4);
  assert.deepEqual(execute.parameters.workflowId, { __rl: true, mode: 'id', value: CHILD });
  assert.equal(execute.parameters.mode, 'once');
  assert.equal(execute.parameters.options.waitForSubWorkflow, false);
  assert.equal(execute.retryOnFail, false);
  assert.equal(execute.onError, 'continueRegularOutput');
  const originalOutcome = { outcome: 'complete', publicationStatus: 'verified', marketDate: '2026-11-04', runId: 'daily-run' };
  const code = nodeByName(updated, NAMES.preserve).parameters.jsCode;
  const asyncFunction = Object.getPrototypeOf(async function () {}).constructor;
  const output = await new asyncFunction('$', code)(() => ({ first: () => ({ json: originalOutcome }) }));
  assert.deepEqual(output, [{ json: originalOutcome }]);
});

test('reapplying hook is idempotent and does not duplicate nodes or connections', () => {
  const once = applyHook(graph());
  const twice = applyHook(once);
  assert.equal(twice, once);
  assert.equal(twice.nodes.length, 100);
  for (const [from, output, to] of [[NAMES.terminal, 0, NAMES.gate], [NAMES.gate, 0, NAMES.execute],
    [NAMES.gate, 1, NAMES.preserve], [NAMES.execute, 0, NAMES.preserve]]) {
    assert.equal(edgeCount(twice, from, output, to), 1);
  }
});

test('rejects invalid child IDs, missing terminal, and partial preexisting hook', () => {
  assert.throws(() => applyHook(graph(), 'https://example.com'), /peg_hook_child_id/);
  const missing = graph();
  missing.nodes = missing.nodes.filter(node => node.name !== NAMES.terminal);
  assert.throws(() => applyHook(missing), /peg_hook_terminal/);
  const partial = graph();
  partial.nodes.push({ name: NAMES.gate });
  assert.throws(() => applyHook(partial), /peg_hook_partial/);
});
