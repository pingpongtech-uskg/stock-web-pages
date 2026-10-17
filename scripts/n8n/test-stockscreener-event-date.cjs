const test = require("node:test");
const assert = require("node:assert/strict");
const vm = require("node:vm");
const source = require("./stockscreener-event-date.cjs");

function resolve(timestamp) {
  return vm.runInNewContext(`(() => { ${source}; return stockscreenerEventDate(${JSON.stringify(timestamp)}); })()`, {});
}

test("scheduled market date follows Taipei event time even after midnight", () => {
  assert.equal(resolve("2026-10-13T18:00:00+08:00"), "2026-10-13");
  assert.equal(resolve("2026-10-13T10:00:00Z"), "2026-10-13");
});

test("recovery tick timestamp is converted in Taipei across year boundary", () => {
  assert.equal(resolve("2026-12-31T16:00:00Z"), "2027-01-01");
});

test("missing or malformed scheduled timestamp fails closed", () => {
  assert.throws(() => resolve(""), /invalid_schedule_timestamp/);
  assert.throws(() => resolve("not-a-timestamp"), /invalid_schedule_timestamp/);
});
