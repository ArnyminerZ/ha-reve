/**
 * Reve location card — status of every charger of a Reve location.
 *
 * type: custom:reve-location-card
 * location: "My location"     # name or id; omit to show every location
 * entities: [sensor.garage]    # optional: pick chargers explicitly instead
 * title: Optional title
 * watch_hours: 2               # how long a "notify me" alert stays armed
 * notify_entity_id: notify.mobile_app_x   # optional (string or list)
 *
 * A visual editor is available in the dashboard card editor.
 */
const STATE = {
  available: { key: "free", icon: "mdi:ev-station" },
  charging: { key: "busy", icon: "mdi:ev-plug-type2" },
  reserved: { key: "busy", icon: "mdi:calendar-lock" },
  blocked: { key: "busy", icon: "mdi:car-brake-alert" },
  planned: { key: "off", icon: "mdi:calendar-clock" },
  inoperative: { key: "fault", icon: "mdi:alert-circle" },
  outoforder: { key: "fault", icon: "mdi:alert-circle" },
  removed: { key: "fault", icon: "mdi:alert-circle" },
  unknown: { key: "off", icon: "mdi:help-circle" },
  unavailable: { key: "off", icon: "mdi:help-circle" },
};

const TRANSLATIONS = {
  en: {
    available: "Free", charging: "In use", reserved: "Reserved", blocked: "Blocked",
    planned: "Planned", inoperative: "Out of service", outoforder: "Out of order",
    removed: "Removed", unknown: "Unknown", unavailable: "Unavailable",
    in_use_for: "In use for {time}", free_for: "Free for {time}",
    notify_me: "Notify me", until: "Until {time}", cancel_alert: "Cancel alert",
    n_free: "{free}/{total} free", title: "Reve chargers", empty: "No Reve chargers found.",
    less_than_minute: "<1 min", minutes: "min",
    editor_title: "Title (optional)",
    editor_location: "Location (empty = all locations)",
    editor_entities: "Chargers (optional, overrides location)",
    editor_watch_hours: "Keep the alert armed for",
    editor_notify: "Notify through (empty = Home Assistant notification)",
  },
  es: {
    available: "Libre", charging: "En uso", reserved: "Reservado", blocked: "Bloqueado",
    planned: "Planificado", inoperative: "Fuera de servicio", outoforder: "Averiado",
    removed: "Retirado", unknown: "Desconocido", unavailable: "No disponible",
    in_use_for: "En uso desde hace {time}", free_for: "Libre desde hace {time}",
    notify_me: "Avisarme", until: "Hasta las {time}", cancel_alert: "Cancelar aviso",
    n_free: "{free}/{total} libres", title: "Cargadores Reve",
    empty: "No se han encontrado cargadores Reve.",
    less_than_minute: "<1 min", minutes: "min",
    editor_title: "Título (opcional)",
    editor_location: "Ubicación (vacío = todas las ubicaciones)",
    editor_entities: "Cargadores (opcional, anula la ubicación)",
    editor_watch_hours: "Mantener el aviso activo durante",
    editor_notify: "Notificar mediante (vacío = notificación de Home Assistant)",
  },
  ca: {
    available: "Lliure", charging: "En ús", reserved: "Reservat", blocked: "Bloquejat",
    planned: "Planificat", inoperative: "Fora de servei", outoforder: "Avariat",
    removed: "Retirat", unknown: "Desconegut", unavailable: "No disponible",
    in_use_for: "En ús des de fa {time}", free_for: "Lliure des de fa {time}",
    notify_me: "Avisa'm", until: "Fins a les {time}", cancel_alert: "Cancel·la l'avís",
    n_free: "{free}/{total} lliures", title: "Carregadors Reve",
    empty: "No s'ha trobat cap carregador Reve.",
    less_than_minute: "<1 min", minutes: "min",
    editor_title: "Títol (opcional)",
    editor_location: "Ubicació (buit = totes les ubicacions)",
    editor_entities: "Carregadors (opcional, substitueix la ubicació)",
    editor_watch_hours: "Mantén l'avís actiu durant",
    editor_notify: "Notifica mitjançant (buit = notificació de Home Assistant)",
  },
};

const lang = (hass) => String(hass?.language || "en").toLowerCase().split("-")[0];

const tr = (hass, key, vars = {}) => {
  const text = (TRANSLATIONS[lang(hass)] || TRANSLATIONS.en)[key] ?? TRANSLATIONS.en[key] ?? key;
  return text.replace(/\{(\w+)\}/g, (_, k) => vars[k] ?? "");
};

const fmtDuration = (hass, ms) => {
  const m = Math.max(0, Math.floor(ms / 60000));
  if (m < 1) return tr(hass, "less_than_minute");
  const d = Math.floor(m / 1440), h = Math.floor((m % 1440) / 60), mm = m % 60;
  if (d) return `${d}d ${h}h`;
  return h ? `${h}h ${mm}m` : `${mm} ${tr(hass, "minutes")}`;
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

  static getStubConfig(hass) {
    const loc = Object.values(hass?.states || {})
      .map((s) => s.entity_id.startsWith("sensor.") && s.attributes.connectors !== undefined
        ? s.attributes.location_name : null)
      .find(Boolean);
    return loc ? { location: loc } : {};
  }

  static getConfigElement() {
    return document.createElement("reve-location-card-editor");
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
      detail = tr(this._hass, "in_use_for", { time: fmtDuration(this._hass, Date.now() - new Date(a.last_status_change)) });
    } else if (s.state === "available" && a.last_status_change) {
      detail = tr(this._hass, "free_for", { time: fmtDuration(this._hass, Date.now() - new Date(a.last_status_change)) });
    }
    const watching = a.watching_until ? new Date(a.watching_until) : null;
    let action = "";
    if (watching) {
      const t = watching.toLocaleTimeString(lang(this._hass), { hour: "2-digit", minute: "2-digit" });
      action = `<button class="act on" data-act="cancel" data-id="${s.entity_id}" title="${tr(this._hass, "cancel_alert")}">
        <ha-icon icon="mdi:bell-ring"></ha-icon><span>${tr(this._hass, "until", { time: t })}</span></button>`;
    } else if (st.key === "busy") {
      action = `<button class="act" data-act="watch" data-id="${s.entity_id}" ${this._busy.has(s.entity_id) ? "disabled" : ""}>
        <ha-icon icon="mdi:bell-plus-outline"></ha-icon><span>${tr(this._hass, "notify_me")}</span></button>`;
    }
    const name = (a.friendly_name || s.entity_id).replace(/'/g, "&#39;");
    return `<div class="row ${st.key}">
      <ha-icon class="ico" icon="${st.icon}"></ha-icon>
      <div class="txt" data-more="${s.entity_id}">
        <div class="name">${name}</div>
        <div class="sub"><b>${tr(this._hass, s.state in STATE ? s.state : "unknown")}</b>${detail ? " · " + detail : ""}</div>
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
        <span class="count ${free ? "free" : ""}">${tr(this._hass, "n_free", { free, total: list.length })}</span></div>`;
      body += list.map((s) => this._row(s)).join("");
    }
    if (!groups.size) body = `<div class="empty">${tr(this._hass, "empty")}</div>`;
    const header = title
      || (groups.size === 1 ? [...groups.keys()][0] : tr(this._hass, "title"));
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

class ReveLocationCardEditor extends HTMLElement {
  setConfig(config) {
    this._config = config;
    this._update();
  }

  set hass(hass) {
    this._hass = hass;
    this._update();
  }

  _schema() {
    const locations = [...new Set(Object.values(this._hass.states)
      .filter((s) => s.entity_id.startsWith("sensor.") && s.attributes.connectors !== undefined
        && s.attributes.location_name)
      .map((s) => s.attributes.location_name))].sort();
    return [
      { name: "title", selector: { text: {} } },
      { name: "location", selector: { select: { options: locations, custom_value: true, mode: "dropdown" } } },
      { name: "entities", selector: { entity: { integration: "reve", domain: "sensor", device_class: "enum", multiple: true } } },
      { name: "watch_hours", selector: { number: { min: 1, max: 168, step: 1, mode: "box", unit_of_measurement: "h" } } },
      { name: "notify_entity_id", selector: { entity: { domain: "notify", multiple: true } } },
    ];
  }

  _update() {
    if (!this._hass || !this._config) return;
    if (!this._form) {
      this._form = document.createElement("ha-form");
      this._form.computeLabel = (item) => {
        const key = {
          title: "editor_title", location: "editor_location", entities: "editor_entities",
          watch_hours: "editor_watch_hours", notify_entity_id: "editor_notify",
        }[item.name];
        return key ? tr(this._hass, key) : item.name;
      };
      this._form.addEventListener("value-changed", (ev) => {
        const config = { ...ev.detail.value };
        for (const [k, v] of Object.entries(config)) {
          if (v === "" || v === undefined || (Array.isArray(v) && !v.length)) delete config[k];
        }
        this._config = config;
        this.dispatchEvent(new CustomEvent("config-changed", {
          bubbles: true, composed: true, detail: { config } }));
      });
      this.appendChild(this._form);
    }
    this._form.hass = this._hass;
    this._form.schema = this._schema();
    this._form.data = { watch_hours: 2, ...this._config };
  }
}

customElements.define("reve-location-card", ReveLocationCard);
customElements.define("reve-location-card-editor", ReveLocationCardEditor);
window.customCards = window.customCards || [];
window.customCards.push({
  type: "reve-location-card",
  name: "Reve location",
  description: "Status of all the chargers of a Reve location, with a notify-when-free button.",
});
