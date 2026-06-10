const rows = document.querySelector("#stationRows");
const form = document.querySelector("#stationForm");
const toast = document.querySelector("#toast");
const logSource = document.querySelector("#logSource");
const obsTypeEditor = document.querySelector("#obsTypeEditor");
const OBS_SYSTEMS = [
  ["G", "GPS"],
  ["R", "GLONASS"],
  ["E", "Galileo"],
  ["C", "BeiDou"],
  ["J", "QZSS"],
  ["S", "SBAS"],
  ["I", "NavIC"],
];
const fields = {
  enabled: document.querySelector("#enabled"),
  name: document.querySelector("#name"),
  host: document.querySelector("#host"),
  port: document.querySelector("#port"),
  mountpoint: document.querySelector("#mountpoint"),
  user: document.querySelector("#user"),
  password: document.querySelector("#password"),
  outputDirectory: document.querySelector("#outputDirectory"),
  markerName: document.querySelector("#markerName"),
  stationCode: document.querySelector("#stationCode"),
  receiverNumber: document.querySelector("#receiverNumber"),
  receiverType: document.querySelector("#receiverType"),
  antennaType: document.querySelector("#antennaType"),
  antennaModel: document.querySelector("#antennaModel"),
  sampleInterval: document.querySelector("#sampleInterval"),
  splitPeriod: document.querySelector("#splitPeriod"),
  mergeInterval: document.querySelector("#mergeInterval"),
  timeSystem: document.querySelector("#timeSystem"),
  approxPosition: document.querySelector("#approxPosition"),
};

let stations = [];
let runtime = [];
let selectedName = "";
let formDirty = false;
let suppressDirty = false;

function setFormDirty(dirty) {
  formDirty = Boolean(dirty);
  const title = document.querySelector("#editorTitle");
  if (!title) return;
  title.dataset.dirty = formDirty ? "1" : "0";
  if (formDirty && !title.textContent.endsWith(" *")) {
    title.textContent += " *";
  } else if (!formDirty && title.textContent.endsWith(" *")) {
    title.textContent = title.textContent.slice(0, -2);
  }
}

function notify(message) {
  toast.textContent = message;
  toast.classList.add("show");
  clearTimeout(notify.timer);
  notify.timer = setTimeout(() => toast.classList.remove("show"), 2600);
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.error || response.statusText);
  return payload;
}

function runtimeByName() {
  return new Map(runtime.map((item) => [item.name, item]));
}

function renderRows() {
  const map = runtimeByName();
  rows.innerHTML = "";
  for (const station of stations) {
    const status = map.get(station.name) || {};
    const tr = document.createElement("tr");
    tr.className = station.name === selectedName ? "selected" : "";
    tr.onclick = () => selectStation(station.name);
    const stateClass = status.alive ? "ok" : station.enabled === false ? "warn" : "bad";
    const stateText = status.alive ? "Running" : station.enabled === false ? "Disabled" : "Stopped";
    tr.innerHTML = `
      <td title="${station.name || ""}">${station.name || ""}</td>
      <td title="${station.ntrip?.mountpoint || ""}">${station.ntrip?.mountpoint || ""}</td>
      <td><span class="state"><span class="dot ${stateClass}"></span>${stateText}</span></td>
      <td>${status.epochs_written ?? 0}</td>
      <td>${status.sample_interval_seconds ?? ""}</td>
      <td title="${status.active_file || ""}">${status.active_file ? status.active_file.split(/[\\/]/).pop() : ""}</td>
    `;
    rows.appendChild(tr);
  }
}

function renderLogSources() {
  const current = logSource.value;
  const sourceNames = new Set(["service", "web"]);
  for (const station of stations) sourceNames.add(station.name);
  for (const item of runtime) sourceNames.add(item.name);
  logSource.innerHTML = `<option value="">All Sources</option>`;
  for (const source of [...sourceNames].filter(Boolean).sort()) {
    const option = document.createElement("option");
    option.value = source;
    option.textContent = source;
    logSource.appendChild(option);
  }
  if ([...logSource.options].some((option) => option.value === current)) {
    logSource.value = current;
  }
}

function renderObsTypes(sysObsTypes = {}) {
  obsTypeEditor.innerHTML = "";
  for (const [system, label] of OBS_SYSTEMS) {
    const row = document.createElement("label");
    row.className = "obs-row";
    row.innerHTML = `
      <span><strong>${system}</strong><small>${label}</small></span>
      <input data-system="${system}" placeholder="C1C L1C D1C S1C" />
    `;
    const input = row.querySelector("input");
    input.value = Array.isArray(sysObsTypes[system]) ? sysObsTypes[system].join(" ") : "";
    obsTypeEditor.appendChild(row);
  }
}

function readObsTypes() {
  const result = {};
  for (const input of obsTypeEditor.querySelectorAll("input[data-system]")) {
    const codes = input.value
      .split(/[\s,]+/)
      .map((item) => item.trim().toUpperCase())
      .filter(Boolean);
    if (codes.length) result[input.dataset.system] = [...new Set(codes)];
  }
  return result;
}

function selectStation(name) {
  if (formDirty && name !== selectedName && !confirm("You have unsaved changes. Switch stations and discard the current edits?")) {
    return;
  }
  selectedName = name;
  const station = stations.find((item) => item.name === name);
  fillForm(station || null);
  renderRows();
}

function fillForm(station) {
  suppressDirty = true;
  const ntrip = station?.ntrip || {};
  const rinex = station?.rinex || {};
  fields.enabled.checked = station?.enabled !== false;
  fields.name.value = station?.name || "";
  fields.host.value = ntrip.host || "";
  fields.port.value = ntrip.port || 2101;
  fields.mountpoint.value = ntrip.mountpoint || "";
  fields.user.value = ntrip.user || "";
  fields.password.value = ntrip.password || "";
  fields.outputDirectory.value = rinex.output_directory || "";
  fields.markerName.value = rinex.marker_name || station?.name || "";
  fields.stationCode.value = rinex.station_code || (station?.name || "").slice(0, 4).toUpperCase();
  fields.receiverNumber.value = rinex.receiver_number || "00";
  fields.receiverType.value = rinex.receiver_type || "UNKNOWN";
  fields.antennaType.value = rinex.antenna_type || "UNKNOWN";
  fields.antennaModel.value = rinex.antenna_model || "";
  fields.sampleInterval.value = rinex.sample_interval_seconds ?? "auto";
  fields.splitPeriod.value = rinex.split_period_seconds || 3600;
  fields.mergeInterval.value = rinex.daily_merge_min_interval_seconds || 15;
  fields.timeSystem.value = "GPS";
  fields.approxPosition.value = Array.isArray(rinex.approx_position) ? rinex.approx_position.join(", ") : "";
  renderObsTypes(rinex.sys_obs_types || {});
  document.querySelector("#editorTitle").textContent = station ? `Station Config: ${station.name}` : "Station Config";
  suppressDirty = false;
  setFormDirty(false);
}

function parseNumberOrAuto(value) {
  const text = String(value ?? "").trim();
  if (!text || text.toLowerCase() === "auto") return "auto";
  const parsed = Number(text);
  return Number.isFinite(parsed) ? parsed : "auto";
}

function parsePosition(value) {
  const text = String(value || "").trim();
  if (!text) return undefined;
  const parts = text.split(",").map((item) => Number(item.trim()));
  if (parts.length < 3 || parts.some((item) => !Number.isFinite(item))) {
    throw new Error("Approx position must be formatted as x, y, z.");
  }
  return parts.slice(0, 3);
}

function stationFromForm() {
  const sysObsTypes = readObsTypes();
  const rinex = {
    output_directory: fields.outputDirectory.value.trim() || undefined,
    marker_name: fields.markerName.value.trim() || fields.name.value.trim(),
    station_code: fields.stationCode.value.trim().toUpperCase() || fields.name.value.trim().slice(0, 4).toUpperCase(),
    receiver_number: fields.receiverNumber.value.trim() || "00",
    receiver_type: fields.receiverType.value.trim() || "UNKNOWN",
    antenna_type: fields.antennaType.value.trim() || "UNKNOWN",
    antenna_model: fields.antennaModel.value.trim(),
    sample_interval_seconds: parseNumberOrAuto(fields.sampleInterval.value),
    split_enabled: true,
    split_period_seconds: Number(fields.splitPeriod.value || 3600),
    daily_merge_min_interval_seconds: Number(fields.mergeInterval.value || 15),
    time_system: "GPS",
    auto_detect_obs_types: Object.keys(sysObsTypes).length === 0,
    sys_obs_types: sysObsTypes,
  };
  const approx = parsePosition(fields.approxPosition.value);
  if (approx) rinex.approx_position = approx;
  return {
    name: fields.name.value.trim(),
    enabled: fields.enabled.checked,
    ntrip: {
      host: fields.host.value.trim(),
      port: Number(fields.port.value || 2101),
      mountpoint: fields.mountpoint.value.trim(),
      user: fields.user.value,
      password: fields.password.value,
    },
    rinex,
  };
}

async function refresh(options = {}) {
  const forceForm = Boolean(options.forceForm);
  const statusPayload = await api("/api/status");
  const stationPayload = await api("/api/stations");
  document.querySelector("#configPath").textContent = statusPayload.config_path || "";
  stations = stationPayload.stations || [];
  runtime = stationPayload.runtime || [];
  const formHasFocus = form.contains(document.activeElement);
  const preserveEditor = !forceForm && (formDirty || formHasFocus);
  if (!selectedName && stations.length && !preserveEditor) selectedName = stations[0].name;
  if (selectedName && !stations.some((item) => item.name === selectedName) && !preserveEditor) selectedName = "";
  if (!preserveEditor) {
    fillForm(stations.find((item) => item.name === selectedName) || null);
  }
  renderRows();
  renderLogSources();
  await refreshLogs();
}

async function refreshLogs() {
  const source = encodeURIComponent(logSource.value || "");
  const logs = await api(`/api/logs?limit=300&source=${source}`);
  if (Array.isArray(logs.sources)) {
    const current = logSource.value;
    for (const sourceName of logs.sources) {
      if (![...logSource.options].some((option) => option.value === sourceName)) {
        const option = document.createElement("option");
        option.value = sourceName;
        option.textContent = sourceName;
        logSource.appendChild(option);
      }
    }
    logSource.value = [...logSource.options].some((option) => option.value === current) ? current : "";
  }
  document.querySelector("#logs").textContent = (logs.lines || []).join("\n");
}

form.addEventListener("input", () => {
  if (!suppressDirty) setFormDirty(true);
});

form.addEventListener("change", () => {
  if (!suppressDirty) setFormDirty(true);
});

form.onsubmit = async (event) => {
  event.preventDefault();
  try {
    const payload = stationFromForm();
    if (!payload.name) throw new Error("Station name is required.");
    if (selectedName) {
      await api(`/api/stations/${encodeURIComponent(selectedName)}`, {
        method: "PUT",
        body: JSON.stringify(payload),
      });
    } else {
      await api("/api/stations", { method: "POST", body: JSON.stringify(payload) });
    }
    selectedName = payload.name;
    notify("Station saved.");
    setFormDirty(false);
    await refresh({ forceForm: true });
  } catch (error) {
    notify(error.message);
  }
};

document.querySelector("#newBtn").onclick = () => {
  if (formDirty && !confirm("You have unsaved changes. Create a new station and discard the current edits?")) {
    return;
  }
  selectedName = "";
  fillForm(null);
  renderRows();
};

document.querySelector("#deleteBtn").onclick = async () => {
  if (!selectedName) return notify("Select a station first.");
  if (!confirm(`Delete station ${selectedName}?`)) return;
  await api(`/api/stations/${encodeURIComponent(selectedName)}`, { method: "DELETE" });
  selectedName = "";
  notify("Station deleted.");
  setFormDirty(false);
  await refresh({ forceForm: true });
};

document.querySelector("#refreshBtn").onclick = () => refresh({ forceForm: false });
document.querySelector("#reloadBtn").onclick = async () => {
  await api("/api/reload", { method: "POST" });
  notify("Config reload requested.");
  await refresh();
};
document.querySelector("#mergeBtn").onclick = async () => {
  await api("/api/merge", { method: "POST" });
  notify("Daily merge scan completed.");
  await refresh();
};
document.querySelector("#copyLogsBtn").onclick = async () => {
  await navigator.clipboard.writeText(document.querySelector("#logs").textContent);
  notify("Logs copied.");
};
logSource.onchange = refreshLogs;
document.querySelector("#clearObsTypesBtn").onclick = () => {
  for (const input of obsTypeEditor.querySelectorAll("input[data-system]")) input.value = "";
  setFormDirty(true);
};

setInterval(refresh, 10000);
refresh().catch((error) => notify(error.message));
