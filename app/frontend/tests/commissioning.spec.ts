import { test, expect } from "@playwright/test";
import { execFileSync } from "node:child_process";
import path from "node:path";

const fixtureCode = `
import json,sys,time
from pathlib import Path
from uuid import uuid4
from academy.auth import local_signer
from academy.settings import Settings
from academy.store import SQLiteStore
from academy.commissioning import authorize,CommissioningRequest,PARTITION,KEY
from academy.runtime_inventory import PROFILE
from academy.runs import RunService,StartRequest,BindRequest,SnapshotRequest,CleanupRequest
from test_dispatch import worker
from test_mixing import mixing_report
store=SQLiteStore('.data/e2e.sqlite')
data=json.loads(sys.argv[1])
if data['action']=='setup':
 old=store.get(PARTITION,KEY)
 if old: store.transact([__import__('academy.store',fromlist=['Write']).Write(PARTITION,KEY,None,old['version'])])
 settings=Settings(allow_demo=True,secret=Path('.data/dev-session.key').read_text())
 subject=local_signer(settings).loads(data['cookie'])['sub']
 name='fixture-commission-'+uuid4().hex[:12]
 worker(store,name,qualified=False,state='quarantined',scenes=[],controls=[],engine_version=PROFILE['engine_commit'],asset_version=PROFILE['asset_commit'])
 authorize(store,CommissioningRequest(grant_id=uuid4(),subject=subject,worker_id=name,engine_version=PROFILE['engine_commit'],asset_version=PROFILE['asset_commit']))
 print(json.dumps({'worker_id':name}))
else:
 service=RunService(store,False)
 claimed=service.claim(data['worker_id'])
 native=uuid4();rid=claimed['run_id'];token=claimed['claim_token']
 service.start(data['worker_id'],rid,StartRequest(claim_token=token,command_id=uuid4()))
 service.bind(data['worker_id'],rid,BindRequest(claim_token=token,native_session_id=native,expected_revision=1,engine_version=PROFILE['engine_commit'],asset_version=PROFILE['asset_commit']))
 _,_,body=mixing_report()
 body.update(run_id=rid,session_id=str(native),plan_hash=claimed['plan_hash'],engine_version=PROFILE['engine_commit'],asset_version=PROFILE['asset_commit'])
 service.snapshot(data['worker_id'],rid,SnapshotRequest(claim_token=token,snapshot=body))
 service.cleanup(data['worker_id'],rid,CleanupRequest(claim_token=token,command_id=uuid4(),native_session_id=native,engine_version=PROFILE['engine_commit'],asset_version=PROFILE['asset_commit'],reset_verified=True,checks={k:True for k in ('objects','liquids','tips','controllers','stopped')}))
 print('{}')
`;
function fixture(data: object) {
  return JSON.parse(
    execFileSync(
      "uv",
      ["run", "python", "-c", fixtureCode, JSON.stringify(data)],
      {
        cwd: path.resolve("../.."),
        env: { ...process.env, PYTHONPATH: "app/backend:app/backend/tests" },
        encoding: "utf8",
      },
    ),
  );
}

test("synthetic commissioning fixture closes browser submit/refresh/cleanup path without qualifying host", async ({
  page,
}) => {
  await page.goto("/");
  await page.getByPlaceholder("Your first name").fill("Commissioning learner");
  await page.getByRole("button", { name: "Enter the learning lab" }).click();
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await page.getByRole("button", { name: "Open my workspace" }).click();
  const cookie = (await page.context().cookies()).find(
    (item) => item.name === "academy_local",
  );
  const host = fixture({ action: "setup", cookie: cookie!.value });
  await page
    .getByRole("button", { name: "Simulation lab", exact: true })
    .click();
  await expect(page.getByText(/Operator commissioning window/)).toBeVisible();
  let submissions = 0;
  page.on("request", (request) => {
    if (request.method() === "POST" && request.url().endsWith("/api/runs"))
      submissions++;
  });
  await page
    .getByRole("button", { name: "Run mixing experiment", exact: true })
    .click();
  await expect.poll(() => submissions).toBe(1);
  await page.reload();
  await expect(page.getByText(/Operator commissioning window/)).toBeVisible();
  expect(submissions).toBe(1);
  fixture({ action: "finish", worker_id: host.worker_id });
  await expect(
    page.getByRole("progressbar", { name: "Confirmed native steps" }),
  ).toHaveAttribute("aria-valuenow", "5");
  await expect(
    page.getByRole("button", { name: "New experiment", exact: true }),
  ).toBeVisible();
  const report = await (
    await page.request.get("/api/commissioning/report")
  ).json();
  expect(report.worker_qualified).toBe(false);
  expect(report.runs).toHaveLength(1);
  expect(report.runs[0].browser).toBeNull(); // No real video was supplied by this fixture.
});
