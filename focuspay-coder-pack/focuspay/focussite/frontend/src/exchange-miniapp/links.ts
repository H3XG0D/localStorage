/** Same public destinations the exchange bot already opens. */
export const FOCUS_BET_URL = "https://t.me/focusludka_bot";
export const FOCUS_VPN_URL = "https://t.me/focusvpn1_bot?start=fp";
export const REVIEWS_URL = "https://t.me/focuspayr";
export const COMMUNITY_URL = "https://t.me/+It9i6n_8FUgwM2Nl";

export function supportUrl(site: string) {
  return `${site.replace(/\/$/, "")}/?chat=1`;
}
