const params = new URLSearchParams(typeof window === "undefined" ? "" : window.location.search);

/** Local visual check without Telegram. Production builds ignore the flag. */
export const PREVIEW = import.meta.env.DEV && params.get("preview") === "1";
export const PREVIEW_ORDER_EMPTY = params.get("order") === "empty";
