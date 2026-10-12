/** A run of the answer's text; `n` is set when the run is one marker number a source may link. */
export type Piece = { text: string; n?: number };

// The backend's marker forms (tutoring/application/answer.py): [1], [1, 2], [1-3], and [1–3] with an en dash.
const MARKER = /\[(\d+(?:\s*[-–,]\s*\d+)*)\]/g;
const NUMBER = /\d+/g;

function push(pieces: Piece[], text: string) {
  if (!text) return;
  const last = pieces[pieces.length - 1];
  if (last && last.n === undefined) last.text += text;
  else pieces.push({ text });
}

// Cuts the answer into text and marker numbers, keeping every character. A single marker is one piece with its
// brackets; in a group each number shown is its own piece, so a range's middle numbers get none.
export function splitMarkers(text: string): Piece[] {
  const pieces: Piece[] = [];
  let at = 0;
  for (const match of text.matchAll(MARKER)) {
    push(pieces, text.slice(at, match.index));
    const group = match[1]!;
    const numbers = [...group.matchAll(NUMBER)];
    if (numbers.length === 1) {
      pieces.push({ text: match[0], n: Number(group) });
    } else {
      let inner = 0;
      push(pieces, "[");
      for (const number of numbers) {
        push(pieces, group.slice(inner, number.index));
        pieces.push({ text: number[0], n: Number(number[0]) });
        inner = number.index + number[0].length;
      }
      push(pieces, "]");
    }
    at = match.index + match[0].length;
  }
  push(pieces, text.slice(at));
  return pieces;
}
