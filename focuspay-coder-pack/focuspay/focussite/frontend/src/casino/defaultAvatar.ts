/** Unique generated picture when a player has no uploaded/Telegram photo. */
export function casinoIdentSeed(userId: number): string | null {
  if (!Number.isFinite(userId) || userId === 0) return null;
  return userId < 0 ? `n${Math.abs(userId)}` : `u${userId}`;
}

export function casinoDefaultAvatarUrl(userId: number | null | undefined): string | null {
  if (userId == null) return null;
  const seed = casinoIdentSeed(userId);
  if (!seed) return null;
  return `/api/public/casino-idents/${seed}?v=3`;
}
