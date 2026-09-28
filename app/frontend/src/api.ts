import { UserManager, WebStorageStateStore } from "oidc-client-ts";
import type { Config } from "./types";

let manager: UserManager | null = null;
export async function configureAuth(config: Config) {
  if (config.auth !== "cognito") return;
  const domain = config.cognito_domain.replace(/\/$/, "");
  manager = new UserManager({
    authority: config.issuer,
    client_id: config.client_id,
    redirect_uri: `${config.app_url}/auth/callback`,
    post_logout_redirect_uri: config.app_url,
    response_type: "code",
    scope: "openid email profile academy/learn",
    automaticSilentRenew: false,
    userStore: new WebStorageStateStore({ store: window.sessionStorage }),
    metadata: {
      issuer: config.issuer,
      authorization_endpoint: `${domain}/oauth2/authorize`,
      token_endpoint: `${domain}/oauth2/token`,
      userinfo_endpoint: `${domain}/oauth2/userInfo`,
      jwks_uri: `${config.issuer}/.well-known/jwks.json`,
      end_session_endpoint: `${domain}/logout`,
    },
  });
  if (window.location.pathname === "/auth/callback") {
    await manager.signinRedirectCallback();
    window.history.replaceState({}, "", "/");
  }
}
export async function signIn() {
  if (manager) await manager.signinRedirect();
}
export async function signOut(config: Config) {
  if (manager) {
    await manager.removeUser();
    window.location.assign(
      `${config.cognito_domain}/logout?client_id=${encodeURIComponent(config.client_id)}&logout_uri=${encodeURIComponent(config.app_url)}`,
    );
  } else await api("/auth/logout", { method: "POST" });
}
export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}
export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const user = await manager?.getUser();
  const headers = new Headers(init.headers);
  if (init.body) headers.set("Content-Type", "application/json");
  if (user && !user.expired)
    headers.set("Authorization", `Bearer ${user.access_token}`);
  const response = await fetch(`/api${path}`, {
    ...init,
    headers,
    credentials: "same-origin",
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    if (response.status === 401)
      window.dispatchEvent(new Event("academy:unauthorized"));
    const detail =
      typeof body.detail === "string"
        ? body.detail
        : Array.isArray(body.detail)
          ? body.detail.map((d: { msg: string }) => d.msg).join("; ")
          : "The request could not be completed.";
    throw new ApiError(response.status, detail);
  }
  return response.json();
}
export const json = (body: unknown, method = "POST") => ({
  method,
  body: JSON.stringify(body),
});
