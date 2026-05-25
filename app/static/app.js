/* =============================================
   澳門氣象資料站 — app.js
   ============================================= */

// ── 常數 ──────────────────────────────────────
const LIVE_API_BASE = "";           // 同源，無需前綴
const REFRESH_INTERVAL_MS = 300000; // 5 分鐘
const COUNTDOWN_TOTAL_S = 300;
const MAP_ZOOM = 14;
const MAP_CENTER = { lat: 22.1668, lon: 113.5557 };
const CIRCUMFERENCE = 2 * Math.PI * 11; // ring-fg r=11

// 指標元資料
const METRIC_META = {
  temperature:            { label: "溫度",       unit: "°C",  icon: "🌡" },
  heat_index:             { label: "體感溫度",   unit: "°C",  icon: "♨" },
  humidity:               { label: "濕度",       unit: "%",   icon: "💧" },
  dew_point:              { label: "露點",       unit: "°C",  icon: "🌿" },
  wind_speed:             { label: "平均風速",   unit: "km/h",icon: "🌬" },
  wind_gust:              { label: "陣風",       unit: "km/h",icon: "💨" },
  rainfall_current:       { label: "即時雨量",   unit: "mm",  icon: "🌧" },
  rainfall_hour:          { label: "一小時雨量", unit: "mm",  icon: "🌧" },
  rainfall_day:           { label: "今日雨量",   unit: "mm",  icon: "🌧" },
  wind_degree:            { label: "風向角度",   unit: "°",   icon: "🧭" },
  mean_sea_level_pressure:{ label: "海平面氣壓", unit: "hPa", icon: "🔵" },
  station_pressure:       { label: "站壓",       unit: "hPa", icon: "🔵" },
};

// ── 狀態 ──────────────────────────────────────
let stations = [];
let selectedMarker = null;
let historyChart = null;
let compareChart = null;
let miniChartTemp = null;
let miniChartWind = null;
let countdownTimer = null;
let countdownLeft = COUNTDOWN_TOTAL_S;
let currentTheme = "dark";
let mapMode = "osm"; // "osm" | "satellite"
let compareSelectedCodes = new Set();
let weatherMap = null;
let leafletMarkers = new Map();
let osmLayer = null;
let satelliteLayer = null;
let selectedStationCode = null;
let activeMetric = "temperature";

// ── DOM 工具 ──────────────────────────────────
const $ = (id) => document.getElementById(id);

// ── 格式化 ────────────────────────────────────
function fmt(value, unit = "") {
  if (value === null || value === undefined) return "--";
  const n = Number(value);
  const str = Number.isInteger(n) ? n.toString() : n.toFixed(1);
  return unit ? `${str} ${unit}` : str;
}

function fmtNum(value) {
  if (value === null || value === undefined) return "--";
  const n = Number(value);
  return Number.isInteger(n) ? n.toString() : n.toFixed(1);
}

function timeLabel(value) {
  if (!value) return "--";
  return value.replace("T", " ").slice(0, 16);
}

function hoursAgo(hours) {
  const d = new Date(Date.now() - hours * 3600000);
  // ISO format 不含毫秒
  return d.toISOString().slice(0, 16).replace("T", " ");
}

function localDateTimeParam(value) {
  return value ? value.replace("T", " ") : "";
}

// ── 溫度顏色分級 ─────────────────────────────
function tempTier(temp) {
  if (temp === null || temp === undefined) return null;
  const t = Number(temp);
  if (t < 22)  return "cold";
  if (t < 28)  return "cool";
  if (t < 33)  return "warm";
  return "hot";
}

function metricValue(reading, metric) {
  if (!reading) return null;
  if (metric === "heat_index") return calcHeatIndex(reading.temperature, reading.humidity);
  return reading[metric];
}

function metricTier(value, metric) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return null;
  const n = Number(value);
  if (metric === "humidity") {
    if (n < 60) return "cold";
    if (n < 75) return "cool";
    if (n < 90) return "warm";
    return "hot";
  }
  if (metric.includes("wind")) {
    if (n < 10) return "cold";
    if (n < 25) return "cool";
    if (n < 45) return "warm";
    return "hot";
  }
  if (metric.includes("rainfall")) {
    if (n <= 0) return "cold";
    if (n < 5) return "cool";
    if (n < 20) return "warm";
    return "hot";
  }
  if (metric.includes("pressure")) {
    if (n < 1000) return "cold";
    if (n < 1010) return "cool";
    if (n < 1020) return "warm";
    return "hot";
  }
  return tempTier(n);
}

// ── API ───────────────────────────────────────
async function getJson(path) {
  if (window.OFFLINE_DATA) {
    if (preferOfflineData()) return getOfflineJson(path);
    try {
      const data = await getLiveJson(path);
      window.LIVE_DATA_ACTIVE = true;
      return data;
    } catch {
      window.LIVE_DATA_ACTIVE = false;
      return getOfflineJson(path);
    }
  }
  return getLiveJson(path);
}

function preferOfflineData() {
  const host = window.location.hostname;
  return window.location.protocol === "file:" ||
    host.endsWith("github.io") ||
    host.endsWith("githubusercontent.com");
}

async function getLiveJson(path) {
  const url = path.startsWith("http") ? path : `${LIVE_API_BASE}${path}`;
  const res = await fetch(url, { cache: "no-store" });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

async function fetchLive(path) {
  return getLiveJson(path);
}

function getOfflineJson(url) {
  const data = window.OFFLINE_DATA;
  if (url === "/api/stations") return data.stations;
  if (url === "/api/health") return data.health;
  if (url === "/api/data-quality") return data.data_quality || {};
  if (url.startsWith("/api/warning-events")) return data.warning_events || { items: [] };
  if (url.startsWith("/api/daily-summary")) return data.daily_summary || {};
  if (url.startsWith("/api/dashboard")) return data.dashboard || {};
  if (url.startsWith("/api/wind-index")) return data.dashboard?.wind_index || {};
  if (url.startsWith("/api/comfort-index")) return data.dashboard?.comfort_index || {};
  if (url.startsWith("/api/warnings")) return data.dashboard?.warnings || {};
  if (url.startsWith("/api/water-level")) return data.dashboard?.water_level || {};
  if (url.startsWith("/api/air-quality")) return data.dashboard?.air_quality || {};
  if (url.startsWith("/api/database-summary")) return data.dashboard?.database || {};
  if (url.startsWith("/api/official-forecast")) return data.dashboard?.official_forecast || {};

  if (url.startsWith("/api/compare")) {
    const params = new URL(url, "http://x").searchParams;
    const metric = params.get("metric") || "temperature";
    const codes = (params.get("codes") || "").split(",").filter(Boolean).map(c => c.toUpperCase());
    const series = {};
    codes.forEach(code => {
      const points = (data.history[code] || [])
        .filter(it => it[metric] != null)
        .map(it => ({ record_time: it.record_time, value: it[metric] }));
      series[code] = points;
    });
    return { metric, series };
  }

  if (url.startsWith("/api/rankings")) {
    const metric = new URL(url, "http://x").searchParams.get("metric") || "temperature";
    const items = data.stations
      .map((s) => s.latest)
      .filter((it) => it && it[metric] != null)
      .sort((a, b) => b[metric] - a[metric])
      .map((it) => ({
        station_code: it.station_code,
        station_name: it.station_name,
        record_time: it.record_time,
        value: it[metric],
      }));
    return { metric, items };
  }

  const latestMatch = url.match(/^\/api\/stations\/([^/]+)\/latest$/);
  if (latestMatch) {
    const code = latestMatch[1].toUpperCase();
    const s = data.stations.find((x) => x.code === code);
    if (!s?.latest) throw new Error("找不到此站點的觀測資料");
    return { ...s.latest, station: s };
  }

  const histMatch = url.match(/^\/api\/stations\/([^/]+)\/history/);
  if (histMatch) {
    const code = histMatch[1].toUpperCase();
    const metric = new URL(url, "http://x").searchParams.get("metric") || "temperature";
    const points = (data.history[code] || [])
      .filter((it) => it[metric] != null)
      .map((it) => ({ record_time: it.record_time, value: it[metric] }));
    return { station_code: code, metric, points };
  }

  throw new Error(`Unknown offline URL: ${url}`);
}

// ── 倒計時圓環 ────────────────────────────────
function startCountdown() {
  clearInterval(countdownTimer);
  countdownLeft = COUNTDOWN_TOTAL_S;
  updateCountdownUI();

  countdownTimer = setInterval(() => {
    countdownLeft--;
    if (countdownLeft <= 0) {
      countdownLeft = COUNTDOWN_TOTAL_S;
      refreshPageData();
    }
    updateCountdownUI();
  }, 1000);
}

function updateCountdownUI() {
  const m = Math.floor(countdownLeft / 60);
  const s = countdownLeft % 60;
  const arc = $("countdownArc");
  const text = $("countdownText");
  if (!arc || !text) return;

  text.textContent = `${m}:${String(s).padStart(2, "0")}`;
  const frac = countdownLeft / COUNTDOWN_TOTAL_S;
  arc.style.strokeDashoffset = CIRCUMFERENCE * (1 - frac);
}

// ── 主題切換 ──────────────────────────────────
function initTheme() {
  const saved = localStorage.getItem("theme") || "dark";
  setTheme(saved, false);

  $("themeBtn").addEventListener("click", () => {
    setTheme(currentTheme === "dark" ? "light" : "dark");
  });
}

function setTheme(theme, save = true) {
  currentTheme = theme;
  document.documentElement.dataset.theme = theme;
  const sun = document.querySelector(".icon-sun");
  const moon = document.querySelector(".icon-moon");
  if (sun && moon) {
    sun.style.display = theme === "dark" ? "" : "none";
    moon.style.display = theme === "light" ? "" : "none";
  }
  if (save) localStorage.setItem("theme", theme);
  // 更新圖表主題
  if (historyChart) updateChartTheme(historyChart);
}

function initMetricMatrix() {
  document.querySelectorAll(".metric-switch").forEach(btn => {
    btn.addEventListener("click", async () => {
      activeMetric = btn.dataset.metric || "temperature";
      document.querySelectorAll(".metric-switch").forEach(item => item.classList.toggle("active", item === btn));
      const mappedMetric = activeMetric === "heat_index" ? "temperature" : activeMetric;
      if ($("rankingMetric")) $("rankingMetric").value = activeMetric;
      if ($("historyMetric")) $("historyMetric").value = mappedMetric;
      if ($("compareMetric")) $("compareMetric").value = mappedMetric;
      updateMapLegend();
      renderMarkers();
      renderSummaryStrip(stations);
      await renderRankings();
      await renderHistory();
      await renderCompare();
    });
  });
}

function updateMapLegend() {
  const title = document.querySelector(".legend-title");
  const meta = METRIC_META[activeMetric] || METRIC_META.temperature;
  if (title) title.textContent = `${meta.label} ${meta.unit}`;
}

// ── 地圖底圖切換 ─────────────────────────────
function initMapLayerToggle() {
  const btn = $("mapLayerToggle");
  if (!btn) return;
  btn.addEventListener("click", () => {
    mapMode = mapMode === "osm" ? "satellite" : "osm";
    $("mapLayerLabel").textContent = mapMode === "osm" ? "OSM 地圖" : "衛星底圖";
    btn.textContent = mapMode === "osm" ? "底圖" : "衛星";
    if (weatherMap && osmLayer && satelliteLayer) {
      if (mapMode === "osm") {
        weatherMap.removeLayer(satelliteLayer);
        osmLayer.addTo(weatherMap);
      } else {
        weatherMap.removeLayer(osmLayer);
        satelliteLayer.addTo(weatherMap);
      }
    }
    const mapEl = $("weatherMap");
    mapEl.classList.toggle("satellite", mapMode === "satellite");
    renderMapTiles();
  });
  $("fitMapBtn")?.addEventListener("click", fitStationsOnMap);
}

function initLeafletMap() {
  if (!window.L || weatherMap) return false;
  weatherMap = L.map("leafletMap", {
    center: [MAP_CENTER.lat, MAP_CENTER.lon],
    zoom: MAP_ZOOM,
    minZoom: 11,
    maxZoom: 18,
    zoomControl: true,
    attributionControl: true,
  });
  osmLayer = L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19,
    attribution: "&copy; OpenStreetMap contributors",
  }).addTo(weatherMap);
  satelliteLayer = L.tileLayer("https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}", {
    maxZoom: 20,
    attribution: "Satellite",
  });
  $("weatherMap")?.classList.add("leaflet-ready");
  return true;
}

function fitStationsOnMap() {
  if (!weatherMap || !stations.length) return;
  const bounds = L.latLngBounds(stations.map(s => [s.lat, s.lon]));
  weatherMap.fitBounds(bounds, { padding: [34, 34], maxZoom: 14 });
}

// ── 地圖投影 ─────────────────────────────────
function latLonToPixel(lat, lon, zoom) {
  const scale = 256 * 2 ** zoom;
  const sinLat = Math.sin((lat * Math.PI) / 180);
  return {
    x: ((lon + 180) / 360) * scale,
    y: (0.5 - Math.log((1 + sinLat) / (1 - sinLat)) / (4 * Math.PI)) * scale,
  };
}

function mapViewport() {
  const mapEl = $("weatherMap");
  const rect = mapEl.getBoundingClientRect();
  const center = latLonToPixel(MAP_CENTER.lat, MAP_CENTER.lon, MAP_ZOOM);
  return {
    width: rect.width,
    height: rect.height,
    left: center.x - rect.width / 2,
    top: center.y - rect.height / 2,
  };
}

function projectStation(station) {
  const viewport = mapViewport();
  const pt = latLonToPixel(station.lat, station.lon, MAP_ZOOM);
  const x = pt.x - viewport.left;
  const y = pt.y - viewport.top;
  return {
    x: Math.max(12, Math.min(Math.max(12, viewport.width - 12), x)),
    y: Math.max(12, Math.min(Math.max(12, viewport.height - 12), y)),
  };
}

// ── 地圖瓦片 ─────────────────────────────────
function renderMapTiles() {
  const layer = $("mapTiles");
  const viewport = mapViewport();
  if (!viewport.width) return;

  const minTX = Math.floor(viewport.left / 256);
  const maxTX = Math.floor((viewport.left + viewport.width) / 256);
  const minTY = Math.floor(viewport.top / 256);
  const maxTY = Math.floor((viewport.top + viewport.height) / 256);

  const tileUrl = mapMode === "satellite"
    ? (x, y, z) => `https://mt1.google.com/vt/lyrs=s&x=${x}&y=${y}&z=${z}`
    : (x, y, z) => `https://tile.openstreetmap.org/${z}/${x}/${y}.png`;

  const tiles = [];
  for (let x = minTX; x <= maxTX; x++) {
    for (let y = minTY; y <= maxTY; y++) {
      const left = Math.round(x * 256 - viewport.left);
      const top  = Math.round(y * 256 - viewport.top);
      tiles.push(
        `<img class="map-tile" src="${tileUrl(x, y, MAP_ZOOM)}" ` +
        `style="left:${left}px;top:${top}px" loading="lazy" alt="">`
      );
    }
  }
  layer.innerHTML = tiles.join("");
}

// ── 站點標記 ─────────────────────────────────
function renderMarkers() {
  if (weatherMap) {
    renderLeafletMarkers();
    return;
  }
  const layer = $("markerLayer");
  layer.innerHTML = "";

  stations.forEach((station) => {
    const latest = station.latest || {};
    const pos = projectStation(station);

    // 標記按鈕
    const marker = document.createElement("button");
    marker.type = "button";
    marker.className = `station-marker${station.has_full_weather ? "" : " wind-only"}`;
    marker.style.left = `${pos.x}px`;
    marker.style.top  = `${pos.y}px`;

    const tier = metricTier(metricValue(latest, activeMetric), activeMetric);
    if (tier) marker.dataset.tempTier = tier;

    marker.title = stationMarkerTitle(station);
    marker.setAttribute("aria-label", marker.title);
    marker.innerHTML = stationMarkerInnerHtml(station);

    marker.addEventListener("click", () => {
      if (selectedMarker) selectedMarker.classList.remove("active");
      marker.classList.add("active");
      selectedMarker = marker;
      selectedStationCode = station.code;
      selectStation(station.code);
    });

    // 站碼標籤
    const label = document.createElement("span");
    label.className = "station-label";
    label.style.left = `${pos.x}px`;
    label.style.top  = `${pos.y}px`;
    label.textContent = station.code;

    layer.appendChild(marker);
    layer.appendChild(label);
  });
}

function renderLeafletMarkers() {
  const presentCodes = new Set(stations.map(s => s.code));
  leafletMarkers.forEach((marker, code) => {
    if (!presentCodes.has(code)) {
      weatherMap.removeLayer(marker);
      leafletMarkers.delete(code);
    }
  });

  stations.forEach((station) => {
    const icon = L.divIcon({
      className: "leaflet-station-icon",
      iconSize: [74, 46],
      iconAnchor: [17, 17],
      html: stationMarkerHtml(station),
    });
    const marker = leafletMarkers.get(station.code);
    if (marker) {
      marker.setLatLng([station.lat, station.lon]);
      marker.setIcon(icon);
      return;
    }
    const created = L.marker([station.lat, station.lon], {
      icon,
      title: stationMarkerTitle(station),
      keyboard: true,
    }).addTo(weatherMap);
    created.on("click", () => {
      selectedStationCode = station.code;
      selectStation(station.code);
      renderLeafletMarkers();
    });
    leafletMarkers.set(station.code, created);
  });
}

function stationMarkerHtml(station) {
  const latest = station.latest || {};
  const tier = metricTier(metricValue(latest, activeMetric), activeMetric);
  return `
    <button type="button"
      class="station-marker${station.has_full_weather ? "" : " wind-only"}${selectedStationCode === station.code ? " active" : ""}"
      ${tier ? `data-temp-tier="${tier}"` : ""}
      aria-label="${safeText(stationMarkerTitle(station))}">
      ${stationMarkerInnerHtml(station)}
    </button>
    <span class="station-label">${safeText(station.code)}</span>
  `;
}

function stationMarkerTitle(station) {
  const latest = station.latest || {};
  const meta = METRIC_META[activeMetric] || METRIC_META.temperature;
  const value = metricValue(latest, activeMetric);
  const tempStr = latest.temperature != null ? fmtNum(latest.temperature) : "";
  return `${station.name}  ${meta.label} ${fmt(value, meta.unit)}  溫度 ${tempStr ? tempStr + "°C" : "--"}  ` +
         `平均風速 ${fmt(latest.wind_speed, "km/h")}  ` +
         `風向 ${latest.wind_direction || "--"}  ` +
         `座標：${station.coordinate_precision === "approx" ? "近似" : "已校正"}`;
}

function stationMarkerInnerHtml(station) {
  const latest = station.latest || {};
  const tempStr = latest.temperature != null ? fmtNum(latest.temperature) : "";
  const meta = METRIC_META[activeMetric] || METRIC_META.temperature;
  const activeValue = metricValue(latest, activeMetric);
  const windStr = activeMetric === "wind_speed" ? fmt(latest.wind_speed, "") : fmt(activeValue, "");
  return renderWindBarb(latest.wind_speed, latest.wind_degree) +
    `<span class="wind-speed-chip" title="${safeText(meta.label)}">${windStr}</span>` +
    (tempStr ? `<span class="temp-chip">${tempStr}</span>` : "");
}

// ── 風標 SVG ──────────────────────────────────
function renderWindBarb(speed, degree) {
  const rot = windBarbRotation(degree);
  const flags = windFlagPaths(Number(speed) || 0);
  return `
    <svg class="wind-barb" viewBox="-18 -18 36 36"
      style="transform:rotate(${rot}deg)" aria-hidden="true">
      <line x1="0" y1="13" x2="0" y2="-13"/>
      ${flags}
    </svg>`;
}

function windBarbRotation(degree) {
  return (degree != null && !Number.isNaN(Number(degree))) ? Number(degree) : 0;
}

function windFlagPaths(speed) {
  const count = Math.min(4, Math.max(1, Math.round(speed / 12)));
  return Array.from({ length: count }, (_, i) => {
    const y = -11 + i * 5;
    return `<path class="flag" d="M0 ${y} L10 ${y + 3}"/>`;
  }).join("");
}

// ── 站點選擇 ─────────────────────────────────
async function selectStation(code) {
  const panel = $("stationPanel");
  panel.innerHTML = `<p class="eyebrow">載入中...</p><p class="muted">正在取得 ${code} 觀測資料…</p>`;

  let data;
  try {
    data = await getJson(`/api/stations/${code}/latest`);
  } catch (err) {
    panel.innerHTML = `<p class="eyebrow error-text">錯誤</p><p class="muted">${err.message}</p>`;
    return;
  }

  const station = data.station || stations.find((s) => s.code === code) || {};

  // 基本資訊
  panel.innerHTML = `
    <p class="eyebrow">${station.region || "站點"}</p>
    <h2>${data.station_name}</h2>
    <p class="muted">觀測時間：${timeLabel(data.record_time)}</p>
    <p class="coord-note">座標狀態：${station.coordinate_precision === "approx" ? "近似座標，待人工校正" : "已校正"} · ${fmtNum(station.lat)}, ${fmtNum(station.lon)}</p>

    <div class="cards">
      ${metricCard("溫度",       fmtNum(data.temperature),        "°C",  data.temperature != null && Number(data.temperature) >= 33)}
      ${metricCard("濕度",       fmtNum(data.humidity),           "%",   false)}
      ${metricCard("露點",       fmtNum(data.dew_point),          "°C",  false)}
      ${metricCard("海平面氣壓", fmtNum(data.mean_sea_level_pressure), "hPa", false)}
      ${metricCard("平均風速",   fmtNum(data.wind_speed),         "km/h",false)}
      ${metricCard("陣風",       fmtNum(data.wind_gust),          "km/h",false)}
      ${metricCard("今日雨量",   fmtNum(data.rainfall_day),       "mm",  false)}
      ${metricCard("一小時雨量", fmtNum(data.rainfall_hour),      "mm",  false)}
    </div>

    <div class="wind-info">
      ${windCompassSvg(data.wind_degree)}
      <div>
        <strong>${data.wind_direction || "--"}</strong>
        <span class="muted">${data.wind_description || ""}</span>
      </div>
    </div>

    ${heatIndexCard(data.temperature, data.humidity)}

    <div class="mini-chart-wrap" id="miniChartTempWrap">
      <p class="mini-chart-label">24 小時溫度趨勢</p>
      <canvas id="miniChartTemp" height="70"></canvas>
    </div>

    <div class="mini-chart-wrap" id="miniChartWindWrap">
      <p class="mini-chart-label">24 小時平均風速趨勢</p>
      <canvas id="miniChartWind" height="70"></canvas>
    </div>
  `;

  // 同步更新歷史站點選擇
  $("historyStation").value = code;

  // 並行載入迷你圖
  Promise.all([
    getJson(`/api/stations/${code}/history?metric=temperature&from=${hoursAgo(24)}`),
    getJson(`/api/stations/${code}/history?metric=wind_speed&from=${hoursAgo(24)}`),
  ]).then(([tempData, windData]) => {
    drawMiniChart("miniChartTemp", tempData.points, "°C");
    drawMiniChart("miniChartWind", windData.points, "km/h");
  }).catch(() => {});

  // 更新主歷史圖
  await renderHistory();
}

function metricCard(label, value, unit, highlight = false) {
  const cls = highlight ? " highlight" : "";
  const display = value === "--" ? "--" : `${value}<span class="metric-unit"> ${unit}</span>`;
  return `
    <div class="metric-card${cls}">
      <span>${label}</span>
      <strong>${display}</strong>
    </div>`;
}

function windCompassSvg(degree) {
  const deg = (degree != null && !Number.isNaN(Number(degree))) ? Number(degree) : 0;
  return `
    <svg class="wind-compass" viewBox="0 0 32 32" aria-hidden="true">
      <circle cx="16" cy="16" r="14" fill="#e8f2f6" stroke="#c0d4dc" stroke-width="1.5"/>
      <g transform="rotate(${deg} 16 16)">
        <polygon points="16,4 19,16 16,13 13,16" fill="#0095b8"/>
        <polygon points="16,28 19,16 16,19 13,16" fill="#ccc"/>
      </g>
    </svg>`;
}

// ── 迷你折線圖（站點面板內） ─────────────────
function drawMiniChart(canvasId, points, unit) {
  const canvas = $(canvasId);
  if (!canvas || !points.length) return;

  const labels = points.map((p) => timeLabel(p.record_time).slice(11, 16));
  const values = points.map((p) => p.value);

  // 每 n 個取一個標籤防擁擠
  const step = Math.max(1, Math.ceil(labels.length / 6));
  const sparseLabels = labels.map((l, i) => (i % step === 0 ? l : ""));

  const isDark = currentTheme === "dark";
  const textColor = isDark ? "#8aacb8" : "#5a7280";
  const gridColor = isDark ? "rgba(255,255,255,.07)" : "rgba(0,0,0,.07)";
  const lineColor = "#00b8e0";
  const fillColor = isDark ? "rgba(0,184,224,.12)" : "rgba(0,149,184,.10)";

  if (canvas._chart) canvas._chart.destroy();

  canvas._chart = new Chart(canvas, {
    type: "line",
    data: {
      labels: sparseLabels,
      datasets: [{
        data: values,
        borderColor: lineColor,
        backgroundColor: fillColor,
        borderWidth: 1.5,
        pointRadius: 0,
        tension: 0.35,
        fill: true,
      }],
    },
    options: {
      responsive: false,
      animation: false,
      plugins: { legend: { display: false }, tooltip: { enabled: false } },
      scales: {
        x: {
          ticks: { color: textColor, font: { size: 10 }, maxRotation: 0 },
          grid: { color: gridColor },
        },
        y: {
          ticks: {
            color: textColor,
            font: { size: 10 },
            callback: (v) => `${v.toFixed(1)}`,
            maxTicksLimit: 4,
          },
          grid: { color: gridColor },
        },
      },
    },
  });
}

// ── 熱感指數 & 舒適度 ─────────────────────────
function calcHeatIndex(tempC, rh) {
  if (tempC == null || rh == null) return null;
  const t = Number(tempC);
  const h = Number(rh);
  if (t < 27) return t; // 低溫時熱感指數等同氣溫
  // Rothfusz (NWS) 公式，轉換到攝氏
  const tf = t * 9 / 5 + 32;
  let hi = -42.379 + 2.04901523 * tf + 10.14333127 * h
    - 0.22475541 * tf * h - 0.00683783 * tf * tf
    - 0.05481717 * h * h + 0.00122874 * tf * tf * h
    + 0.00085282 * tf * h * h - 0.00000199 * tf * tf * h * h;
  return (hi - 32) * 5 / 9;
}

function comfortLevel(heatIndex) {
  if (heatIndex == null) return null;
  if (heatIndex < 27)  return { label: "舒適", cls: "comfort-ok" };
  if (heatIndex < 32)  return { label: "略感悶熱", cls: "comfort-warn" };
  if (heatIndex < 38)  return { label: "悶熱", cls: "comfort-hot" };
  if (heatIndex < 44)  return { label: "非常悶熱", cls: "comfort-danger" };
  return { label: "極度危險", cls: "comfort-extreme" };
}

function heatIndexCard(temp, humidity) {
  const hi = calcHeatIndex(temp, humidity);
  const comfort = comfortLevel(hi);
  if (!comfort) return "";
  const hiStr = hi != null ? hi.toFixed(1) : "--";
  return `
    <div class="heat-index-card ${comfort.cls}">
      <div class="hi-row">
        <span class="hi-label">體感溫度</span>
        <strong class="hi-val">${hiStr}°C</strong>
      </div>
      <div class="hi-comfort">${comfort.label}</div>
    </div>`;
}

// ── 今日統計 ──────────────────────────────────
async function renderDailySummary() {
  let data;
  try {
    data = await getJson("/api/daily-summary");
  } catch {
    return;
  }

  function setDaily(id, val, digits = 1) {
    const el = $(id);
    if (!el) return;
    el.textContent = val != null ? Number(val).toFixed(digits) : "--";
  }

  setDaily("dTempHi", data.max_temp);
  setDaily("dTempLo", data.min_temp);
  setDaily("dHumHi", data.max_humidity, 0);
  setDaily("dHumLo", data.min_humidity, 0);
  setDaily("dPresHi", data.max_pressure, 1);
  setDaily("dPresLo", data.min_pressure, 1);
  setDaily("dGust", data.max_gust, 1);
  setDaily("dRain", data.max_rain_day, 1);

  // 移除 loading 狀態
  document.querySelectorAll(".daily-card.loading").forEach(el => el.classList.remove("loading"));
}

// ── 培正版監測模組 ─────────────────────────────
async function renderDashboardModules() {
  let data;
  try {
    data = await getJson("/api/dashboard");
  } catch {
    renderModuleError();
    return;
  }

  renderWarnings(data.warnings || {});
  renderWindIndex(data.wind_index || {});
  renderWaterLevel(data.water_level || {});
  renderAirQuality(data.air_quality || {});
  renderDatabasePanel(data.database || {});
  renderOfficialForecast(data.official_forecast || {});
  renderOverviewWarnings(data.warnings || {});
}

async function renderDataQuality() {
  let data;
  try {
    data = await getJson("/api/data-quality");
  } catch {
    const panel = $("qualityPanel");
    if (panel) panel.innerHTML = `<div class="module-empty">資料品質載入失敗</div>`;
    return;
  }
  const delay = data.delay_minutes;
  $("overviewDataTime") && ($("overviewDataTime").textContent = timeLabel(data.latest_data_time));
  $("overviewDelay") && ($("overviewDelay").textContent = delay == null ? "--" : `${delay} 分鐘`);
  $("overviewFetch") && ($("overviewFetch").textContent = data.latest_fetch?.status || "--");
  $("overviewFetchDetail") && ($("overviewFetchDetail").textContent = `最近抓取：${timeLabel(data.latest_fetch?.fetched_at)}`);
  const status = $("qualityStatus");
  if (status) {
    const bad = data.missing_stations?.length || data.stale_stations?.length;
    status.textContent = bad ? "需檢查" : "正常";
    status.classList.toggle("pending", !!bad);
  }
  const panel = $("qualityPanel");
  if (!panel) return;
  panel.innerHTML = `
    <div class="quality-item"><span>SQLite 記錄</span><strong>${data.reading_count ?? "--"}</strong></div>
    <div class="quality-item"><span>有資料站點</span><strong>${data.station_count ?? "--"} / ${data.expected_station_count ?? "--"}</strong></div>
    <div class="quality-item"><span>缺測站</span><strong>${data.missing_stations?.length ?? 0}</strong></div>
    <div class="quality-item"><span>延遲站</span><strong>${data.stale_stations?.length ?? 0}</strong></div>
    ${(data.external_sources || []).slice(0, 4).map(src => `
      <div class="quality-item">
        <span>${safeText(src.cache_key)}</span>
        <strong>${datasetStatus(src.status)}</strong>
      </div>
    `).join("")}
  `;
}

async function renderWarningEvents() {
  const panel = $("warningEventList");
  if (!panel) return;
  let data;
  try {
    data = await getJson("/api/warning-events?limit=12");
  } catch {
    panel.innerHTML = `<div class="module-empty">警告事件載入失敗</div>`;
    return;
  }
  const items = data.items || [];
  panel.innerHTML = items.length
    ? items.map(item => `
      <div class="warning-event">
        <strong>${safeText(item.warning_type)} · ${datasetStatus(item.status)}</strong>
        <span>${timeLabel(item.issued_at || item.updated_at)}｜${safeText(item.message || "")}</span>
      </div>
    `).join("")
    : `<div class="module-empty">尚未累積警告事件。按「立即更新」或等待排程抓取後會寫入。</div>`;
}

function renderOverviewWarnings(data) {
  const items = data.items || [];
  const active = items.filter(item => item.status === "active" || item.level === "watch" || item.level === "official");
  const title = $("overviewWarning");
  const detail = $("overviewWarningDetail");
  if (title) title.textContent = active.length ? `${active.length} 項` : "無生效";
  if (detail) detail.textContent = active[0]?.message || data.source || "SMG 官方警告與本地派生提示";
}

function safeText(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function renderWarnings(data) {
  const status = $("warningStatus");
  const list = $("warningList");
  if (!status || !list) return;
  const items = data.items || [];
  const activeCount = items.filter(item => item.status === "active" || item.level === "watch" || item.level === "official").length;
  status.textContent = activeCount ? `${activeCount} 項生效 / 提示` : "官方無警告";
  status.classList.toggle("pending", !activeCount);
  list.innerHTML = items.length
    ? items.map(item => `
        <div class="alert-item ${item.level || "watch"}">
          <strong>${safeText(item.type)}</strong>
          <span>${safeText(item.message)}</span>
          ${item.issued_at ? `<small>${timeLabel(item.issued_at)}</small>` : ""}
        </div>
      `).join("")
    : `<div class="module-empty">官方警告及本地站點派生提示均未有生效項目。</div>`;
}

function renderWindIndex(data) {
  const panel = $("windIndexPanel");
  if (!panel) return;
  const strongest = data.strongest_station;
  panel.innerHTML = `
    <div class="module-metric large">
      <span>風力級別</span>
      <strong>${data.beaufort?.level ?? "--"}</strong>
      <em>${data.beaufort?.label || "資料不足"}</em>
    </div>
    <div class="module-metric">
      <span>橋上平均</span>
      <strong>${fmtNum(data.bridge_average_kmh)} <small>km/h</small></strong>
    </div>
    <div class="module-metric">
      <span>陸地平均</span>
      <strong>${fmtNum(data.land_average_kmh)} <small>km/h</small></strong>
    </div>
    <div class="module-metric">
      <span>最高陣風</span>
      <strong>${fmtNum(data.max_gust_kmh)} <small>km/h</small></strong>
    </div>
    <div class="module-note">
      最強站點：${strongest ? `${strongest.station_name}（${fmtNum(strongest.wind_gust || strongest.wind_speed)} km/h）` : "暫無資料"}
    </div>
  `;
}

function renderWaterLevel(data) {
  const panel = $("waterLevelPanel");
  const badge = $("waterStatus");
  if (!panel) return;

  // SMG 沒有公開水位 XML，提供官方頁面連結
  const links = [
    { name: "SMG 潮汐預報",    url: "https://www.smg.gov.mo/zh/subpage/31/page/31",      desc: "澳門氣象局官方潮汐資料" },
    { name: "颱風天文潮汐",    url: "https://www.smg.gov.mo/zh/subpage/54/page/54",      desc: "颱風期間潮位資訊" },
    { name: "海事及水務局",    url: "https://www.marine.gov.mo/zh/info/tide.html",       desc: "澳門港口水位資料" },
    { name: "廣東省水文局",    url: "http://www.gdwater.gov.cn/",                         desc: "珠江流域水位監測" },
  ];

  if (badge) {
    badge.textContent = "外部連結";
    badge.className = "module-status";
    badge.style.background = "rgba(100,160,200,0.15)";
    badge.style.color = "var(--accent)";
  }

  panel.innerHTML = links.map(link => `
    <a class="service-tile active" href="${link.url}" target="_blank" rel="noopener"
       style="text-decoration:none;cursor:pointer;">
      <strong>${safeText(link.name)}</strong>
      <span>${safeText(link.desc)}</span>
      <small style="color:var(--accent)">↗ 開啟官方頁面</small>
    </a>
  `).join("");
}

function renderAirQuality(data) {
  const panel = $("airQualityPanel");
  const badge = $("airStatus");
  if (!panel) return;
  const items = data.items || [];
  if (items.length) {
    if (badge) { badge.textContent = "運作中"; badge.className = "module-status ok"; }
    const tip = data.complementary?.general_public || data.complementary?.sensitive_population_groups || "";
    panel.innerHTML = `
      ${tip ? `<div class="service-tile active wide"><strong>${safeText(data.complementary?.level || "空氣質量")}</strong><span>${safeText(tip)}</span></div>` : ""}
      ${items.map(item => `
        <div class="service-tile active">
          <strong>${safeText(item.station_name || item.station_code)}</strong>
          <span>AQI ${safeText(item.value)} · ${safeText(item.level)}</span>
          <small>${safeText(item.valid_for || data.updated_at || "")}</small>
        </div>
      `).join("")}
    `;
    return;
  }
  if (badge) {
    const isPending = !data.status || data.status === "pending_source";
    badge.textContent = isPending ? "待接入" : (data.status === "unavailable" ? "無法連線" : data.status);
    badge.className = "module-status" + (isPending ? " pending" : "");
  }
  const metrics = data.metrics || ["AQI", "PM2.5", "PM10", "NO2"];
  panel.innerHTML = metrics.map(metric => `
    <div class="service-tile ${data.status || "pending_source"}">
      <strong>${safeText(metric)}</strong>
      <span>${safeText(data.error || data.source || "等待資料源")}</span>
    </div>
  `).join("");
}

function renderDatabasePanel(data) {
  const panel = $("databasePanel");
  if (!panel) return;
  const datasets = data.datasets || [];
  panel.innerHTML = `
    <div class="database-summary-line">
      <span>站點</span><strong>${data.station_count ?? "--"}</strong>
      <span>最新觀測</span><strong>${timeLabel(data.latest_data_time)}</strong>
    </div>
    <a class="dataset-export" href="/api/export/weather.csv" download>下載氣象站 CSV</a>
    ${datasets.map(ds => `
      <div class="dataset-row ${ds.status}">
        <span>${ds.name}</span>
        <strong>${datasetStatus(ds.status)}</strong>
      </div>
    `).join("")}
  `;
}

function renderOfficialForecast(data) {
  const panel = $("officialForecastPanel");
  const badge = $("forecastStatus");
  if (!panel) return;
  const items = data.items || [];
  if (items.length) {
    if (badge) { badge.textContent = "運作中"; badge.className = "module-status ok"; }
    panel.innerHTML = items.slice(0, 7).map(item => `
      <div class="forecast-tile">
        <div>
          <strong>${safeText(item.day_of_week || "")}</strong>
          <span>${safeText((item.valid_for || "").slice(5))}</span>
        </div>
        ${item.icon_url ? `<img src="${safeText(item.icon_url)}" alt="">` : ""}
        <p>${safeText(item.description)}</p>
        <footer>
          <b>${fmtNum(item.temp_low)}-${fmtNum(item.temp_high)}°C</b>
          <span>${fmtNum(item.humidity_low)}-${fmtNum(item.humidity_high)}%</span>
        </footer>
      </div>
    `).join("");
    return;
  }
  if (badge) {
    const isPending = !data.status || data.status === "pending_source";
    badge.textContent = isPending ? "待接入" : (data.status === "unavailable" ? "無法連線" : data.status);
    badge.className = "module-status" + (isPending ? " pending" : "");
  }
  panel.innerHTML = `
    <div class="service-tile ${data.status || "pending_source"}">
      <strong>七日天氣預報</strong>
      <span>${safeText(data.error || data.source || "等待資料源")}</span>
    </div>
    <div class="service-tile pending_source">
      <strong>官方 / ML 分離</strong>
      <span>${safeText(data.note || "避免混淆官方預報和本地模型預測。")}</span>
    </div>
  `;
}

function datasetStatus(status) {
  return {
    active: "運作中",
    derived: "派生",
    pending_source: "待資料源",
    unavailable: "暫不可用",
    stale: "快取資料",
  }[status] || status || "--";
}

function renderModuleError() {
  ["warningList", "windIndexPanel", "waterLevelPanel", "airQualityPanel", "databasePanel", "officialForecastPanel"].forEach(id => {
    const el = $(id);
    if (el) el.innerHTML = `<div class="module-empty">模組載入失敗</div>`;
  });
}

// ── 多站對比 ──────────────────────────────────
const COMPARE_COLORS = [
  "#00b8e0", "#c8e03a", "#f0a440", "#e05252",
  "#a070d8", "#3ac87e", "#f07090", "#60d0c0",
];

function fillComparePicker() {
  const picker = $("compareStationPicker");
  if (!picker) return;
  picker.innerHTML = stations.map((s, i) => `
    <label class="compare-chip ${compareSelectedCodes.has(s.code) ? "selected" : ""}"
           data-code="${s.code}"
           style="--chip-color:${COMPARE_COLORS[i % COMPARE_COLORS.length]}">
      <input type="checkbox" value="${s.code}"
        ${compareSelectedCodes.has(s.code) ? "checked" : ""}
        aria-label="${s.name}">
      <span>${s.code}</span>
    </label>
  `).join("");

  picker.querySelectorAll("input[type=checkbox]").forEach(cb => {
    cb.addEventListener("change", () => {
      const code = cb.value;
      if (cb.checked) compareSelectedCodes.add(code);
      else compareSelectedCodes.delete(code);
      cb.closest(".compare-chip").classList.toggle("selected", cb.checked);
      renderCompare();
    });
  });
}

function initGroupPresets() {
  document.querySelectorAll(".group-chip").forEach(btn => {
    btn.addEventListener("click", async () => {
      document.querySelectorAll(".group-chip").forEach(item => item.classList.toggle("active", item === btn));
      const group = btn.dataset.group || "all";
      const metric = btn.dataset.metric || "temperature";
      compareSelectedCodes = new Set(stationsForGroup(group).map(s => s.code));
      if ($("compareMetric")) $("compareMetric").value = metric;
      fillComparePicker();
      await renderCompare();
    });
  });
}

function stationsForGroup(group) {
  if (group === "bridge") return stations.filter(s => s.region === "橋上" || !s.has_full_weather);
  if (group === "land") return stations.filter(s => s.has_full_weather);
  if (group === "macau") return stations.filter(s => s.region === "澳門半島");
  if (group === "islands") return stations.filter(s => ["氹仔", "路環", "路氹", "橫琴澳大"].includes(s.region));
  return stations;
}

async function renderCompare() {
  if (compareSelectedCodes.size === 0) {
    if (compareChart) { compareChart.destroy(); compareChart = null; }
    return;
  }
  const metric  = $("compareMetric").value;
  const hours   = parseInt($("compareRange").value, 10) || 24;
  const codes   = [...compareSelectedCodes].join(",");

  let data;
  try {
    data = await getJson(
      `/api/compare?codes=${encodeURIComponent(codes)}&metric=${encodeURIComponent(metric)}&from=${hoursAgo(hours)}`
    );
  } catch { return; }

  const meta = METRIC_META[metric] || { label: metric, unit: "" };
  const allTimes = new Set();
  Object.values(data.series).forEach(pts => pts.forEach(p => allTimes.add(p.record_time)));
  const sortedTimes = [...allTimes].sort();

  const step = Math.max(1, Math.ceil(sortedTimes.length / 10));
  const labels = sortedTimes.map((t, i) => i % step === 0 ? timeLabel(t).slice(5) : "");

  const colors = getChartColors();
  const context = $("compareChartContext");
  if (context) {
    context.textContent = `${compareSelectedCodes.size} 個站點 · ${METRIC_META[metric]?.label || metric} · 最近 ${hours} 小時`;
  }
  const datasets = [...compareSelectedCodes].map((code, ci) => {
    const pts = data.series[code] || [];
    const ptsMap = Object.fromEntries(pts.map(p => [p.record_time, p.value]));
    const values = sortedTimes.map(t => ptsMap[t] ?? null);
    const station = stations.find(s => s.code === code);
    const color = COMPARE_COLORS[ci % COMPARE_COLORS.length];
    return {
      label: station ? `${station.name}` : code,
      data: values,
      borderColor: color,
      backgroundColor: color + "22",
      borderWidth: 2,
      pointRadius: 0,
      pointHoverRadius: 4,
      tension: 0.35,
      fill: false,
      spanGaps: true,
    };
  });

  const canvas = $("compareChart");
  const chartType = metric.includes("rainfall") ? "bar" : "line";
  if (compareChart) {
    compareChart.config.type = chartType;
    compareChart.data.labels = labels;
    compareChart.data.datasets = datasets;
    compareChart.options.plugins.tooltip.callbacks.label =
      (ctx) => ` ${ctx.dataset.label}: ${ctx.parsed.y?.toFixed(1)} ${meta.unit}`;
    compareChart.options.unit = meta.unit;
    compareChart.update();
  } else {
    compareChart = new Chart(canvas, {
      type: chartType,
      data: { labels, datasets },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        unit: meta.unit,
        interaction: { mode: "index", intersect: false },
        plugins: {
          legend: { labels: { color: colors.text, font: { size: 12 }, boxWidth: 16 } },
          tooltip: {
            callbacks: {
              label: (ctx) => ` ${ctx.dataset.label}: ${ctx.parsed.y?.toFixed(1)} ${meta.unit}`,
            },
          },
        },
        scales: {
          x: {
            ticks: { color: colors.text, font: { size: 11 }, maxRotation: 0, autoSkip: true },
            grid: { color: colors.grid },
          },
          y: {
            ticks: {
              color: colors.text,
              font: { size: 12 },
              callback: (v) => `${v.toFixed(1)} ${meta.unit}`,
            },
            grid: { color: colors.grid },
          },
        },
      },
    });
  }
}


function renderSummaryStrip(stationList) {
  const all = stationList.map((s) => s.latest).filter(Boolean);

  function best(metric, high = true) {
    const valid = all.filter((it) => it[metric] != null);
    if (!valid.length) return null;
    valid.sort((a, b) => high ? b[metric] - a[metric] : a[metric] - b[metric]);
    return valid[0];
  }

  function setSummary(valueId, stationId, item, metric, unit) {
    const el = $(valueId);
    const sub = $(stationId);
    if (!el || !sub) return;
    el.textContent = item ? `${fmtNum(item[metric])} ${unit}` : "--";
    sub.textContent = item ? item.station_name : "";
    el.closest(".summary-card")?.classList.remove("loading");
  }

  setSummary("summaryMaxTemp",       "summaryMaxTempStation",       best("temperature"), "temperature", "°C");
  setSummary("summaryMinTemp",       "summaryMinTempStation",       best("temperature", false), "temperature", "°C");
  setSummary("summaryMaxHumidity",   "summaryMaxHumidityStation",   best("humidity"), "humidity", "%");
  setSummary("summaryMaxGust",       "summaryMaxGustStation",       best("wind_gust"), "wind_gust", "km/h");
  setSummary("summaryMaxRain",       "summaryMaxRainStation",       best("rainfall_day"), "rainfall_day", "mm");
}

// ── 狀態列 ────────────────────────────────────
async function refreshStatus() {
  const dot  = $("statusDot");
  const text = $("statusText");
  dot.className = "status-dot loading";
  text.textContent = "正在更新…";

  let health;
  try {
    health = await getJson("/api/health");
  } catch {
    dot.className = "status-dot error";
    text.textContent = "無法連線至後端";
    text.classList.add("error-text");
    return;
  }

  text.classList.remove("error-text");
  const success = health.latest_success;

  if (success) {
    dot.className = "status-dot ok";
    // 優先顯示觀測資料時間（SMG XML 的 record_time）
    const dataTime = health.latest_data_time || success.fetched_at;
    const fetchTime = success.fetched_at;
    text.innerHTML =
      `資料觀測時間：<strong>${timeLabel(dataTime)}</strong>` +
      `<span class="status-fetch-hint">（伺服器抓取：${timeLabel(fetchTime)}）` +
      `｜ SMG 約每 10 分鐘發布一次</span>`;
    $("footerUpdate").textContent = `最近狀態：${health.latest_fetch?.status || "--"}`;
  } else {
    dot.className = "status-dot error";
    const msg = health.latest_fetch?.message || "尚未有資料，請先執行一次抓取";
    text.textContent = `尚未成功抓取：${msg}`;
    text.classList.add("error-text");
  }
}

// ── 排行 ──────────────────────────────────────
async function renderRankings() {
  const metric = $("rankingMetric").value;
  const rows = $("rankingRows");
  rows.innerHTML = `<tr><td colspan="5" class="table-loading">載入中…</td></tr>`;

  let data;
  try {
    if (metric === "heat_index") {
      data = {
        metric,
        items: stations
          .map(s => ({ station_code: s.code, station_name: s.name, record_time: s.latest?.record_time, value: metricValue(s.latest, "heat_index") }))
          .filter(item => item.value != null)
          .sort((a, b) => b.value - a.value),
      };
    } else {
      data = await getJson(`/api/rankings?metric=${encodeURIComponent(metric)}`);
    }
  } catch {
    rows.innerHTML = `<tr><td colspan="5" class="table-loading">載入失敗</td></tr>`;
    return;
  }

  const unit = METRIC_META[metric]?.unit || "";
  const rankClass = ["gold", "silver", "bronze"];

  if (!data.items.length) {
    rows.innerHTML = `<tr><td colspan="5" class="table-loading">暫無資料</td></tr>`;
    return;
  }

  rows.innerHTML = data.items.map((item, i) => {
    const cls = rankClass[i] || "";
    const station = stations.find((s) => s.code === item.station_code) || {};
    return `
      <tr>
        <td><span class="rank-num ${cls}">${i + 1}</span></td>
        <td>${item.station_name}</td>
        <td><span class="region-badge">${station.region || "--"}</span></td>
        <td>${timeLabel(item.record_time)}</td>
        <td><strong>${fmtNum(item.value)}</strong> <span style="color:var(--muted);font-size:13px">${unit}</span></td>
      </tr>`;
  }).join("");
}

// ── 歷史圖表 ─────────────────────────────────
function getChartColors() {
  const isDark = currentTheme === "dark";
  return {
    text:    isDark ? "#aac0cc" : "#3a5060",
    grid:    isDark ? "rgba(255,255,255,.06)" : "rgba(0,0,0,.06)",
    line:    "#00b8e0",
    fill:    isDark ? "rgba(0,184,224,.15)" : "rgba(0,149,184,.10)",
    panel:   isDark ? "#131f26" : "#ffffff",
  };
}

function metricColor(metric) {
  return {
    temperature: "#d66a2c",
    humidity: "#1976a3",
    dew_point: "#2a9d78",
    wind_speed: "#5874c9",
    wind_gust: "#8c61c8",
    rainfall_current: "#2f80c0",
    rainfall_hour: "#2f80c0",
    rainfall_day: "#2f80c0",
    mean_sea_level_pressure: "#56616f",
    station_pressure: "#56616f",
  }[metric] || "#00a6c8";
}

function updateChartTheme(chart) {
  const colors = getChartColors();
  chart.options.scales.x.ticks.color = colors.text;
  chart.options.scales.x.grid.color  = colors.grid;
  chart.options.scales.y.ticks.color = colors.text;
  chart.options.scales.y.grid.color  = colors.grid;
  chart.options.plugins.legend.labels.color = colors.text;
  chart.update("none");
}

function chartStats(points) {
  const values = points.map((p) => Number(p.value)).filter(Number.isFinite);
  if (!values.length) return null;
  const latest = values[values.length - 1];
  const first = values[0];
  const high = Math.max(...values);
  const low = Math.min(...values);
  const avg = values.reduce((sum, value) => sum + value, 0) / values.length;
  return { latest, high, low, avg, change: latest - first };
}

function renderHistoryStats(points, meta) {
  const wrap = $("historyChartStats");
  if (!wrap) return;
  const stats = chartStats(points);
  if (!stats) {
    wrap.innerHTML = `<div class="chart-stat"><span>資料</span><strong>暫無</strong></div>`;
    return;
  }
  const unit = meta.unit || "";
  const sign = stats.change > 0 ? "+" : "";
  wrap.innerHTML = [
    ["最新", fmt(stats.latest, unit)],
    ["最高", fmt(stats.high, unit)],
    ["最低", fmt(stats.low, unit)],
    ["平均", fmt(stats.avg, unit)],
    ["區間變化", `${sign}${fmt(stats.change, unit)}`],
  ].map(([label, value]) => `
    <div class="chart-stat">
      <span>${label}</span>
      <strong>${value}</strong>
    </div>
  `).join("");
}

async function renderHistory() {
  const code   = $("historyStation").value;
  const metric = $("historyMetric").value;
  const hours  = parseInt($("historyRange").value, 10) || 24;
  const rangeMode = $("historyRange").value;
  const interval = $("historyInterval")?.value || "";
  if (!code) return;

  const rows = $("historyRows");
  rows.innerHTML = `<tr><td colspan="2" class="table-loading">載入中…</td></tr>`;

  let data;
  try {
    const params = new URLSearchParams({ metric });
    if (rangeMode === "custom") {
      const from = localDateTimeParam($("historyFrom")?.value);
      const to = localDateTimeParam($("historyTo")?.value);
      if (from) params.set("from", from);
      if (to) params.set("to", to);
    } else {
      params.set("from", hoursAgo(hours));
    }
    if (interval) params.set("interval", interval);
    data = await getJson(`/api/stations/${code}/history?${params.toString()}`);
    updateHistoryExportLink(code, metric, params);
  } catch {
    rows.innerHTML = `<tr><td colspan="2" class="table-loading">載入失敗</td></tr>`;
    return;
  }

  const meta  = METRIC_META[metric] || { label: metric, unit: "" };
  const unit  = meta.unit;
  const pts   = data.points;
  renderHistoryStats(pts, meta);

  // 計算標籤間隔（防過密）
  const step = Math.max(1, Math.ceil(pts.length / 10));
  const labels = pts.map((p, i) => (i % step === 0 || i === pts.length - 1 ? timeLabel(p.record_time).slice(5) : ""));
  const values = pts.map((p) => p.value);

  const colors = getChartColors();
  const lineColor = metricColor(metric);
  const chartType = metric.includes("rainfall") ? "bar" : "line";
  const canvas = $("historyChart");

  if (historyChart) {
    historyChart.config.type = chartType;
    historyChart.data.labels = labels;
    historyChart.data.datasets[0].data = values;
    historyChart.data.datasets[0].label = `${meta.label} (${unit})`;
    historyChart.data.datasets[0].borderColor = lineColor;
    historyChart.data.datasets[0].backgroundColor = `${lineColor}22`;
    historyChart.options.unit = unit;
    updateChartTheme(historyChart);
    historyChart.update();
  } else {
    historyChart = new Chart(canvas, {
      type: chartType,
      data: {
        labels,
        datasets: [{
          label: `${meta.label} (${unit})`,
          data: values,
          borderColor: lineColor,
          backgroundColor: `${lineColor}22`,
          borderWidth: 2.6,
          pointRadius: pts.length > 100 ? 0 : 3,
          pointHoverRadius: 5,
          tension: 0.35,
          fill: true,
        }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        unit,
        interaction: { mode: "index", intersect: false },
        plugins: {
          legend: {
            labels: { color: colors.text, font: { size: 13 } },
          },
          tooltip: {
            callbacks: {
              label: (ctx) => ` ${ctx.parsed.y?.toFixed(1)} ${unit}`,
            },
          },
        },
        scales: {
          x: {
            ticks: {
              color: colors.text,
              font: { size: 11 },
              maxRotation: 0,
              autoSkip: true,
            },
            grid: { color: colors.grid },
          },
          y: {
            ticks: {
              color: colors.text,
              font: { size: 12 },
              callback: (v) => `${v.toFixed(1)} ${unit}`,
            },
            grid: { color: colors.grid },
          },
        },
      },
    });
  }

  // 表格（最新在前）
  if (!pts.length) {
    rows.innerHTML = `<tr><td colspan="2" class="table-loading">暫無資料</td></tr>`;
    return;
  }
  rows.innerHTML = pts.slice().reverse().map((p) =>
    `<tr><td>${timeLabel(p.record_time)}</td>` +
    `<td><strong>${fmtNum(p.value)}</strong> <span style="color:var(--muted);font-size:12px">${unit}</span></td></tr>`
  ).join("");
}

function updateHistoryExportLink(code, metric, params) {
  const link = $("historyExportLink");
  if (!link) return;
  const exportParams = new URLSearchParams(params);
  exportParams.set("code", code);
  exportParams.set("metric", metric);
  link.href = `/api/export/history.csv?${exportParams.toString()}`;
}

// ── 站點下拉選單 ─────────────────────────────
function fillStationSelect() {
  const sel = $("historyStation");
  sel.innerHTML = stations
    .map((s) => `<option value="${s.code}">${s.name} (${s.region})</option>`)
    .join("");
  const defaultCode = stations.find((s) => s.code === "TG")?.code || stations[0]?.code;
  if (defaultCode) sel.value = defaultCode;
}

function initHistoryControls() {
  const to = new Date();
  const from = new Date(Date.now() - 24 * 3600000);
  if ($("historyTo")) $("historyTo").value = to.toISOString().slice(0, 16);
  if ($("historyFrom")) $("historyFrom").value = from.toISOString().slice(0, 16);
}

// ── 刷新 ──────────────────────────────────────
async function triggerRefresh() {
  if (window.OFFLINE_DATA && preferOfflineData()) return;
  const btn = $("refreshBtn");
  btn?.classList.add("spinning");
  btn && (btn.disabled = true);
  try {
    await fetchLive("/api/refresh");
  } catch { /* 靜默失敗 */ }
  btn?.classList.remove("spinning");
  btn && (btn.disabled = false);
}

async function refreshPageData() {
  stations = await getJson("/api/stations");
  renderMarkers();
  renderSummaryStrip(stations);
  await refreshStatus();
  await renderRankings();
  await renderHistory();
  await renderDailySummary();
  await renderDashboardModules();
  await renderDataQuality();
  await renderWarningEvents();
  await renderCompare();
  startCountdown();
}

// ── 初始化 ────────────────────────────────────
async function init() {
  initTheme();
  initMapLayerToggle();
  initLeafletMap();
  initMetricMatrix();
  initHistoryControls();
  initGroupPresets();

  // 刷新按鈕
  $("refreshBtn")?.addEventListener("click", async () => {
    await triggerRefresh();
    await refreshPageData();
  });

  // 狀態設為載入中
  $("statusDot").className = "status-dot loading";

  try {
    stations = await getJson("/api/stations");
  } catch (err) {
    $("statusText").textContent = `載入失敗：${err.message}`;
    $("statusText").classList.add("error-text");
    $("statusDot").className = "status-dot error";
    return;
  }

  renderMapTiles();
  renderMarkers();
  fitStationsOnMap();
  fillStationSelect();
  fillComparePicker();
  renderSummaryStrip(stations);
  await refreshStatus();
  await renderRankings();
  await renderHistory();
  await renderDailySummary();
  await renderDashboardModules();
  await renderDataQuality();
  await renderWarningEvents();
  startCountdown();
}

// ── 事件監聽 ─────────────────────────────────
$("rankingMetric")?.addEventListener("change", renderRankings);
$("historyStation")?.addEventListener("change", renderHistory);
$("historyMetric")?.addEventListener("change", renderHistory);
$("historyRange")?.addEventListener("change", renderHistory);
$("historyInterval")?.addEventListener("change", renderHistory);
$("historyFrom")?.addEventListener("change", renderHistory);
$("historyTo")?.addEventListener("change", renderHistory);
$("compareMetric")?.addEventListener("change", renderCompare);
$("compareRange")?.addEventListener("change", renderCompare);

window.addEventListener("resize", () => {
  if (!stations.length) return;
  renderMapTiles();
  renderMarkers();
});

// ── 啟動 ──────────────────────────────────────
init().catch((err) => {
  const text = $("statusText");
  text.textContent = `啟動失敗：${err.message}`;
  text.classList.add("error-text");
  $("statusDot").className = "status-dot error";
});
