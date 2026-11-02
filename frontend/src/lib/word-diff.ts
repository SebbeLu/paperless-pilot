export type DiffKind = "same" | "added" | "removed" | "warn";
export type DiffPart = { text: string; kind: DiffKind };

// Größere Texte vergleicht die Tabelle nicht mehr (Speicher); dann zählt nur, ob ein Wort
// irgendwo im anderen Text vorkommt.
const MAX_CELLS = 4_000_000;

const normalize = (word: string) => word.toLocaleLowerCase("de").replace(/[^\p{L}\p{N}]/gu, "");
const keyOf = (word: string) => normalize(word) || word;

/** Wortweiser Vergleich; Leerraum und Zeilenumbrüche bleiben erhalten. `suspicious` markiert
 * Wörter im neuen Text gelb, unabhängig davon, ob sie neu sind. */
export function wordDiff(
  oldText: string,
  newText: string,
  suspicious: (word: string) => boolean = () => false,
): { old: DiffPart[]; new: DiffPart[] } {
  const oldTokens = oldText.split(/(\s+)/).filter(Boolean);
  const newTokens = newText.split(/(\s+)/).filter(Boolean);
  const oldWords = wordIndexes(oldTokens);
  const newWords = wordIndexes(newTokens);
  const [oldKept, newKept] = common(
    oldWords.map((i) => keyOf(oldTokens[i] ?? "")),
    newWords.map((i) => keyOf(newTokens[i] ?? "")),
  );
  const oldKinds = kinds(oldTokens, oldWords, oldKept, () => "removed");
  const newKinds = kinds(newTokens, newWords, newKept, () => "added");
  newWords.forEach((tokenIndex) => {
    if (suspicious(newTokens[tokenIndex] ?? "")) newKinds[tokenIndex] = "warn";
  });
  return { old: merge(oldTokens, oldKinds), new: merge(newTokens, newKinds) };
}

/** Prüfregel wie im Backend: Zahlen mit mindestens vier Ziffern, die im alten Text fehlen –
 * sinnvoll nur, wenn der alte Text überhaupt Zahlen enthält. Dazu Stellen aus den Warnungen. */
export function suspiciousWords(oldText: string, flagged: string[]): (word: string) => boolean {
  const old = normalize(oldText);
  const comparable = (old.match(/\d/g)?.length ?? 0) >= 10;
  const flaggedKeys = new Set(flagged.map(normalize).filter(Boolean));
  return (word) => {
    const key = normalize(word);
    if (!key) return false;
    if (flaggedKeys.has(key)) return true;
    const digits = key.match(/\d/g)?.length ?? 0;
    return comparable && digits >= 4 && !old.includes(key);
  };
}

function wordIndexes(tokens: string[]): number[] {
  return tokens.flatMap((token, i) => (/\S/.test(token) ? [i] : []));
}

function kinds(
  tokens: string[],
  words: number[],
  kept: Set<number>,
  changed: () => DiffKind,
): DiffKind[] {
  const result: DiffKind[] = tokens.map(() => "same");
  words.forEach((tokenIndex, wordIndex) => {
    if (!kept.has(wordIndex)) result[tokenIndex] = changed();
  });
  return result;
}

/** Benachbarte Wörter gleicher Art samt Leerraum dazwischen zu einem Teil zusammenfassen. */
function merge(tokens: string[], tokenKinds: DiffKind[]): DiffPart[] {
  const parts: DiffPart[] = [];
  tokens.forEach((text, i) => {
    let kind = tokenKinds[i] ?? "same";
    if (!/\S/.test(text)) {
      const before = tokenKinds[i - 1];
      kind = before && before === tokenKinds[i + 1] ? before : "same";
    }
    const last = parts[parts.length - 1];
    if (last && last.kind === kind) last.text += text;
    else parts.push({ text, kind });
  });
  return parts;
}

/** Indizes der Wörter, die in beiden Folgen gemeinsam stehen (längste gemeinsame Teilfolge). */
function common(a: string[], b: string[]): [Set<number>, Set<number>] {
  const keptA = new Set<number>();
  const keptB = new Set<number>();
  let start = 0;
  while (start < a.length && start < b.length && a[start] === b[start]) {
    keptA.add(start);
    keptB.add(start);
    start++;
  }
  let endA = a.length;
  let endB = b.length;
  while (endA > start && endB > start && a[endA - 1] === b[endB - 1]) {
    endA--;
    endB--;
    keptA.add(endA);
    keptB.add(endB);
  }
  const n = endA - start;
  const m = endB - start;
  if (n === 0 || m === 0) return [keptA, keptB];
  if (n * m > MAX_CELLS) {
    const inB = new Set(b.slice(start, endB));
    const inA = new Set(a.slice(start, endA));
    for (let i = start; i < endA; i++) if (inB.has(a[i] ?? "")) keptA.add(i);
    for (let j = start; j < endB; j++) if (inA.has(b[j] ?? "")) keptB.add(j);
    return [keptA, keptB];
  }
  const width = m + 1;
  const lengths = new Uint16Array((n + 1) * width);
  for (let i = n - 1; i >= 0; i--) {
    for (let j = m - 1; j >= 0; j--) {
      lengths[i * width + j] =
        a[start + i] === b[start + j]
          ? (lengths[(i + 1) * width + j + 1] ?? 0) + 1
          : Math.max(lengths[(i + 1) * width + j] ?? 0, lengths[i * width + j + 1] ?? 0);
    }
  }
  let i = 0;
  let j = 0;
  while (i < n && j < m) {
    if (a[start + i] === b[start + j]) {
      keptA.add(start + i++);
      keptB.add(start + j++);
    } else if ((lengths[(i + 1) * width + j] ?? 0) >= (lengths[i * width + j + 1] ?? 0)) {
      i++;
    } else {
      j++;
    }
  }
  return [keptA, keptB];
}
