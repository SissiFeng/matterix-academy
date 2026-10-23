import { useEffect, useRef, useState } from "react";
import { Monitor, RefreshCw } from "lucide-react";
import { api, ApiError, json } from "./api";
import { terminalRuns, type SimulationRun } from "./simulationTypes";
import s from "./SimulationLab.module.css";

type Grant = {
  run_id: string;
  session_id: string;
  native_session_id: string;
  plan_hash: string;
  client_id: string;
  expires: number;
  signaling_url: string;
  ice_servers: RTCIceServer[];
};

export type ViewportRun = Pick<
  SimulationRun,
  "run_id" | "session_id" | "plan_hash" | "status"
>;

export default function IsaacViewport({ run }: { run: ViewportRun | null }) {
  const video = useRef<HTMLVideoElement>(null);
  const [status, setStatus] = useState("Waiting for a run");
  const [connected, setConnected] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const runId = run?.run_id;
  const sessionId = run?.session_id;
  const planHash = run?.plan_hash;
  const ended = !!run && terminalRuns.has(run.status);
  const started = !!run && !["queued", "claimed"].includes(run.status);
  useEffect(() => {
    setConnected(false);
    if (!runId || !sessionId || !planHash || !started || ended) {
      setStatus(
        ended
          ? "Live view ended"
          : runId
            ? "Waiting for Isaac"
            : "Waiting for a run",
      );
      return;
    }
    let alive = true;
    let socket: WebSocket | undefined;
    let peer: RTCPeerConnection | undefined;
    let renewTimer: number | undefined;
    let retryTimer: number | undefined;
    let frameTimer: number | undefined;
    let setupTimer: number | undefined;
    const clientId = crypto.randomUUID();
    const abort = new AbortController();
    let lastFrames = -1;
    let hasFrame = false;
    let stillSince = Date.now();
    const close = () => {
      window.clearTimeout(renewTimer);
      window.clearTimeout(retryTimer);
      window.clearTimeout(setupTimer);
      window.clearInterval(frameTimer);
      socket?.close();
      peer?.close();
      if (video.current) video.current.srcObject = null;
      if (alive) setConnected(false);
    };
    const fail = (message: string) => {
      if (alive) {
        close();
        setStatus(message);
      }
    };
    const renew = async () => {
      try {
        await api(`/runs/${runId}/viewer/renew`, {
          ...json({
            client_id: clientId,
            frame_received: hasFrame,
            frames_decoded:
              video.current?.getVideoPlaybackQuality().totalVideoFrames ?? 0,
          }),
          signal: abort.signal,
        });
        if (alive) renewTimer = window.setTimeout(renew, 10000);
      } catch {
        fail("Viewing access ended. Reconnect to view this run.");
      }
    };
    const connect = async () => {
      setStatus("Preparing the live viewport…");
      let grant: Grant;
      try {
        grant = await api<Grant>(`/runs/${runId}/viewer`, {
          ...json({ client_id: clientId }),
          signal: abort.signal,
        });
      } catch (e) {
        if (!alive) return;
        if (e instanceof ApiError && e.status === 409) {
          retryTimer = window.setTimeout(connect, 3000);
          return;
        }
        fail("Live video is unavailable. The run state remains separate.");
        return;
      }
      if (!alive) return;
      if (
        grant.run_id !== runId ||
        grant.session_id !== sessionId ||
        grant.plan_hash !== planHash ||
        grant.client_id !== clientId
      ) {
        fail("Viewport identity did not match this run.");
        return;
      }
      peer = new RTCPeerConnection({
        iceServers: grant.ice_servers,
        iceTransportPolicy: "relay",
      });
      // View-only: no microphone, camera, keyboard, desktop or control channel.
      peer.addTransceiver("video", { direction: "recvonly" });
      socket = new WebSocket(grant.signaling_url);
      const send = (action: string, payload: unknown) => {
        if (socket?.readyState === WebSocket.OPEN)
          socket.send(
            JSON.stringify({
              action,
              messagePayload: btoa(JSON.stringify(payload)),
            }),
          );
      };
      peer.onicecandidate = (event) => {
        if (event.candidate) send("ICE_CANDIDATE", event.candidate.toJSON());
      };
      peer.ontrack = (event) => {
        if (!alive || !video.current) return;
        video.current.srcObject = new MediaStream([event.track]);
        void video.current
          .play()
          .catch(() => setStatus("Press play to show the live viewport"));
      };
      peer.onconnectionstatechange = () => {
        if (!alive) return;
        if (peer?.connectionState === "connected") {
          setStatus("Waiting for rendered frames…");
          window.clearTimeout(setupTimer);
        } else if (
          ["failed", "disconnected", "closed"].includes(
            peer?.connectionState ?? "",
          )
        )
          fail("Video disconnected. Reconnect to view this run.");
      };
      const pendingIce: RTCIceCandidateInit[] = [];
      // Serialize SDP and ICE operations: WebSocket event callbacks can overlap.
      let messages = Promise.resolve();
      socket.onmessage = (event) => {
        messages = messages
          .then(async () => {
            if (!alive || !peer) return;
            const message = JSON.parse(event.data);
            if (message.messageType === "STATUS_RESPONSE")
              throw new Error("Signaling rejected the request");
            const payload = JSON.parse(atob(message.messagePayload));
            if (message.messageType === "SDP_ANSWER") {
              await peer.setRemoteDescription(payload);
              for (const candidate of pendingIce.splice(0))
                await peer.addIceCandidate(candidate);
            } else if (message.messageType === "ICE_CANDIDATE") {
              if (peer.remoteDescription) await peer.addIceCandidate(payload);
              else pendingIce.push(payload);
            }
          })
          .catch(() => fail("Video negotiation failed. Reconnect to retry."));
      };
      socket.onopen = () => {
        void (async () => {
          if (!alive || !peer) return;
          await peer.setLocalDescription(await peer.createOffer());
          send("SDP_OFFER", peer.localDescription?.toJSON());
          renewTimer = window.setTimeout(renew, 10000);
        })().catch(() => fail("Could not connect the live viewport."));
      };
      socket.onerror = () => fail("Video signaling is unavailable.");
      socket.onclose = () => {
        if (alive && peer?.connectionState !== "closed")
          fail("Video signaling disconnected.");
      };
      setupTimer = window.setTimeout(
        () => fail("Video connection timed out. Reconnect to retry."),
        45000,
      );
      frameTimer = window.setInterval(() => {
        const frames =
          video.current?.getVideoPlaybackQuality().totalVideoFrames ?? 0;
        if (frames > 0 && frames !== lastFrames) {
          hasFrame = true;
          stillSince = Date.now();
          setConnected(true);
          setStatus("Live Isaac viewport");
        } else if (Date.now() - stillSince > 5000 && frames > 0) {
          setConnected(false);
          setStatus("Video stalled · state may still be updating");
        }
        lastFrames = frames;
      }, 1000);
    };
    void connect();
    return () => {
      alive = false;
      abort.abort();
      close();
    };
  }, [runId, sessionId, planHash, started, ended, attempt]);

  return (
    <section className={s.viewport} aria-label="Isaac live viewport">
      <div className={s.viewportBar}>
        <span>
          <i className={connected ? s.liveDot : s.waitDot} />
          {status}
        </span>
        <span>ISAAC / MATTERIX</span>
      </div>
      <div className={s.videoStage}>
        <video
          ref={video}
          autoPlay
          muted
          playsInline
          controls
          aria-label="Live native Isaac simulation"
        />
        {!connected && (
          <div className={s.videoEmpty}>
            <Monitor size={40} strokeWidth={1} />
            <strong>{status}</strong>
            <p>
              {ended
                ? "The observed result is saved beside this view."
                : "The Ubuntu GPU renders this view. A run must be connected before experiment motion begins."}
            </p>
            {started && !ended && (
              <button onClick={() => setAttempt((n) => n + 1)}>
                <RefreshCw size={15} /> Reconnect video
              </button>
            )}
          </div>
        )}
      </div>
      <footer>
        <span>View only · no physical hardware</span>
        <span>Video and state have independent connection status</span>
      </footer>
    </section>
  );
}
