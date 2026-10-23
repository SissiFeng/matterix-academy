import { test } from "node:test";
import assert from "node:assert/strict";
import {
  captureRun,
  isFreshRecovery,
  videoUsesCurrentRelay,
} from "./commissioning-response.mjs";
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

test("reload recovery requires a fresh document GET of the same run at its confirmed version", () => {
  const receipt = {
    method: "GET",
    pathname: "/api/sessions/abc-123/remote-run",
    value: { run_id: "a", version: 4 },
    requestNavigation: 2,
    minimumNavigation: 2,
    runId: "a",
    minimumVersion: 4,
  };
  assert.equal(isFreshRecovery(receipt), true);
  for (const stale of [
    { ...receipt, requestNavigation: 1 },
    { ...receipt, requestNavigation: undefined },
    { ...receipt, method: "POST", pathname: "/api/runs" },
    { ...receipt, value: { run_id: "b", version: 4 } },
    { ...receipt, value: { run_id: "a", version: 3 } },
    { ...receipt, value: undefined },
  ])
    assert.equal(isFreshRecovery(stale), false);
});

function relayPeer(track, options = {}) {
  const stats = new Map([
    ["transport", { type: "transport", selectedCandidatePairId: "pair" }],
    [
      "pair",
      {
        id: "pair",
        type: "candidate-pair",
        state: "succeeded",
        nominated: true,
        localCandidateId: "local",
        remoteCandidateId: "remote",
      },
    ],
    ["local", { candidateType: "relay" }],
    ["remote", { candidateType: "relay" }],
  ]);
  return {
    connectionState: "connected",
    getReceivers: () => [{ track }],
    getStats: async () => stats,
    ...options,
  };
}

test("a previous run's closed or unrelated connected relay peer cannot validate the current video", async () => {
  const old = { kind: "video", readyState: "live" };
  const current = { kind: "video", readyState: "live" };
  const video = { srcObject: { getVideoTracks: () => [current] } };
  assert.equal(await videoUsesCurrentRelay(video, [relayPeer(current)]), true);
  assert.equal(await videoUsesCurrentRelay(video, [relayPeer(old)]), false);
  assert.equal(
    await videoUsesCurrentRelay(video, [
      relayPeer(current, { connectionState: "closed" }),
    ]),
    false,
  );
  const direct = relayPeer(current, { getStats: async () => new Map() });
  assert.equal(
    await videoUsesCurrentRelay(video, [
      relayPeer(old, { connectionState: "closed" }),
      direct,
    ]),
    false,
  );
  assert.equal(
    await videoUsesCurrentRelay({ srcObject: null }, [relayPeer(current)]),
    false,
  );
});

test("relay proof rejects a peer closing during stats collection and a historical unselected pair", async () => {
  const track = { kind: "video", readyState: "live" };
  const video = { srcObject: { getVideoTracks: () => [track] } };
  const closing = relayPeer(track);
  const original = closing.getStats;
  closing.getStats = async () => {
    closing.connectionState = "closed";
    return original();
  };
  assert.equal(await videoUsesCurrentRelay(video, [closing]), false);
  const changing = relayPeer(track);
  const changingStats = changing.getStats;
  const changingVideo = { srcObject: { getVideoTracks: () => [track] } };
  changing.getStats = async () => {
    changingVideo.srcObject = { getVideoTracks: () => [] };
    return changingStats();
  };
  assert.equal(await videoUsesCurrentRelay(changingVideo, [changing]), false);
  const stale = relayPeer(track);
  const staleStats = await stale.getStats();
  staleStats.get("transport").selectedCandidatePairId = "other-pair";
  assert.equal(await videoUsesCurrentRelay(video, [stale]), false);
});
