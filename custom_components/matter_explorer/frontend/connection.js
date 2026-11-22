/* Connection to Home Assistant: load, live subscription, reconnect banner, live events.
 * Methods of <matter-explorer-panel>, mixed into its prototype by matter-explorer-panel.js (`this` is the panel). */

import { changedKey } from "./filters.js";
import { errText, lostSummary, isRunning } from "./bulk.js";

export const connectionMethods = {
  /* The websocket to HA can drop (HA restart, network blip). While it is down the values on screen are
   * not current: show a banner and grey the tree. When it is back, subscribe again and reload everything
   * (events were missed meanwhile). */
  _watchConnection() {
    const conn = this._hass && this._hass.connection;
    if (this._connListeners || !conn || !conn.addEventListener) return;
    const down = () => this._onDisconnected();
    const up = () => this._onReconnected();
    conn.addEventListener("disconnected", down);
    conn.addEventListener("ready", up);
    this._connListeners = { conn, down, up };
  },

  _onDisconnected() {
    if (this._disconnected) return;
    this._disconnected = true;
    this._unsub = null; // the subscription died with the socket
    this._live = false;
    const d = this._dlg;
    if (isRunning(d)) {
      const pr = d.progress || { done: 0, total: 0 };
      d.stage = "lost";
      d.busy = false;
      d.lost = lostSummary(pr.done, pr.total);
      if (d.unsub) {
        try {
          d.unsub();
        } catch (_e) {
          /* socket already gone */
        }
      }
      this._renderDialog();
    }
    this._renderBanner();
    this._renderStatus();
  },

  async _onReconnected() {
    if (!this._disconnected) return;
    this._disconnected = false;
    this._renderBanner();
    await this._subscribe();
    await this._load(); // fresh values; the rows of an open across view are rebuilt by _render
    if (this._dlg && this._dlg.stage === "lost") this._renderDialog();
  },

  _renderBanner() {
    const el = this.shadowRoot && this.shadowRoot.getElementById("banner");
    if (!el) return;
    el.hidden = !this._disconnected;
    el.textContent = this._disconnected ? "Reconnecting… values shown may be out of date." : "";
    const main = this.shadowRoot.getElementById("main");
    if (main) main.classList.toggle("stale", this._disconnected);
  },

  async _load() {
    this._loading = true;
    try {
      const res = await this._hass.callWS({ type: "matter_explorer/nodes" });
      this._nodes = res.nodes;
      this._missing = res.missing_exposed || [];
      this._error = null;
    } catch (err) {
      this._error = errText(err, String(err));
    }
    this._loading = false;
    this._render();
  },

  async _subscribe() {
    if (this._unsub || this._subscribing || !this._hass) return;
    this._subscribing = true;
    try {
      const unsub = await this._hass.connection.subscribeMessage(
        (ev) => this._onEvent(ev),
        { type: "matter_explorer/subscribe" },
        { resubscribe: false } // we subscribe and reload ourselves on reconnect
      );
      if (!this.isConnected) unsub();
      else this._unsub = unsub;
      this._live = !!this._unsub;
    } catch (err) {
      this._live = false;
    }
    this._subscribing = false;
    this._renderStatus();
  },

  _stop() {
    if (this._connListeners) {
      const { conn, down, up } = this._connListeners;
      conn.removeEventListener("disconnected", down);
      conn.removeEventListener("ready", up);
      this._connListeners = null;
    }
    if (this._unsub) {
      const u = this._unsub;
      this._unsub = null;
      try {
        u();
      } catch (_e) {
        /* connection already gone */
      }
    }
    this._live = false;
  },

  _onEvent(ev) {
    if (!this._nodes) return;
    if (ev.event === "attribute_updated") {
      const node = this._node(ev.node_id);
      const entry = node && this._attrByPath(node, ev.path);
      if (!entry) return;
      entry.value = ev.value;
      entry.display_value = ev.display_value;
      this._changed.add(changedKey(ev.node_id, ev.path));
      if (this._filters.changedOnly && this._view === "tree") this._renderMain();
      for (const el of this.shadowRoot.querySelectorAll(`[data-vk="${CSS.escape(`${ev.node_id}:${ev.path}`)}"]`)) {
        el.innerHTML = this._valueHtml(entry);
        el.classList.remove("flash");
        void el.offsetWidth;
        el.classList.add("flash");
      }
    } else if (ev.event === "node_updated") {
      const node = this._node(ev.node_id);
      if (node && node.available !== ev.available) {
        node.available = ev.available;
        this._render();
      }
    } else if (ev.event === "node_added" || ev.event === "node_removed") {
      this._load();
    }
  },
};
