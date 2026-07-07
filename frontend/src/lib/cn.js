// Tiny classnames joiner — accepts strings, arrays, and { class: bool } maps.
// No dependency; last-writer-wins is not attempted (keep call sites clean).
export function cn(...args) {
  const out = [];
  for (const a of args) {
    if (!a) continue;
    if (typeof a === "string" || typeof a === "number") {
      out.push(a);
    } else if (Array.isArray(a)) {
      const inner = cn(...a);
      if (inner) out.push(inner);
    } else if (typeof a === "object") {
      for (const [key, val] of Object.entries(a)) {
        if (val) out.push(key);
      }
    }
  }
  return out.join(" ");
}
