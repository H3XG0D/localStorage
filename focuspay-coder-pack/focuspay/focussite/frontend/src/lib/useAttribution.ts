// Fire referral-attribution tracking once per browser when a ref/promo token is
// present in the URL (query param or /ref//invite path).
import { useEffect } from "react";
import { getDeviceFingerprint } from "@/lib/api";
import { trackAttribution } from "@/lib/public";

const DONE_KEY = "focuspay_attr_tracked";

export function useReferralAttribution() {
  useEffect(() => {
    try {
      const url = new URL(window.location.href);
      const promo = url.searchParams.get("promo");
      const ref = url.searchParams.get("ref") || url.searchParams.get("r");
      let kind: "promo" | "user" | "auto" | null = null;
      let token: string | null = null;
      if (promo) {
        kind = "promo";
        token = promo;
      } else if (ref) {
        kind = "auto";
        token = ref;
      }
      if (!token || !kind) return;
      const already = window.localStorage.getItem(DONE_KEY);
      if (already === token) return;
      trackAttribution(kind, token, getDeviceFingerprint())
        .then(() => window.localStorage.setItem(DONE_KEY, token as string))
        .catch(() => undefined);
    } catch {
      /* ignore */
    }
  }, []);
}
