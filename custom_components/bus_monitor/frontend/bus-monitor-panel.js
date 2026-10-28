// Bus Monitor sidebar panel: route map, checkpoint editor and route heatmap.
// Plain web component (no build step); Leaflet is vendored next to this file.
import * as L from "./leaflet/leaflet-src.esm.js";

const BASE = new URL(".", import.meta.url).pathname; // e.g. /bus_monitor_static/
const R = 6371008.8;
const rad = Math.PI / 180;

function distanceM(a, b) {
  const dp = (b.lat - a.lat) * rad;
  const dl = (b.lon - a.lon) * rad;
  const x =
    Math.sin(dp / 2) ** 2 + Math.cos(a.lat * rad) * Math.cos(b.lat * rad) * Math.sin(dl / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(x));
}

// Heatmap colour: rare detours light and faint, the usual route dark and solid.
function heatStyle(frac) {
  const light = [245, 158, 11];
  const dark = [127, 29, 29];
  const t = Math.max(0, Math.min(1, frac));
  const c = light.map((v, i) => Math.round(v + (dark[i] - v) * t));
  return { color: `rgb(${c.join(",")})`, opacity: 0.4 + 0.55 * t };
}

// Analog alarm-clock outline with the minute number on its face.
function clockSvg(minutes, faded) {
  const ink = "#1e293b";
  const size = minutes >= 10 ? 12.5 : 14;
  return `<svg class="clock${faded ? " faded" : ""}" width="32" height="34" viewBox="0 0 40 42" aria-hidden="true">
    <path d="M10 35 L6.5 40 M30 35 L33.5 40" stroke="${ink}" stroke-width="3" stroke-linecap="round"/>
    <path d="M4 13 A8 8 0 0 1 15.5 4.5" fill="none" stroke="${ink}" stroke-width="3.2" stroke-linecap="round"/>
    <path d="M36 13 A8 8 0 0 0 24.5 4.5" fill="none" stroke="${ink}" stroke-width="3.2" stroke-linecap="round"/>
    <rect x="18" y="3.5" width="4" height="5" rx="1" fill="${ink}"/>
    <circle cx="20" cy="23" r="14.5" fill="#fff" stroke="${ink}" stroke-width="3"/>
    <text x="20" y="23.5" text-anchor="middle" dominant-baseline="central"
          font-family="Roboto, Arial, sans-serif" font-weight="800" font-size="${size}" fill="${ink}">${minutes}</text>
  </svg>`;
}

// Short form for the map sign: "Elm Street" -> "Elm St".
function shortStreet(name) {
  return String(name || "")
    .replace(/\bEast\b/g, "E")
    .replace(/\bWest\b/g, "W")
    .replace(/\bNorth\b/g, "N")
    .replace(/\bSouth\b/g, "S")
    .replace(/\bStreet\b/g, "St")
    .replace(/\bAvenue\b/g, "Av")
    .replace(/\bRoad\b/g, "Rd")
    .replace(/\bBoulevard\b/g, "Blvd")
    .replace(/\bPlace\b/g, "Pl")
    .replace(/\bDrive\b/g, "Dr");
}

const esc = (s) =>
  String(s ?? "").replace(/[&<>"']/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[ch]);

class BusMonitorPanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._profiles = [];
    this._sel = null;
    this._draft = [];
    this._dirty = false;
    this._canEdit = false;
    this._addMode = false;
    this._route = null;
    this._layersOn = { checkpoints: true, minutes: true, latest: true, today: true, heatmap: false };
  }

  set hass(hass) {
    const first = !this._hass;
    this._hass = hass;
    if (this._menuBtn) this._menuBtn.hass = hass;
    if (first) this._init();
    else this._updateBus();
  }

  set narrow(narrow) {
    this._narrow = narrow;
    this.toggleAttribute("narrow", !!narrow);
    if (this._menuBtn) this._menuBtn.narrow = narrow;
  }

  set panel(_panel) {}

  connectedCallback() {
    if (this._map) setTimeout(() => this._map.invalidateSize(), 50);
    this._timer = setInterval(() => this._refresh(false), 30000);
  }

  disconnectedCallback() {
    clearInterval(this._timer);
  }

  // ---------------------------------------------------------------- setup
  async _init() {
    this._render();
    await this._refresh(true);
  }

  _render() {
    this.shadowRoot.innerHTML = `
      <link rel="stylesheet" href="${BASE}leaflet/leaflet.css">
      <style>
        :host { display: flex; flex-direction: column; height: 100%; background: var(--primary-background-color);
                color: var(--primary-text-color); font-family: var(--paper-font-body1_-_font-family, Roboto, sans-serif); }
        .toolbar { display: flex; align-items: center; gap: 12px; height: var(--header-height, 56px); padding: 0 12px;
                   background: var(--app-header-background-color, var(--primary-color)); color: var(--app-header-text-color, #fff);
                   border-bottom: var(--app-header-border-bottom, none); box-sizing: border-box; flex: none; }
        .toolbar .title { font-size: 20px; flex: 1; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
        .toolbar select { font: inherit; font-size: 14px; padding: 4px 6px; border-radius: 6px; max-width: 45vw; }
        .body { flex: 1; display: flex; min-height: 0; }
        .map { flex: 1; min-width: 0; position: relative; }
        .map.adding { cursor: crosshair; }
        /* muted base map so the route, heatmap and checkpoints stand out */
        .leaflet-tile-pane { filter: grayscale(1) brightness(1.04) contrast(.85); opacity: .85; }
        .map.dark .leaflet-tile-pane { filter: grayscale(1) invert(1) brightness(.85) contrast(.85); opacity: 1; }
        .map.adding .leaflet-container { cursor: crosshair; }
        /* !important: Leaflet sets position:relative inline if the map is created before the panel is attached */
        #map { position: absolute !important; inset: 0; }
        .side { width: 360px; flex: none; overflow-y: auto; padding: 12px; box-sizing: border-box;
                background: var(--card-background-color); border-left: 1px solid var(--divider-color); }
        :host([narrow]) .body { flex-direction: column; }
        :host([narrow]) .map { flex: none; height: 55vh; }
        :host([narrow]) .side { width: auto; border-left: none; border-top: 1px solid var(--divider-color); }
        h3 { margin: 16px 0 8px; font-size: 15px; font-weight: 500; }
        h3:first-child { margin-top: 0; }
        .muted { color: var(--secondary-text-color); font-size: 13px; }
        .summary { font-size: 14px; line-height: 1.5; }
        .layers label { display: flex; align-items: center; gap: 8px; font-size: 14px; padding: 3px 0; }
        .legend { margin: 6px 0 0 26px; }
        .legend .bar { height: 8px; border-radius: 4px; width: 180px;
                       background: linear-gradient(90deg, rgba(245,158,11,.45), rgb(190,90,40), rgb(127,29,29)); }
        .legend .ends { display: flex; justify-content: space-between; width: 180px; font-size: 11px; color: var(--secondary-text-color); }
        .cp { border: 1px solid var(--divider-color); border-radius: 8px; padding: 8px; margin-bottom: 8px; }
        .cp.sel { border-color: var(--primary-color); box-shadow: 0 0 0 1px var(--primary-color); }
        .cp .row { display: flex; gap: 6px; align-items: center; margin-top: 6px; font-size: 13px; }
        .cp input[type=text] { flex: 1; min-width: 0; }
        .cp input[type=number] { width: 64px; }
        .cp input { font: inherit; padding: 4px 6px; border: 1px solid var(--divider-color); border-radius: 6px;
                    background: var(--primary-background-color); color: var(--primary-text-color); }
        .cp .badge { width: 22px; height: 22px; flex: none; border-radius: 50%; display: grid; place-items: center;
                     background: #ffb700; color: #1e293b; font-weight: 700; font-size: 11px; border: 2px solid #1e293b; }
        .cp .badge.shadow { background: #cbd5e1; }
        .cp .badge.street { background: #15803d; color: #fff; border-color: #14532d; border-radius: 4px; }
        .cp select { font: inherit; padding: 3px 4px; border: 1px solid var(--divider-color); border-radius: 6px;
                     background: var(--primary-background-color); color: var(--primary-text-color); }
        button { font: inherit; font-size: 14px; padding: 6px 12px; border-radius: 18px; cursor: pointer;
                 border: 1px solid var(--primary-color); background: transparent; color: var(--primary-color); }
        button.primary { background: var(--primary-color); color: var(--text-primary-color, #fff); }
        button.danger { border-color: var(--error-color, #db4437); color: var(--error-color, #db4437); padding: 2px 10px; font-size: 12px; }
        button:disabled { opacity: .45; cursor: default; }
        .actions { display: flex; flex-wrap: wrap; gap: 8px; margin: 8px 0; }
        .msg { font-size: 13px; margin-top: 6px; min-height: 18px; }
        .msg.err { color: var(--error-color, #db4437); }
        .empty { padding: 24px; }
        /* map markers */
        .cp-marker { width: 26px; height: 26px; border-radius: 50%; display: grid; place-items: center; font: 700 12px/1 sans-serif;
                     background: #ffb700; color: #1e293b; border: 2px solid #1e293b; box-shadow: 0 1px 4px rgba(0,0,0,.4); }
        .cp-marker.shadow { background: #cbd5e1; }
        .cp-marker.sel, .cp-street.sel { outline: 3px solid var(--primary-color); }
        .cp-marker.auto { box-shadow: 0 0 0 2px #fff, 0 0 0 4px #2563eb, 0 1px 4px rgba(0,0,0,.4); position: relative; }
        .cp-marker.auto::after { content: "A"; position: absolute; right: -9px; top: -9px; width: 14px; height: 14px; border-radius: 50%;
                                 background: #2563eb; color: #fff; font: 700 9px/14px sans-serif; text-align: center; }
        .cp-street { display: inline-block; transform: translate(-50%, -50%); white-space: nowrap; padding: 3px 7px;
                     background: #15803d; color: #fff; font: 700 11px/1.1 Roboto, Arial, sans-serif; border-radius: 4px;
                     border: 2px solid #fff; box-shadow: 0 0 0 1.5px #14532d, 0 1px 4px rgba(0,0,0,.45); }
        .cp-street.shadow { background: #64748b; }
        .clock { display: block; filter: drop-shadow(0 1px 2px rgba(0,0,0,.35)); }
        .clock.faded { opacity: .55; }
        .stop-marker { width: 18px; height: 18px; border-radius: 4px; background: #e53935; border: 2px solid #fff;
                       box-shadow: 0 1px 4px rgba(0,0,0,.5); }
        .bus-marker { width: 30px; height: 30px; border-radius: 50%; background: #1e293b; border: 2px solid #ffb700;
                      display: grid; place-items: center; box-shadow: 0 1px 6px rgba(0,0,0,.5); }
        .bus-marker svg { width: 18px; height: 18px; fill: #ffb700; }
      </style>
      <div class="toolbar">
        <ha-menu-button></ha-menu-button>
        <div class="title">Bus Monitor</div>
        <select id="profile" aria-label="Bus profile"></select>
      </div>
      <div class="body">
        <div class="map" id="mapwrap"><div id="map"></div></div>
        <div class="side" id="side"></div>
      </div>`;
    this._menuBtn = this.shadowRoot.querySelector("ha-menu-button");
    this._menuBtn.hass = this._hass;
    this._menuBtn.narrow = this._narrow;
    this.shadowRoot.getElementById("profile").addEventListener("change", (e) => this._select(e.target.value));

    if (this._hass?.themes?.darkMode) this.shadowRoot.getElementById("mapwrap").classList.add("dark");
    this._map = L.map(this.shadowRoot.getElementById("map"), { zoomControl: true }).setView([40.65, -73.95], 13);
    // Standard OpenStreetMap tiles (fine for light personal use, attribution required).
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19,
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank">OpenStreetMap</a> contributors',
    }).addTo(this._map);
    this._canvas = L.canvas({ padding: 0.3 });
    this._heatLayer = L.layerGroup();
    this._latestLayer = L.layerGroup();
    this._todayLayer = L.layerGroup();
    this._stopLayer = L.layerGroup().addTo(this._map);
    this._cpLayer = L.layerGroup();
    this._minutesLayer = L.layerGroup();
    this._busLayer = L.layerGroup().addTo(this._map);
    this._map.on("click", (e) => this._mapClick(e));
    this._map.on("zoomend", () => this._drawMinuteMarks());
    new ResizeObserver(() => {
      this._map.invalidateSize();
      if (this._pendingFit && this._mapHasSize()) this._fit();
    }).observe(this.shadowRoot.getElementById("mapwrap"));
  }

  // ---------------------------------------------------------------- data
  async _refresh(fit) {
    if (!this._hass) return;
    try {
      const ov = await this._hass.callWS({ type: "bus_monitor/overview" });
      this._profiles = ov.profiles;
      this._canEdit = ov.can_edit;
    } catch (err) {
      this._error = err.message || String(err);
      this._renderSide();
      return;
    }
    const sel = this.shadowRoot.getElementById("profile");
    sel.innerHTML = this._profiles
      .map((p) => `<option value="${esc(p.id)}">${esc(p.bus)} – ${esc(p.name)}</option>`)
      .join("");
    if (!this._profiles.length) {
      this._renderSide();
      return;
    }
    if (!this._sel || !this._profiles.find((p) => p.id === this._sel)) this._sel = this._profiles[0].id;
    sel.value = this._sel;
    if (!this._dirty) this._draft = this._profile().checkpoints.map((c) => ({ ...c }));
    await this._loadRoute();
    this._drawAll(fit);
  }

  async _loadRoute() {
    try {
      this._route = await this._hass.callWS({ type: "bus_monitor/route", profile: this._sel });
      if (this._route.trips >= 2 && this._heatDefaulted !== this._sel) {
        this._layersOn.heatmap = true;
        this._heatDefaulted = this._sel;
      }
    } catch (err) {
      this._route = null;
    }
  }

  _profile() {
    return this._profiles.find((p) => p.id === this._sel);
  }

  async _select(id) {
    if (this._dirty && !confirm("Discard unsaved checkpoint changes?")) {
      this.shadowRoot.getElementById("profile").value = this._sel;
      return;
    }
    this._sel = id;
    this._dirty = false;
    this._selIdx = null;
    this._draft = this._profile().checkpoints.map((c) => ({ ...c }));
    await this._loadRoute();
    this._drawAll(true);
  }

  // ---------------------------------------------------------------- drawing
  _drawAll(fit) {
    const p = this._profile();
    if (!p) return;
    this._drawStop(p);
    this._drawRoute();
    this._drawCheckpoints();
    this._updateBus();
    this._applyLayers();
    this._renderSide();
    if (fit) this._fit();
  }

  _mapHasSize() {
    const size = this._map.getSize();
    return size.x > 0 && size.y > 0;
  }

  _fit() {
    // Fitting a map that has no size yet zooms to nonsense; do it once it's laid out.
    if (!this._mapHasSize()) {
      this._pendingFit = true;
      return;
    }
    this._pendingFit = false;
    const p = this._profile();
    const pts = [];
    if (p.stop) pts.push([p.stop.lat, p.stop.lon]);
    this._draft.forEach((c) => pts.push([c.lat, c.lon]));
    (this._route?.latest?.path || []).forEach((q) => pts.push(q));
    if (p.position) pts.push([p.position.lat, p.position.lon]);
    if (pts.length > 1) this._map.fitBounds(L.latLngBounds(pts).pad(0.1), { maxZoom: 17 });
    else if (pts.length) this._map.setView(pts[0], 16);
  }

  _drawStop(p) {
    this._stopLayer.clearLayers();
    if (!p.stop) return;
    const ll = [p.stop.lat, p.stop.lon];
    L.circle(ll, { radius: p.stop.radius_m, color: "#e53935", weight: 1, fillOpacity: 0.1 }).addTo(this._stopLayer);
    L.marker(ll, { icon: L.divIcon({ className: "", html: '<div class="stop-marker"></div>', iconSize: [18, 18] }) })
      .bindTooltip(`Your stop${p.stop.expected_arrival ? ` · usually ${p.stop.expected_arrival}` : ""}`)
      .addTo(this._stopLayer);
  }

  _drawRoute() {
    this._heatLayer.clearLayers();
    this._latestLayer.clearLayers();
    this._todayLayer.clearLayers();
    const r = this._route;
    if (!r) return;
    const hm = r.heatmap;
    if (hm && hm.cells.length) {
      const hl = hm.dlat / 2;
      const hw = hm.dlon / 2;
      for (const [lat, lon, frac, count] of hm.cells) {
        const s = heatStyle(frac);
        L.rectangle(
          [
            [lat - hl, lon - hw],
            [lat + hl, lon + hw],
          ],
          { renderer: this._canvas, stroke: false, fillColor: s.color, fillOpacity: s.opacity, interactive: false },
        ).addTo(this._heatLayer);
      }
    }
    if (r.latest?.path?.length) {
      L.polyline(r.latest.path, { color: "#2563eb", weight: 4, opacity: 0.8 })
        .bindTooltip(`Latest recorded trip (${r.latest.date})`, { sticky: true })
        .addTo(this._latestLayer);
    }
    if (r.today?.length) {
      L.polyline(r.today, { color: "#16a34a", weight: 4, opacity: 0.9, dashArray: "6 6" })
        .bindTooltip("Today so far", { sticky: true })
        .addTo(this._todayLayer);
    }
    this._drawMinuteMarks();
  }

  // Alarm clocks along the route: where the bus usually is N minutes before the stop.
  // Every minute when zoomed in, every 2nd / 5th minute further out to avoid clutter.
  _drawMinuteMarks() {
    if (!this._minutesLayer) return;
    this._minutesLayer.clearLayers();
    const marks = this._route?.minute_marks || [];
    const zoom = this._map.getZoom();
    const step = zoom >= 16 ? 1 : zoom >= 15 ? 2 : 5;
    for (const m of marks) {
      if (m.minutes % step !== 0) continue;
      const unsure = m.spread_m > 150; // trips disagree a lot here: show it faded
      L.marker([m.lat, m.lon], {
        zIndexOffset: -1000, // keep checkpoints and the bus on top
        keyboard: false,
        icon: L.divIcon({
          className: "",
          html: clockSvg(m.minutes, unsure),
          iconSize: [32, 34],
          iconAnchor: [16, 19],
        }),
      })
        .bindTooltip(
          `Usually about ${m.minutes} min from your stop` +
            ` <span style="opacity:.7">(${m.trips} trip${m.trips === 1 ? "" : "s"}${m.trips > 1 ? `, ±${m.spread_m} m` : ""})</span>`,
        )
        .addTo(this._minutesLayer);
    }
  }

  _drawCheckpoints() {
    this._cpLayer.clearLayers();
    const p = this._profile() || { bus: "The bus" };
    this._draft.forEach((c, i) => {
      const street = c.kind === "street";
      const autoOn = !street && c.auto_place && c.auto_trips; // currently placed by recorded trips
      const circle = L.circle([c.lat, c.lon], {
        radius: c.radius_m,
        color: c.announce === false ? "#64748b" : street ? "#15803d" : "#b45309",
        weight: 1,
        fillOpacity: 0.12,
        interactive: false,
      }).addTo(this._cpLayer);
      const mods = `${c.announce === false ? " shadow" : ""}${this._selIdx === i ? " sel" : ""}${autoOn ? " auto" : ""}`;
      const html = street
        ? `<div class="cp-street${mods}">${esc(shortStreet(c.label))}</div>`
        : `<div class="cp-marker${mods}">${esc(c.minutes || "•")}</div>`;
      const m = L.marker([c.lat, c.lon], {
        draggable: this._canEdit && !autoOn,
        zIndexOffset: 500,
        icon: L.divIcon({ className: "", html, iconSize: street ? null : [26, 26], iconAnchor: street ? [0, 0] : undefined }),
      })
        .bindTooltip(
          street
            ? `Street checkpoint: “${esc(p.bus)} is at ${esc(c.label)}.”`
            : `${esc(c.label)}${autoOn ? ` · auto-placed from ${c.auto_trips} trips` : ""}`,
        )
        .addTo(this._cpLayer);
      m.on("drag", (e) => circle.setLatLng(e.target.getLatLng()));
      m.on("dragend", (e) => {
        const ll = e.target.getLatLng();
        Object.assign(this._draft[i], { lat: +ll.lat.toFixed(6), lon: +ll.lng.toFixed(6) });
        this._markDirty();
      });
      m.on("click", () => {
        this._selIdx = i;
        this._drawCheckpoints();
        this._renderSide();
        this.shadowRoot.querySelector(`.cp[data-i="${i}"]`)?.scrollIntoView({ block: "nearest", behavior: "smooth" });
      });
    });
  }

  _updateBus() {
    const p = this._profile();
    if (!p || !this._busLayer) return;
    const st = p.tracker_entity && this._hass.states[p.tracker_entity];
    const lat = st?.attributes?.latitude ?? p.position?.lat;
    const lon = st?.attributes?.longitude ?? p.position?.lon;
    if (lat == null || lon == null) {
      this._busLayer.clearLayers();
      return;
    }
    const svg =
      '<svg viewBox="0 0 24 24"><path d="M4,7H12.5A2,2 0 0 1 14.5,9V16.5A2,2 0 0 1 12.5,18.5H4A2,2 0 0 1 2,16.5V9A2,2 0 0 1 4,7ZM4.3,9A0.8,0.8 0 0 0 3.5,9.8V11.7A0.8,0.8 0 0 0 4.3,12.5H12.2A0.8,0.8 0 0 0 13,11.7V9.8A0.8,0.8 0 0 0 12.2,9ZM2.1,17.8H14.4A0.9,0.9 0 0 1 15.3,18.7A0.9,0.9 0 0 1 14.4,19.6H2.1A0.9,0.9 0 0 1 1.2,18.7A0.9,0.9 0 0 1 2.1,17.8ZM3,19.2H5.6V21.5H3ZM10.9,19.2H13.5V21.5H10.9Z" transform="translate(3.5 0)"/></svg>';
    if (!this._busMarker) {
      this._busMarker = L.marker([lat, lon], {
        zIndexOffset: 1000,
        icon: L.divIcon({ className: "", html: `<div class="bus-marker">${svg}</div>`, iconSize: [30, 30] }),
      });
    }
    this._busMarker.setLatLng([lat, lon]);
    this._busMarker.bindTooltip(`${esc(p.bus)}${st?.attributes?.speed_mph != null ? ` · ${st.attributes.speed_mph} mph` : ""}`);
    if (!this._busLayer.hasLayer(this._busMarker)) this._busLayer.addLayer(this._busMarker);
    const sum = this.shadowRoot.getElementById("bus-dist");
    if (sum && p.stop) sum.textContent = `${(distanceM({ lat, lon }, p.stop) / 1609.344).toFixed(1)} mi from your stop`;
  }

  _applyLayers() {
    const on = this._layersOn;
    const set = (layer, show) => (show ? layer.addTo(this._map) : layer.remove());
    set(this._heatLayer, on.heatmap);
    set(this._latestLayer, on.latest);
    set(this._todayLayer, on.today);
    set(this._minutesLayer, on.minutes);
    set(this._cpLayer, on.checkpoints);
  }

  // ---------------------------------------------------------------- editing
  _mapClick(e) {
    if (!this._addMode) return;
    const kind = this._addMode;
    this._addMode = false;
    this.shadowRoot.getElementById("mapwrap").classList.remove("adding");
    this._addCheckpoint(e.latlng.lat, e.latlng.lng, kind);
  }

  _uniqueLabel(base) {
    let label = base;
    for (let n = 2; this._draft.some((c) => c.label === label); n++) label = `${base} (${n})`;
    return label;
  }

  // Direction of travel near a point, from the latest recorded trip (for "cross street").
  _bearingNear(lat, lon) {
    const path = this._route?.latest?.path || [];
    if (path.length < 2) return null;
    let best = 0;
    let bestD = Infinity;
    path.forEach(([la, lo], k) => {
      const d = distanceM({ lat, lon }, { lat: la, lon: lo });
      if (d < bestD) [best, bestD] = [k, d];
    });
    if (bestD > 150) return null;
    const a = path[Math.max(0, best - 2)];
    const b = path[Math.min(path.length - 1, best + 2)];
    const y = Math.sin((b[1] - a[1]) * rad) * Math.cos(b[0] * rad);
    const x = Math.cos(a[0] * rad) * Math.sin(b[0] * rad) - Math.sin(a[0] * rad) * Math.cos(b[0] * rad) * Math.cos((b[1] - a[1]) * rad);
    return (Math.atan2(y, x) / rad + 360) % 360;
  }

  async _addCheckpoint(lat, lon, kind = "time") {
    const point = { lat: +lat.toFixed(6), lon: +lon.toFixed(6), announce: true };
    if (kind === "street") {
      const cp = { ...point, kind: "street", label: this._uniqueLabel("Looking up street…"), minutes: 0, radius_m: 40, auto_place: false };
      this._draft.push(cp);
      this._selIdx = this._draft.length - 1;
      this._layersOn.checkpoints = true;
      this._markDirty();
      let name = null;
      let problem = null;
      try {
        const res = await this._hass.callWS({ type: "bus_monitor/street_name", lat, lon, bearing: this._bearingNear(lat, lon) });
        name = res.name;
      } catch (err) {
        problem = err.message || String(err);
      }
      cp.label = this._uniqueLabel(name || "Street checkpoint");
      this._markDirty(); // clears the message, so set it afterwards
      if (problem || !name) this._setMsg(`Couldn't look up the street name${problem ? ` (${problem})` : ""}. Type it in.`, true);
      return;
    }
    const used = new Set(this._draft.filter((c) => c.kind !== "street").map((c) => c.minutes));
    const minutes = [10, 5, 2, 15, 8, 3, 1].find((m) => !used.has(m)) ?? 1;
    this._draft.push({ ...point, kind: "time", label: this._uniqueLabel(`${minutes} minutes away`), minutes, radius_m: 60, auto_place: true });
    this._selIdx = this._draft.length - 1;
    this._layersOn.checkpoints = true;
    this._markDirty();
  }

  _markDirty() {
    this._dirty = true;
    this._msg = "";
    this._drawCheckpoints();
    this._applyLayers();
    this._renderSide();
  }

  async _save() {
    const labels = this._draft.map((c) => c.label.trim());
    if (labels.some((l) => !l)) return this._setMsg("Every checkpoint needs a name.", true);
    if (new Set(labels).size !== labels.length) return this._setMsg("Checkpoint names must be different.", true);
    this._saving = true;
    this._renderSide();
    try {
      await this._hass.callWS({
        type: "bus_monitor/set_checkpoints",
        profile: this._sel,
        checkpoints: this._draft.map((c) => ({
          label: c.label.trim(),
          minutes: Number(c.minutes) || 0,
          lat: c.lat,
          lon: c.lon,
          radius_m: Math.max(10, Math.min(1000, Number(c.radius_m) || 60)),
          announce: c.announce !== false,
          kind: c.kind === "street" ? "street" : "time",
          auto_place: c.kind !== "street" && !!c.auto_place,
        })),
      });
      this._dirty = false;
      this._msg = "Saved. Bus Monitor is reloading with the new checkpoints.";
      this._msgErr = false;
      setTimeout(() => this._refresh(false), 2500);
    } catch (err) {
      this._msg = `Couldn't save: ${err.message || err}`;
      this._msgErr = true;
    }
    this._saving = false;
    this._renderSide();
  }

  _discard() {
    this._dirty = false;
    this._selIdx = null;
    this._draft = this._profile().checkpoints.map((c) => ({ ...c }));
    this._msg = "";
    this._drawCheckpoints();
    this._renderSide();
  }

  _setMsg(text, err) {
    this._msg = text;
    this._msgErr = !!err;
    this._renderSide();
  }

  // ---------------------------------------------------------------- side panel
  _renderSide() {
    const side = this.shadowRoot.getElementById("side");
    if (!side) return;
    if (this._error) {
      side.innerHTML = `<div class="empty msg err">Couldn't load Bus Monitor: ${esc(this._error)}</div>`;
      return;
    }
    const p = this._profile();
    if (!p) {
      side.innerHTML = `<div class="empty muted">No bus profiles yet. Add one in Settings → Devices &amp; services → Bus Monitor → Configure.</div>`;
      return;
    }
    const r = this._route;
    const trips = r?.trips ?? 0;
    const edit = this._canEdit;
    const dis = edit ? "" : "disabled";
    side.innerHTML = `
      <h3>${esc(p.bus)} · ${esc(p.name)}</h3>
      <div class="summary">
        Status: <b>${esc(p.status.replace("_", " "))}</b><br>
        <span id="bus-dist" class="muted"></span><br>
        <span class="muted">Watching ${esc(p.window[0])}–${esc(p.window[1])} · ${trips} trip${trips === 1 ? "" : "s"} recorded</span>
      </div>

      <h3>Map layers</h3>
      <div class="layers">
        <label><input type="checkbox" data-layer="checkpoints" ${this._layersOn.checkpoints ? "checked" : ""}> Checkpoints</label>
        <label><input type="checkbox" data-layer="latest" ${this._layersOn.latest ? "checked" : ""} ${r?.latest ? "" : "disabled"}>
          Latest trip ${r?.latest ? `<span class="muted">(${esc(r.latest.date)})</span>` : '<span class="muted">(none yet)</span>'}</label>
        <label><input type="checkbox" data-layer="minutes" ${this._layersOn.minutes ? "checked" : ""} ${r?.minute_marks?.length ? "" : "disabled"}>
          Minutes away <span class="muted">(${r?.minute_marks?.length ? "usual times to your stop" : "after the first recorded trip"})</span></label>
        <label><input type="checkbox" data-layer="today" ${this._layersOn.today ? "checked" : ""}> Today so far</label>
        <label><input type="checkbox" data-layer="heatmap" ${this._layersOn.heatmap ? "checked" : ""} ${trips ? "" : "disabled"}>
          Route heatmap <span class="muted">(${trips} trip${trips === 1 ? "" : "s"})</span></label>
        ${
          this._layersOn.heatmap && trips
            ? `<div class="legend"><div class="bar"></div><div class="ends"><span>rare detour</span><span>usual route</span></div></div>`
            : ""
        }
        ${trips ? "" : '<div class="muted">The heatmap builds up as trips are recorded (each trip that reaches your stop during the watch window).</div>'}
      </div>

      <h3>Checkpoints</h3>
      ${edit ? "" : '<div class="muted">Only administrators can change checkpoints.</div>'}
      ${this._draft.length ? "" : '<div class="muted">No checkpoints yet. Add one, then drag it to where the bus is about that many minutes from your stop.</div>'}
      ${this._draft
        .map(
          (c, i) => `
        <div class="cp ${this._selIdx === i ? "sel" : ""}" data-i="${i}">
          <div class="row">
            ${
              c.kind === "street"
                ? `<span class="badge street ${c.announce === false ? "shadow" : ""}">St</span>`
                : `<span class="badge ${c.announce === false ? "shadow" : ""}">${esc(c.minutes || "•")}</span>`
            }
            <input type="text" data-f="label" value="${esc(c.label)}" ${dis} aria-label="Name">
          </div>
          <div class="row">
            <select data-f="kind" ${dis} aria-label="Type">
              <option value="time" ${c.kind === "street" ? "" : "selected"}>Minutes away</option>
              <option value="street" ${c.kind === "street" ? "selected" : ""}>Street</option>
            </select>
            ${
              c.kind === "street"
                ? ""
                : `<label>Min <input type="number" min="1" max="90" data-f="minutes" value="${esc(c.minutes)}" ${dis}></label>`
            }
            <label>Radius <input type="number" min="10" max="1000" step="5" data-f="radius_m" value="${esc(Math.round(c.radius_m))}" ${dis}> m</label>
          </div>
          ${
            c.kind === "street"
              ? `<div class="row muted">Says: “${esc(p.bus)} is at ${esc(c.label)}.”</div>`
              : `<div class="row"><label><input type="checkbox" data-f="auto_place" ${c.auto_place ? "checked" : ""} ${dis}> Auto-place</label>
                 <span class="muted">${
                   !c.auto_place
                     ? "drag to place"
                     : c.auto_trips
                       ? `from ${c.auto_trips} trips (usual spot ${esc(c.minutes)} min out)`
                       : `manual until ${p.min_auto_trips ?? 5} trips are recorded`
                 }</span></div>`
          }
          <div class="row">
            <label><input type="checkbox" data-f="announce" ${c.announce === false ? "" : "checked"} ${dis}> Announce</label>
            <span style="flex:1"></span>
            ${edit ? `<button class="danger" data-act="remove">Remove</button>` : ""}
          </div>
        </div>`,
        )
        .join("")}
      ${
        edit
          ? `<div class="actions">
              <button data-act="add-time">${this._addMode === "time" ? "Click the map…" : "+ Minutes checkpoint"}</button>
              <button data-act="add-street">${this._addMode === "street" ? "Click the map…" : "+ Street checkpoint"}</button>
              <button data-act="addbus" ${p.position ? "" : "disabled"}>+ At bus</button>
            </div>
            <div class="actions">
              <button class="primary" data-act="save" ${this._dirty && !this._saving ? "" : "disabled"}>${this._saving ? "Saving…" : "Save changes"}</button>
              <button data-act="discard" ${this._dirty ? "" : "disabled"}>Discard</button>
            </div>`
          : ""
      }
      <div class="msg ${this._msgErr ? "err" : ""}">${esc(this._msg || (this._dirty ? "Unsaved changes" : ""))}</div>
      <div class="muted">Drag a checkpoint to move it (auto-placed ones move themselves). Street checkpoints announce the street name.
        Untick "Announce" to trial a spot silently (shadow mode).</div>`;

    side.querySelectorAll("input[data-layer]").forEach((el) =>
      el.addEventListener("change", () => {
        this._layersOn[el.dataset.layer] = el.checked;
        this._applyLayers();
        this._renderSide();
      }),
    );
    side.querySelectorAll(".cp").forEach((row) => {
      const i = Number(row.dataset.i);
      row.querySelectorAll("input[data-f]").forEach((el) =>
        el.addEventListener("change", () => {
          const f = el.dataset.f;
          this._draft[i][f] = f === "announce" || f === "auto_place" ? el.checked : f === "label" ? el.value : Number(el.value);
          this._markDirty();
        }),
      );
      row.querySelector('select[data-f="kind"]')?.addEventListener("change", async (e) => {
        const c = this._draft[i];
        c.kind = e.target.value;
        if (c.kind === "street") {
          c.minutes = 0;
          c.auto_place = false;
          try {
            const res = await this._hass.callWS({ type: "bus_monitor/street_name", lat: c.lat, lon: c.lon, bearing: this._bearingNear(c.lat, c.lon) });
            if (res.name) c.label = this._uniqueLabel(res.name);
          } catch (err) {
            /* keep the current name */
          }
        } else if (!c.minutes) {
          c.minutes = 10;
          c.label = this._uniqueLabel("10 minutes away");
        }
        this._markDirty();
      });
      row.querySelector('[data-act="remove"]')?.addEventListener("click", () => {
        this._draft.splice(i, 1);
        this._selIdx = null;
        this._markDirty();
      });
    });
    for (const kind of ["time", "street"]) {
      side.querySelector(`[data-act="add-${kind}"]`)?.addEventListener("click", () => {
        this._addMode = this._addMode === kind ? false : kind;
        this._layersOn.checkpoints = true;
        this.shadowRoot.getElementById("mapwrap").classList.toggle("adding", !!this._addMode);
        this._applyLayers();
        this._renderSide();
      });
    }
    side.querySelector('[data-act="addbus"]')?.addEventListener("click", () => {
      const st = p.tracker_entity && this._hass.states[p.tracker_entity];
      const lat = st?.attributes?.latitude ?? p.position?.lat;
      const lon = st?.attributes?.longitude ?? p.position?.lon;
      if (lat != null) this._addCheckpoint(lat, lon);
    });
    side.querySelector('[data-act="save"]')?.addEventListener("click", () => this._save());
    side.querySelector('[data-act="discard"]')?.addEventListener("click", () => this._discard());
    this._updateBus();
  }
}

customElements.define("bus-monitor-panel", BusMonitorPanel);
