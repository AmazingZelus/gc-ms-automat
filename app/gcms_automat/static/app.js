// User interface logic. Plain JavaScript, no external libraries (works offline).
"use strict";

// ---- This reads the secret token from the address and creates a tab id ----
const TOKEN = new URLSearchParams(window.location.search).get("token") || "";
const CLIENT_ID = (crypto.randomUUID ? crypto.randomUUID()
  : String(Date.now()) + Math.random().toString(16).slice(2));
const HEARTBEAT_INTERVAL_MS = 5000;
let serverGone = false;

// ---- This is a helper for calling the local API ----
async function api(path, body) {
  const options = {
    method: body === undefined ? "GET" : "POST",
    headers: { "X-App-Token": TOKEN, "Content-Type": "application/json" },
  };
  if (body !== undefined) options.body = JSON.stringify(body);
  const response = await fetch(path, options);
  let data = {};
  try { data = await response.json(); } catch (e) { /* not JSON */ }
  if (!response.ok || data.ok === false) {
    throw new Error(data.error || ("Chyba serveru (" + response.status + ")"));
  }
  return data;
}

// ---- This shows the "app is not running" banner and disables the buttons ----
function markServerGone() {
  serverGone = true;
  document.getElementById("offline-banner").hidden = false;
  document.querySelectorAll("button, select").forEach((el) => { el.disabled = true; });
}

// ---- This tells the server every few seconds that this tab is still open ----
async function sendHeartbeat() {
  if (serverGone) return;
  try {
    await api("/api/heartbeat", { cid: CLIENT_ID });
  } catch (e) {
    markServerGone();
  }
}

// ---- This says goodbye when the tab is closed, so the server can stop ----
// sendBeacon is delivered even while the page is closing; it cannot send headers,
// so the token travels in the address.
function sayGoodbye() {
  const url = "/api/closing?token=" + encodeURIComponent(TOKEN) + "&cid=" + encodeURIComponent(CLIENT_ID);
  navigator.sendBeacon(url, "");
}

// ---- This loads the app name, version and library versions ----
async function loadInfo() {
  const info = await api("/api/info");
  document.title = info.app + " v" + info.version;
  document.getElementById("app-name").textContent = info.app;
  document.getElementById("app-version").textContent = "verze " + info.version;
  document.getElementById("exports-dir").textContent = info.exports_dir;

  const select = document.getElementById("csv-format");
  info.csv_formats.forEach((fmt) => {
    const option = document.createElement("option");
    option.value = fmt.key;
    option.textContent = fmt.label;
    option.selected = fmt.key === info.default_csv_format;
    select.appendChild(option);
  });

  const list = document.getElementById("lib-versions");
  const rows = [["Python", info.python]].concat(Object.entries(info.libraries));
  rows.forEach(([name, version]) => {
    const item = document.createElement("li");
    item.textContent = name + " " + version;
    list.appendChild(item);
  });
}

// ---- This is the "Export test" button ----
async function onExportClick() {
  const result = document.getElementById("export-result");
  result.className = "result";
  result.textContent = "Ukládám…";
  try {
    const data = await api("/api/export-test", { csv_format: document.getElementById("csv-format").value });
    result.classList.add("ok");
    result.textContent = "Uloženo: " + data.path;
  } catch (e) {
    result.classList.add("error");
    result.textContent = "Export se nepodařil: " + e.message;
  }
}

// ---- This is the "Otevřít složku s exporty" button ----
async function onOpenFolderClick() {
  try { await api("/api/open-exports", {}); }
  catch (e) { alert("Složku nelze otevřít: " + e.message); }
}

// ---- This is the "Ukončit" button ----
async function onQuitClick() {
  try { await api("/api/shutdown", {}); } catch (e) { /* server may already be gone */ }
  markServerGone();
  document.getElementById("offline-banner").textContent =
    "Aplikace byla ukončena. Tuto kartu můžete zavřít.";
}

// ---- This wires everything together when the page loads ----
document.getElementById("btn-export").addEventListener("click", onExportClick);
document.getElementById("btn-open-folder").addEventListener("click", onOpenFolderClick);
document.getElementById("btn-quit").addEventListener("click", onQuitClick);
window.addEventListener("pagehide", sayGoodbye);
// If the browser restores this page from its cache (Back button), reconnect at once.
window.addEventListener("pageshow", (event) => { if (event.persisted) sendHeartbeat(); });

sendHeartbeat();
setInterval(sendHeartbeat, HEARTBEAT_INTERVAL_MS);
loadInfo().catch(markServerGone);
