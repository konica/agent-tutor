import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const kc = {
  init: vi.fn(),
  updateToken: vi.fn(),
  login: vi.fn(),
  logout: vi.fn(),
  token: undefined as string | undefined,
};
vi.mock("keycloak-js", () => ({ default: vi.fn(function () { return kc; }) }));

const { authConfig, createKeycloakClient } = await import("./keycloakClient");
const config = { url: "http://localhost:10401", realm: "smart-tutor", clientId: "smart-tutor-web" };

describe("keycloak client", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    kc.init.mockResolvedValue(true);
    kc.updateToken.mockResolvedValue(false);
    kc.token = "access-token";
  });

  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it("uses Keycloak on the page's origin when built with VITE_KEYCLOAK_URL=/auth", () => {
    vi.stubEnv("VITE_KEYCLOAK_URL", "/auth");
    expect(authConfig().url).toBe(`${window.location.origin}/auth`);
  });

  it("falls back to the local Keycloak defaults when the build variables are empty", () => {
    vi.stubEnv("VITE_KEYCLOAK_URL", "");
    vi.stubEnv("VITE_KEYCLOAK_REALM", "");
    vi.stubEnv("VITE_KEYCLOAK_CLIENT_ID", "");
    expect(authConfig()).toEqual(config);
  });

  it("signs in with PKCE and login-required", async () => {
    await createKeycloakClient(config).init();
    expect(kc.init).toHaveBeenCalledWith({ onLoad: "login-required", pkceMethod: "S256", checkLoginIframe: false });
  });

  it("init runs keycloak once", async () => {
    const auth = createKeycloakClient(config);
    await Promise.all([auth.init(), auth.init()]); // StrictMode mounts effects twice
    await auth.init();
    expect(kc.init).toHaveBeenCalledOnce();
  });

  it("retries init after a failure", async () => {
    kc.init.mockRejectedValueOnce(new Error("network"));
    const auth = createKeycloakClient(config);
    await expect(auth.init()).rejects.toThrow("network");
    await expect(auth.init()).resolves.toBeUndefined();
    expect(kc.init).toHaveBeenCalledTimes(2);
  });

  it("refreshes a token that expires within 60 seconds before handing it out", async () => {
    await expect(createKeycloakClient(config).getToken()).resolves.toBe("access-token");
    expect(kc.updateToken).toHaveBeenCalledWith(60);
  });

  it("fails getToken when the refresh fails", async () => {
    kc.updateToken.mockRejectedValue(new Error("refresh token expired"));
    await expect(createKeycloakClient(config).getToken()).rejects.toThrow();
  });

  it("signs out back to the app", async () => {
    await createKeycloakClient(config).signOut();
    expect(kc.logout).toHaveBeenCalledWith({ redirectUri: `${window.location.origin}/` });
  });

  it("signs in from a page that never initialised Keycloak, without onLoad", async () => {
    await createKeycloakClient(config).signIn({ redirectTo: "/library" });
    expect(kc.init).toHaveBeenCalledWith({ pkceMethod: "S256", checkLoginIframe: false });
    expect(kc.login).toHaveBeenCalledWith({ redirectUri: `${window.location.origin}/library` });
  });

  it("opens the registration page for a new account", async () => {
    await createKeycloakClient(config).signIn({ register: true, redirectTo: "/library" });
    expect(kc.login).toHaveBeenCalledWith({ action: "register", redirectUri: `${window.location.origin}/library` });
  });

  it("signs in again to the current page after a session ends", async () => {
    const auth = createKeycloakClient(config);
    await auth.init();
    await auth.signIn();
    expect(kc.init).toHaveBeenCalledOnce(); // reuses the login-required init
    expect(kc.login).toHaveBeenCalledWith({});
  });

  it("initialises Keycloak once when sign-in is chosen twice", async () => {
    const auth = createKeycloakClient(config);
    await Promise.all([auth.signIn(), auth.signIn({ register: true })]);
    expect(kc.init).toHaveBeenCalledOnce();
  });
});
