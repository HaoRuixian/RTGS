const messages = {
  zh: {
    appTitle: "GNSS-IR实时水位",
    refresh: "刷新",
    newStation: "新增测站",
    logout: "登出",
    stations: "测站",
    receiverStatus: "接收机状态",
    waterLevel: "水位",
    overview: "总览",
    spaceView: "空间视图",
    config: "配置",
    products: "结果",
    postProcess: "后处理",
    logs: "日志",
    start: "启动",
    stop: "停止",
    restart: "重启",
    stationLocation: "测站位置",
    latitude: "纬度",
    longitude: "经度",
    height: "高程",
    rinexPostProcessing: "RINEX 后处理",
    files: "文件",
    observationRinex: "观测 RINEX",
    ephemerisFile: "星历 / SP3",
    ephemerisType: "星历类型",
    useRinexPosition: "使用 RINEX APPROX POSITION XYZ",
    runPostProcess: "开始后处理",
    runningPostProcess: "正在后处理...",
    postProcessSummary: "后处理摘要",
    postProcessProducts: "后处理产品",
    epochs: "历元",
    observations: "观测记录",
    output: "输出",
    noFileSelected: "未选择文件",
    waitingResult: "等待结果",
    noStation: "没有测站",
    saved: "已保存",
    restartHint: "保存后需重启测站才生效",
    currentStation: "测站",
    idle: "空闲",
    noCoordinate: "没有测站坐标",
    ready: "就绪",
    done: "完成",
    error: "错误",
    postProcessWaiting: "等待 RINEX 后处理产品",
    choosePostFiles: "请选择 RINEX 观测文件和星历文件",
    chooseStation: "请选择已配置测站",
    viewerOnly: "当前账号只有查看权限",
    completed: "已完成",
    rinexPosition: "RINEX 坐标",
    configPosition: "配置坐标"
  },
  en: {
    appTitle: "GNSS-IR Realtime Water Level",
    refresh: "Refresh",
    newStation: "New Station",
    logout: "Logout",
    stations: "Stations",
    receiverStatus: "Receiver Status",
    waterLevel: "Water Level",
    overview: "Overview",
    spaceView: "Space View",
    config: "Config",
    products: "Products",
    postProcess: "Post Process",
    logs: "Logs",
    start: "Start",
    stop: "Stop",
    restart: "Restart",
    stationLocation: "Station Location",
    latitude: "Latitude",
    longitude: "Longitude",
    height: "Height",
    rinexPostProcessing: "RINEX Post Processing",
    files: "Files",
    observationRinex: "Observation RINEX",
    ephemerisFile: "Ephemeris / SP3",
    ephemerisType: "Ephemeris Type",
    useRinexPosition: "Use RINEX APPROX POSITION XYZ",
    runPostProcess: "Run Post Process",
    runningPostProcess: "Running...",
    postProcessSummary: "Post Process Summary",
    postProcessProducts: "Post Process Products",
    epochs: "Epochs",
    observations: "Observations",
    output: "Output",
    noFileSelected: "No file selected",
    waitingResult: "Waiting for results",
    noStation: "No station",
    saved: "Saved",
    restartHint: "Restart the station to apply changes",
    currentStation: "Station",
    idle: "Idle",
    noCoordinate: "No station coordinate",
    ready: "ready",
    done: "done",
    error: "error",
    postProcessWaiting: "Waiting for RINEX post-process products",
    choosePostFiles: "Choose a RINEX observation file and an ephemeris file",
    chooseStation: "Choose an existing station",
    viewerOnly: "This account has view-only permission",
    completed: "Completed",
    rinexPosition: "RINEX position",
    configPosition: "Config position"
  }
};

const t = new Proxy({}, {
  get: (_target, key) => tr(String(key))
});

const state = {
  status: null,
  user: null,
  stationConfigs: [],
  selected: null,
  pendingConfirm: null,
  creatingStation: false,
  products: [],
  productTypeFilter: "",
  productRange: { start: "", end: "" },
  chartLayouts: {},
  chartHover: {},
  irConfig: null,
  activeTab: "overview",
  stationFormDirty: false,
  irFormDirty: false,
  postprocess: null,
  postprocessRunning: false,
  language: localStorage.getItem("rtgsLanguage") || "zh",
  refreshInFlight: false,
  productsSignature: ""
};

const $ = (id) => document.getElementById(id);

function tr(key) {
  return messages[state.language]?.[key] || messages.zh[key] || key;
}

function applyLanguage() {
  if (!messages[state.language]) state.language = "zh";
  document.documentElement.lang = state.language === "zh" ? "zh-CN" : "en";
  document.title = tr("appTitle");
  document.querySelectorAll("[data-i18n]").forEach((node) => {
    node.textContent = tr(node.dataset.i18n);
  });
  document.querySelectorAll("[data-i18n-label]").forEach((node) => {
    const select = node.querySelector("select");
    const input = node.querySelector("input");
    const control = select || input;
    node.childNodes[0].nodeValue = tr(node.dataset.i18nLabel);
    if (control && !node.contains(control)) node.appendChild(control);
  });
  const toggle = $("langToggleBtn");
  if (toggle) toggle.textContent = state.language === "zh" ? "EN" : "中文";
  updateFilePickers();
  renderOverview();
  renderProducts();
  renderPostprocessResult();
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options
  });
  const payload = await response.json();
  if (response.status === 401 && path !== "/api/login" && path !== "/api/session") {
    state.user = null;
    showLogin();
  }
  if (!response.ok || payload.ok === false) throw new Error(payload.error || response.statusText);
  return payload;
}

function canAdmin() {
  return Boolean(state.user?.permissions?.admin || state.user?.role === "admin");
}

function fmtTime(value) {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toLocaleString();
}

function fmtDateTimeLocal(value) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  const offsetDate = new Date(date.getTime() - date.getTimezoneOffset() * 60000);
  return offsetDate.toISOString().slice(0, 16);
}

function fmtNum(value, digits = 3) {
  const number = Number(value);
  if (!Number.isFinite(number)) return "-";
  return number.toFixed(digits);
}

function fmtAge(seconds) {
  const value = Number(seconds);
  if (!Number.isFinite(value)) return "-";
  if (value < 1) return "<1s";
  if (value < 60) return `${Math.round(value)}s`;
  return `${Math.round(value / 60)}min`;
}

function fmtBytes(value) {
  const bytes = Number(value);
  if (!Number.isFinite(bytes) || bytes <= 0) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let size = bytes;
  let index = 0;
  while (size >= 1024 && index < units.length - 1) {
    size /= 1024;
    index += 1;
  }
  return `${size.toFixed(index === 0 ? 0 : 1)} ${units[index]}`;
}

function selectedRuntime() {
  const stations = (state.status && state.status.stations) || [];
  return stations.find((item) => item.name === state.selected) || null;
}

function selectedConfig() {
  if (state.creatingStation) return null;
  return state.stationConfigs.find((item) => item.name === state.selected) || null;
}

async function refreshAll(options = {}) {
  if (!state.user) return;
  if (state.refreshInFlight) return;
  state.refreshInFlight = true;
  try {
    const background = Boolean(options.background);
    const previousSelected = state.selected;
    const [status, stations] = await Promise.all([api("/api/status"), api("/api/stations")]);
    state.status = status;
    state.stationConfigs = stations.stations || [];
    $("configPath").textContent = status.config_path || "";
    if (!state.creatingStation) {
      const runtimeNames = new Set((status.stations || []).map((item) => item.name));
      if (!state.selected || !runtimeNames.has(state.selected)) {
        const first = (status.stations || [])[0];
        state.selected = first ? first.name : null;
      }
    }
    if (state.selected !== previousSelected) {
      state.products = [];
      state.productRange = { start: "", end: "" };
      state.irConfig = null;
      state.postprocess = null;
      state.productsSignature = "";
    }
    renderStationList();
    renderOverview();
    fillStationFormIfSafe();
    const tasks = [refreshProducts({ force: !background })];
    if (!background || state.activeTab === "logs") tasks.push(refreshLogs());
    if (!background || !state.irConfig) tasks.push(refreshIrConfigIfNeeded());
    await Promise.all(tasks);
    renderPostprocessResult();
    renderOverview();
    drawAllVisuals();
  } finally {
    state.refreshInFlight = false;
  }
}

function renderStationList() {
  const list = $("stationList");
  list.innerHTML = "";
  const stations = (state.status && state.status.stations) || [];
  $("runningCount").textContent = `${state.status?.running_count || 0} / ${state.status?.station_count || 0}`;
  if (!stations.length) {
    list.innerHTML = `<div class="empty">${t.noStation}</div>`;
    return;
  }
  for (const station of stations) {
    const health = station.stream_health || {};
    const latest = latestProductValue(station.latest_product, state.products);
    const card = document.createElement("div");
    card.className = `station-card${station.name === state.selected ? " active" : ""}`;
    card.onclick = () => selectStation(station.name);
    const badgeClass = statusClass(health.label || station.state, station.last_error);
    card.innerHTML = `
      <div>
        <strong>${escapeHtml(station.name)}</strong>
        <span>${escapeHtml(streamLabel(station.obs_settings || station))}</span>
        <small>${escapeHtml(latest)}</small>
      </div>
      <em class="badge ${badgeClass}">${escapeHtml(health.label || station.state || "idle")}</em>
    `;
    list.appendChild(card);
  }
}

async function selectStation(name) {
  state.selected = name;
  state.creatingStation = false;
  state.products = [];
  state.productRange = { start: "", end: "" };
  state.productsSignature = "";
  state.irConfig = null;
  state.postprocess = null;
  state.stationFormDirty = false;
  state.irFormDirty = false;
  renderStationList();
  renderOverview();
  fillStationForm();
  await Promise.all([refreshProducts(), refreshLogs(), loadIrConfig()]);
  renderPostprocessResult();
  drawAllVisuals();
}

function renderOverview() {
  const runtime = selectedRuntime();
  setActionButtonState(runtime);
  $("selectedStationLabel").textContent = state.selected ? `${tr("currentStation")} ${state.selected}` : `${tr("currentStation")} -`;
  if (!runtime) {
    $("headerStateLabel").textContent = tr("idle");
    $("headerStateLabel").className = "header-state warning";
    toggleInitPanel(null);
    renderStationLocation();
    setPostprocessControls();
    if (state.activeTab === "overview") {
      drawProductChart("overviewProductChart");
      drawLspArcChart([]);
    }
    return;
  }
  const health = runtime.stream_health || {};
  const init = runtime.initialization || {};
  const epoch = runtime.epoch_summary || {};
  const latestSea = latestProduct("sea_level");

  setText("stateValue", runtime.state || "-");
  $("selectedStationLabel").textContent = state.selected ? `${tr("currentStation")} ${state.selected}` : `${tr("currentStation")} -`;
  $("headerStateLabel").textContent = health.label || runtime.state || tr("idle");
  $("headerStateLabel").className = `header-state ${statusClass(health.label || runtime.state, runtime.last_error)}`;
  setText("healthValue", `${health.label || "-"} / msg ${fmtAge(health.message_age_seconds)}`);
  setText("seaLevelValue", latestSea ? `${fmtNum(latestSea.value, 3)} ${latestSea.unit || "m"}` : "-");
  setText("seaLevelTime", latestSea ? fmtTime(latestSea.timestamp) : "-");
  $("productCount").textContent = String(state.products.length || runtime.products_emitted || 0);
  $("overviewProductCount").textContent = String(state.products.length || runtime.products_emitted || 0);

  $("streamHealthBadge").textContent = health.label || runtime.state || "-";
  $("streamHealthBadge").className = `badge ${statusClass(health.label || runtime.state, runtime.last_error)}`;
  $("obsStreamInfo").textContent = streamLabel(runtime.obs_settings || runtime);
  $("lastMessageInfo").textContent = fmtTime(runtime.last_message_time);
  $("lastEpochInfo").textContent = fmtTime(runtime.last_epoch_time);
  $("bytesInfo").textContent = fmtBytes(runtime.bytes_received || 0);
  const eph = runtime.ephemeris_stream || {};
  $("ephStreamInfo").textContent = eph.enabled ? `${streamLabel(eph.settings || eph)} / ${eph.state || "-"}` : "disabled";
  $("lastEphMessageInfo").textContent = fmtTime(eph.last_message_time);
  if (eph.enabled && eph.state) {
    $("streamHealthBadge").textContent = `${health.label || runtime.state || "-"} / EPH ${eph.state}`;
  }

  toggleInitPanel(init);
  const progress = Math.max(0, Math.min(1, Number(init.progress || 0)));
  if ($("initProgress")) $("initProgress").style.width = `${Math.round(progress * 100)}%`;
  if ($("initBadge")) $("initBadge").textContent = init.rh_initialized ? "ready" : "LSP";
  if ($("initReason")) $("initReason").textContent = init.rh_initialized
    ? `LSP 初始化完成，初始 RH ${fmtNum(init.rh_initial_m, 3)} m，参与初始化弧段 ${init.rh_initial_arc_count || 0}`
    : (init.waiting_reason || "-");
  if ($("arcCountInfo")) $("arcCountInfo").textContent = String(init.tracked_arc_count || 0);
  if ($("maxLspSamplesInfo")) $("maxLspSamplesInfo").textContent = String(init.max_lsp_samples || 0);
  if ($("requiredSamplesInfo")) $("requiredSamplesInfo").textContent = String(init.required_lsp_samples || 0);
  if ($("initializedArcInfo")) $("initializedArcInfo").textContent = String(init.initialized_arc_count || 0);
  if (state.activeTab === "overview") drawLspArcChart(init.arcs || []);

  const inversionSatelliteCount = epoch.inversion_satellite_count ?? uniqueCount(runtime.record_samples || [], "satellite");
  const inversionArcCount = epoch.inversion_arc_count ?? countRecordArcs(runtime.record_samples || []);
  $("recordCountBadge").textContent = `${epoch.record_count || 0} \u6761\u8bb0\u5f55`;
  $("satCountInfo").textContent = String(epoch.satellite_count || 0);
  $("inversionSatInfo").textContent = String(inversionSatelliteCount || 0);
  $("inversionArcInfo").textContent = String(inversionArcCount || 0);
  $("recordCountInfo").textContent = String(epoch.record_count || 0);

  renderBars(runtime.system_counts || {});
  renderArcTable(init.arcs || []);
  renderSampleTable(runtime.record_samples || []);
  renderStationLocation();
  setPostprocessControls();
  renderError(runtime.last_error || health.last_filter_warning || "");
}

function setActionButtonState(runtime) {
  const start = $("startBtn");
  const stop = $("stopBtn");
  const restart = $("restartBtn");
  if (!start || !stop || !restart) return;
  const selectedExisting = Boolean(state.selected && !state.creatingStation);
  const active = isStationActive(runtime);
  const allowed = canAdmin();
  start.disabled = !allowed || !selectedExisting || active;
  stop.disabled = !allowed || !selectedExisting || !active;
  restart.disabled = !allowed || !selectedExisting || !active;
}

function isStationActive(runtime) {
  if (!runtime) return false;
  const stateName = String(runtime.state || "").toLowerCase();
  return Boolean(runtime.alive) || ["starting", "connecting", "waiting", "running", "reconnecting"].includes(stateName);
}

function toggleInitPanel(init) {
  const panel = $("initPanel");
  if (!panel) return;
  panel.classList.toggle("lsp-ready", Boolean(init && init.rh_initialized));
}

function statusClass(label, hasError = false) {
  const value = String(label || "").toLowerCase();
  if (hasError || value.includes("error") || value.includes("failed") || value.includes("offline") || value.includes("stale")) return "error";
  if (value.includes("warn") || value.includes("waiting") || value.includes("idle")) return "warning";
  if (value.includes("running") || value.includes("healthy") || value.includes("online") || value.includes("ready")) return "running";
  if (value.includes("connecting") || value.includes("processing") || value.includes("reconnecting") || value.includes("lsp")) return "processing";
  return "";
}

function uniqueCount(items, key) {
  return new Set((items || []).map((item) => item && item[key]).filter(Boolean)).size;
}

function countRecordArcs(records) {
  return new Set((records || []).map((item) => [
    item.constellation || "",
    item.satellite || ""
  ].join("|")).filter((value) => value !== "||")).size;
}

function renderBars(counts) {
  const box = $("systemBars");
  box.innerHTML = "";
  const entries = Object.entries(counts);
  const max = Math.max(1, ...entries.map(([, value]) => Number(value) || 0));
  for (const [key, value] of entries) {
    const row = document.createElement("div");
    row.className = "bar-row";
    row.innerHTML = `<span>${escapeHtml(key)}</span><i style="width:${(Number(value) / max) * 100}%"></i><b>${escapeHtml(value)}</b>`;
    box.appendChild(row);
  }
}

function renderArcTable(arcs) {
  $("arcTableBadge").textContent = String(arcs.length);
  const body = $("arcBody");
  body.innerHTML = "";
  for (const arc of arcs.slice(0, 40)) {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${escapeHtml(arc.arc)}</td>
      <td>${escapeHtml(arc.sample_count || 0)}</td>
      <td>${escapeHtml(arc.detrended_sample_count || 0)}</td>
      <td>${escapeHtml(fmtNum(arc.last_elevation_deg, 2))}</td>
      <td>${escapeHtml(arc.signal_count || "")}</td>
    `;
    body.appendChild(tr);
  }
}

function renderSampleTable(samples) {
  const body = $("sampleBody");
  body.innerHTML = "";
  for (const item of samples.slice(0, 60)) {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${escapeHtml(item.satellite)}</td>
      <td>${escapeHtml(item.signal)}</td>
      <td>${escapeHtml(fmtNum(item.snr, 1))}</td>
      <td>${escapeHtml(fmtNum(item.azimuth_deg, 1))}</td>
      <td>${escapeHtml(fmtNum(item.elevation_deg, 1))}</td>
    `;
    body.appendChild(tr);
  }
}

function renderError(message) {
  const box = $("errorBox");
  const pill = $("lastErrorPill");
  if (message) {
    box.textContent = message;
    box.classList.remove("hidden");
    pill.textContent = message;
    pill.classList.remove("hidden");
  } else {
    box.classList.add("hidden");
    pill.classList.add("hidden");
  }
}

function stationGeo() {
  const position = state.irConfig?.station?.receiver_position || {};
  const numeric = (value) => (value === null || value === undefined || value === "" ? NaN : Number(value));
  const lat = numeric(position.latitude_deg);
  const lon = numeric(position.longitude_deg);
  const height = numeric(position.height_m);
  return {
    lat: Number.isFinite(lat) ? lat : null,
    lon: Number.isFinite(lon) ? lon : null,
    height: Number.isFinite(height) ? height : null
  };
}

function renderStationLocation() {
  const geo = stationGeo();
  const hasLatLon = Number.isFinite(geo.lat) && Number.isFinite(geo.lon);
  setText("stationLatInfo", hasLatLon ? `${fmtNum(geo.lat, 6)} deg` : "-");
  setText("stationLonInfo", hasLatLon ? `${fmtNum(geo.lon, 6)} deg` : "-");
  setText("stationHeightInfo", Number.isFinite(geo.height) ? `${fmtNum(geo.height, 3)} m` : "-");
  const badge = $("stationMapBadge");
  if (badge) {
    badge.textContent = hasLatLon ? "OSM" : tr("noCoordinate");
    badge.className = `badge ${hasLatLon ? "running" : "warning"}`;
  }
  drawStationMap(geo);
}

function drawStationMap(geo) {
  const map = $("stationMap");
  if (!map) return;
  const lat = Number(geo?.lat);
  const lon = Number(geo?.lon);
  if (!Number.isFinite(lat) || !Number.isFinite(lon)) {
    map.dataset.key = "";
    map.innerHTML = `<div class="map-empty">${escapeHtml(tr("noCoordinate"))}</div>`;
    return;
  }
  const rect = map.getBoundingClientRect();
  const width = Math.max(320, Math.round(rect.width || map.clientWidth || 420));
  const height = Math.max(210, Math.round(rect.height || map.clientHeight || 260));
  const zoom = Math.abs(lat) > 70 ? 12 : 15;
  const key = `${lat.toFixed(6)},${lon.toFixed(6)},${width}x${height},${zoom}`;
  if (map.dataset.key === key && map.children.length) return;
  map.dataset.key = key;
  map.textContent = "";

  const center = latLonToWorld(lat, lon, zoom);
  const topLeft = { x: center.x - width / 2, y: center.y - height / 2 };
  const startX = Math.floor(topLeft.x / 256);
  const endX = Math.floor((topLeft.x + width) / 256);
  const startY = Math.floor(topLeft.y / 256);
  const endY = Math.floor((topLeft.y + height) / 256);
  const maxTile = 2 ** zoom;
  for (let x = startX; x <= endX; x += 1) {
    for (let y = startY; y <= endY; y += 1) {
      if (y < 0 || y >= maxTile) continue;
      const img = document.createElement("img");
      const wrappedX = ((x % maxTile) + maxTile) % maxTile;
      img.className = "map-tile";
      img.alt = "";
      img.draggable = false;
      img.loading = "lazy";
      img.src = `https://tile.openstreetmap.org/${zoom}/${wrappedX}/${y}.png`;
      img.style.left = `${Math.round(x * 256 - topLeft.x)}px`;
      img.style.top = `${Math.round(y * 256 - topLeft.y)}px`;
      map.appendChild(img);
    }
  }

  const marker = document.createElement("div");
  marker.className = "station-marker";
  marker.innerHTML = `<strong>${escapeHtml(state.selected || "Station")}</strong><span>${fmtNum(lat, 5)}, ${fmtNum(lon, 5)}</span>`;
  map.appendChild(marker);
  const scale = mapScale(lat, zoom);
  const scaleNode = document.createElement("div");
  scaleNode.className = "map-scale";
  scaleNode.innerHTML = `<span>${escapeHtml(scale.label)}</span><i style="width:${scale.pixels}px"></i>`;
  map.appendChild(scaleNode);
  const attribution = document.createElement("a");
  attribution.className = "map-attribution";
  attribution.href = "https://www.openstreetmap.org/copyright";
  attribution.target = "_blank";
  attribution.rel = "noreferrer";
  attribution.textContent = "OpenStreetMap";
  map.appendChild(attribution);
}

function mapScale(lat, zoom) {
  const metersPerPixel = 156543.03392 * Math.cos(Number(lat) * Math.PI / 180) / (2 ** zoom);
  const targetMeters = metersPerPixel * 92;
  const niceMeters = niceDistance(targetMeters);
  return {
    pixels: Math.max(42, Math.round(niceMeters / metersPerPixel)),
    label: niceMeters >= 1000 ? `${fmtNum(niceMeters / 1000, niceMeters >= 10000 ? 0 : 1)} km` : `${Math.round(niceMeters)} m`
  };
}

function niceDistance(value) {
  const steps = [1, 2, 5];
  const exponent = Math.floor(Math.log10(Math.max(1, value)));
  const base = 10 ** exponent;
  for (const step of steps) {
    const candidate = step * base;
    if (candidate >= value) return candidate;
  }
  return 10 * base;
}

function latLonToWorld(lat, lon, zoom) {
  const scale = 256 * (2 ** zoom);
  const clampedLat = Math.max(-85.05112878, Math.min(85.05112878, Number(lat)));
  const sinLat = Math.sin(clampedLat * Math.PI / 180);
  return {
    x: ((Number(lon) + 180) / 360) * scale,
    y: (0.5 - Math.log((1 + sinLat) / (1 - sinLat)) / (4 * Math.PI)) * scale
  };
}

async function refreshProducts(options = {}) {
  if (!state.selected) {
    state.products = [];
    state.productsSignature = "";
    renderProducts();
    return;
  }
  const signature = productRefreshSignature();
  if (!options.force && state.productsSignature === signature) return;
  const needsAll = Boolean(state.productRange.start || state.productRange.end || state.activeTab === "products");
  const params = new URLSearchParams({ limit: needsAll ? "all" : "600" });
  if (state.productRange.start) params.set("start", new Date(state.productRange.start).toISOString());
  if (state.productRange.end) params.set("end", new Date(state.productRange.end).toISOString());
  const payload = await api(`/api/stations/${encodeURIComponent(state.selected)}/products?${params.toString()}`);
  state.products = payload.products || [];
  state.productsSignature = signature;
  syncProductRangeInputs();
  renderProducts();
}

function productRefreshSignature() {
  const runtime = selectedRuntime() || {};
  return [
    state.selected || "",
    runtime.products_emitted || 0,
    runtime.last_product_time || "",
    state.productRange.start || "",
    state.productRange.end || "",
    state.activeTab === "products" ? "all" : "recent"
  ].join("|");
}

async function refreshLogs() {
  if (!state.selected) return;
  const payload = await api(`/api/logs?limit=240&source=${encodeURIComponent(state.selected)}`);
  $("logBox").textContent = (payload.lines || [])
    .map((line) => `[${fmtTime(line.time)}] ${line.source}: ${line.message}`)
    .join("\n");
}

async function refreshIrConfigIfNeeded() {
  if (!state.selected || state.irConfig || state.irFormDirty) return;
  await loadIrConfig();
}

async function loadIrConfig() {
  if (!state.selected) return;
  const payload = await api(`/api/stations/${encodeURIComponent(state.selected)}/reflectometry-config`);
  state.irConfig = payload.raw || {};
  $("irConfigPath").textContent = payload.path || "IR YAML";
  $("yamlEditor").value = payload.yaml_text || objectToYaml(state.irConfig);
  fillIrForm();
  renderStationLocation();
}

function fillStationFormIfSafe() {
  if (state.activeTab === "config" && state.stationFormDirty) return;
  fillStationForm();
}

function fillStationForm() {
  const form = $("stationForm");
  const config = selectedConfig();
  if (!form) return;
  setAdminControls();
  if (!config) {
    form.reset();
    form.elements.enabled.checked = true;
    form.elements.obs_port.value = 2101;
    form.elements.obs_connect_timeout_seconds.value = 15;
    form.elements.obs_reconnect_delay_seconds.value = 5;
    form.elements.eph_port.value = 2101;
    form.elements.eph_connect_timeout_seconds.value = 15;
    form.elements.eph_reconnect_delay_seconds.value = 5;
    form.elements.max_product_history.value = 1000;
    $("deleteStationBtn").disabled = true;
    return;
  }
  const obs = config.obs_settings || config.ntrip || {};
  const eph = config.eph_settings || config.ephemeris_ntrip || {};
  const runtime = config.runtime || {};
  form.elements.name.value = config.name || "";
  form.elements.reflectometry_config.value = config.reflectometry_config || "";
  form.elements.obs_host.value = obs.host || "";
  form.elements.obs_port.value = obs.port || 2101;
  form.elements.obs_mountpoint.value = obs.mountpoint || "";
  form.elements.obs_user.value = obs.user || "";
  form.elements.obs_password.value = obs.password || "";
  form.elements.obs_connect_timeout_seconds.value = obs.connect_timeout_seconds || 15;
  form.elements.obs_reconnect_delay_seconds.value = obs.reconnect_delay_seconds || 5;
  form.elements.eph_enabled.checked = Boolean(eph.enabled || eph.mountpoint);
  form.elements.eph_mountpoint.value = eph.mountpoint || "";
  form.elements.eph_host.value = eph.host || "";
  form.elements.eph_port.value = eph.port || 2101;
  form.elements.eph_user.value = eph.user || "";
  form.elements.eph_password.value = eph.password || "";
  form.elements.eph_connect_timeout_seconds.value = eph.connect_timeout_seconds || obs.connect_timeout_seconds || 15;
  form.elements.eph_reconnect_delay_seconds.value = eph.reconnect_delay_seconds || obs.reconnect_delay_seconds || 5;
  form.elements.max_product_history.value = runtime.max_product_history || 1000;
  form.elements.enabled.checked = Boolean(config.enabled);
  form.elements.auto_start.checked = Boolean(runtime.auto_start);
  $("deleteStationBtn").disabled = !canAdmin();
}

function readStationForm() {
  const form = $("stationForm");
  return {
    name: form.elements.name.value.trim(),
    enabled: form.elements.enabled.checked,
    reflectometry_config: form.elements.reflectometry_config.value.trim(),
    obs_settings: {
      source_type: "NTRIP Server",
      enabled: true,
      host: form.elements.obs_host.value.trim(),
      port: Number(form.elements.obs_port.value || 2101),
      mountpoint: form.elements.obs_mountpoint.value.trim(),
      user: form.elements.obs_user.value,
      password: form.elements.obs_password.value,
      connect_timeout_seconds: Number(form.elements.obs_connect_timeout_seconds.value || 15),
      reconnect_delay_seconds: Number(form.elements.obs_reconnect_delay_seconds.value || 5)
    },
    eph_settings: {
      source_type: "NTRIP Server",
      enabled: form.elements.eph_enabled.checked,
      host: form.elements.eph_host.value.trim(),
      port: Number(form.elements.eph_port.value || 2101),
      mountpoint: form.elements.eph_mountpoint.value.trim(),
      user: form.elements.eph_user.value,
      password: form.elements.eph_password.value,
      connect_timeout_seconds: Number(form.elements.eph_connect_timeout_seconds.value || 15),
      reconnect_delay_seconds: Number(form.elements.eph_reconnect_delay_seconds.value || 5)
    },
    runtime: {
      auto_start: form.elements.auto_start.checked,
      max_product_history: Number(form.elements.max_product_history.value || 1000)
    }
  };
}

function fillIrForm() {
  const form = $("irForm");
  const raw = state.irConfig || {};
  if (!form) return;
  form.elements.station_id.value = raw.station?.station_id || "";
  form.elements.exclude_constellations.value = listToText(raw.input?.exclude_constellations);
  form.elements.exclude_signals.value = listToText(raw.input?.exclude_signals);
  const zone = (raw.geometry?.reflection_zones || [])[0] || {};
  form.elements.min_elevation_deg.value = raw.processing?.min_elevation_deg ?? zone.min_elevation_deg ?? "";
  form.elements.max_elevation_deg.value = raw.processing?.max_elevation_deg ?? zone.max_elevation_deg ?? "";
  form.elements.min_reflector_height.value = raw.ir?.min_reflector_height ?? "";
  form.elements.max_reflector_height.value = raw.ir?.max_reflector_height ?? "";
  form.elements.sea_level_reference.value = raw.products?.sea_level_reference ?? "";
  const ekf = raw.ir?.ekf || {};
  form.elements.q_rh.value = ekf.q_rh ?? "";
  form.elements.measurement_variance.value = ekf.measurement_variance ?? "";
  form.elements.initial_rh_m.value = ekf.initial_rh_m ?? "";
  form.elements.rh_init_min_samples.value = ekf.rh_init_min_samples ?? "";
  form.elements.init_min_samples.value = ekf.init_min_samples ?? "";
  form.elements.rh_init_max_arcs.value = ekf.rh_init_max_arcs ?? "";
  form.elements.output_interval_seconds.value = ekf.output_interval_seconds ?? "";
  form.elements.output_window_seconds.value = ekf.output_window_seconds ?? "";
  form.elements.max_time_gap_seconds.value = ekf.max_time_gap_seconds ?? "";
}

function applyIrFormToRaw() {
  const form = $("irForm");
  const raw = deepClone(state.irConfig || {});
  raw.station ||= {};
  raw.input ||= {};
  raw.processing ||= {};
  raw.ir ||= {};
  raw.ir.ekf ||= {};
  raw.products ||= {};
  raw.geometry ||= {};
  raw.geometry.reflection_zones ||= [];
  raw.station.station_id = form.elements.station_id.value.trim();
  raw.input.constellations = [];
  raw.input.signals = [];
  raw.input.exclude_constellations = textToList(form.elements.exclude_constellations.value);
  raw.input.exclude_signals = textToList(form.elements.exclude_signals.value);
  raw.processing.min_elevation_deg = numberOrNull(form.elements.min_elevation_deg.value);
  raw.processing.max_elevation_deg = numberOrNull(form.elements.max_elevation_deg.value);
  raw.ir.min_reflector_height = numberOrNull(form.elements.min_reflector_height.value);
  raw.ir.max_reflector_height = numberOrNull(form.elements.max_reflector_height.value);
  raw.ir.estimation_mode = "ekf";
  raw.products.sea_level_reference = numberOrNull(form.elements.sea_level_reference.value);
  raw.ir.ekf.q_rh = numberOrNull(form.elements.q_rh.value);
  raw.ir.ekf.measurement_variance = numberOrNull(form.elements.measurement_variance.value);
  raw.ir.ekf.initial_rh_m = numberOrNull(form.elements.initial_rh_m.value);
  raw.ir.ekf.rh_init_min_samples = integerOrNull(form.elements.rh_init_min_samples.value);
  raw.ir.ekf.init_min_samples = integerOrNull(form.elements.init_min_samples.value);
  raw.ir.ekf.rh_init_max_arcs = integerOrNull(form.elements.rh_init_max_arcs.value);
  raw.ir.ekf.output_interval_seconds = integerOrNull(form.elements.output_interval_seconds.value);
  raw.ir.ekf.output_window_seconds = integerOrNull(form.elements.output_window_seconds.value);
  raw.ir.ekf.max_time_gap_seconds = numberOrNull(form.elements.max_time_gap_seconds.value);
  for (const zone of raw.geometry.reflection_zones) {
    zone.min_elevation_deg = raw.processing.min_elevation_deg;
    zone.max_elevation_deg = raw.processing.max_elevation_deg;
  }
  state.irConfig = raw;
  $("yamlEditor").value = objectToYaml(raw);
  return raw;
}

function renderProducts() {
  const body = $("productsBody");
  body.innerHTML = "";
  updateProductTypeFilter();
  const rows = filteredProducts();
  $("productCount").textContent = String(rows.length);
  updateProductRangeMeta(rows);
  updateProductSummary(rows);
  for (const product of rows.slice().reverse().slice(0, 600)) {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${escapeHtml(fmtTime(product.timestamp))}</td>
      <td>${escapeHtml(product.product_type || "")}</td>
      <td>${escapeHtml(fmtNum(product.value, 4))}</td>
      <td>${escapeHtml(product.unit || "")}</td>
      <td>${escapeHtml(productArcCount(product))}</td>
      <td>${escapeHtml(fmtNum(product.confidence, 3))}</td>
    `;
    body.appendChild(tr);
  }
  if (state.activeTab === "overview") {
    drawProductChart("overviewProductChart");
  } else if (state.activeTab === "products") {
    drawProductChart("productChart");
    drawProductDiagnostics(rows);
    drawProductDistribution(rows);
  }
}

async function submitPostprocess(event) {
  event.preventDefault();
  if (!canAdmin()) return showTransientError(tr("viewerOnly"));
  if (!state.selected || state.creatingStation) return showTransientError(tr("chooseStation"));
  const form = $("postprocessForm");
  const obsFile = form.elements.observation_file.files[0];
  const ephFile = form.elements.ephemeris_file.files[0];
  if (!obsFile || !ephFile) return showTransientError(tr("choosePostFiles"));

  const body = new FormData(form);
  state.postprocessRunning = true;
  setPostprocessControls();
  setText("postprocessStatus", tr("runningPostProcess"));
  $("postprocessBadge").textContent = "running";
  $("postprocessBadge").className = "badge processing";
  try {
    const response = await fetch(`/api/stations/${encodeURIComponent(state.selected)}/postprocess`, {
      method: "POST",
      body
    });
    let payload = {};
    try {
      payload = await response.json();
    } catch (_error) {
      payload = {};
    }
    if (response.status === 401) {
      state.user = null;
      showLogin();
    }
    if (!response.ok || payload.ok === false) {
      throw new Error(payload.error || response.statusText || "Post process failed");
    }
    state.postprocess = payload;
    renderPostprocessResult();
    await refreshLogs().catch(() => null);
  } catch (error) {
    setText("postprocessStatus", error.message || "Post process failed");
    $("postprocessBadge").textContent = "error";
    $("postprocessBadge").className = "badge error";
    showTransientError(error.message || "Post process failed");
  } finally {
    state.postprocessRunning = false;
    setPostprocessControls();
  }
}

function renderPostprocessResult() {
  const payload = state.postprocess;
  const products = payload?.products || [];
  if (!payload && state.postprocessRunning) {
    setPostprocessControls();
    if (state.activeTab === "postprocess") drawPostprocessChart();
    return;
  }
  setText("postProductCountBadge", String(products.length));
  setText("postEpochCount", payload ? String(payload.epoch_count || 0) : "-");
  setText("postObservationCount", payload ? String(payload.observation_count || 0) : "-");
  setText("postProductCount", payload ? String(payload.product_count || products.length || 0) : "-");
  setText("postOutputDir", payload?.output_dir || "-");
  setText("postJobId", payload?.job_id || "-");
  setText("postArcCount", payload ? `${payload.arc_solution_count || 0} arcs` : "-");
  setText(
    "postRinexMeta",
    payload ? `RINEX ${payload.rinex_version || "-"} / ${payload.rinex_time_system || "-"}` : "-"
  );
  setText("postPositionMeta", payload ? (payload.used_rinex_position ? tr("rinexPosition") : tr("configPosition")) : "-");
  if (payload) {
    setText("postprocessStatus", `${tr("completed")} ${payload.job_id || ""}`.trim());
    $("postprocessBadge").textContent = tr("done");
    $("postprocessBadge").className = "badge running";
  } else {
    setText("postprocessStatus", "-");
    $("postprocessBadge").textContent = tr("ready");
    $("postprocessBadge").className = "badge";
  }

  const body = $("postprocessProductsBody");
  if (body) {
    body.innerHTML = "";
    for (const product of products.slice().reverse().slice(0, 300)) {
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td>${escapeHtml(fmtTime(product.timestamp))}</td>
        <td>${escapeHtml(product.product_type || "")}</td>
        <td>${escapeHtml(fmtNum(product.value, 4))}</td>
        <td>${escapeHtml(product.unit || "")}</td>
        <td>${escapeHtml(productArcCount(product))}</td>
        <td>${escapeHtml(fmtNum(product.confidence, 3))}</td>
      `;
      body.appendChild(tr);
    }
  }
  setPostprocessControls();
  if (state.activeTab === "postprocess") drawPostprocessChart();
}

function primaryPostprocessSeries(products) {
  const rows = products || [];
  const sea = rows.filter((item) => item.product_type === "sea_level");
  const dynamicSea = rows.filter((item) => item.product_type === "sea_level_dynamic_corrected");
  const rh = rows.filter((item) => item.product_type === "reflector_height");
  return sea.length ? sea : (dynamicSea.length ? dynamicSea : rh);
}

function drawPostprocessChart() {
  const canvas = $("postprocessChart");
  if (!canvas) return;
  const rect = canvas.getBoundingClientRect();
  const ratio = window.devicePixelRatio || 1;
  canvas.width = Math.max(480, Math.floor(rect.width * ratio));
  canvas.height = Math.floor(260 * ratio);
  const ctx = canvas.getContext("2d");
  ctx.scale(ratio, ratio);
  const width = canvas.width / ratio;
  const height = canvas.height / ratio;
  clearCanvas(ctx, width, height);
  const series = normalizeChartSeries(primaryPostprocessSeries(state.postprocess?.products || []));
  if (series.length < 2) return drawCanvasMessage(ctx, tr("postProcessWaiting"));
  drawLineSeries(ctx, width, height, series, series[0]?.unit || "m", series[0]?.product_type || "", "postprocessChart");
}

function setPostprocessControls() {
  const form = $("postprocessForm");
  if (!form) return;
  const allowed = canAdmin() && Boolean(state.selected) && !state.creatingStation;
  const disabled = !allowed || state.postprocessRunning;
  for (const element of form.elements) {
    element.disabled = disabled;
  }
  const button = $("runPostprocessBtn");
  if (button) {
    button.disabled = disabled;
    button.textContent = state.postprocessRunning ? tr("runningPostProcess") : tr("runPostProcess");
  }
}

function updateFilePickers() {
  const form = $("postprocessForm");
  if (!form) return;
  const obsFile = form.elements.observation_file?.files?.[0];
  const ephFile = form.elements.ephemeris_file?.files?.[0];
  setText("obsFileName", obsFile ? `${obsFile.name} / ${fmtBytes(obsFile.size)}` : tr("noFileSelected"));
  setText("ephFileName", ephFile ? `${ephFile.name} / ${fmtBytes(ephFile.size)}` : tr("noFileSelected"));
}

function drawAllVisuals() {
  renderStationLocation();
  if (state.activeTab === "overview") {
    drawProductChart("overviewProductChart");
    drawLspArcChart(selectedRuntime()?.initialization?.arcs || []);
  } else if (state.activeTab === "products") {
    drawProductChart("productChart");
    drawProductDiagnostics(filteredProducts());
    drawProductDistribution(filteredProducts());
  } else if (state.activeTab === "space") {
    drawSpacePlot();
  } else if (state.activeTab === "postprocess") {
    drawPostprocessChart();
  }
}

function productArcCount(product) {
  return product?.metadata?.active_satellite_arc_count
    ?? product?.metadata?.active_arc_count
    ?? product?.source_arc_count
    ?? "";
}

function updateProductRangeMeta(rows) {
  const meta = $("productRangeMeta");
  if (!meta) return;
  if (!state.products.length) {
    meta.textContent = "\u65e0\u5386\u53f2\u7ed3\u679c";
    return;
  }
  const allTimes = state.products
    .map((item) => new Date(item.timestamp).getTime())
    .filter(Number.isFinite)
    .sort((a, b) => a - b);
  if (!allTimes.length) {
    meta.textContent = `${rows.length} \u6761\u7ed3\u679c`;
    return;
  }
  meta.textContent = `${rows.length} \u6761\u7ed3\u679c / ${fmtTime(allTimes[0])} - ${fmtTime(allTimes[allTimes.length - 1])}`;
}

function syncProductRangeInputs() {
  const start = $("productStartTime");
  const end = $("productEndTime");
  if (start && document.activeElement !== start) start.value = state.productRange.start || "";
  if (end && document.activeElement !== end) end.value = state.productRange.end || "";
}

function updateProductSummary(rows) {
  const series = normalizeChartSeries(primaryProductSeries(rows));
  const latest = series[series.length - 1];
  const values = series.map((item) => item._value);
  const arcs = series.map((item) => Number(productArcCount(item))).filter(Number.isFinite);
  const confidences = series.map((item) => Number(item.confidence)).filter(Number.isFinite);
  setText("productLatestMetric", latest ? `${fmtNum(latest.value, 4)} ${latest.unit || ""}` : "-");
  setText("productLatestTime", latest ? fmtTime(latest.timestamp) : "-");
  if (values.length) {
    const min = Math.min(...values);
    const max = Math.max(...values);
    const delta = latest ? latest._value - series[0]._value : 0;
    setText("productRangeMetric", `${fmtNum(min, 3)} - ${fmtNum(max, 3)}`);
    setText("productDeltaMetric", `Δ ${fmtNum(delta, 4)}`);
  } else {
    setText("productRangeMetric", "-");
    setText("productDeltaMetric", "-");
  }
  if (confidences.length) {
    const avg = confidences.reduce((sum, value) => sum + value, 0) / confidences.length;
    setText("productConfidenceMetric", fmtNum(avg, 3));
    setText("productConfidenceMinMetric", `min ${fmtNum(Math.min(...confidences), 3)}`);
  } else {
    setText("productConfidenceMetric", "-");
    setText("productConfidenceMinMetric", "-");
  }
  if (arcs.length) {
    const avg = arcs.reduce((sum, value) => sum + value, 0) / arcs.length;
    setText("productArcMetric", fmtNum(avg, 1));
    setText("productArcMaxMetric", `max ${Math.max(...arcs)}`);
  } else {
    setText("productArcMetric", "-");
    setText("productArcMaxMetric", "-");
  }
}

function setText(id, value) {
  const node = $(id);
  if (node) node.textContent = value;
}

function primaryProductSeries(products) {
  const rows = products || [];
  if (state.productTypeFilter) return rows;
  const sea = rows.filter((item) => item.product_type === "sea_level");
  const rh = rows.filter((item) => item.product_type === "reflector_height");
  return sea.length ? sea : rh;
}

function drawProductChart(canvasId = "productChart") {
  const canvas = $(canvasId);
  if (!canvas) return;
  const rect = canvas.getBoundingClientRect();
  const ratio = window.devicePixelRatio || 1;
  canvas.width = Math.max(480, Math.floor(rect.width * ratio));
  canvas.height = Math.floor(260 * ratio);
  const ctx = canvas.getContext("2d");
  ctx.scale(ratio, ratio);
  const width = canvas.width / ratio;
  const height = canvas.height / ratio;
  clearCanvas(ctx, width, height);
  const products = filteredProducts();
  const series = normalizeChartSeries(primaryProductSeries(products));
  if (series.length < 2) return drawCanvasMessage(ctx, t.waitingResult);
  drawLineSeries(ctx, width, height, series, series[0]?.unit || "m", state.productTypeFilter || series[0]?.product_type || "", canvasId);
}

function drawSpacePlot() {
  const canvas = $("spaceCanvas");
  if (!canvas) return;
  const runtime = selectedRuntime();
  const sats = runtime?.skyplot || [];
  const zones = runtime?.reflection_zones || [];
  $("spacePlotBadge").textContent = `${sats.length} sat / ${zones.length} zone`;
  const ctx = setupCanvas(canvas, 520);
  const width = canvas.width / (window.devicePixelRatio || 1);
  const height = canvas.height / (window.devicePixelRatio || 1);
  clearCanvas(ctx, width, height);
  const cx = width / 2;
  const cy = height / 2;
  const radius = Math.min(width, height) * 0.42;
  zones.forEach((zone, index) => {
    ctx.fillStyle = index % 2 ? "rgba(47, 95, 143, 0.13)" : "rgba(31, 122, 109, 0.13)";
    for (const window of zone.azimuth_windows || []) {
      drawAzimuthElevationZone(
        ctx,
        cx,
        cy,
        radius,
        window[0],
        window[1],
        zone.min_elevation_deg,
        zone.max_elevation_deg
      );
    }
  });
  ctx.strokeStyle = "#cbd5dc";
  ctx.lineWidth = 1;
  for (const ring of [0.25, 0.5, 0.75, 1]) {
    ctx.beginPath();
    ctx.arc(cx, cy, radius * ring, 0, Math.PI * 2);
    ctx.stroke();
  }
  for (let az = 0; az < 360; az += 45) {
    const p = polarToCanvas(cx, cy, radius, az, 0);
    ctx.beginPath();
    ctx.moveTo(cx, cy);
    ctx.lineTo(p.x, p.y);
    ctx.stroke();
  }
  for (const sat of sats) {
    const p = polarToCanvas(cx, cy, radius, sat.azimuth_deg, sat.elevation_deg);
    ctx.fillStyle = systemColor(sat.system);
    ctx.beginPath();
    ctx.arc(p.x, p.y, 4 + Math.min(4, Number(sat.signal_count || 0)), 0, Math.PI * 2);
    ctx.fill();
    ctx.fillStyle = "#2f3942";
    ctx.font = "11px Segoe UI, Arial";
    ctx.fillText(sat.satellite, p.x + 7, p.y + 4);
  }
  ctx.fillStyle = "#2f3942";
  ctx.font = "12px Segoe UI, Arial";
  ctx.fillText("N", cx - 4, cy - radius - 10);
  zones.forEach((zone, index) => ctx.fillText(`${zone.name}: ${zone.min_elevation_deg}-${zone.max_elevation_deg} deg`, 14, 22 + index * 18));
  if (!sats.length && !zones.length) drawCanvasMessage(ctx, "No skyplot/reflection-zone data");
}

function drawLspArcChart(arcs) {
  const canvas = $("lspArcCanvas");
  if (!canvas) return;
  const ctx = setupCanvas(canvas, 150);
  const width = canvas.width / (window.devicePixelRatio || 1);
  const height = canvas.height / (window.devicePixelRatio || 1);
  clearCanvas(ctx, width, height);
  const rows = (arcs || [])
    .slice(0, 18)
    .map((arc) => ({
      label: arc.satellite || arc.arc || "-",
      samples: Number(arc.sample_count || 0),
      lsp: Number(arc.detrended_sample_count || 0),
      ready: Boolean(arc.initialized)
    }));
  if (!rows.length) return drawCanvasMessage(ctx, "Waiting for tracked arcs");
  const left = 42;
  const right = 12;
  const top = 22;
  const bottom = 24;
  const plotWidth = width - left - right;
  const max = Math.max(1, ...rows.map((item) => Math.max(item.samples, item.lsp)));
  const barGap = 4;
  const barHeight = Math.max(4, (height - top - bottom - rows.length * barGap) / rows.length);
  ctx.font = "10px Segoe UI, Arial";
  rows.forEach((row, index) => {
    const y = top + index * (barHeight + barGap);
    ctx.fillStyle = "#5f6972";
    ctx.fillText(row.label, 8, y + barHeight - 1);
    ctx.fillStyle = "#e5ebef";
    ctx.fillRect(left, y, plotWidth, barHeight);
    ctx.fillStyle = row.ready ? "#3f7c5f" : "#557da4";
    ctx.fillRect(left, y, (row.lsp / max) * plotWidth, barHeight);
    ctx.fillStyle = "rgba(47, 95, 143, 0.28)";
    ctx.fillRect(left, y + barHeight * 0.58, (row.samples / max) * plotWidth, Math.max(2, barHeight * 0.35));
  });
  ctx.fillStyle = "#5f6972";
  ctx.fillText(`max ${max}`, left, height - 8);
}

function drawProductDiagnostics(rows) {
  const canvas = $("productDiagnosticsChart");
  if (!canvas) return;
  const ctx = setupCanvas(canvas, 190);
  const width = canvas.width / (window.devicePixelRatio || 1);
  const height = canvas.height / (window.devicePixelRatio || 1);
  clearCanvas(ctx, width, height);
  const series = normalizeChartSeries(primaryProductSeries(rows)).filter((item) => Number.isFinite(Number(item.confidence)));
  if (series.length < 2) return drawCanvasMessage(ctx, "Waiting for diagnostics");
  const arcs = series.map((item) => Number(productArcCount(item))).filter(Number.isFinite);
  const maxArc = Math.max(1, ...arcs);
  const pad = { left: 42, right: 16, top: 18, bottom: 32 };
  const plot = { left: pad.left, right: width - pad.right, top: pad.top, bottom: height - pad.bottom };
  const timeStart = series[0]._time;
  const timeSpan = Math.max(series[series.length - 1]._time - timeStart, 1);
  const xFor = (time) => plot.left + ((time - timeStart) / timeSpan) * (plot.right - plot.left);
  const yConf = (value) => plot.bottom - Math.max(0, Math.min(1, Number(value))) * (plot.bottom - plot.top);
  const yArc = (value) => plot.bottom - (Number(value || 0) / maxArc) * (plot.bottom - plot.top);
  drawMiniGrid(ctx, plot);
  drawMiniSeries(ctx, series.map((item) => ({ x: xFor(item._time), y: yConf(item.confidence) })), "#3f7c5f");
  drawMiniSeries(ctx, series.map((item) => ({ x: xFor(item._time), y: yArc(productArcCount(item)) })), "#2f5f8f");
  ctx.fillStyle = "#5f6972";
  ctx.font = "11px Segoe UI, Arial";
  ctx.fillText("confidence", plot.left, 12);
  ctx.fillText(`arcs max ${maxArc}`, plot.right - 72, 12);
}

function drawProductDistribution(rows) {
  const canvas = $("productDistributionChart");
  if (!canvas) return;
  const ctx = setupCanvas(canvas, 190);
  const width = canvas.width / (window.devicePixelRatio || 1);
  const height = canvas.height / (window.devicePixelRatio || 1);
  clearCanvas(ctx, width, height);
  const values = normalizeChartSeries(primaryProductSeries(rows)).map((item) => item._value);
  if (values.length < 3) return drawCanvasMessage(ctx, "Waiting for distribution");
  const min = Math.min(...values);
  const max = Math.max(...values);
  const bins = 12;
  const counts = Array.from({ length: bins }, () => 0);
  const span = Math.max(max - min, 0.001);
  values.forEach((value) => {
    const index = Math.min(bins - 1, Math.max(0, Math.floor(((value - min) / span) * bins)));
    counts[index] += 1;
  });
  const pad = { left: 34, right: 14, top: 18, bottom: 32 };
  const plotWidth = width - pad.left - pad.right;
  const plotHeight = height - pad.top - pad.bottom;
  const maxCount = Math.max(1, ...counts);
  const barWidth = plotWidth / bins;
  counts.forEach((count, index) => {
    const barHeight = (count / maxCount) * plotHeight;
    const x = pad.left + index * barWidth + 2;
    const y = pad.top + plotHeight - barHeight;
    ctx.fillStyle = "#6b8aa7";
    ctx.fillRect(x, y, Math.max(2, barWidth - 4), barHeight);
  });
  ctx.fillStyle = "#5f6972";
  ctx.font = "11px Segoe UI, Arial";
  ctx.fillText(fmtNum(min, 3), pad.left, height - 14);
  const maxText = fmtNum(max, 3);
  ctx.fillText(maxText, width - pad.right - ctx.measureText(maxText).width, height - 14);
}

function drawMiniGrid(ctx, plot) {
  ctx.strokeStyle = "#e6ebef";
  ctx.lineWidth = 1;
  for (let index = 0; index <= 3; index += 1) {
    const y = plot.top + (index / 3) * (plot.bottom - plot.top);
    ctx.beginPath();
    ctx.moveTo(plot.left, y);
    ctx.lineTo(plot.right, y);
    ctx.stroke();
  }
}

function drawMiniSeries(ctx, points, color) {
  if (!points.length) return;
  ctx.strokeStyle = color;
  ctx.lineWidth = 2;
  ctx.beginPath();
  points.forEach((point, index) => {
    if (index === 0) ctx.moveTo(point.x, point.y);
    else ctx.lineTo(point.x, point.y);
  });
  ctx.stroke();
}

function bindEvents() {
  $("loginForm").onsubmit = async (event) => {
    event.preventDefault();
    await login();
  };
  $("logoutBtn").onclick = async () => {
    await api("/api/logout", { method: "POST" }).catch(() => null);
    state.user = null;
    state.status = null;
    state.stationConfigs = [];
    state.products = [];
    state.postprocess = null;
    showLogin();
  };
  $("langToggleBtn").onclick = () => {
    state.language = state.language === "zh" ? "en" : "zh";
    localStorage.setItem("rtgsLanguage", state.language);
    applyLanguage();
  };
  $("reloadBtn").onclick = async () => {
    if (!canAdmin()) return showTransientError(tr("viewerOnly"));
    state.irConfig = null;
    await api("/api/reload", { method: "POST" });
    await refreshAll();
  };
  $("newStationBtn").onclick = () => {
    if (!canAdmin()) return showTransientError(tr("viewerOnly"));
    state.selected = null;
    state.creatingStation = true;
    state.products = [];
    state.productsSignature = "";
    state.irConfig = null;
    state.postprocess = null;
    state.stationFormDirty = false;
    state.irFormDirty = false;
    renderStationList();
    renderOverview();
    renderProducts();
    renderPostprocessResult();
    fillStationForm();
    switchTab("config");
  };
  $("startBtn").onclick = async () => {
    if (!canAdmin()) return showTransientError(tr("viewerOnly"));
    if (!state.selected) return;
    await api(`/api/stations/${encodeURIComponent(state.selected)}/start`, { method: "POST" });
    await refreshAll();
  };
  $("stopBtn").onclick = async () => {
    if (!canAdmin()) return showTransientError(tr("viewerOnly"));
    if (!state.selected) return;
    const ok = await confirmAction(`${tr("stop")} ${tr("currentStation")} ${state.selected}?`);
    if (!ok) return;
    await api(`/api/stations/${encodeURIComponent(state.selected)}/stop`, { method: "POST" });
    await refreshAll();
  };
  $("restartBtn").onclick = async () => {
    if (!canAdmin()) return showTransientError(tr("viewerOnly"));
    if (!state.selected) return;
    const ok = await confirmAction(`${tr("restart")} ${tr("currentStation")} ${state.selected}?`);
    if (!ok) return;
    await api(`/api/stations/${encodeURIComponent(state.selected)}/restart`, { method: "POST" });
    await refreshAll();
  };
  $("deleteStationBtn").onclick = async () => {
    if (!canAdmin()) return showTransientError(tr("viewerOnly"));
    if (!state.selected || state.creatingStation) return;
    await api(`/api/stations/${encodeURIComponent(state.selected)}`, { method: "DELETE" });
    state.selected = null;
    state.productRange = { start: "", end: "" };
    state.productsSignature = "";
    await refreshAll();
  };
  $("stationForm").onsubmit = async (event) => {
    event.preventDefault();
    if (!canAdmin()) return showTransientError(tr("viewerOnly"));
    const payload = readStationForm();
    const method = selectedConfig() ? "PUT" : "POST";
    const url = method === "PUT" ? `/api/stations/${encodeURIComponent(state.selected)}` : "/api/stations";
    await api(url, { method, body: JSON.stringify(payload) });
    state.selected = payload.name;
    state.creatingStation = false;
    state.stationFormDirty = false;
    await refreshAll();
  };
  $("irForm").onsubmit = async (event) => {
    event.preventDefault();
    if (!canAdmin()) return showTransientError(tr("viewerOnly"));
    const raw = applyIrFormToRaw();
    await saveIrConfig(raw);
  };
  $("postprocessForm").onsubmit = submitPostprocess;
  $("postprocessForm").elements.observation_file.addEventListener("change", updateFilePickers);
  $("postprocessForm").elements.ephemeris_file.addEventListener("change", updateFilePickers);
  $("reloadIrBtn").onclick = async () => {
    if (!canAdmin()) return showTransientError(tr("viewerOnly"));
    state.irFormDirty = false;
    state.irConfig = null;
    await loadIrConfig();
  };
  $("saveYamlBtn").onclick = async () => {
    if (!canAdmin()) return showTransientError(tr("viewerOnly"));
    if (!state.selected) return;
    await api(`/api/stations/${encodeURIComponent(state.selected)}/reflectometry-config`, {
      method: "PUT",
      body: JSON.stringify({ yaml_text: $("yamlEditor").value })
    });
    state.irFormDirty = false;
    await loadIrConfig();
    showTransientError(`${t.saved}; ${t.restartHint}`);
  };
  $("yamlEditor").addEventListener("input", () => {
    state.irFormDirty = true;
  });
  $("stationForm").addEventListener("input", () => {
    state.stationFormDirty = true;
  });
  $("irForm").addEventListener("input", () => {
    state.irFormDirty = true;
  });
  $("productTypeFilter").addEventListener("change", (event) => {
    state.productTypeFilter = event.target.value;
    renderProducts();
  });
  $("productApplyRangeBtn").onclick = async () => {
    state.productRange = {
      start: $("productStartTime").value || "",
      end: $("productEndTime").value || ""
    };
    await refreshProducts();
  };
  $("productResetRangeBtn").onclick = async () => {
    state.productRange = { start: "", end: "" };
    syncProductRangeInputs();
    await refreshProducts();
  };
  for (const id of ["productChart", "overviewProductChart"]) {
    const canvas = $(id);
    if (!canvas) continue;
    canvas.addEventListener("mousemove", (event) => updateChartHover(id, event));
    canvas.addEventListener("mouseleave", () => {
      delete state.chartHover[id];
      drawProductChart(id);
    });
  }
  $("exportCsvBtn").onclick = () => exportProducts("csv");
  $("exportJsonBtn").onclick = () => exportProducts("json");
  $("confirmCancelBtn").onclick = () => closeConfirm(false);
  $("confirmOkBtn").onclick = () => closeConfirm(true);
  $("confirmOverlay").addEventListener("click", (event) => {
    if (event.target === $("confirmOverlay")) closeConfirm(false);
  });
  window.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && state.pendingConfirm) closeConfirm(false);
  });
  document.querySelectorAll(".tab").forEach((tab) => tab.addEventListener("click", () => switchTab(tab.dataset.tab)));
  window.addEventListener("resize", drawAllVisuals);
}

async function login() {
  const form = $("loginForm");
  const error = $("loginError");
  error.classList.add("hidden");
  try {
    const payload = await api("/api/login", {
      method: "POST",
      body: JSON.stringify({
        username: form.elements.username.value.trim(),
        password: form.elements.password.value
      })
    });
    state.user = payload.user;
    form.elements.password.value = "";
    showApp();
    await refreshAll();
  } catch (errorValue) {
    error.textContent = errorValue.message || "Login failed";
    error.classList.remove("hidden");
  }
}

async function initializeAuth() {
  try {
    const payload = await api("/api/session");
    if (payload.authenticated && payload.user) {
      state.user = payload.user;
      showApp();
      await refreshAll();
      return;
    }
  } catch (_error) {
    // Fall through to login screen.
  }
  showLogin();
}

function showLogin() {
  document.body.classList.add("logged-out");
  $("loginScreen").classList.remove("hidden");
  $("appWorkbench").classList.add("hidden");
  $("userBadge").textContent = "-";
}

function showApp() {
  document.body.classList.remove("logged-out");
  $("loginScreen").classList.add("hidden");
  $("appWorkbench").classList.remove("hidden");
  const role = state.user?.role || "viewer";
  $("userBadge").textContent = `${state.user?.display_name || state.user?.username || "-"} / ${role}`;
  setAdminControls();
}

function setAdminControls() {
  const allowed = canAdmin();
  document.body.classList.toggle("viewer-mode", !allowed);
  const ids = [
    "reloadBtn",
    "newStationBtn",
    "saveStationBtn",
    "deleteStationBtn",
    "saveIrBtn",
    "reloadIrBtn",
    "saveYamlBtn",
    "runPostprocessBtn"
  ];
  for (const id of ids) {
    const node = $(id);
    if (node) node.disabled = !allowed;
  }
  for (const formId of ["stationForm", "irForm", "postprocessForm"]) {
    const form = $(formId);
    if (!form) continue;
    for (const element of form.elements) {
      if (element.tagName === "BUTTON") continue;
      element.disabled = !allowed;
    }
  }
  const yaml = $("yamlEditor");
  if (yaml) yaml.disabled = !allowed;
  setActionButtonState(selectedRuntime());
  setPostprocessControls();
}

function confirmAction(message) {
  const overlay = $("confirmOverlay");
  if (!overlay) return Promise.resolve(window.confirm(message));
  $("confirmMessage").textContent = message;
  overlay.classList.remove("hidden");
  $("confirmOkBtn").focus();
  return new Promise((resolve) => {
    state.pendingConfirm = resolve;
  });
}

function closeConfirm(accepted) {
  const resolve = state.pendingConfirm;
  state.pendingConfirm = null;
  $("confirmOverlay")?.classList.add("hidden");
  if (resolve) resolve(Boolean(accepted));
}

async function saveIrConfig(raw) {
  if (!state.selected) return;
  await api(`/api/stations/${encodeURIComponent(state.selected)}/reflectometry-config`, {
    method: "PUT",
    body: JSON.stringify({ config: raw })
  });
  state.irFormDirty = false;
  await loadIrConfig();
  showTransientError(`${t.saved}; ${t.restartHint}`);
}

function switchTab(name) {
  state.activeTab = name;
  document.querySelectorAll(".tab").forEach((tab) => tab.classList.toggle("active", tab.dataset.tab === name));
  document.querySelectorAll(".tab-panel").forEach((panel) => panel.classList.remove("active"));
  $(`${name}Tab`).classList.add("active");
  if (name === "products") refreshProducts({ force: true }).catch((error) => showTransientError(error.message));
  if (name === "logs") refreshLogs().catch((error) => showTransientError(error.message));
  drawAllVisuals();
}

function latestProduct(type) {
  return state.products.slice().reverse().find((item) => item.product_type === type) || null;
}

function latestProductValue(product, history) {
  const latest = product || (history || []).slice().reverse()[0];
  return latest ? `${fmtNum(latest.value, 3)} ${latest.unit || ""}` : "-";
}

function filteredProducts() {
  if (!state.productTypeFilter) return state.products;
  return state.products.filter((item) => item.product_type === state.productTypeFilter);
}

function updateProductTypeFilter() {
  const select = $("productTypeFilter");
  if (!select) return;
  const previous = state.productTypeFilter;
  const types = Array.from(new Set(state.products.map((item) => item.product_type).filter(Boolean))).sort();
  select.innerHTML = `<option value="">全部</option>` + types.map((type) => `<option value="${escapeHtml(type)}">${escapeHtml(type)}</option>`).join("");
  if (types.includes(previous)) {
    select.value = previous;
  } else {
    state.productTypeFilter = "";
    select.value = "";
  }
}

function exportProducts(format) {
  const rows = filteredProducts();
  if (!rows.length) return showTransientError("No products to export");
  const suffix = state.productTypeFilter || "all";
  if (format === "json") {
    downloadText(`${state.selected || "station"}_${suffix}_products.json`, JSON.stringify(rows, null, 2), "application/json");
    return;
  }
  const fields = ["timestamp", "product_type", "value", "unit", "solution_arc_count", "confidence"];
  const lines = [fields.join(",")];
  for (const row of rows) {
    lines.push([
      row.timestamp,
      row.product_type,
      row.value,
      row.unit,
      productArcCount(row),
      row.confidence
    ].map(csvCell).join(","));
  }
  downloadText(`${state.selected || "station"}_${suffix}_products.csv`, lines.join("\n"), "text/csv");
}

function downloadText(filename, text, mimeType) {
  const blob = new Blob([text], { type: `${mimeType};charset=utf-8` });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

function csvCell(value) {
  const text = String(value ?? "");
  return /[",\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}

function streamLabel(stream) {
  if (!stream) return "-";
  const host = stream.host || "-";
  const port = stream.port || "-";
  const mountpoint = stream.mountpoint || "-";
  return `${host}:${port} / ${mountpoint}`;
}

function listToText(value) {
  return Array.isArray(value) ? value.join(",") : "";
}

function textToList(value) {
  return String(value || "").split(/[,\s]+/).map((item) => item.trim()).filter(Boolean);
}

function numberOrNull(value) {
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function integerOrNull(value) {
  const number = Number.parseInt(value, 10);
  return Number.isFinite(number) ? number : null;
}

function deepClone(value) {
  return JSON.parse(JSON.stringify(value || {}));
}

function objectToYaml(value, indent = 0) {
  if (Array.isArray(value)) {
    if (!value.length) return "[]";
    return value.map((item) => `${" ".repeat(indent)}- ${yamlValue(item, indent + 2)}`).join("\n");
  }
  if (value && typeof value === "object") {
    return Object.entries(value).map(([key, item]) => {
      if (item && typeof item === "object") return `${" ".repeat(indent)}${key}:\n${objectToYaml(item, indent + 2)}`;
      return `${" ".repeat(indent)}${key}: ${yamlScalar(item)}`;
    }).join("\n");
  }
  return yamlScalar(value);
}

function yamlValue(value, indent) {
  if (Array.isArray(value) || (value && typeof value === "object")) {
    return `\n${objectToYaml(value, indent)}`;
  }
  return yamlScalar(value);
}

function yamlScalar(value) {
  if (value === null || value === undefined) return "null";
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  const text = String(value);
  if (!text || /[:#\n\[\]{},]/.test(text)) return JSON.stringify(text);
  return text;
}

function setupCanvas(canvas, cssHeight) {
  const rect = canvas.getBoundingClientRect();
  const ratio = window.devicePixelRatio || 1;
  canvas.width = Math.max(360, Math.floor(rect.width * ratio));
  canvas.height = Math.floor(cssHeight * ratio);
  const ctx = canvas.getContext("2d");
  ctx.scale(ratio, ratio);
  return ctx;
}

function clearCanvas(ctx, width, height) {
  ctx.clearRect(0, 0, width, height);
  ctx.fillStyle = "#f7f8fa";
  ctx.fillRect(0, 0, width, height);
}

function drawCanvasMessage(ctx, message) {
  ctx.fillStyle = "#64707a";
  ctx.font = "12px Segoe UI, Arial";
  ctx.fillText(message || "Waiting for stream data", 18, 30);
}

function normalizeChartSeries(series) {
  return (series || [])
    .map((item) => ({
      ...item,
      _time: new Date(item.timestamp).getTime(),
      _value: Number(item.value)
    }))
    .filter((item) => Number.isFinite(item._time) && Number.isFinite(item._value))
    .sort((a, b) => a._time - b._time);
}

function drawLineSeries(ctx, width, height, series, unit = "m", label = "", canvasId = "productChart") {
  const values = series.map((item) => item._value);
  const rawMin = Math.min(...values);
  const rawMax = Math.max(...values);
  const rawSpan = Math.max(rawMax - rawMin, 0.001);
  const min = rawMin - rawSpan * 0.08;
  const max = rawMax + rawSpan * 0.08;
  const span = Math.max(max - min, 0.001);
  const startTime = series[0]._time;
  const endTime = series[series.length - 1]._time;
  const timeSpan = Math.max(endTime - startTime, 1);
  const pad = { left: 70, right: 24, top: 32, bottom: 56 };
  const plot = {
    left: pad.left,
    right: width - pad.right,
    top: pad.top,
    bottom: height - pad.bottom,
    width: width - pad.left - pad.right,
    height: height - pad.top - pad.bottom
  };
  const xFor = (time) => plot.left + ((time - startTime) / timeSpan) * plot.width;
  const yFor = (value) => plot.top + ((max - value) / span) * plot.height;
  const points = series.map((item) => ({
    item,
    x: xFor(item._time),
    y: yFor(item._value)
  }));

  ctx.save();
  ctx.strokeStyle = "#d7dee5";
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(plot.left, plot.top);
  ctx.lineTo(plot.left, plot.bottom);
  ctx.lineTo(plot.right, plot.bottom);
  ctx.stroke();

  ctx.font = "11px Segoe UI, Arial";
  ctx.fillStyle = "#5f6972";
  ctx.textBaseline = "middle";
  for (const tick of buildValueTicks(min, max, 5)) {
    const y = yFor(tick);
    ctx.strokeStyle = "#e6ebef";
    ctx.beginPath();
    ctx.moveTo(plot.left, y);
    ctx.lineTo(plot.right, y);
    ctx.stroke();
    ctx.fillText(`${tick.toFixed(3)} ${unit || ""}`, 8, y);
  }

  ctx.textBaseline = "top";
  for (const tick of buildTimeTicks(startTime, endTime, width < 680 ? 3 : 5)) {
    const x = xFor(tick);
    ctx.strokeStyle = "#eef2f5";
    ctx.beginPath();
    ctx.moveTo(x, plot.top);
    ctx.lineTo(x, plot.bottom);
    ctx.stroke();
    const text = formatAxisTime(tick, startTime, endTime);
    const textWidth = ctx.measureText(text).width;
    ctx.fillStyle = "#5f6972";
    ctx.fillText(text, Math.min(Math.max(plot.left, x - textWidth / 2), plot.right - textWidth), plot.bottom + 10);
  }

  if (label) {
    ctx.fillStyle = "#2f3942";
    ctx.font = "12px Segoe UI, Arial";
    ctx.textBaseline = "alphabetic";
    ctx.fillText(label, plot.left, 18);
  }

  const color = label === "reflector_height" ? "#2f5f8f" : "#1f7a6d";
  ctx.strokeStyle = color;
  ctx.lineWidth = 2.3;
  ctx.lineJoin = "round";
  ctx.lineCap = "round";
  drawSmoothPath(ctx, points);
  ctx.stroke();

  ctx.fillStyle = "#ffffff";
  ctx.strokeStyle = color;
  ctx.lineWidth = 1.5;
  for (const point of samplePoints(points, 90)) {
    ctx.beginPath();
    ctx.arc(point.x, point.y, 2.6, 0, Math.PI * 2);
    ctx.fill();
    ctx.stroke();
  }

  state.chartLayouts[canvasId] = { points, plot, unit, label };
  const hoverIndex = state.chartHover[canvasId]?.index;
  if (Number.isInteger(hoverIndex) && points[hoverIndex]) {
    drawChartHover(ctx, points[hoverIndex], plot, unit);
  }
  ctx.restore();
}

function drawSmoothPath(ctx, points) {
  if (!points.length) return;
  ctx.beginPath();
  ctx.moveTo(points[0].x, points[0].y);
  if (points.length === 2) {
    ctx.lineTo(points[1].x, points[1].y);
    return;
  }
  for (let index = 0; index < points.length - 1; index += 1) {
    const current = points[index];
    const next = points[index + 1];
    const midX = (current.x + next.x) / 2;
    const midY = (current.y + next.y) / 2;
    ctx.quadraticCurveTo(current.x, current.y, midX, midY);
  }
  const last = points[points.length - 1];
  ctx.lineTo(last.x, last.y);
}

function drawChartHover(ctx, point, plot, unit) {
  ctx.save();
  ctx.strokeStyle = "rgba(47, 57, 66, 0.28)";
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(point.x, plot.top);
  ctx.lineTo(point.x, plot.bottom);
  ctx.stroke();
  ctx.fillStyle = "#ffffff";
  ctx.strokeStyle = "#1f7a6d";
  ctx.lineWidth = 2;
  ctx.beginPath();
  ctx.arc(point.x, point.y, 4.5, 0, Math.PI * 2);
  ctx.fill();
  ctx.stroke();

  const item = point.item;
  const lines = [
    fmtTime(item.timestamp),
    `${fmtNum(item.value, 4)} ${unit || item.unit || ""}`,
    `\u89e3\u7b97\u5f27\u6bb5 ${productArcCount(item) || "-"}`,
    `confidence ${fmtNum(item.confidence, 3)}`
  ];
  ctx.font = "12px Segoe UI, Arial";
  const tooltipWidth = Math.max(...lines.map((line) => ctx.measureText(line).width)) + 22;
  const tooltipHeight = lines.length * 20 + 14;
  let x = point.x + 14;
  if (x + tooltipWidth > plot.right) x = point.x - tooltipWidth - 14;
  let y = point.y - tooltipHeight / 2;
  y = Math.max(plot.top + 6, Math.min(plot.bottom - tooltipHeight - 6, y));
  ctx.fillStyle = "rgba(31, 41, 51, 0.92)";
  ctx.strokeStyle = "rgba(255, 255, 255, 0.18)";
  roundedRect(ctx, x, y, tooltipWidth, tooltipHeight, 6);
  ctx.fill();
  ctx.stroke();
  ctx.fillStyle = "#f8fafc";
  ctx.textBaseline = "top";
  lines.forEach((line, index) => ctx.fillText(line, x + 11, y + 9 + index * 20));
  ctx.restore();
}

function roundedRect(ctx, x, y, width, height, radius) {
  const r = Math.min(radius, width / 2, height / 2);
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.lineTo(x + width - r, y);
  ctx.quadraticCurveTo(x + width, y, x + width, y + r);
  ctx.lineTo(x + width, y + height - r);
  ctx.quadraticCurveTo(x + width, y + height, x + width - r, y + height);
  ctx.lineTo(x + r, y + height);
  ctx.quadraticCurveTo(x, y + height, x, y + height - r);
  ctx.lineTo(x, y + r);
  ctx.quadraticCurveTo(x, y, x + r, y);
  ctx.closePath();
}

function updateChartHover(canvasId, event) {
  const layout = state.chartLayouts[canvasId];
  const canvas = $(canvasId);
  if (!layout || !canvas || !layout.points.length) return;
  const rect = canvas.getBoundingClientRect();
  const x = event.clientX - rect.left;
  let nearestIndex = 0;
  let nearestDistance = Infinity;
  layout.points.forEach((point, index) => {
    const distance = Math.abs(point.x - x);
    if (distance < nearestDistance) {
      nearestDistance = distance;
      nearestIndex = index;
    }
  });
  state.chartHover[canvasId] = { index: nearestIndex };
  drawProductChart(canvasId);
}

function buildValueTicks(min, max, count) {
  const ticks = [];
  if (!Number.isFinite(min) || !Number.isFinite(max) || count <= 1) return ticks;
  const step = (max - min) / (count - 1);
  for (let index = 0; index < count; index += 1) ticks.push(min + step * index);
  return ticks.reverse();
}

function buildTimeTicks(start, end, count) {
  if (!Number.isFinite(start) || !Number.isFinite(end) || count <= 1) return [];
  if (start === end) return [start];
  const step = (end - start) / (count - 1);
  const ticks = [];
  for (let index = 0; index < count; index += 1) ticks.push(start + step * index);
  return ticks;
}

function samplePoints(points, maxCount) {
  if (points.length <= maxCount) return points;
  const step = Math.ceil(points.length / maxCount);
  return points.filter((_point, index) => index % step === 0 || index === points.length - 1);
}

function formatAxisTime(value, start, end) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "-";
  const span = Math.abs(end - start);
  if (span > 48 * 60 * 60 * 1000) {
    return date.toLocaleDateString([], { month: "2-digit", day: "2-digit" });
  }
  return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function formatShortTime(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "-";
  return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function polarToCanvas(cx, cy, radius, azimuth, elevation) {
  const az = (Number(azimuth) - 90) * Math.PI / 180;
  const r = radius * (1 - Math.max(0, Math.min(90, Number(elevation))) / 90);
  return { x: cx + Math.cos(az) * r, y: cy + Math.sin(az) * r };
}

function drawAzimuthSector(ctx, cx, cy, radius, start, end) {
  const startRad = (Number(start) - 90) * Math.PI / 180;
  const endRad = (Number(end) - 90) * Math.PI / 180;
  ctx.beginPath();
  ctx.moveTo(cx, cy);
  ctx.arc(cx, cy, radius, startRad, endRad, false);
  ctx.closePath();
  ctx.fill();
}

function drawAzimuthElevationZone(ctx, cx, cy, radius, start, end, minElevation, maxElevation) {
  const startRad = (Number(start) - 90) * Math.PI / 180;
  const endRad = (Number(end) - 90) * Math.PI / 180;
  const outerR = elevationToRadius(radius, minElevation);
  const innerR = elevationToRadius(radius, maxElevation);
  ctx.beginPath();
  ctx.arc(cx, cy, outerR, startRad, endRad, false);
  ctx.arc(cx, cy, innerR, endRad, startRad, true);
  ctx.closePath();
  ctx.fill();
}

function elevationToRadius(radius, elevation) {
  return radius * (1 - Math.max(0, Math.min(90, Number(elevation))) / 90);
}

function systemColor(system) {
  return { G: "#2f5f8f", R: "#9b4441", E: "#6b5f8f", C: "#1f7a6d", J: "#9a6a2f", S: "#66707a", I: "#3f7280" }[system] || "#34404a";
}

function showTransientError(message) {
  const box = $("errorBox");
  box.textContent = message;
  box.classList.remove("hidden");
  setTimeout(() => box.classList.add("hidden"), 3500);
}

function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

bindEvents();
applyLanguage();
initializeAuth().catch((error) => showTransientError(error.message));
setInterval(() => {
  refreshAll({ background: true }).catch((error) => showTransientError(error.message));
}, 6000);
