import { expect, test } from "@playwright/test";
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import {
  acceptanceReport,
  measureVideo,
  readEvidence,
  recordRead,
  recordSubmission,
  recordVideo,
  saveEvidence,
  type EvidenceRun,
  type ServerReport,
} from "../src/commissioningEvidence";

test("download format reaches the existing Python evaluator with explicitly synthetic native fixtures", async ({}, testInfo) => {
  const runsRoot = testInfo.outputPath("synthetic-native");
  const options = {
    cwd: fileURLToPath(new URL("../../../", import.meta.url)),
    env: { ...process.env, PYTHONPATH: "app/backend:app/backend/tests" },
    encoding: "utf8" as const,
  };
  const fixtureData = JSON.parse(
    execFileSync(
      "uv",
      [
        "run",
        "python",
        "-c",
        `
import json,sys
from pathlib import Path
from uuid import uuid4
from test_studio_commissioning_evidence import artifacts
folder=Path(sys.argv[1]); folder.mkdir(parents=True)
runtime,browser,approval=artifacts(folder)
for entry in browser['server_report']['runs']:
 entry['run'].update(session_id=str(uuid4()),version=5,status='completed',completed_steps=4,total_steps=4)
browser['server_report'].update(expires=9999999999,worker_qualified=False)
print(json.dumps(dict(runtime=runtime,server=browser['server_report'],approval=approval)))
`,
        runsRoot,
      ],
      options,
    ),
  );
  const server = fixtureData.server as ServerReport;
  let state = readEvidence(
    { getItem: () => null, setItem: () => {} },
    { ...server, runs: [] },
  );
  for (const [index, { run }] of server.runs.entries()) {
    const documentId = `fixture-document-${index}`;
    state = recordSubmission(state, {
      run_id: run.run_id,
      session_id: run.session_id,
      plan_hash: run.plan_hash,
      document_id: documentId,
      expected_version: 1,
    });
    state = recordRead(state, run, documentId, false, 90);
    const receipt = {
      run_id: run.run_id,
      session_id: run.session_id,
      plan_hash: run.plan_hash,
      native_session_id: run.snapshot!.session_id,
      client_id: `fixture-viewer-${index}`,
      frames_decoded: 10,
      relay_verified: true,
      observed_at: 100,
    };
    state = recordVideo(state, receipt, documentId);
    if (!index) {
      state = recordRead(state, run, "fixture-reloaded", true, 110);
      state = recordVideo(
        state,
        { ...receipt, client_id: "fixture-new-viewer", observed_at: 120 },
        "fixture-reloaded",
      );
    }
  }
  const browser = acceptanceReport(state, server);
  expect(browser.status).toBe("completed");
  const result = JSON.parse(
    execFileSync(
      "uv",
      [
        "run",
        "python",
        "-c",
        `
import json,sys
from pathlib import Path
from academy.commissioning_evidence import evaluate
data=json.load(sys.stdin)
print(json.dumps(evaluate(data['runtime'],data['browser'],Path(sys.argv[1]),commissioning_request=data['approval'])))
`,
        runsRoot,
      ],
      { ...options, input: JSON.stringify({ ...fixtureData, browser }) },
    ),
  );
  expect(result.browser_native_path_passed).toBe(true); // Fixture consistency, never real GPU evidence.
  expect(result.worker_qualified).toBe(false);
});

function fixture() {
  const memory = new Map<string, string>();
  const storage = {
    getItem: (key: string) => memory.get(key) ?? null,
    setItem: (key: string, value: string) => {
      memory.set(key, value);
    },
  };
  const server: ServerReport = {
    grant_id: "grant-1",
    expires: 9999999999,
    worker_qualified: false,
    runs: [],
  };
  let state = readEvidence(storage, server);
  for (let index = 0; index < 2; index++) {
    const run = {
      run_id: `run-${index}`,
      session_id: `session-${index}`,
      plan_hash: String(index).repeat(64),
      version: 5,
      completed_steps: 4,
      total_steps: 4,
      status: "completed",
      scene: "workflow-studio-flex",
      instrument: "flex",
      commissioning: true,
      stale_seconds: 0,
      cleanup: { reset_verified: true },
      snapshot: {
        run_id: `run-${index}`,
        session_id: `native-${index}`,
        plan_hash: String(index).repeat(64),
        status: "completed",
        steps: Array.from({ length: 4 }, (_, step) => ({
          index: step,
          status: "completed",
        })),
        native_state: { studio: { observation_model: "native-semantic" } },
      },
    } as EvidenceRun;
    state = recordSubmission(state, {
      run_id: run.run_id,
      session_id: run.session_id,
      expected_version: 1,
      plan_hash: run.plan_hash,
      document_id: `document-${index}`,
    });
    const video = {
      run_id: run.run_id,
      session_id: run.session_id,
      plan_hash: run.plan_hash,
      native_session_id: `native-${index}`,
      client_id: `viewer-${index}`,
      frames_decoded: 25,
      relay_verified: true,
      observed_at: 100,
    };
    state = recordRead(state, run, `document-${index}`, false, 90);
    state = recordVideo(state, video, `document-${index}`);
    if (!index) {
      state = recordRead(state, run, "reloaded-document", true, 110);
      state = recordVideo(
        state,
        { ...video, client_id: "reloaded-viewer", observed_at: 120 },
        "reloaded-document",
      );
    }
    server.runs.push({
      run,
      browser: {
        run_id: run.run_id,
        native_session_id: `native-${index}`,
        plan_hash: run.plan_hash,
        frames_decoded: 25,
        source: "browser-report",
      },
    });
  }
  return { state, server, storage, memory };
}

test("in-app evidence survives reload and completes only with both server-bound relay videos", () => {
  const f = fixture();
  saveEvidence(f.storage, f.state);
  const restored = readEvidence(f.storage, f.server);
  expect(acceptanceReport(restored, f.server)).toMatchObject({
    schema: "academy.studio-browser-commissioning/1",
    status: "completed",
    submission_posts: 2,
    refresh_verified: true,
  });
  expect(
    acceptanceReport(restored, f.server).browser_runs[0].refresh_frames_decoded,
  ).toBe(25);
  expect(() => recordSubmission(restored, restored.submissions[0])).toThrow(
    /already recorded/,
  );
  const denied = {
    ...f.storage,
    setItem: () => {
      throw new Error("Storage unavailable");
    },
  };
  expect(() => saveEvidence(denied, f.state)).toThrow(/Storage unavailable/);
});

test("missing, stale, wrong-run, failed and unmeasured evidence stays incomplete", () => {
  const changes: ((f: ReturnType<typeof fixture>) => void)[] = [
    (f) => {
      f.state.history_missing = true;
    },
    (f) => {
      f.server.grant_id = "different";
    },
    (f) => {
      f.server.runs[0].browser = null;
    },
    (f) => {
      f.server.runs[0].browser!.native_session_id = "other";
    },
    (f) => {
      f.server.runs[1].run.status = "failed";
    },
    (f) => {
      f.server.runs[1].run.cleanup = null;
    },
    (f) => {
      f.state.submissions.push({ ...f.state.submissions[0] });
    },
    (f) => {
      f.state.videos[0].relay_verified = false;
    },
    (f) => {
      f.state.videos[1].frames_decoded = 0;
    },
    (f) => {
      f.state.videos[1].observed_at = 100;
    },
    (f) => {
      f.state.videos[1].native_session_id = "other-native";
    },
    (f) => {
      f.state.recoveries = [];
    },
    (f) => {
      f.state.submissions.reverse();
    },
  ];
  for (const change of changes) {
    const f = fixture();
    change(f);
    expect(acceptanceReport(f.state, f.server).status).toBe("incomplete");
  }
  const f = fixture();
  expect(readEvidence(f.storage, f.server).history_missing).toBe(true);
  f.memory.set("academy.studio-evidence.grant-1", "broken");
  expect(() => readEvidence(f.storage, f.server)).toThrow();
});

test("recovery requires a new reloaded document and a fresh nonregressing same-native GET", () => {
  const f = fixture();
  const state = { ...f.state, recoveries: [] };
  const original = f.server.runs[0].run;
  for (const [run, document, reloaded] of [
    [original, "reloaded-document", true],
    [original, "third-document", false],
    [{ ...original, version: 1 }, "third-document", true],
    [
      {
        ...original,
        snapshot: { ...original.snapshot!, session_id: "wrong-native" },
      },
      "third-document",
      true,
    ],
  ] as const)
    expect(
      recordRead(state, run, document, reloaded, 200).recoveries,
    ).toHaveLength(0);
  expect(
    recordRead(state, original, "third-document", true, 200).recoveries,
  ).toHaveLength(1);
});

test("download strips credentials and transport details rather than exporting server or storage extras", () => {
  const f = fixture();
  const dirty = f.server as ServerReport & {
    access_token: string;
    ice_servers: object[];
  };
  dirty.access_token = "DO-NOT-EXPORT";
  dirty.ice_servers = [{ credential: "DO-NOT-EXPORT" }];
  Object.assign(dirty.runs[0].run, {
    signaling_url: "DO-NOT-EXPORT",
    claim_token: "DO-NOT-EXPORT",
  });
  Object.assign(f.state.videos[0], { credential: "DO-NOT-EXPORT" });
  Object.assign(f.state, { access_token: "DO-NOT-EXPORT" });
  expect(JSON.stringify(acceptanceReport(f.state, dirty))).not.toContain(
    "DO-NOT-EXPORT",
  );
});

test("actual video measurement rejects old tracks, unselected relay pairs and old frames", async () => {
  const originalStream = globalThis.MediaStream;
  const track = { kind: "video", readyState: "live" };
  class Stream {
    getVideoTracks() {
      return [track];
    }
  }
  globalThis.MediaStream = Stream as unknown as typeof MediaStream;
  try {
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
    const peer = {
      connectionState: "connected",
      getReceivers: () => [{ track }],
      getStats: async () => stats,
    } as unknown as RTCPeerConnection;
    const video = {
      srcObject: new Stream(),
      getVideoPlaybackQuality: () => ({ totalVideoFrames: 20 }),
    } as unknown as HTMLVideoElement;
    expect(await measureVideo(peer, video, 10)).toEqual({
      frames_decoded: 10,
      relay_verified: true,
    });
    expect(await measureVideo(peer, video, 20)).toBeNull();
    stats.set("transport", {
      type: "transport",
      selectedCandidatePairId: "other",
    });
    expect((await measureVideo(peer, video, 10))?.relay_verified).toBe(false);
    video.srcObject = null;
    expect(await measureVideo(peer, video, 10)).toBeNull();
  } finally {
    globalThis.MediaStream = originalStream;
  }
});
