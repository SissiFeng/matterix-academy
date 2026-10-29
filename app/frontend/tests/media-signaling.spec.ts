import { expect, test } from "@playwright/test";

for (const scenario of ["empty", "malformed", "rejected"] as const) {
  test(`viewport signaling handles ${scenario} frames`, async ({ page }) => {
    await page.route("**/api/runs/fixture-run/viewer", async (route) => {
      const { client_id } = route.request().postDataJSON();
      await route.fulfill({
        json: {
          run_id: "fixture-run",
          session_id: "fixture-session",
          plan_hash: "fixture-hash",
          native_session_id: "fixture-native",
          client_id,
          signaling_url: "wss://fixture.invalid",
          ice_servers: [],
        },
      });
    });
    await page.goto("/");
    await page.evaluate(async (scenario) => {
      // Synthetic signaling only: no native/GPU or decoded-frame evidence.
      class Peer {
        connectionState = "new";
        remoteDescription: unknown = null;
        localDescription = {
          toJSON: () => ({ type: "offer", sdp: "fixture" }),
        };
        onconnectionstatechange?: () => void;
        addTransceiver() {}
        async createOffer() {
          return this.localDescription;
        }
        async setLocalDescription() {}
        async setRemoteDescription(answer: unknown) {
          this.remoteDescription = answer;
          this.connectionState = "connected";
          this.onconnectionstatechange?.();
        }
        close() {
          this.connectionState = "closed";
        }
      }
      class Socket {
        static OPEN = 1;
        readyState = 1;
        onopen?: () => void;
        onmessage?: (event: { data: string }) => void;
        constructor() {
          setTimeout(() => this.onopen?.(), 0);
        }
        send(raw: string) {
          if (JSON.parse(raw).action !== "SDP_OFFER") return;
          const frames =
            scenario === "empty"
              ? [
                  "",
                  JSON.stringify({
                    messageType: "SDP_ANSWER",
                    messagePayload: btoa(
                      JSON.stringify({ type: "answer", sdp: "fixture" }),
                    ),
                  }),
                  "",
                ]
              : [
                  scenario === "malformed"
                    ? "{"
                    : JSON.stringify({
                        messageType: "STATUS_RESPONSE",
                        statusResponse: { statusCode: "403" },
                      }),
                ];
          for (const data of frames) this.onmessage?.({ data });
        }
        close() {
          this.readyState = 3;
        }
      }
      Object.assign(window, { RTCPeerConnection: Peer, WebSocket: Socket });
      const reactUrl = "/node_modules/.vite/deps/react.js";
      const domUrl = "/node_modules/.vite/deps/react-dom_client.js";
      const viewportUrl = "/src/IsaacViewport.tsx";
      const { default: React } = await import(reactUrl);
      const { default: ReactDOM } = await import(domUrl);
      const { default: Viewport } = await import(viewportUrl);
      const host = document.createElement("main");
      document.body.replaceChildren(host);
      ReactDOM.createRoot(host).render(
        React.createElement(Viewport, {
          run: {
            run_id: "fixture-run",
            session_id: "fixture-session",
            plan_hash: "fixture-hash",
            status: "running",
          },
        }),
      );
    }, scenario);
    if (scenario === "empty") {
      await expect(
        page.getByText("Waiting for rendered frames…"),
      ).toBeVisible();
      await expect(
        page.getByText("Video negotiation failed. Reconnect to retry."),
      ).toHaveCount(0);
    } else {
      await expect(
        page.getByText("Video negotiation failed. Reconnect to retry."),
      ).toBeVisible();
    }
  });
}
