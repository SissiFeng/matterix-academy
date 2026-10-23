// Pure preconditions for the opt-in live Studio harness; these do not authorize a run.
import assert from "node:assert/strict";

const canonical = (value) =>
  JSON.stringify(value, (_key, item) =>
    item && typeof item === "object" && !Array.isArray(item)
      ? Object.fromEntries(
          Object.entries(item).sort(([a], [b]) => a.localeCompare(b)),
        )
      : item,
  );
export function checkedStudioRequest(request) {
  const scope = request?.studio;
  assert.match(
    request?.grant_id ?? "",
    /^[a-f0-9-]{36}$/,
    "A reviewed commissioning grant is required",
  );
  assert.equal(typeof request.subject, "string");
  assert.ok(request.subject.length > 0);
  assert.equal(request.max_runs, 2, "Approve exactly two runs");
  assert.equal(
    scope?.instrument,
    "flex",
    "This acceptance pair targets the reviewed Flex scene",
  );
  assert.equal(scope.scene, "workflow-studio-flex");
  assert.equal(scope.plans?.length, 2);
  assert.notEqual(scope.plans[0].plan_hash, scope.plans[1].plan_hash);
  for (const [index, entry] of scope.plans.entries()) {
    assert.match(entry.plan_hash, /^[a-f0-9]{64}$/);
    const plan = entry.experiment;
    assert.equal(plan?.course_id, "workflow-sandbox");
    assert.equal(plan.instrument, scope.instrument);
    assert.equal(plan.diluent_volume, 0);
    assert.equal(plan.actions?.length, 4);
    assert.deepEqual(
      plan.actions.map(({ kind, well }) => [kind, well]),
      [
        ["pickup", "stock"],
        ["aspirate", "stock"],
        ["dispense", "A1"],
        ["drop", "stock"],
      ],
    );
    for (const action of plan.actions.slice(1, 3))
      assert.equal(action.volume, index === 0 ? 100 : 50);
    assert.equal(plan.layout.waste, "D3");
    assert.equal(new Set(Object.values(plan.layout)).size, 4);
    for (const slot of Object.values(plan.layout))
      assert.match(slot, /^[A-D][1-3]$/);
  }
  const [first, second] = scope.plans.map(({ experiment }) => experiment);
  assert.equal(first.source_volume, second.source_volume);
  assert.ok(
    ["tips", "stock", "plate"].some(
      (item) => first.layout[item] !== second.layout[item],
    ),
    "Second plan must move labware as well as change the transfer",
  );
  return request;
}
export function checkSavedPlan(session, approved, preflight, scope) {
  assert.equal(
    canonical(session.experiment),
    canonical(approved.experiment),
    "Saved normalized plan differs from operator approval",
  );
  assert.equal(preflight.session_id, session.id);
  assert.equal(preflight.session_version, session.version);
  assert.equal(
    preflight.plan_hash,
    approved.plan_hash,
    "Server plan hash must match the exact approved plan",
  );
  assert.equal(preflight.instrument, scope.instrument);
  assert.equal(preflight.scene, scope.scene);
  assert.equal(
    preflight.commissioning,
    true,
    "An explicit commissioning window is required",
  );
  assert.equal(preflight.enabled, true);
  assert.equal(
    preflight.ready,
    true,
    "Saved plan is not ready for native commissioning",
  );
}
export function checkRunBinding(run, session, approved, scope) {
  assert.equal(run?.session_id, session.id);
  assert.equal(run.plan_hash, approved.plan_hash);
  assert.equal(run.scene, scope.scene);
  assert.equal(run.instrument, scope.instrument);
}
export function checkCompletedRun(run, session, approved, scope) {
  checkRunBinding(run, session, approved, scope);
  assert.equal(run.status, "completed");
  assert.equal(run.completed_steps, approved.experiment.actions.length);
  assert.equal(run.total_steps, approved.experiment.actions.length);
  assert.equal(run.cleanup?.reset_verified, true);
  assert.equal(run.snapshot?.run_id, run.run_id);
  assert.equal(run.snapshot?.plan_hash, approved.plan_hash);
  assert.equal(
    run.snapshot?.native_state?.studio?.observation_model,
    "native-semantic",
  );
}
export function checkServerReport(report, request, browserRuns) {
  assert.equal(report.grant_id, request.grant_id);
  assert.equal(report.runs?.length, 2);
  assert.equal(browserRuns.length, 2);
  assert.equal(new Set(browserRuns.map((run) => run.run_id)).size, 2);
  for (const [index, record] of report.runs.entries()) {
    const browser = browserRuns[index];
    assert.equal(
      record.run.run_id,
      browser.run_id,
      "Server receipt must retain approved plan order",
    );
    assert.equal(record.run.plan_hash, request.studio.plans[index].plan_hash);
    assert.equal(record.run.scene, request.studio.scene);
    assert.equal(record.run.instrument, request.studio.instrument);
    assert.equal(record.run.cleanup?.reset_verified, true);
    assert.equal(record.browser?.run_id, browser.run_id);
    assert.equal(record.browser?.plan_hash, record.run.plan_hash);
    assert.equal(record.browser?.source, "browser-report");
    assert.ok(record.browser?.frames_decoded > 0);
    assert.ok(browser.frames_decoded > 0);
    assert.equal(browser.relay_verified, true);
  }
}
