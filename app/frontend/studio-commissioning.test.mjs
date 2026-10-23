import { test } from "node:test";
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import {
  checkedStudioRequest,
  checkSavedPlan,
  checkRunBinding,
  checkCompletedRun,
  checkServerReport,
} from "./studio-commissioning-contract.mjs";

function approvedRequest() {
  return {
    grant_id: "eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee",
    subject: "approved-subject",
    max_runs: 2,
    studio: {
      instrument: "flex",
      scene: "workflow-studio-flex",
      plans: [100, 50].map((volume, index) => ({
        plan_hash: String(index + 1).repeat(64),
        experiment: {
          title: "Reviewed native transfer",
          course_id: "workflow-sandbox",
          instrument: "flex",
          transfer_volume: 100,
          source_volume: 1000,
          diluent_volume: 0,
          layout: {
            stock: "D1",
            plate: "D2",
            tips: index === 0 ? "B1" : "C1",
            waste: "D3",
          },
          actions: [
            { kind: "pickup", well: "stock", volume: 100 },
            { kind: "aspirate", well: "stock", volume },
            { kind: "dispense", well: "A1", volume },
            { kind: "drop", well: "stock", volume: 100 },
          ],
        },
      })),
    },
  };
}
function fixture() {
  const request = approvedRequest();
  const approved = request.studio.plans[0];
  const session = {
    id: "saved-session",
    version: 1,
    experiment: approved.experiment,
  };
  const preflight = {
    session_id: session.id,
    session_version: 1,
    plan_hash: approved.plan_hash,
    instrument: "flex",
    scene: request.studio.scene,
    ready: true,
    enabled: true,
    commissioning: true,
  };
  const run = {
    run_id: "native-run",
    session_id: session.id,
    plan_hash: approved.plan_hash,
    scene: request.studio.scene,
    instrument: "flex",
    status: "completed",
    completed_steps: 4,
    total_steps: 4,
    cleanup: { reset_verified: true },
    snapshot: {
      run_id: "native-run",
      plan_hash: approved.plan_hash,
      native_state: { studio: { observation_model: "native-semantic" } },
    },
  };
  return { request, approved, session, preflight, run };
}
test("acceptance requires two approved exact transfer plans with changed volume and geometry", () => {
  assert.equal(checkedStudioRequest(approvedRequest()).studio.plans.length, 2);
  for (const change of [
    (r) => (r.studio.plans[1].experiment.actions[1].volume = 100),
    (r) => (r.studio.plans[1].experiment.layout.tips = "B1"),
    (r) => (r.studio.plans[1].experiment.source_volume = 900),
    (r) => (r.studio.plans[0].experiment.diluent_volume = 100),
    (r) => (r.studio.plans[1].plan_hash = r.studio.plans[0].plan_hash),
    (r) => (r.max_runs = 3),
    (r) => (r.studio.instrument = "ot2"),
  ]) {
    const request = approvedRequest();
    change(request);
    assert.throws(() => checkedStudioRequest(request));
  }
});
test("server preflight must bind complete saved plan, revision, approval and native scene", () => {
  const f = fixture();
  checkSavedPlan(f.session, f.approved, f.preflight, f.request.studio);
  for (const patch of [
    { ready: false },
    { enabled: false },
    { commissioning: false },
    { session_id: "other" },
    { session_version: 2 },
    { plan_hash: "9".repeat(64) },
    { scene: "flex-mixing" },
  ])
    assert.throws(() =>
      checkSavedPlan(
        f.session,
        f.approved,
        { ...f.preflight, ...patch },
        f.request.studio,
      ),
    );
  const changed = structuredClone(f.session);
  changed.experiment.title = "Different hash-bound title";
  assert.throws(() =>
    checkSavedPlan(changed, f.approved, f.preflight, f.request.studio),
  );
  const reordered = {
    ...f.session,
    experiment: Object.fromEntries(
      Object.entries(f.session.experiment).reverse(),
    ),
  };
  checkSavedPlan(reordered, f.approved, f.preflight, f.request.studio);
});
test("complete evidence requires the matching run, all four saved steps and native reset", () => {
  const f = fixture();
  checkCompletedRun(f.run, f.session, f.approved, f.request.studio);
  for (const patch of [
    { status: "running" },
    { completed_steps: 3 },
    { total_steps: 5 },
    { cleanup: null },
    { snapshot: null },
    { scene: "flex-mixing" },
    { plan_hash: "wrong" },
  ])
    assert.throws(() =>
      checkCompletedRun(
        { ...f.run, ...patch },
        f.session,
        f.approved,
        f.request.studio,
      ),
    );
  assert.throws(() =>
    checkRunBinding(
      { ...f.run, session_id: "another learner session" },
      f.session,
      f.approved,
      f.request.studio,
    ),
  );
});
function evidence() {
  const request = approvedRequest();
  const browserRuns = [0, 1].map((index) => ({
    run_id: `run-${index}`,
    frames_decoded: 42,
    relay_verified: true,
  }));
  const report = {
    grant_id: request.grant_id,
    runs: browserRuns.map((row, index) => ({
      run: {
        run_id: row.run_id,
        plan_hash: request.studio.plans[index].plan_hash,
        scene: request.studio.scene,
        instrument: "flex",
        cleanup: { reset_verified: true },
      },
      browser: {
        run_id: row.run_id,
        plan_hash: request.studio.plans[index].plan_hash,
        source: "browser-report",
        frames_decoded: 42,
      },
    })),
  };
  return { request, report, browserRuns };
}
test("ordered server receipts need both current decoded relay videos and the reviewed grant", () => {
  const e = evidence();
  checkServerReport(e.report, e.request, e.browserRuns);
  for (const change of [
    (e) => (e.report.grant_id = "wrong-grant"),
    (e) => e.report.runs.reverse(),
    (e) => (e.report.runs[1].browser = null),
    (e) => (e.report.runs[1].browser.frames_decoded = 0),
    (e) => (e.browserRuns[1].relay_verified = false),
    (e) => (e.browserRuns[1].run_id = e.browserRuns[0].run_id),
    (e) => (e.report.runs[0].run.cleanup.reset_verified = false),
  ]) {
    const e = evidence();
    change(e);
    assert.throws(() => checkServerReport(e.report, e.request, e.browserRuns));
  }
});
test("live executable refuses missing authorization flags before opening a browser", () => {
  const result = spawnSync(
    process.execPath,
    [new URL("./studio-commissioning.mjs", import.meta.url).pathname],
    {
      encoding: "utf8",
      env: { ...process.env, ACADEMY_COMMISSIONING_URL: "" },
    },
  );
  assert.notEqual(result.status, 0);
  assert.match(result.stderr, /Requires --confirm-live --request/);
});
