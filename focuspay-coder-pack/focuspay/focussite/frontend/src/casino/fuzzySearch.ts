/** Fold + token fuzzy match for the casino lobby canvas search. */

export function foldQuery(value: string): string {
  return value
    .toLowerCase()
    .replace(/ё/g, "е")
    .replace(/[^a-zа-я0-9]+/gi, " ")
    .trim();
}

function levenshtein(left: string, right: string): number {
  if (left === right) return 0;
  if (!left.length) return right.length;
  if (!right.length) return left.length;
  const rows = left.length + 1;
  const cols = right.length + 1;
  const grid = new Array<number>(rows * cols);
  for (let i = 0; i < rows; i += 1) grid[i * cols] = i;
  for (let j = 0; j < cols; j += 1) grid[j] = j;
  for (let i = 1; i < rows; i += 1) {
    for (let j = 1; j < cols; j += 1) {
      const cost = left[i - 1] === right[j - 1] ? 0 : 1;
      grid[i * cols + j] = Math.min(
        grid[(i - 1) * cols + j] + 1,
        grid[i * cols + j - 1] + 1,
        grid[(i - 1) * cols + j - 1] + cost,
      );
    }
  }
  return grid[left.length * cols + right.length];
}

function tokenHits(token: string, word: string): boolean {
  if (!token || !word) return false;
  if (word.includes(token)) return true;
  if (token.includes(word) && word.length >= 3) return true;
  const max = token.length >= 6 ? 2 : token.length >= 4 ? 1 : 0;
  return max > 0 && levenshtein(token, word) <= max;
}

export function fuzzyMatch(query: string, fields: string[]): boolean {
  const folded = foldQuery(query);
  if (!folded) return true;
  const hay = foldQuery(fields.join(" "));
  if (hay.includes(folded)) return true;
  const words = hay.split(/\s+/).filter(Boolean);
  return folded.split(/\s+/).every((token) => words.some((word) => tokenHits(token, word)));
}

export const fuzzySearch = fuzzyMatch;
