/** Local Vite on loopback — never true in production builds. */
export function isLocalDev(): boolean {
  if (!import.meta.env.DEV) return false;
  const host = window.location.hostname;
  return host === "localhost" || host === "127.0.0.1" || host === "[::1]";
}
