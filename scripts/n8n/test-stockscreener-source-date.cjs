const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { execFileSync } = require("node:child_process");

const folder = __dirname;
const workflowPath = path.join(folder, "stockscreener.workflow.json");

function generatedWorkflow() {
  execFileSync(process.execPath, [path.join(folder, "build-workflow.cjs")]);
  return JSON.parse(fs.readFileSync(workflowPath, "utf8"));
}

function nodeByName(workflow, name) {
  const node = workflow.nodes.find((item) => item.name === name);
  assert.ok(node, `missing workflow node: ${name}`);
  return node;
}

function initialize(workflow, input, now) {
  const code = nodeByName(workflow, "Resolve official session and validate operator")
    .parameters.jsCode;
  const run = new Function("$input", "$now", "$execution", code);
  return run(
    { first: () => ({ json: input }) },
    { setZone: () => ({ toISODate: () => now.slice(0, 10) }) },
    { id: "test-execution" },
  )[0].json.state;
}

function runKind(workflow, mode) {
  const assignments = nodeByName(workflow, "Scheduled same-day inputs")
    .parameters.assignments.assignments;
  const expression = assignments.find(({ name }) => name === "run_kind").value;
  const body = expression.replace(/^=\{\{\s*/, "").replace(/\s*\}\}$/, "");
  return new Function("$execution", `return (${body});`)({ mode });
}

test("generated scheduled input keeps the event timestamp and routes manual tests as manual", () => {
  const workflow = generatedWorkflow();
  const assignments = nodeByName(workflow, "Scheduled same-day inputs")
    .parameters.assignments.assignments;
  const values = Object.fromEntries(assignments.map(({ name, value }) => [name, value]));

  assert.equal(runKind(workflow, "test"), "manual");
  assert.equal(runKind(workflow, "manual"), "manual");
  assert.equal(runKind(workflow, "trigger"), "scheduled");
  assert.match(values.run_kind, /^=\{\{/);
  assert.equal(values.schedule_timestamp, '={{ $json.timestamp || "" }}');
});

test("generated scheduled market date comes from the original Taipei trigger event", () => {
  const workflow = generatedWorkflow();
  const initialize = nodeByName(workflow, "Resolve official session and validate operator")
    .parameters.jsCode;

  assert.ok(initialize.includes("schedule_timestamp"));
  assert.ok(initialize.includes("invalid_schedule_timestamp"));
  assert.ok(initialize.includes("Asia/Taipei"));
});

test("recovery initialization uses the scheduled event date instead of post-midnight wall clock", () => {
  const workflow = generatedWorkflow();
  const state = initialize(workflow, {
    run_kind: "scheduled",
    schedule_timestamp: "2026-10-13T15:30:00.000Z",
    site_url: "https://stockscreener.andyshih.uk",
  }, "2026-10-14T00:30:00+08:00");

  assert.equal(state.marketDate, "2026-10-13");
  assert.equal(state.runKind, "scheduled");
});

test("manual execution still uses the current Taipei date without a schedule timestamp", () => {
  const workflow = generatedWorkflow();
  const state = initialize(workflow, {
    run_kind: "manual",
    mode: "screen",
    site_url: "https://stockscreener.andyshih.uk",
  }, "2026-10-14T00:30:00+08:00");

  assert.equal(state.marketDate, "2026-10-14");
  assert.equal(state.runKind, "manual");
  assert.equal(state.resolveLatest, true);
});
