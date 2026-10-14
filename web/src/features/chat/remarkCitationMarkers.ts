import { splitMarkers } from "./citationMarkers";

/** The part of an mdast node this plugin reads and writes. */
type MdNode = { type: string; value?: string; children?: MdNode[]; data?: Record<string, unknown> };

// Text inside a link stays text: a marker's button can't sit inside a link. Code is its own node type, never `text`.
const KEEP = new Set(["link", "linkReference"]);

function split(text: MdNode): MdNode[] {
  return splitMarkers(text.value ?? "").map((p) =>
    p.n === undefined
      ? { type: "text", value: p.text }
      : {
          type: "citationMarker",
          data: { hName: "span", hProperties: { dataMarker: p.n } },
          children: [{ type: "text", value: p.text }],
        },
  );
}

function walk(node: MdNode) {
  if (!node.children || KEEP.has(node.type)) return;
  node.children = node.children.flatMap((child) => {
    if (child.type === "text") return split(child);
    walk(child);
    return [child];
  });
}

// A remark plugin: each marker number in the answer's prose becomes a `span` with `data-marker`, which Answer renders as
// a link to its source (DESIGN.md → Chat). The rest of the text is kept as written. The tree is typed `object` so the
// plugin fits react-markdown's plugin list without importing unified's types.
export function remarkCitationMarkers() {
  return (tree: object) => walk(tree as MdNode);
}
