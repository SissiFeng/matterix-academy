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

// A reload is accepted only from a session GET initiated in the new document.
// A late pre-reload response, cached latest object, or another POST is insufficient.
export function isFreshRecovery({
  method,
  pathname,
  value,
  requestNavigation,
  minimumNavigation,
  runId,
  minimumVersion,
}) {
  return (
    method === "GET" &&
    /^\/api\/sessions\/[a-f0-9-]+\/remote-run$/.test(pathname) &&
    Number.isInteger(requestNavigation) &&
    requestNavigation >= minimumNavigation &&
    value?.run_id === runId &&
    Number.isInteger(value.version) &&
    value.version >= minimumVersion
  );
}

// This function is also serialized into the browser by locator.evaluate().
// It has no module dependencies: tests supply peers, the browser uses its captured peers.
export async function videoUsesCurrentRelay(
  video,
  peers = globalThis.__commissioningPeers ?? [],
) {
  for (const peer of peers) {
    const carriesVideo = () =>
      peer.connectionState === "connected" &&
      peer
        .getReceivers()
        .some(
          ({ track }) =>
            track?.kind === "video" &&
            track.readyState === "live" &&
            (video.srcObject?.getVideoTracks?.() ?? []).includes(track),
        );
    if (!carriesVideo()) continue;
    let stats;
    try {
      stats = await peer.getStats();
    } catch {
      continue;
    }
    if (!carriesVideo()) continue;
    const selected = new Set(
      [...stats.values()]
        .filter((row) => row.type === "transport")
        .map((row) => row.selectedCandidatePairId)
        .filter(Boolean),
    );
    for (const row of stats.values()) {
      if (
        row.type !== "candidate-pair" ||
        !selected.has(row.id) ||
        row.state !== "succeeded" ||
        !row.nominated
      )
        continue;
      const local = stats.get(row.localCandidateId);
      const remote = stats.get(row.remoteCandidateId);
      if (local?.candidateType === "relay" && remote?.candidateType === "relay")
        return true;
    }
  }
  return false;
}
