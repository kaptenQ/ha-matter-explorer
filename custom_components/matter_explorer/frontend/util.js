/* Small shared helpers and constants of the panel modules. */

export const PRESETS = [
  { label: "Child lock (516/1)", cluster: 516, attribute: 1 },
  { label: "On/Off (6/0)", cluster: 6, attribute: 0 },
];
export const FLASH_MS = 1500;

export const esc = (v) =>
  String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
export const isStructured = (v) => v !== null && typeof v === "object";

export function fmtScalar(v) {
  if (v === null || v === undefined) return "null";
  if (typeof v === "boolean") return v ? "true" : "false";
  return String(v);
}
