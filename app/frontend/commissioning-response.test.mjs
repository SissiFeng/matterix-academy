import { test } from "node:test";
import assert from "node:assert/strict";
import { captureRun } from "./commissioning-response.mjs";
test("tracks real submit/session polling URLs and rejects stale or unrelated receipts", () => {
  let state = captureRun("POST", "/api/runs", { run_id: "a", version: 1 });
  state = captureRun(
    "GET",
    "/api/sessions/abc-123/remote-run",
    { run_id: "a", version: 4 },
    state.currentRunId,
    state.latest,
  );
  assert.equal(state.latest.version, 4);
  for (const value of [
    { run_id: "a", version: 2 },
    { run_id: "b", version: 9 },
    null,
  ]) {
    state = captureRun(
      "GET",
      "/api/sessions/abc-123/remote-run",
      value,
      state.currentRunId,
      state.latest,
    );
    assert.equal(state.latest.version, 4);
    assert.equal(state.currentRunId, "a");
  }
});
