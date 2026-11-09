/** Local Vite only — never true in production builds. */
export { isLocalDev as isLocalDevPanel } from "@/lib/isLocalDev";

export function isJwtExpired(token: string, skewMs = 5000): boolean {
  try {
    const payload = token.split(".")[1];
    if (!payload) return false;
    const json = JSON.parse(atob(payload.replace(/-/g, "+").replace(/_/g, "/")));
    if (typeof json.exp !== "number") return false;
    return json.exp * 1000 <= Date.now() + skewMs;
  } catch {
    return false;
  }
}

export const DEV_STUB_ACCOUNT = {
  admin: {
    id: 0,
    username: "dev",
    display_name: "Dev",
    is_admin: true,
    can_view_finance: true,
    rbac_role: "ADMIN" as const,
    totp_enabled: false,
  },
  operator: {
    id: 0,
    username: "dev",
    display_name: "Dev",
    is_admin: false,
    can_view_finance: false,
    rbac_role: "OPERATOR" as const,
    totp_enabled: false,
    permissions: [
      "templates.view",
      "templates.create",
      "antispam.phrases",
      "orders.history",
      "payout.requisites",
      "payout.requisites.confirm",
    ],
  },
};
