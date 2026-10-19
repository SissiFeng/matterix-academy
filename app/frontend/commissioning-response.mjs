// Follow the same submission and session-polling contract as SimulationLab.
export function captureRun(method, pathname, value, currentRunId, latest) {
  const submission = method === "POST" && pathname === "/api/runs";
  const polling =
    method === "GET" &&
    /^\/api\/sessions\/[a-f0-9-]+\/remote-run$/.test(pathname);
  if (!(submission || polling) || !value?.run_id)
    return { currentRunId, latest };
  if (submission) currentRunId = value.run_id;
  if (
    value.run_id === currentRunId &&
    (!latest || value.version >= latest.version)
  )
    latest = value;
  return { currentRunId, latest };
}
