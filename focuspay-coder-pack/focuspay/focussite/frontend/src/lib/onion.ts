/** Tor v3 helpers for the public site. */

export function isOnionHost(host = typeof window !== "undefined" ? window.location.hostname : ""): boolean {
  return host.toLowerCase().split(":")[0].endsWith(".onion");
}

export interface SiteOnionConfig {
  telegram_bot_username?: string;
  public_site_url?: string;
  public_onion_url?: string | null;
  doliv_onion_url?: string | null;
}
