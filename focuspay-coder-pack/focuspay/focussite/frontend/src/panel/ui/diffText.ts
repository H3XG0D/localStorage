export type DiffSegment = { text: string; changed: boolean };

/** Split two strings into common prefix/suffix and the changed middle. */
export function diffSegments(before: string, after: string): { before: DiffSegment[]; after: DiffSegment[] } {
  if (before === after) {
    return {
      before: before ? [{ text: before, changed: false }] : [],
      after: after ? [{ text: after, changed: false }] : [],
    };
  }
  let prefix = 0;
  const prefixMax = Math.min(before.length, after.length);
  while (prefix < prefixMax && before[prefix] === after[prefix]) prefix += 1;
  let suffix = 0;
  while (
    suffix < before.length - prefix &&
    suffix < after.length - prefix &&
    before[before.length - 1 - suffix] === after[after.length - 1 - suffix]
  ) {
    suffix += 1;
  }
  const slice = (value: string): DiffSegment[] =>
    [
      { text: value.slice(0, prefix), changed: false },
      { text: value.slice(prefix, value.length - suffix), changed: true },
      { text: value.slice(value.length - suffix), changed: false },
    ].filter((part) => part.text.length > 0);
  return { before: slice(before), after: slice(after) };
}

function selfCheck(): void {
  const same = diffSegments("15.00", "15.00");
  if (same.before.some((part) => part.changed) || same.after.some((part) => part.changed)) {
    throw new Error("diffSegments: identical values must not be marked changed");
  }
  const part = diffSegments("1200", "1250");
  if (part.before.find((item) => item.changed)?.text !== "0" || part.after.find((item) => item.changed)?.text !== "5") {
    throw new Error("diffSegments: must highlight only the changed slice");
  }
}
selfCheck();
