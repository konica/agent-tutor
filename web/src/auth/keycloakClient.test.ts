import { beforeEach, describe, expect, it, vi } from "vitest";

const kc = {
  init: vi.fn(),
  updateToken: vi.fn(),
  login: vi.fn(),
  logout: vi.fn(),
  token: undefined as string | undefined,
};
vi.mock("keycloak-js", () => ({ default: vi.fn(function () { return kc; }) }));

const { createKeycloakClient } = await import("./keycloakClient");
const config = { url: "http://localhost:10401", realm: "smart-tutor", clientId: "smart-tutor-web" };

describe("keycloak client", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    kc.init.mockResolvedValue(true);
    kc.updateToken.mockResolvedValue(false);
    kc.token = "access-token";
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
});
