/* Shadow DOM stylesheet of the panel. */

import { FLASH_MS } from "./util.js";

export const STYLE = `
:host { display: block; height: 100%; overflow: auto; background: var(--primary-background-color);
  color: var(--primary-text-color); font-family: var(--paper-font-body1_-_font-family, Roboto, sans-serif); }
* { box-sizing: border-box; }
header { position: sticky; top: 0; z-index: 2; display: flex; flex-wrap: wrap; align-items: center; gap: 8px 12px;
  padding: 8px 16px; background: var(--app-header-background-color, var(--card-background-color));
  color: var(--app-header-text-color, var(--primary-text-color)); border-bottom: 1px solid var(--divider-color); }
header h1 { font-size: 20px; font-weight: 400; margin: 0 8px 0 0; }
input[type=text] { font: inherit; padding: 6px 10px; min-width: 260px; border-radius: 6px;
  border: 1px solid var(--divider-color); background: var(--card-background-color); color: var(--primary-text-color); }
button { font: inherit; cursor: pointer; padding: 5px 12px; border-radius: 6px; border: 1px solid var(--divider-color);
  background: var(--card-background-color); color: var(--primary-text-color); }
button:hover { border-color: var(--primary-color); }
button.active { background: var(--primary-color); color: var(--text-primary-color, #fff); border-color: var(--primary-color); }
button.link { border: none; background: none; padding: 0 4px; color: var(--primary-color); }
.spacer { flex: 1; }
.status { color: var(--secondary-text-color); font-size: 12px; }
.live::before { content: "●"; color: var(--success-color, #43a047); margin-right: 4px; }
.off::before { content: "●"; color: var(--disabled-text-color, #9e9e9e); margin-right: 4px; }
main { padding: 12px 16px 48px; max-width: 1400px; margin: 0 auto; container: explorer / inline-size; }
.row { display: flex; align-items: baseline; gap: 8px; padding: 3px 6px; border-radius: 4px; min-height: 28px; }
.row:hover { background: var(--secondary-background-color); }
.toggle { cursor: pointer; user-select: none; }
.twist { width: 16px; color: var(--secondary-text-color); display: inline-block; flex: none; }
.children { margin-left: 18px; border-left: 1px solid var(--divider-color); padding-left: 6px; }
.node > .row { font-weight: 500; font-size: 15px; }
.cluster > .row { font-weight: 500; }
.unavailable { opacity: .5; }
.diff-added td:first-child .badge { color: var(--success-color, #43a047); }
.diff-removed td:first-child .badge { color: var(--error-color, #db4437); }
.diff-changed td:first-child .badge { color: var(--warning-color, #ffa600); }
.badge { font-size: 11px; padding: 1px 6px; border-radius: 8px; background: var(--secondary-background-color);
  color: var(--secondary-text-color); border: 1px solid var(--divider-color); white-space: nowrap; }
.badge.warn { color: var(--error-color, #db4437); border-color: var(--error-color, #db4437); }
.id { color: var(--secondary-text-color); font-size: 12px; font-family: var(--code-font-family, monospace); }
/* Columns shrink (name/path wrap) so the last one always fits its unwrapped "Add as entity" label. */
.attr { display: grid; grid-template-columns: minmax(110px, 1.1fr) 64px minmax(90px, 2fr) minmax(80px, 1fr) 72px 28px minmax(max-content, 1fr);
  gap: 8px; align-items: baseline; padding: 3px 6px; border-radius: 4px; }
.attr:hover { background: var(--secondary-background-color); }
.attr > * { min-width: 0; }
.attr .aname, .attr .apath { overflow-wrap: anywhere; }
.attr .entity-id { overflow-wrap: anywhere; }
.attr .val { font-family: var(--code-font-family, monospace); word-break: break-word; }
.attr .raw { color: var(--secondary-text-color); font-size: 12px; }
.type { color: var(--secondary-text-color); font-size: 12px; }
.rw { text-align: center; font-size: 12px; font-weight: 600; }
.rw.w { color: var(--warning-color, #ff9800); }
details summary { cursor: pointer; color: var(--primary-color); }
pre { margin: 4px 0; padding: 6px 8px; max-height: 320px; overflow: auto; font-size: 12px; white-space: pre-wrap;
  background: var(--secondary-background-color); border-radius: 4px; font-family: var(--code-font-family, monospace); }
@keyframes flash { from { background: var(--primary-color); color: var(--text-primary-color, #fff); } to { background: transparent; } }
.flash { animation: flash ${FLASH_MS}ms ease-out; border-radius: 3px; }
.empty, .msg { padding: 24px; text-align: center; color: var(--secondary-text-color); }
.error { color: var(--error-color, #db4437); }
.toast { margin: 8px 16px; padding: 8px 12px; border: 1px solid var(--error-color, #db4437); color: var(--error-color, #db4437); border-radius: 6px; cursor: pointer; }
.toast[hidden] { display: none; }
table { width: 100%; border-collapse: collapse; margin-top: 12px; }
th, td { text-align: left; padding: 6px 10px; border-bottom: 1px solid var(--divider-color); vertical-align: baseline; }
th { color: var(--secondary-text-color); font-weight: 500; font-size: 12px; }
td.val { font-family: var(--code-font-family, monospace); }
.picker { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; margin: 4px 0 8px; }
.cands { display: flex; flex-wrap: wrap; gap: 6px; margin: 6px 0; }
h2 { font-size: 17px; font-weight: 500; margin: 12px 0 4px; }
button.edit { padding: 0 6px; margin-left: 4px; font-size: 12px; }
button.identify, button.export { padding: 0 6px; margin-left: 8px; font-size: 12px; }
.overlay { position: fixed; inset: 0; z-index: 10; background: rgba(0,0,0,.5); display: flex; align-items: center; justify-content: center; }
.dialog { background: var(--card-background-color); color: var(--primary-text-color); border-radius: 12px; padding: 20px 24px;
  width: min(520px, 92vw); box-shadow: 0 8px 32px rgba(0,0,0,.4); }
.dialog h3 { margin: 0 0 12px; font-size: 18px; font-weight: 500; }
.dialog dl { display: grid; grid-template-columns: 110px 1fr; gap: 4px 12px; margin: 8px 0 12px; }
.dialog dt { color: var(--secondary-text-color); } .dialog dd { margin: 0; font-family: var(--code-font-family, monospace); }
.dialog .ctl { margin: 12px 0; display: flex; gap: 8px; align-items: center; }
.dialog select, .dialog input[type=number] { font: inherit; padding: 6px 10px; border-radius: 6px; min-width: 200px;
  border: 1px solid var(--divider-color); background: var(--card-background-color); color: var(--primary-text-color); }
.dialog .warn { border: 1px solid var(--error-color, #db4437); color: var(--error-color, #db4437); border-radius: 6px; padding: 8px 10px; margin: 8px 0; }
.dialog .hint { color: var(--secondary-text-color); font-size: 12px; }
.dialog .actions { display: flex; gap: 8px; justify-content: flex-end; margin-top: 16px; }
.dialog.wide { max-width: min(900px, 94vw); max-height: 90vh; overflow: auto; }
.dialog table { margin-top: 4px; font-size: 13px; }
.dialog td.o-ok { color: var(--success-color, #43a047); } .dialog td.o-bad { color: var(--error-color, #db4437); }
.dialog td.o-skip { color: var(--secondary-text-color); }
.banner { padding: 8px 16px; background: var(--warning-color, #ffa600); color: #000; font-weight: 500; }
main.stale { opacity: 0.45; pointer-events: none; }
.missing { margin: 8px 16px; padding: 8px 12px; border: 1px solid var(--warning-color, #ffa600); border-radius: 8px; }
.missing .row { display: flex; gap: 8px; align-items: center; padding: 2px 0; }
.bulk { display: flex; flex-wrap: wrap; gap: 8px 12px; align-items: center; margin: 8px 0; padding: 8px 10px; border: 1px solid var(--divider-color); border-radius: 8px; }
td.sel { width: 28px; } .why { color: var(--secondary-text-color); font-size: 12px; }
.dialog .result { padding: 8px 10px; border-radius: 6px; margin: 8px 0; font-weight: 500; }
.result.ok { border: 1px solid var(--success-color, #43a047); color: var(--success-color, #43a047); }
.result.bad { border: 1px solid var(--error-color, #db4437); color: var(--error-color, #db4437); }
button.danger { background: var(--error-color, #db4437); border-color: var(--error-color, #db4437); color: #fff; }
label.expose { white-space: nowrap; display: inline-flex; gap: 4px; align-items: center; font-size: 12px; cursor: pointer; }
.entity-id { font-size: 11px; color: var(--secondary-text-color); font-family: var(--code-font-family, monospace); word-break: break-all; }
.searchbox { position: relative; display: flex; align-items: center; flex: 1 1 240px; max-width: 420px; min-width: 200px; }
.searchbox svg { position: absolute; left: 10px; width: 18px; height: 18px; fill: var(--secondary-text-color); pointer-events: none; }
.searchbox input { width: 100%; font: inherit; font-size: 15px; padding: 8px 12px 8px 36px; border-radius: 20px;
  border: 1px solid var(--primary-color); background: var(--card-background-color); color: var(--primary-text-color); }
.searchbox input:focus { outline: 2px solid var(--primary-color); outline-offset: 1px; }
kbd { font-family: var(--code-font-family, monospace); font-size: 11px; padding: 0 4px; border: 1px solid var(--divider-color); border-radius: 3px; }
#filters-btn { display: inline-flex; align-items: center; gap: 4px; }
#filters-btn svg { width: 18px; height: 18px; fill: currentColor; }
#filters-btn.has { border-color: var(--primary-color); color: var(--primary-color); font-weight: 500; }
#fpanel { position: fixed; top: 0; right: 0; bottom: 0; width: 320px; max-width: 100%; z-index: 6; display: flex; flex-direction: column;
  background: var(--card-background-color); color: var(--primary-text-color); border-left: 1px solid var(--divider-color);
  box-shadow: -4px 0 16px rgba(0,0,0,.25); }
#fpanel[hidden] { display: none; }
.fhead { display: flex; align-items: center; justify-content: space-between; padding: 10px 16px; border-bottom: 1px solid var(--divider-color); }
.fhead h2 { margin: 0; font-size: 18px; font-weight: 500; }
.fbody { flex: 1; overflow-y: auto; padding: 4px 16px 16px; }
.fbody h3 { margin: 14px 0 6px; font-size: 12px; font-weight: 500; letter-spacing: .06em; text-transform: uppercase; color: var(--secondary-text-color); }
.fsub { font-weight: 500; margin: 6px 0 2px; }
.fhint { color: var(--secondary-text-color); font-size: 12px; font-weight: 400; }
.fhint.indent { margin: -2px 0 6px 28px; }
.frow { display: flex; align-items: center; gap: 10px; padding: 6px 4px; min-height: 32px; cursor: pointer; border-radius: 6px; }
.frow:hover { background: var(--secondary-background-color); }
.frow input { width: 18px; height: 18px; margin: 0; flex: none; accent-color: var(--primary-color); }
.mlist { max-height: 210px; overflow-y: auto; border: 1px solid var(--divider-color); border-radius: 8px; padding: 2px 4px; margin-bottom: 8px; }
.fsel { display: flex; flex-direction: column; gap: 4px; margin: 8px 0; font-weight: 500; }
.fsel select { font: inherit; font-weight: 400; padding: 6px 8px; width: 100%; border-radius: 6px;
  border: 1px solid var(--divider-color); background: var(--secondary-background-color); color: var(--primary-text-color); }
.fsel select.on { border-color: var(--primary-color); }
.ffoot { padding: 10px 16px; border-top: 1px solid var(--divider-color); }
.ffoot button { width: 100%; }
.ffoot button[disabled] { opacity: .5; cursor: default; }
#fpanel input:focus-visible, #fpanel select:focus-visible { outline: 2px solid var(--primary-color); outline-offset: 1px; }
@media (min-width: 701px) { :host(.fp-open) main { padding-right: 336px; } :host(.fp-open) header { padding-right: 336px; } }
@media (max-width: 600px) { #fpanel { top: auto; left: 0; width: 100%; max-height: 85vh; border-left: none; border-top: 1px solid var(--divider-color);
  border-radius: 14px 14px 0 0; box-shadow: 0 -4px 16px rgba(0,0,0,.3); } }
.count { color: var(--secondary-text-color); font-size: 12px; white-space: nowrap; }
.toggle:focus-visible, button:focus-visible { outline: 2px solid var(--primary-color); outline-offset: 1px; }
.dialog dd { overflow-wrap: anywhere; }
.tablewrap { overflow-x: auto; }
.brk { display: none; }
.rw { display: flex; align-items: baseline; justify-content: center; }
.epname { font-weight: 500; color: var(--primary-color); }
.restored { margin: 8px 0; padding: 6px 12px; border-radius: 8px; font-size: 13px; color: var(--secondary-text-color);
  background: var(--secondary-background-color); border: 1px solid var(--divider-color); }
.restored button.link { padding: 0 2px; font-size: 13px; text-decoration: underline; }
@media (max-width: 700px) { header { padding-left: 8px; padding-right: 8px; }
  header { position: static; } .row { flex-wrap: wrap; } .node > .row .name { flex: 1 1 60%; min-width: 0; overflow-wrap: anywhere; }
  .badge { white-space: normal; overflow-wrap: anywhere; } main { padding-left: 8px; padding-right: 8px; } }
/* Narrow main (phone, or a desktop with the filters panel open): each attribute is a card: name + value, then
   path / type / R/W, then the actions. */
@container explorer (max-width: 640px) {
  .row { flex-wrap: wrap; }
  .attr { display: flex; flex-wrap: wrap; gap: 4px 12px; align-items: baseline; padding: 10px 12px; margin: 6px 0;
    border: 1px solid var(--divider-color); border-radius: 10px; background: var(--card-background-color); }
  .attr .aname { order: 1; flex: 1 1 40%; min-width: 0; font-weight: 500; overflow-wrap: anywhere; }
  .attr .val { order: 2; flex: 1 1 40%; min-width: 0; text-align: right; }
  .attr .brk { display: block; flex: 0 0 100%; height: 0; }
  .attr .brk.b1 { order: 3; }
  .attr .apath { order: 4; overflow-wrap: anywhere; }
  .attr .type { order: 5; }
  .attr .rw { order: 6; display: contents; }
  .attr .rwl { order: 6; font-size: 12px; font-weight: 600; }
  .attr .brk.b2 { order: 7; }
  .attr button.edit { order: 8; }
  .attr button.link { order: 8; }
  .attr .expose-wrap { order: 8; }
  .attr .entity-id { flex-basis: 100%; }
  .attr:hover { background: var(--card-background-color); }
  .attr label.expose { gap: 6px; }
}
/* Phone: touch targets >= 40 px. */
@media (max-width: 600px) {
  .attr button, .attr label.expose { min-height: 40px; min-width: 40px; display: inline-flex; align-items: center; justify-content: center; padding: 0 12px; margin: 0; }
  .attr label.expose { justify-content: flex-start; gap: 8px; font-size: 14px; }
  .attr label.expose input { width: 20px; height: 20px; margin: 0; }
  .attr button.link { border: 1px solid var(--divider-color); }
}
`;
