/**
 * Reve location card — status of every charger of a Reve location.
 *
 * type: custom:reve-location-card
 * location: "My location"     # name or id; omit to show every location
 * entities: [sensor.garage]    # optional: pick chargers explicitly instead
 * title: Optional title
 * watch_hours: 2               # how long a "notify me" alert stays armed
 * notify_entity_id: notify.mobile_app_x   # optional (string or list)
 */
const STATE = {
  available: { key: "free", icon: "mdi:ev-station", label: "Free" },
  charging: { key: "busy", icon: "mdi:ev-plug-type2", label: "In use" },
  reserved: { key: "busy", icon: "mdi:calendar-lock", label: "Reserved" },
  blocked: { key: "busy", icon: "mdi:car-brake-alert", label: "Blocked" },
  planned: { key: "off", icon: "mdi:calendar-clock", label: "Planned" },
  inoperative: { key: "fault", icon: "mdi:alert-circle", label: "Out of service" },
  outoforder: { key: "fault", icon: "mdi:alert-circle", label: "Out of order" },
  removed: { key: "fault", icon: "mdi:alert-circle", label: "Removed" },
  unknown: { key: "off", icon: "mdi:help-circle", label: "Unknown" },
  unavailable: { key: "off", icon: "mdi:help-circle", label: "Unavailable" },
};

const fmtDuration = (ms) => {
  const m = Math.max(0, Math.floor(ms / 60000));
  if (m < 1) return "<1 min";
  const d = Math.floor(m / 1440), h = Math.floor((m % 1440) / 60), mm = m % 60;
  if (d) return `${d}d ${h}h`;
  return h ? `${h}h ${mm}m` : `${mm} min`;
};

class ReveLocationCard extends HTMLElement {
  setConfig(config) {
    if (!config) throw new Error("Invalid configuration");
    this._config = { watch_hours: 2, ...config };
    this._busy = new Set();
    if (!this.shadowRoot) this.attachShadow({ mode: "open" });
    this._render();
  }

  set hass(hass) {
    this._hass = hass;
    this._render();
  }

  connectedCallback() {
    this._timer = setInterval(() => this._render(), 30000);
  }

  disconnectedCallback() {
    clearInterval(this._timer);
  }

  getCardSize() {
    return 3;
  }

  static getStubConfig() {
    return {};
  }

  _chargers() {
    const states = this._hass.states;
    const { entities, location } = this._config;
    let list;
    if (entities?.length) {
      list = entities.map((e) => states[typeof e === "string" ? e : e.entity]).filter(Boolean);
    } else {
      list = Object.values(states).filter(
        (s) => s.entity_id.startsWith("sensor.") && s.attributes.location_name !== undefined
          && s.attributes.connectors !== undefined
      );
      if (location) {
        const wanted = String(location).toLowerCase();
        list = list.filter(
          (s) => String(s.attributes.location_name).toLowerCase() === wanted
            || String(s.attributes.location_id) === String(location)
        );
      }
    }
    const groups = new Map();
    for (const s of list) {
      const name = s.attributes.location_name || "Reve";
      if (!groups.has(name)) groups.set(name, []);
      groups.get(name).push(s);
    }
    for (const g of groups.values()) {
      g.sort((a, b) => (a.attributes.friendly_name || "").localeCompare(b.attributes.friendly_name || ""));
    }
    return groups;
  }

  _row(s) {
    const a = s.attributes;
    const st = STATE[s.state] || STATE.unknown;
    const connectors = (a.connectors || [])
      .map((c) => [c.standard?.replace(/_/g, " "), c.max_power ? `${+(c.max_power / 1000).toFixed(1)} kW` : null]
        .filter(Boolean).join(" · "))
      .filter(Boolean).join(", ");
    let detail = connectors;
    if (s.state === "charging" && a.last_status_change) {
      detail = `In use for ${fmtDuration(Date.now() - new Date(a.last_status_change))}`;
    } else if (s.state === "available" && a.last_status_change) {
      detail = `Free for ${fmtDuration(Date.now() - new Date(a.last_status_change))}`;
    }
    const watching = a.watching_until ? new Date(a.watching_until) : null;
    let action = "";
    if (watching) {
      const t = watching.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
      action = `<button class="act on" data-act="cancel" data-id="${s.entity_id}" title="Cancel alert">
        <ha-icon icon="mdi:bell-ring"></ha-icon><span>Until ${t}</span></button>`;
    } else if (st.key === "busy") {
      action = `<button class="act" data-act="watch" data-id="${s.entity_id}" ${this._busy.has(s.entity_id) ? "disabled" : ""}>
        <ha-icon icon="mdi:bell-plus-outline"></ha-icon><span>Notify me</span></button>`;
    }
    const name = (a.friendly_name || s.entity_id).replace(/'/g, "&#39;");
    return `<div class="row ${st.key}">
      <ha-icon class="ico" icon="${st.icon}"></ha-icon>
      <div class="txt" data-more="${s.entity_id}">
        <div class="name">${name}</div>
        <div class="sub"><b>${st.label}</b>${detail ? " · " + detail : ""}</div>
      </div>${action}</div>`;
  }

  _render() {
    if (!this._hass || !this._config || !this.shadowRoot) return;
    const groups = this._chargers();
    const title = this._config.title;
    let body = "";
    for (const [name, list] of groups) {
      const free = list.filter((s) => s.state === "available").length;
      body += `<div class="loc"><span>${title && groups.size === 1 ? "" : name}</span>
        <span class="count ${free ? "free" : ""}">${free}/${list.length} free</span></div>`;
      body += list.map((s) => this._row(s)).join("");
    }
    if (!groups.size) body = `<div class="empty">No Reve chargers found.</div>`;
    const header = title
      || (groups.size === 1 ? [...groups.keys()][0] : "Reve chargers");
    this.shadowRoot.innerHTML = `
      <style>
        .row{display:flex;align-items:center;gap:12px;padding:10px 16px}
        .ico{--mdc-icon-size:28px;flex:none;color:var(--c)}
        .free{--c:var(--success-color,#43a047)} .busy{--c:var(--warning-color,#fb8c00)}
        .fault{--c:var(--error-color,#db4437)} .off{--c:var(--disabled-text-color,#9e9e9e)}
        .txt{flex:1;min-width:0;cursor:pointer}
        .name{font-weight:500;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
        .sub{font-size:.85em;color:var(--secondary-text-color)} .sub b{color:var(--c)}
        .loc{display:flex;justify-content:space-between;padding:8px 16px 0;font-size:.8em;
          text-transform:uppercase;letter-spacing:.06em;color:var(--secondary-text-color)}
        .count.free{color:var(--success-color,#43a047)}
        .act{display:flex;align-items:center;gap:6px;border:1px solid var(--divider-color);
          background:none;color:var(--primary-text-color);border-radius:16px;padding:6px 12px;
          cursor:pointer;font:inherit;font-size:.85em;flex:none}
        .act.on{background:var(--primary-color);color:var(--text-primary-color,#fff);border-color:transparent}
        .act:disabled{opacity:.5} .act ha-icon{--mdc-icon-size:18px}
        .empty{padding:16px;color:var(--secondary-text-color)}
        ha-card{padding-bottom:8px}
      </style>
      <ha-card header="${header.replace(/"/g, "&quot;")}">${body}</ha-card>`;
    this.shadowRoot.querySelectorAll(".act").forEach((b) =>
      b.addEventListener("click", () => this._act(b.dataset.act, b.dataset.id)));
    this.shadowRoot.querySelectorAll(".txt").forEach((t) =>
      t.addEventListener("click", () => this.dispatchEvent(new CustomEvent("hass-more-info", {
        bubbles: true, composed: true, detail: { entityId: t.dataset.more } }))));
  }

  async _act(act, entityId) {
    this._busy.add(entityId);
    try {
      if (act === "cancel") {
        await this._hass.callService("reve", "cancel_watch", {}, { entity_id: entityId });
      } else {
        const data = { duration: { hours: Number(this._config.watch_hours) || 2 } };
        const n = this._config.notify_entity_id;
        if (n) data.notify_entity_id = n;
        await this._hass.callService("reve", "watch_availability", data, { entity_id: entityId });
      }
    } catch (err) {
      this.dispatchEvent(new CustomEvent("hass-notification", {
        bubbles: true, composed: true, detail: { message: err.message || String(err) } }));
    } finally {
      this._busy.delete(entityId);
      this._render();
    }
  }
}

customElements.define("reve-location-card", ReveLocationCard);
window.customCards = window.customCards || [];
window.customCards.push({
  type: "reve-location-card",
  name: "Reve location",
  description: "Status of all the chargers of a Reve location, with a notify-when-free button.",
});
