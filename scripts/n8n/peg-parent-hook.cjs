'use strict';

const NAMES = {
  terminal: 'Show durable operation outcome',
  gate: 'PEG enrichment eligible?',
  execute: 'Enrich PEG evidence',
  preserve: 'Preserve Stockscreener outcome',
};

function validChildId(value) {
  return typeof value === 'string' && /^[A-Za-z0-9_-]{6,128}$/.test(value);
}

function edge(node) { return { node, type: 'main', index: 0 }; }
function edgesAt(connections, name, output) {
  return connections?.[name]?.main?.[output] || [];
}
function hasEdge(connections, from, output, to) {
  return edgesAt(connections, from, output).some(item => item?.node === to && item.type === 'main' && item.index === 0);
}
function addEdge(connections, from, output, to) {
  const main = Array.isArray(connections[from]?.main) ? connections[from].main.map(branch => [...branch]) : [];
  while (main.length <= output) main.push([]);
  if (!hasEdge(connections, from, output, to)) main[output].push(edge(to));
  connections[from] = { ...(connections[from] || {}), main };
}
function nodesFor(childID, terminalPosition) {
  const [x, y] = Array.isArray(terminalPosition) ? terminalPosition : [0, 0];
  const eligible = `={{ ['complete','already_complete','published_with_warnings'].includes($json.outcome) && $json.publicationStatus === 'verified' && /^\\d{4}-\\d{2}-\\d{2}$/.test($json.marketDate || '') && !Number.isNaN(Date.parse($json.marketDate + 'T00:00:00Z')) && new Date($json.marketDate + 'T00:00:00Z').toISOString().slice(0,10) === $json.marketDate }}`;
  return [
    { name: NAMES.gate, type: 'n8n-nodes-base.if', typeVersion: 2.2,
      parameters: { conditions: { options: { caseSensitive: true, leftValue: '', typeValidation: 'strict', version: 2 },
        conditions: [{ id: 'peg-publication-eligible', leftValue: eligible, rightValue: true,
          operator: { type: 'boolean', operation: 'true', singleValue: true } }], combinator: 'and' } }, position: [x + 260, y] },
    { name: NAMES.execute, type: 'n8n-nodes-base.executeWorkflow', typeVersion: 1.4,
      parameters: { workflowId: { __rl: true, mode: 'id', value: childID }, mode: 'once', options: { waitForSubWorkflow: false } },
      position: [x + 520, y - 100], retryOnFail: false, onError: 'continueRegularOutput' },
    { name: NAMES.preserve, type: 'n8n-nodes-base.code', typeVersion: 2,
      parameters: { mode: 'runOnceForAllItems', jsCode: `return [{json:$('${NAMES.terminal}').first().json}];` }, position: [x + 780, y] },
  ];
}

function applyHook(originalGraph, childID = 'yFYPbnopMWJisvld') {
  if (!originalGraph || !Array.isArray(originalGraph.nodes) || !originalGraph.connections || typeof originalGraph.connections !== 'object') {
    throw new Error('peg_hook_graph');
  }
  if (!validChildId(childID)) throw new Error('peg_hook_child_id');
  const terminal = originalGraph.nodes.find(node => node?.name === NAMES.terminal);
  if (!terminal) throw new Error('peg_hook_terminal');
  const names = new Set(originalGraph.nodes.map(node => node?.name));
  const hookNames = [NAMES.gate, NAMES.execute, NAMES.preserve];
  const existingCount = hookNames.filter(name => names.has(name)).length;
  if (existingCount > 0 && existingCount < hookNames.length) throw new Error('peg_hook_partial');
  let nodes = originalGraph.nodes;
  if (!existingCount) nodes = [...originalGraph.nodes, ...nodesFor(childID, terminal.position)];
  else {
    const execute = originalGraph.nodes.find(node => node.name === NAMES.execute);
    if (execute?.parameters?.workflowId?.value !== childID) throw new Error('peg_hook_child_id_mismatch');
  }

  const expected = [[NAMES.terminal, 0, NAMES.gate], [NAMES.gate, 0, NAMES.execute],
    [NAMES.gate, 1, NAMES.preserve], [NAMES.execute, 0, NAMES.preserve]];
  if (expected.every(([from, output, to]) => hasEdge(originalGraph.connections, from, output, to))) return originalGraph;
  const connections = { ...originalGraph.connections };
  for (const [from, output, to] of expected) addEdge(connections, from, output, to);
  return { ...originalGraph, nodes, connections };
}

module.exports = { applyHook, validChildId, NAMES };
