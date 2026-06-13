const $ = (id) => document.getElementById(id);

// Runtime/UI lifecycle. Keep network activity completely quiet until the user is authenticated.
let isAuthenticated = false;
let bindingsInstalled = false;
let initStarted = false;
let taskStatusPollBusy = false;
let logHistoryPollBusy = false;
let appsPollBusy = false;
let outreachPollBusy = false;
let runtimeInfo = { cloud: false, runtime: "local", websockets: true, subprocess_tasks: true, system_cron: true, shutdown_endpoint: true };

function isCloudMode() {
  return !!(runtimeInfo && runtimeInfo.cloud);
}

async function loadRuntimeInfo() {
  try {
    const res = await fetch("/api/runtime", { credentials: "include" });
    if (res.ok) {
      runtimeInfo = await res.json();
      applyRuntimeUi();
    }
  } catch (_) {
    // Keep local defaults if the endpoint is unavailable.
  }
  return runtimeInfo;
}

function applyRuntimeUi() {
  const cloud = isCloudMode();
  document.documentElement.toggleAttribute("data-cloud-mode", cloud);
  const banner = $("cloudBanner");
  if (banner) banner.style.display = cloud ? "block" : "none";

  const startButtons = document.querySelectorAll('[id^="start-"]');
  startButtons.forEach((btn) => {
    if (cloud && !runtimeInfo.subprocess_tasks) {
      btn.disabled = true;
      btn.classList.add("cloud-disabled");
      btn.title = "Browser automation tasks do not run inside the Vercel dashboard. Use the included GitHub Actions worker or a desktop/worker install.";
    } else {
      btn.classList.remove("cloud-disabled");
    }
  });

  const quitBtn = $("quitDashboardBtn");
  if (quitBtn) {
    quitBtn.disabled = cloud;
    quitBtn.classList.toggle("cloud-disabled", cloud);
    quitBtn.title = cloud ? "Serverless Vercel deployments cannot be shut down from the browser." : "Stop all tasks, clear schedules, and shut down port 8787";
  }

  ["verifyCronBtn", "syncSystemCronBtn", "clearSystemCronBtn"].forEach((id) => {
    const btn = $(id);
    if (!btn) return;
    btn.disabled = cloud;
    btn.classList.toggle("cloud-disabled", cloud);
    if (cloud) btn.title = "System crontab is a desktop feature and is unavailable on Vercel.";
  });
}

let triggerHistory = {};
function updateTriggerUI(baseTask) {
  const el = $("run-count-" + baseTask);
  if (!el) return;
  const history = triggerHistory[baseTask] || [];
  if (history.length === 0) {
    el.innerHTML = "";
    el.title = "";
  } else {
    const times = history.map(t => typeof t === "number" ? fmtTime(t) : t);
    // Reverse to show the most recent at the top
    const reversedTimes = [...times].reverse();
    
    let html = `<select style="font-size: 11px; padding: 2px 16px 2px 4px; max-width: 140px; margin-right: 8px; border: 1px solid var(--border); border-radius: 4px; background: transparent; color: var(--muted); cursor: pointer; outline: none; appearance: auto;">`;
    html += `<option value="" disabled selected>Triggered (${history.length})</option>`;
    for (const t of reversedTimes) {
      html += `<option value="${t}">${t}</option>`;
    }
    html += `</select>`;
    el.innerHTML = html;
    el.title = `Exact times triggered:\n${times.join("\n")}`;
  }
}

function setAuthenticated(value) {
  isAuthenticated = !!value;
  document.documentElement.toggleAttribute("data-authenticated", isAuthenticated);
}

function isPageActive(pageId) {
  const page = $(pageId);
  return !!(page && page.classList.contains("page--active"));
}

function handleUnauthorized() {
  setAuthenticated(false);
  disconnectLogs();
  showLoginOverlay();
  setPill($("serverStatus"), "Login required", "bad");
}


// Tab navigation
window.switchTab = (target) => {
  document.querySelectorAll(".tabbar:not(.sub-tabbar) .tab").forEach(t => t.classList.remove("tab--active"));
  const tabBtn = document.querySelector(`.tabbar:not(.sub-tabbar) .tab[data-tab="${target}"]`);
  if (tabBtn) tabBtn.classList.add("tab--active");
  
  document.querySelectorAll(".page").forEach(p => { p.classList.remove("page--active"); p.style.display = "none"; });
  const page = $(`page-${target}`);
  if (page) { page.classList.add("page--active"); page.style.display = "block"; }
  if (target === "agent" && isAuthenticated && window.initAgentPanel) {
    window.initAgentPanel();
  }
};

window.switchSubTab = (target) => {
  document.querySelectorAll(".sub-tabbar .sub-tab").forEach(t => t.classList.remove("tab--active"));
  const tabBtn = document.querySelector(`.sub-tabbar .sub-tab[data-subtab="${target}"]`);
  if (tabBtn) tabBtn.classList.add("tab--active");
  
  document.querySelectorAll(".subpage").forEach(p => { p.classList.remove("subpage--active"); p.style.display = "none"; });
  const page = $(`subpage-${target}`);
  if (page) { page.classList.add("subpage--active"); page.style.display = "block"; }
};

document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll(".tabbar:not(.sub-tabbar) .tab").forEach(tab => {
    tab.addEventListener("click", () => window.switchTab(tab.dataset.tab));
  });
  document.querySelectorAll(".sub-tabbar .sub-tab").forEach(tab => {
    tab.addEventListener("click", () => window.switchSubTab(tab.dataset.subtab));
  });
});

function showLoginOverlay() {
  setAuthenticated(false);
  document.body.classList.remove("app-authenticated");
  const overlay = $("loginOverlay");
  if (overlay) overlay.style.display = "flex";
  if (activeLogSocket) {
    try { activeLogSocket.close(); } catch {}
    activeLogSocket = null;
  }
  wsConnected = false;
  logConnectionStarted = false;
}

function hideLoginOverlay() {
  setAuthenticated(true);
  document.body.classList.add("app-authenticated");
  const overlay = $("loginOverlay");
  if (overlay) overlay.style.display = "none";
}

function loginOverlayVisible() {
  const overlay = $("loginOverlay");
  return !!overlay && overlay.style.display !== "none";
}

document.addEventListener("DOMContentLoaded", () => {
  const loginForm = $("loginForm");
  if (loginForm) {
    loginForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      const email = $("loginEmail").value.trim();
      const password = $("loginPassword").value.trim();
      const errorEl = $("loginError");
      errorEl.style.display = "none";
      
      try {
        const res = await fetch("/api/login", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ email, password }),
          credentials: "include"
        });
        if (res.ok) {
          await enterAuthenticatedMode();
        } else {
          errorEl.style.display = "block";
        }
      } catch (err) {
        errorEl.textContent = "Error: " + err.message;
        errorEl.style.display = "block";
      }
    });
  }

  const googleLoginBtn = $("googleLoginBtn");
  if (googleLoginBtn) {
    googleLoginBtn.addEventListener("click", async (e) => {
      e.preventDefault();
      try {
        const originalText = googleLoginBtn.innerHTML;
        googleLoginBtn.innerHTML = "Loading...";
        googleLoginBtn.disabled = true;
        
        const sysInfo = await fetch("/api/system_info").then(r => r.json());
        const clientId = sysInfo.google_client_id;
        
        if (!clientId) {
          alert("Google Client ID is not configured on the server. Please add GOOGLE_CLIENT_ID to your .env file.");
          googleLoginBtn.innerHTML = originalText;
          googleLoginBtn.disabled = false;
          return;
        }
        
        const scope = "https://www.googleapis.com/auth/userinfo.email https://www.googleapis.com/auth/drive.file";
        const redirectUri = window.location.origin + window.location.pathname;
        const url = `https://accounts.google.com/o/oauth2/v2/auth?client_id=${clientId}&redirect_uri=${encodeURIComponent(redirectUri)}&response_type=token&scope=${encodeURIComponent(scope)}`;
        window.location.assign(url);
      } catch (err) {
        alert("Could not start Google Login: " + err.message);
        googleLoginBtn.innerHTML = "Continue with Google";
        googleLoginBtn.disabled = false;
      }
    });
  }
  
  // Check for OAuth hash globally on load
  const hash = window.location.hash;
  if (hash && hash.includes("access_token=")) {
    const params = new URLSearchParams(hash.substring(1));
    const token = params.get("access_token");
    if (token) {
      // Clear hash cleanly
      window.history.replaceState(null, null, window.location.pathname + window.location.search);
      
      // Attempt login
      const overlay = $("loginOverlay");
      if (overlay) overlay.style.display = "flex";
      const loginError = $("loginError");
      if (loginError) {
        loginError.textContent = "Authenticating with Google...";
        loginError.style.display = "block";
        loginError.style.color = "var(--text-muted)";
      }
      
      fetch("/api/login/google", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ credential: token }),
        credentials: "include"
      }).then(async res => {
        if (res.ok) {
          // Success! Save drive token and reload to initialize app
          try {
            sessionStorage.setItem("googleToken", token);
            localStorage.setItem("naukriDriveToken", JSON.stringify({
              token: token,
              expires: Date.now() + (55 * 60 * 1000)
            }));
            // Mark as logged in
            localStorage.setItem("naukri_login", JSON.stringify({ user: "google_sso" }));
          } catch(e) {}
          await enterAuthenticatedMode();
        } else {
          // Failed to log in with google (maybe invalid audience or email not found)
          const errData = await res.json().catch(() => ({}));
          alert("Google Login Failed: " + (errData.detail || "Unknown error"));
          if (loginError) {
             loginError.textContent = "Google Login Failed";
             loginError.style.color = "var(--danger)";
          }
        }
      }).catch(err => {
        alert("Google Login Error: " + err.message);
      });
    }
  } else if (hash && hash.includes("error=")) {
    const params = new URLSearchParams(hash.substring(1));
    const error = params.get("error");
    alert("Google Authorization Error: " + error + "\nMake sure you added " + window.location.origin + window.location.pathname + " to 'Authorized redirect URIs' in Google Cloud Console.");
    window.history.replaceState(null, null, window.location.pathname + window.location.search);
  }

  const renderGoogleBtn = async () => {
    if (!$("googleSignInBtnContainer")) return;
    try {
      const sysInfo = await api("/api/system_info");
      if (sysInfo.google_client_id && window.google && window.google.accounts) {
        $("googleSignInSeparator").style.display = "block";
        google.accounts.id.initialize({
          client_id: sysInfo.google_client_id,
          callback: async (response) => {
            try {
              const errorEl = $("loginError");
              errorEl.style.display = "none";
              const res = await fetch("/api/login/google", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ credential: response.credential }),
                credentials: "include"
              });
              if (res.ok) {
                await enterAuthenticatedMode();
              } else {
                const body = await res.json();
                errorEl.textContent = body.detail || "Google Login failed";
                errorEl.style.display = "block";
              }
            } catch (e) {
              const errorEl = $("loginError");
              errorEl.textContent = "Error connecting to server";
              errorEl.style.display = "block";
            }
          }
        });
        google.accounts.id.renderButton(
          $("googleSignInBtnContainer"),
          { theme: "outline", size: "large", text: "signin_with", width: 250 }
        );
      }
    } catch(e) {}
  };
  // Defer slightly to let Google's script load if it's still parsing
  setTimeout(renderGoogleBtn, 500);

  const logoutBtn = $("logoutBtn");
  if (logoutBtn) {
    logoutBtn.addEventListener("click", async () => {
      try {
        await fetch("/api/logout", { method: "POST", credentials: "include" });
        leaveAuthenticatedMode();
      } catch (err) {}
    });
  }
});

const seen = new Set();
let lastSeenTs = 0;
let wsConnected = false;
let logConnectionStarted = false;
let activeLogSocket = null;
let logReconnectTimer = null;
let logReconnectDelayMs = 1000;
let minTs = 0;

const API_KEY_STORAGE = "naukri_api_key";
let apiKey = "";

const MAX_LOG_LINES = 2000;
const MAX_PENDING = 4000;
const FLUSH_BATCH = 250;
let pending = [];
let flushScheduled = false;

function setApiKey(value) {
  apiKey = (value || "").trim();
  if (apiKey) localStorage.setItem(API_KEY_STORAGE, apiKey);
  else localStorage.removeItem(API_KEY_STORAGE);
}

function loadApiKey() {
  apiKey = localStorage.getItem(API_KEY_STORAGE) || "";
  const el = $("apiKey");
  if (el) el.value = apiKey;
}

function sleep(ms) {
  return new Promise((r) => setTimeout(r, ms));
}

function parseTimes(text) {
  const seen = new Set();
  const values = [];
  for (const raw of (text || "").split(",")) {
    const trimmed = raw.trim();
    if (!trimmed) continue;
    const match = trimmed.match(/^(\d{1,2}):(\d{2})$/);
    if (!match) throw new Error(`Invalid time: ${trimmed}. Use HH:MM, e.g. 09:00`);
    const hour = Number(match[1]);
    const minute = Number(match[2]);
    if (hour < 0 || hour > 23 || minute < 0 || minute > 59) {
      throw new Error(`Invalid time: ${trimmed}. Use 00:00 through 23:59`);
    }
    const normalized = `${String(hour).padStart(2, "0")}:${String(minute).padStart(2, "0")}`;
    if (!seen.has(normalized)) {
      seen.add(normalized);
      values.push(normalized);
    }
  }
  return values.sort();
}

function setPill(pill, text, kind = "muted") {
  if (!pill) return;
  pill.textContent = text;
  pill.classList.remove("pill--muted", "pill--ok", "pill--bad");
  if (kind === "ok") pill.classList.add("pill--ok");
  else if (kind === "bad") pill.classList.add("pill--bad");
  else pill.classList.add("pill--muted");
}

function fmtTime(ts) {
  try {
    const d = new Date(ts * 1000);
    return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  } catch {
    return "";
  }
}

// Schedule config key mapping
const SCHEDULE_CONFIG = {
  naukri:        { enabled: "schedule_enabled_naukri",        times: "schedule_times" },
  bot:           { enabled: "schedule_enabled_bot",           times: "bot_schedule_times" },
  linkedin:      { enabled: "schedule_enabled_linkedin",      times: "linkedin_schedule_times" },
  intl_linkedin: { enabled: "schedule_enabled_intl_linkedin", times: "intl_linkedin_schedule_times" },
  intl_indeed:   { enabled: "schedule_enabled_intl_indeed",   times: "intl_indeed_schedule_times" },
  intl_reed:     { enabled: "schedule_enabled_intl_reed",     times: "intl_reed_schedule_times" },
  intl_crawler:  { enabled: "schedule_enabled_intl_crawler",  times: "intl_crawler_schedule_times" },
  lead_scraper:  { enabled: "schedule_enabled_lead_scraper",  times: "lead_scraper_schedule_times" },
};

function updateScheduleStatusPills(cfg) {
  for (const [task, keys] of Object.entries(SCHEDULE_CONFIG)) {
    const pill = $(`sch-status-${task}`);
    if (!pill) continue;
    const enabled = !!cfg[keys.enabled];
    const times = Array.isArray(cfg[keys.times]) ? cfg[keys.times] : [];
    if (enabled && times.length) {
      pill.textContent = `⏰ ${times.join(", ")}`;
      pill.className = "pill pill--ok";
      pill.style.fontSize = "11px";
    } else {
      pill.textContent = "OFF";
      pill.className = "pill pill--muted";
      pill.style.fontSize = "11px";
    }
  }
}

function renderSystemSchedules(data) {
  const el = $("systemSchedules");
  if (!el) return;

  const add = (line) => {
    const div = document.createElement("div");
    div.textContent = line;
    el.appendChild(div);
  };

  el.innerHTML = "";

  const cron = (data && data.cron) || null;
  if (!cron) {
    add("Not available.");
    return;
  }
  if (!cron.available) {
    add(cron.error || "cron not available.");
    return;
  }

  const tasks = cron.tasks || {};
  const fmt = (arr) => (arr && arr.length ? arr.join(", ") : "None");
  const hasAny =
    (tasks.naukri && tasks.naukri.length) ||
    (tasks.bot && tasks.bot.length) ||
    (tasks.linkedin && tasks.linkedin.length) ||
    (tasks.intl_linkedin && tasks.intl_linkedin.length) ||
    (tasks.intl_indeed && tasks.intl_indeed.length) ||
    (tasks.intl_reed && tasks.intl_reed.length) ||
    (tasks.intl_crawler && tasks.intl_crawler.length) ||
    (tasks.lead_scraper && tasks.lead_scraper.length);

  if (!hasAny && !(cron.unparsed || []).length) {
    add("No cron schedules detected.");
    return;
  }

  add(`Naukri job applier: ${fmt(tasks.naukri)}`);
  add(`Naukri bot: ${fmt(tasks.bot)}`);
  add(`LinkedIn: ${fmt(tasks.linkedin)}`);
  add(`Intl LinkedIn: ${fmt(tasks.intl_linkedin)}`);
  add(`Intl Indeed: ${fmt(tasks.intl_indeed)}`);
  add(`Intl Reed: ${fmt(tasks.intl_reed)}`);
  add(`Intl Crawler: ${fmt(tasks.intl_crawler)}`);
  add(`Lead Scraper: ${fmt(tasks.lead_scraper)}`);
  if ((cron.unparsed || []).length) {
    const n = cron.unparsed.length;
    add(`(${n} cron entr${n === 1 ? "y" : "ies"} couldn't be parsed):`);
    for (const entry of cron.unparsed) {
      const task = entry.task || "unknown";
      const cronExpr = entry.cron || "";
      const reason = entry.reason || "unknown reason";
      add(`- ${task}: ${cronExpr} (${reason})`);
    }
  }
}

async function refreshSystemSchedules() {
  const el = $("systemSchedules");
  if (!el) return;

  try {
    if (isCloudMode()) {
      el.textContent = "System cron is unavailable on Vercel. Use Vercel Cron for one daily HTTP trigger or the included GitHub Actions workflow for real automation schedules.";
      return;
    }
    el.textContent = "Checking…";
    const data = await api("/api/schedules/system");
    renderSystemSchedules(data);
  } catch (e) {
    const msg = (e && e.message) || "Unknown error";
    el.textContent = msg.includes("Unauthorized") ? "Please log in to view schedules." : `Unavailable: ${msg}`;
  }
}

async function syncSystemSchedules() {
  if (isCloudMode()) {
    alert("System crontab sync is only available in the local macOS/Linux desktop install. Vercel uses vercel.json cron and cannot edit a system crontab.");
    return;
  }
  if (
    !confirm(
      "Sync system cron schedules from the in-app scheduler?\n\nThis will overwrite existing cron entries for these scripts to avoid duplicates."
    )
  ) {
    return;
  }

  const el = $("systemSchedules");
  try {
    if (el) el.textContent = "Syncing…";
    const res = await api("/api/schedules/system/sync", { method: "POST", body: "{}" });
    renderSystemSchedules(res);
    setPill($("settingsSaved"), "Cron synced", "ok");
    setTimeout(() => setPill($("settingsSaved"), "Saved", "muted"), 1500);
  } catch (e) {
    const msg = (e && e.message) || "Unknown error";
    if (el) el.textContent = `Sync failed: ${msg}`;
    alert(`Sync failed: ${msg}`);
  }
}

async function clearSystemSchedules() {
  if (isCloudMode()) {
    alert("System crontab is not available on Vercel.");
    return;
  }
  if (!confirm("Remove system cron schedules for these tasks?")) return;

  const el = $("systemSchedules");
  try {
    if (el) el.textContent = "Removing…";
    const res = await api("/api/schedules/system", { method: "DELETE" });
    renderSystemSchedules(res);
    setPill($("settingsSaved"), "Cron removed", "ok");
    setTimeout(() => setPill($("settingsSaved"), "Saved", "muted"), 1500);
  } catch (e) {
    const msg = (e && e.message) || "Unknown error";
    if (el) el.textContent = `Remove failed: ${msg}`;
    alert(`Remove failed: ${msg}`);
  }
}

async function deleteSchedule(task) {
  const meta = {
    naukri: {
      label: "Naukri job applier",
      enabledKey: "schedule_enabled_naukri",
      timesKey: "schedule_times",
      enabledId: "sch-enabled-naukri",
      timesId: "sch-times-naukri",
    },
    bot: {
      label: "Naukri bot",
      enabledKey: "schedule_enabled_bot",
      timesKey: "bot_schedule_times",
      enabledId: "sch-enabled-bot",
      timesId: "sch-times-bot",
    },
    linkedin: {
      label: "LinkedIn",
      enabledKey: "schedule_enabled_linkedin",
      timesKey: "linkedin_schedule_times",
      enabledId: "sch-enabled-linkedin",
      timesId: "sch-times-linkedin",
    },
    intl_linkedin: { label: "Intl LinkedIn", enabledKey: "schedule_enabled_intl_linkedin", timesKey: "intl_linkedin_schedule_times", enabledId: "sch-enabled-intl_linkedin", timesId: "sch-times-intl_linkedin" },
    intl_indeed: { label: "Intl Indeed", enabledKey: "schedule_enabled_intl_indeed", timesKey: "intl_indeed_schedule_times", enabledId: "sch-enabled-intl_indeed", timesId: "sch-times-intl_indeed" },
    intl_reed: { label: "Intl Reed", enabledKey: "schedule_enabled_intl_reed", timesKey: "intl_reed_schedule_times", enabledId: "sch-enabled-intl_reed", timesId: "sch-times-intl_reed" },
    intl_crawler: { label: "Intl Crawler", enabledKey: "schedule_enabled_intl_crawler", timesKey: "intl_crawler_schedule_times", enabledId: "sch-enabled-intl_crawler", timesId: "sch-times-intl_crawler" },
    lead_scraper: { label: "Lead Scraper", enabledKey: "schedule_enabled_lead_scraper", timesKey: "lead_scraper_schedule_times", enabledId: "sch-enabled-lead_scraper", timesId: "sch-times-lead_scraper" },
  }[task];

  if (!meta) return;
  if (!confirm(`Delete schedule for ${meta.label}? This will disable it and clear its times.`)) return;

  try {
    // Optimistically clear inputs (refreshAll() will re-hydrate from server after save).
    $(meta.enabledId).checked = false;
    $(meta.timesId).value = "";

    await api("/api/config", {
      method: "PUT",
      body: JSON.stringify({
        [meta.enabledKey]: false,
        [meta.timesKey]: [],
      }),
    });

    setPill($("settingsSaved"), "Schedule deleted", "ok");
    setTimeout(() => setPill($("settingsSaved"), "Saved", "muted"), 1500);
    await refreshAll();
    await refreshSystemSchedules();
  } catch (e) {
    appendLog({ ts: Date.now() / 1000, task: "ui", kind: "status", line: `Delete schedule failed: ${e.message}\n` });
    alert(`Delete schedule failed: ${e.message}`);
    await refreshAll();
  }
}

async function api(path, opts = {}) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 30000);
  try {
    const baseHeaders = { "Content-Type": "application/json" };
    if (apiKey) baseHeaders["X-API-Key"] = apiKey;
    const res = await fetch(path, {
      headers: { ...baseHeaders, ...(opts.headers || {}) },
      signal: controller.signal,
      credentials: "include",
      ...opts,
    });
    if (res.status === 401) {
      handleUnauthorized();
      throw new Error("Unauthorized");
    }
    if (!res.ok) {
      let msg = `HTTP ${res.status}`;
      try {
        const body = await res.json();
        msg = body.detail || JSON.stringify(body);
      } catch {}
      throw new Error(msg);
    }
    const result = await res.json();
    
    // Auto-backup to Google Drive on mutating operations
    const method = (opts.method || "GET").toUpperCase();
    if (["POST", "PUT", "PATCH", "DELETE"].includes(method)) {
      const ignorePaths = ["/api/login", "/api/login/google", "/api/logout"];
      if (!ignorePaths.includes(path)) {
        if (window.driveSyncApi && sessionStorage.getItem("googleToken")) {
          // Trigger backup asynchronously without blocking the UI
          setTimeout(() => {
            if (typeof window.driveSyncApi.backup === "function") {
              window.driveSyncApi.backup();
            }
          }, 500);
        }
      }
    }
    
    return result;
  } catch (e) {
    if (e && e.name === "AbortError") {
      throw new Error("Request timed out (server busy)");
    }
    throw e;
  } finally {
    clearTimeout(timeout);
  }
}

async function apiUpload(path, formData) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 60000);
  try {
    const headers = {};
    if (apiKey) headers["X-API-Key"] = apiKey;
    const res = await fetch(path, {
      method: "POST",
      headers,
      body: formData,
      signal: controller.signal,
      credentials: "include",
    });
    if (res.status === 401) {
      handleUnauthorized();
      throw new Error("Unauthorized");
    }
    if (!res.ok) {
      let msg = `HTTP ${res.status}`;
      try {
        const body = await res.json();
        msg = body.detail || JSON.stringify(body);
      } catch {}
      throw new Error(msg);
    }
    return res.json();
  } catch (e) {
    if (e && e.name === "AbortError") {
      throw new Error("Request timed out (server busy)");
    }
    throw e;
  } finally {
    clearTimeout(timeout);
  }
}

function fmtBytes(n) {
  if (typeof n !== "number" || !isFinite(n)) return "";
  if (n < 1024) return `${n} B`;
  const kb = n / 1024;
  if (kb < 1024) return `${kb.toFixed(1)} KB`;
  const mb = kb / 1024;
  return `${mb.toFixed(1)} MB`;
}

function renderResumeStatus(data) {
  const el = $("resumeStatus");
  if (!el) return;

  const resume = (data && data.resume) || null;
  if (!resume) {
    el.textContent = "Resume: unavailable.";
    return;
  }

  if (!resume.path) {
    el.textContent = "Resume: not set. Upload a file above (recommended for deploy) or set a local path.";
    return;
  }

  if (resume.exists) {
    const size = resume.size ? ` (${fmtBytes(resume.size)})` : "";
    el.textContent = `Resume: ${resume.filename || "file"}${size} — ready.`;
    
    if (resume.parsed) {
      $("parsedResumeSection").style.display = "block";
      const p = resume.parsed;
      const lines = [
        `Name:       ${p.full_name || "—"}`,
        `Email:      ${p.email || "—"}`,
        `Phone:      ${p.phone || "—"}`,
        `Location:   ${p.location || "—"}`,
        `Experience: ${p.experience_years_str || "—"}`,
        `Skills:     ${(p.skills_text || "").substring(0, 100) || "—"}...`,
        `LinkedIn:   ${p.linkedin_url || "—"}`,
      ];
      $("parsedResumeContent").textContent = lines.join("\n");
    } else {
      $("parsedResumeSection").style.display = "none";
    }
  } else {
    el.textContent = `Resume path is set, but the file is missing on this server: ${resume.path}`;
    $("parsedResumeSection").style.display = "none";
  }
}

async function refreshResumeStatus() {
  const el = $("resumeStatus");
  if (!el) return;

  try {
    el.textContent = "Checking resume…";
    const data = await api("/api/resume");
    renderResumeStatus(data);
  } catch (e) {
    const msg = (e && e.message) || "Unknown error";
    el.textContent = msg.includes("Unauthorized") ? "Resume: please log in." : `Resume: ${msg}`;
  }
}

async function uploadResume() {
  const fileInput = $("resumeFile");
  const status = $("resumeStatus");
  if (!fileInput || !fileInput.files || !fileInput.files.length) {
    alert("Choose a resume file first.");
    return;
  }

  const file = fileInput.files[0];
  const fd = new FormData();
  fd.append("file", file);

  try {
    if (status) status.textContent = "Uploading resume…";
    await apiUpload("/api/resume", fd);
    fileInput.value = "";
    await refreshAll();
    await refreshResumeStatus();
    setPill($("settingsSaved"), "Resume uploaded", "ok");
    setTimeout(() => setPill($("settingsSaved"), "Saved", "muted"), 1500);
  } catch (e) {
    if (status) status.textContent = `Upload failed: ${e.message}`;
    alert(`Upload failed: ${e.message}`);
  }
}

async function deleteResume() {
  if (!confirm("Delete the uploaded resume and clear Resume path?")) return;
  try {
    await api("/api/resume", { method: "DELETE" });
    await refreshAll();
    await refreshResumeStatus();
    setPill($("settingsSaved"), "Resume deleted", "ok");
    setTimeout(() => setPill($("settingsSaved"), "Saved", "muted"), 1500);
  } catch (e) {
    alert(`Delete failed: ${e.message}`);
  }
}


async function enterAuthenticatedMode() {
  setAuthenticated(true);
  hideLoginOverlay();
  const logoutBtn = $("logoutBtn");
  if (logoutBtn) logoutBtn.style.display = "inline-block";
  setPill($("serverStatus"), "Connected", "ok");
  await loadRuntimeInfo();
  connectLogs();
  await refreshAll();
  await refreshSystemSchedules();
  await refreshResumeStatus();
  try { await fetchHistoryIncremental(200); } catch {}
  if (isPageActive("page-agent") && window.initAgentPanel) {
    window.initAgentPanel();
  }
}

function leaveAuthenticatedMode() {
  setAuthenticated(false);
  disconnectLogs();
  if (window.stopAgentPanelPolling) window.stopAgentPanelPolling();
  const logoutBtn = $("logoutBtn");
  if (logoutBtn) logoutBtn.style.display = "none";
  showLoginOverlay();
  setPill($("serverStatus"), "Logged out", "muted");
}

async function refreshTaskStatuses() {
  if (!isAuthenticated || taskStatusPollBusy || document.hidden) return;
  taskStatusPollBusy = true;
  try {
    const tasks = await api("/api/tasks");
    updateTaskUI("naukri", tasks.naukri);
    updateTaskUI("bot", tasks.bot);
    updateTaskUI("linkedin", tasks.linkedin);
    updateTaskUI("intl_linkedin", tasks.intl_linkedin);
    updateTaskUI("intl_indeed", tasks.intl_indeed);
    updateTaskUI("intl_reed", tasks.intl_reed);
    updateTaskUI("intl_crawler", tasks.intl_crawler);
    updateTaskUI("lead_scraper", tasks.lead_scraper);
    applyRuntimeUi();
  } catch (e) {
    if (!String(e.message || "").includes("Unauthorized")) {
      setPill($("serverStatus"), "Polling paused", "bad");
    }
  } finally {
    taskStatusPollBusy = false;
  }
}

async function emergencyStopAll() {
  const message = "Stop every running app task now, disable all saved schedules, and remove system cron entries?\n\nThe dashboard will stay open, but no background job should continue from this app.";
  if (!confirm(message)) return;
  const buttons = [$("panicStopBtn"), $("emergencyStopBtn")].filter(Boolean);
  const originals = buttons.map((btn) => btn.textContent);
  buttons.forEach((btn) => { btn.disabled = true; btn.textContent = "Stopping..."; });
  try {
    const res = await api("/api/control/stop_all", {
      method: "POST",
      body: JSON.stringify({ disable_schedules: true, clear_system_cron: true })
    });
    const taskCount = res.tasks ? Object.keys(res.tasks).length : 0;
    const disabled = res.schedules ? (res.schedules.disabled || 0) : 0;
    const cronRemoved = res.cron ? (res.cron.removed || 0) : 0;
    appendLog({ ts: Date.now() / 1000, task: "ui", kind: "status", line: `Stop All complete: checked ${taskCount} task(s), disabled ${disabled} schedule flag(s), removed ${cronRemoved} cron entr${cronRemoved === 1 ? "y" : "ies"}.\n` });
    setPill($("settingsSaved"), "All stopped", "ok");
    await refreshAll();
    await refreshSystemSchedules();
  } catch (e) {
    alert(`Stop All failed: ${e.message}`);
  } finally {
    buttons.forEach((btn, i) => { btn.disabled = false; btn.textContent = originals[i] || "Stop All"; });
  }
}

async function shutdownDashboard() {
  if (isCloudMode()) {
    alert("This is a Vercel serverless deployment, so there is no local :8787 server to shut down. Stop All still clears in-app state for the current session.");
    return;
  }
  const message = "Stop all running tasks, disable all schedules, remove cron entries, and shut down the dashboard server on this port?\n\nUse start.sh/start.bat to launch it again.";
  if (!confirm(message)) return;
  const btn = $("quitDashboardBtn");
  const original = btn ? btn.textContent : "Quit";
  if (btn) { btn.disabled = true; btn.textContent = "Quitting..."; }
  try {
    await api("/api/control/shutdown", {
      method: "POST",
      body: JSON.stringify({ disable_schedules: true, clear_system_cron: true })
    });
    setPill($("serverStatus"), "Shutting down", "bad");
    appendLog({ ts: Date.now() / 1000, task: "ui", kind: "status", line: "Dashboard shutdown requested. You can close this browser tab.\n" });
  } catch (e) {
    alert(`Dashboard shutdown failed: ${e.message}`);
    if (btn) { btn.disabled = false; btn.textContent = original; }
  }
}

async function refreshAll() {
  const [cfg, tasks] = await Promise.all([api("/api/config"), api("/api/tasks")]);

  // Settings
  $("cfg-email").value = cfg.email || "";
  $("cfg-password").value = cfg.password || "";
  $("cfg-resume-path").value = cfg.resume_path || "";
  $("cfg-job-titles").value = cfg.job_titles || "";

  $("cfg-linkedin-email").value = cfg.linkedin_email || "";
  $("cfg-linkedin-password").value = cfg.linkedin_password || "";
  $("cfg-linkedin-phone").value = cfg.linkedin_phone || "";
  $("cfg-reed-email").value = cfg.reed_email || "";
  $("cfg-reed-password").value = cfg.reed_password || "";
  if ($("cfg-ctc-inr")) $("cfg-ctc-inr").value = cfg.ctc_inr || "";

  // Mark fields sourced from .env with a subtle visual cue
  const envHintFields = [
    ["cfg-email", "_email_source"],
    ["cfg-resume-path", "_resume_path_source"],
    ["cfg-linkedin-email", "_linkedin_email_source"],
    ["cfg-linkedin-phone", "_linkedin_phone_source"],
  ];
  for (const [fieldId, srcKey] of envHintFields) {
    const el = $(fieldId);
    if (!el) continue;
    const existing = el.parentElement?.querySelector(".env-badge");
    if (existing) existing.remove();
    if (cfg[srcKey] === ".env") {
      const badge = document.createElement("span");
      badge.className = "env-badge";
      badge.textContent = "from .env";
      badge.title = "This value comes from your .env file. Edit here to override in config.json.";
      el.parentElement?.appendChild(badge);
    }
  }
  // Password env indicators
  const pwFields = [
    ["cfg-password", "_password_set_via_env"],
    ["cfg-linkedin-password", "_linkedin_password_set_via_env"],
  ];
  for (const [fieldId, envKey] of pwFields) {
    const el = $(fieldId);
    if (!el) continue;
    const existing = el.parentElement?.querySelector(".env-badge");
    if (existing) existing.remove();
    if (cfg[envKey]) {
      const badge = document.createElement("span");
      badge.className = "env-badge";
      badge.textContent = "set in .env";
      badge.title = "Password is set in your .env file. The dots are a placeholder.";
      el.parentElement?.appendChild(badge);
    }
  }

  // Task preferences
  $("headless-naukri").checked = typeof cfg.ui_headless_naukri === "boolean" ? cfg.ui_headless_naukri : true;
  $("headless-bot").checked = typeof cfg.ui_headless_bot === "boolean" ? cfg.ui_headless_bot : true;
  $("headless-linkedin").checked =
    typeof cfg.ui_headless_linkedin === "boolean" ? cfg.ui_headless_linkedin : true;
  if ($("headless-intl_linkedin")) $("headless-intl_linkedin").checked = typeof cfg.ui_headless_intl_linkedin === "boolean" ? cfg.ui_headless_intl_linkedin : true;
  $("headless-intl_indeed").checked = typeof cfg.ui_headless_intl_indeed === "boolean" ? cfg.ui_headless_intl_indeed : true;
  $("headless-intl_reed").checked = typeof cfg.ui_headless_intl_reed === "boolean" ? cfg.ui_headless_intl_reed : true;
  $("headless-intl_crawler").checked = typeof cfg.ui_headless_intl_crawler === "boolean" ? cfg.ui_headless_intl_crawler : true;
  if ($("headless-lead_scraper")) $("headless-lead_scraper").checked = typeof cfg.ui_headless_lead_scraper === "boolean" ? cfg.ui_headless_lead_scraper : true;

  // Intl settings
  // Per-agent region pickers
  const AGENT_IDS = ["naukri", "linkedin", "intl_linkedin", "intl_indeed", "intl_reed", "intl_crawler"];
  const defaultRegions = { naukri: "Indian", linkedin: "Indian", intl_linkedin: "European", intl_indeed: "European", intl_reed: "European", intl_crawler: "European" };
  AGENT_IDS.forEach(id => {
    const el = $("region-" + id);
    if (el) el.value = cfg["region_" + id] || defaultRegions[id] || "Indian";
  });

  // Scheduler
  $("sch-enabled-naukri").checked = !!cfg.schedule_enabled_naukri;
  $("sch-enabled-bot").checked = !!cfg.schedule_enabled_bot;
  $("sch-enabled-linkedin").checked = !!cfg.schedule_enabled_linkedin;
  if ($("sch-enabled-intl_linkedin")) $("sch-enabled-intl_linkedin").checked = !!cfg.schedule_enabled_intl_linkedin;
  $("sch-enabled-intl_indeed").checked = !!cfg.schedule_enabled_intl_indeed;
  $("sch-enabled-intl_reed").checked = !!cfg.schedule_enabled_intl_reed;
  $("sch-enabled-intl_crawler").checked = !!cfg.schedule_enabled_intl_crawler;
  if ($("sch-enabled-lead_scraper")) $("sch-enabled-lead_scraper").checked = !!cfg.schedule_enabled_lead_scraper;

  $("sch-times-naukri").value = (cfg.schedule_times || []).join(", ");
  $("sch-times-bot").value = (cfg.bot_schedule_times || []).join(", ");
  $("sch-times-linkedin").value = (cfg.linkedin_schedule_times || []).join(", ");
  if ($("sch-times-intl_linkedin")) $("sch-times-intl_linkedin").value = (cfg.intl_linkedin_schedule_times || cfg.intl_schedule_times || []).join(", ");
  if ($("sch-times-lead_scraper")) $("sch-times-lead_scraper").value = (cfg.lead_scraper_schedule_times || []).join(", ");
  if ($("sch-times-intl_indeed")) $("sch-times-intl_indeed").value = (cfg.intl_indeed_schedule_times || cfg.intl_schedule_times || []).join(", ");
  if ($("sch-times-intl_reed")) $("sch-times-intl_reed").value = (cfg.intl_reed_schedule_times || cfg.intl_schedule_times || []).join(", ");
  if ($("sch-times-intl_crawler")) $("sch-times-intl_crawler").value = (cfg.intl_crawler_schedule_times || cfg.intl_schedule_times || []).join(", ");

  updateScheduleStatusPills(cfg);

  // Task statuses
  updateTaskUI("naukri", tasks.naukri);
  updateTaskUI("bot", tasks.bot);
  updateTaskUI("linkedin", tasks.linkedin);
  updateTaskUI("intl_linkedin", tasks.intl_linkedin);
  updateTaskUI("intl_indeed", tasks.intl_indeed);
  updateTaskUI("intl_reed", tasks.intl_reed);
  updateTaskUI("intl_crawler", tasks.intl_crawler);
  updateTaskUI("lead_scraper", tasks.lead_scraper);
}

function updateTaskUI(task, st) {
  const statusPill = $(`status-${task}`);
  const startBtn = $(`start-${task}`);
  const stopBtn = $(`stop-${task}`);

  if (!st) {
    setPill(statusPill, "Unknown", "bad");
    if (startBtn) startBtn.disabled = isCloudMode() && !runtimeInfo.subprocess_tasks;
    if (stopBtn) stopBtn.disabled = true;
    applyRuntimeUi();
    return;
  }

  if (st.running) {
    const since = st.started_at ? ` since ${fmtTime(st.started_at)}` : "";
    setPill(statusPill, `Running${since}`, "ok");
    if (startBtn) startBtn.disabled = true;
    if (stopBtn) stopBtn.disabled = false;
  } else {
    let suffix = "";
    if (typeof st.last_exit_code === "number") suffix = ` (exit ${st.last_exit_code})`;
    setPill(statusPill, `Idle${suffix}`, "muted");
    if (startBtn) startBtn.disabled = isCloudMode() && !runtimeInfo.subprocess_tasks ? true : false;
    if (stopBtn) stopBtn.disabled = true;
  }
  applyRuntimeUi();
}

function appendLog(evt) {
  if (typeof evt.ts === "number" && evt.ts < minTs) return;

  const key = `${evt.ts}|${evt.task}|${evt.kind}|${evt.line}`;
  if (seen.has(key)) return;
  seen.add(key);

  if (typeof evt.ts === "number") lastSeenTs = Math.max(lastSeenTs, evt.ts);
  if (seen.size > 8000) {
    // Best-effort cap to avoid unlimited growth
    const it = seen.values();
    for (let i = 0; i < 2500; i++) {
      const v = it.next();
      if (v.done) break;
      seen.delete(v.value);
    }
  }

  pending.push(evt);
  if (pending.length > MAX_PENDING) {
    pending = pending.slice(pending.length - MAX_PENDING);
  }

  if (evt.line && evt.line.includes("Started (pid")) {
    let baseTask = evt.task;
    const knownTasks = ["naukri", "linkedin", "bot", "intl_linkedin", "intl_indeed", "intl_reed", "intl_crawler", "lead_scraper", "ui", "api", "config", "scheduler", "agent"];
    for (const kt of knownTasks) {
      if (evt.task === kt || evt.task.startsWith(kt + "_")) {
         baseTask = kt;
         break;
      }
    }
    if (!triggerHistory[baseTask]) triggerHistory[baseTask] = [];
    triggerHistory[baseTask].push(evt.ts);
    updateTriggerUI(baseTask);
  }

  if (!flushScheduled) {
    flushScheduled = true;
    requestAnimationFrame(flushLogs);
  }
}

function flushLogs() {
  flushScheduled = false;
  
  const chunk = pending.splice(0, FLUSH_BATCH);
  const frags = {};

  for (const evt of chunk) {
    const line = document.createElement("div");
    line.className = "log__line";

    const meta = document.createElement("span");
    meta.className = "log__meta";
    meta.textContent = `[${fmtTime(evt.ts)}] [${evt.task}] `;

    const msg = document.createElement("span");
    msg.textContent = evt.line || "";

    line.appendChild(meta);
    line.appendChild(msg);
    
    let baseTask = evt.task;
    const knownTasks = ["naukri", "linkedin", "bot", "intl_linkedin", "intl_indeed", "intl_reed", "intl_crawler", "lead_scraper", "ui", "api", "config", "scheduler", "agent"];
    for (const kt of knownTasks) {
      if (evt.task === kt || evt.task.startsWith(kt + "_")) {
         baseTask = kt;
         break;
      }
    }
    
    if (!frags[baseTask]) frags[baseTask] = document.createDocumentFragment();
    frags[baseTask].appendChild(line);
  }

  for (const task in frags) {
    const logEl = $("log-" + task);
    if (!logEl) continue;
    
    const isScrolledToBottom = logEl.scrollHeight - logEl.clientHeight <= logEl.scrollTop + 40;
    logEl.appendChild(frags[task]);

    while (logEl.childNodes.length > MAX_LOG_LINES) {
      logEl.removeChild(logEl.firstChild);
    }

    if (isScrolledToBottom) {
      logEl.scrollTop = logEl.scrollHeight;
    }
  }

  if (pending.length) {
    flushScheduled = true;
    requestAnimationFrame(flushLogs);
  }
}

async function fetchHistoryIncremental(limit = 200) {
  const history = await api(`/api/logs/history?limit=${limit}`);
  for (const evt of history) {
    if (typeof evt.ts === "number" && evt.ts <= lastSeenTs) continue;
    appendLog(evt);
  }
}

function disconnectLogs() {
  if (logReconnectTimer) {
    clearTimeout(logReconnectTimer);
    logReconnectTimer = null;
  }
  wsConnected = false;
  logConnectionStarted = false;
  if (activeLogSocket) {
    try { activeLogSocket.close(1000, "client disconnect"); } catch {}
    activeLogSocket = null;
  }
}

function connectLogs() {
  if (!isAuthenticated) return;
  if (isCloudMode() || runtimeInfo.websockets === false) {
    wsConnected = false;
    setPill($("serverStatus"), "Connected (polling)", "ok");
    return;
  }
  if (activeLogSocket && [WebSocket.CONNECTING, WebSocket.OPEN].includes(activeLogSocket.readyState)) return;

  logConnectionStarted = true;
  const status = $("serverStatus");
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const qs = apiKey ? `?api_key=${encodeURIComponent(apiKey)}` : "";
  const ws = new WebSocket(`${proto}://${location.host}/ws/logs${qs}`);
  activeLogSocket = ws;

  ws.onopen = () => {
    wsConnected = true;
    logReconnectDelayMs = 1000;
    if (logReconnectTimer) {
      clearTimeout(logReconnectTimer);
      logReconnectTimer = null;
    }
    setPill(status, "Connected", "ok");
  };

  ws.onclose = (evt) => {
    if (activeLogSocket === ws) activeLogSocket = null;
    wsConnected = false;
    if (!isAuthenticated) return;
    if (evt && evt.code === 1008) {
      handleUnauthorized();
      return;
    }
    setPill(status, "Disconnected", "bad");
    if (!logReconnectTimer) {
      const delay = logReconnectDelayMs;
      logReconnectTimer = setTimeout(() => {
        logReconnectTimer = null;
        connectLogs();
      }, delay);
      logReconnectDelayMs = Math.min(logReconnectDelayMs * 2, 30000);
    }
  };

  ws.onerror = () => {
    wsConnected = false;
    setPill(status, "Disconnected", "bad");
  };

  ws.onmessage = (e) => {
    try {
      const payload = JSON.parse(e.data);
      if (Array.isArray(payload)) {
        for (const evt of payload) appendLog(evt);
      } else {
        appendLog(payload);
      }
    } catch {
      // ignore malformed websocket frames
    }
  };
}


async function startTask(task) {
  if (isCloudMode() && !runtimeInfo.subprocess_tasks) {
    alert("Vercel dashboard mode cannot run browser automation tasks directly. Deploy the included GitHub Actions workflow or run the desktop worker for actual automation.");
    return;
  }
  try {
    const headlessCheckbox = $(`headless-${task}`);
    const headless = headlessCheckbox ? headlessCheckbox.checked : false;
    const targetEl = $(`target-${task}`);
    const target = targetEl ? Number(targetEl.value || 30) : 30;

    await api(`/api/tasks/${task}/start`, {
      method: "POST",
      body: JSON.stringify({ target, headless }),
    });
    await refreshAll();
  } catch (e) {
    if ((e.message || "").includes("Request timed out")) {
      appendLog({ ts: Date.now() / 1000, task: "ui", kind: "status", line: `Start timed out (${task}). Checking status…\n` });
      // The server may still have started the task; confirm before showing an error.
      for (let i = 0; i < 20; i++) {
        await sleep(500);
        try {
          const tasks = await api("/api/tasks");
          updateTaskUI("naukri", tasks.naukri);
          updateTaskUI("bot", tasks.bot);
          updateTaskUI("linkedin", tasks.linkedin);
          if (tasks[task] && tasks[task].running) {
            appendLog({ ts: Date.now() / 1000, task: "ui", kind: "status", line: `Start confirmed (${task}).\n` });
            return;
          }
        } catch {}
      }

      // Don't pop an alert for timeouts; the server might still be working and status will update.
      appendLog({ ts: Date.now() / 1000, task: "ui", kind: "status", line: `Start request timed out (${task}). If it starts later, status will update automatically.\n` });
      return;
    }
    appendLog({ ts: Date.now() / 1000, task: "ui", kind: "status", line: `Start failed (${task}): ${e.message}\n` });
    alert(`Start failed (${task}): ${e.message}`);
  }
}

async function stopTask(task) {
  try {
    await api(`/api/tasks/${task}/stop`, { method: "POST" });
    await refreshAll();
  } catch (e) {
    if ((e.message || "").includes("Request timed out")) {
      appendLog({ ts: Date.now() / 1000, task: "ui", kind: "status", line: `Stop timed out (${task}). Checking status…\n` });
      for (let i = 0; i < 20; i++) {
        await sleep(500);
        try {
          const tasks = await api("/api/tasks");
          updateTaskUI("naukri", tasks.naukri);
          updateTaskUI("bot", tasks.bot);
          updateTaskUI("linkedin", tasks.linkedin);
          if (tasks[task] && !tasks[task].running) {
            appendLog({ ts: Date.now() / 1000, task: "ui", kind: "status", line: `Stop confirmed (${task}).\n` });
            return;
          }
        } catch {}
      }

      appendLog({ ts: Date.now() / 1000, task: "ui", kind: "status", line: `Stop request timed out (${task}). Status will update automatically.\n` });
      return;
    }
    appendLog({ ts: Date.now() / 1000, task: "ui", kind: "status", line: `Stop failed (${task}): ${e.message}\n` });
    alert(`Stop failed (${task}): ${e.message}`);
  }
}

async function saveSettings() {
  try {
    const payload = {
      email: $("cfg-email").value.trim(),
      password: $("cfg-password").value,
      resume_path: $("cfg-resume-path").value.trim(),
      job_titles: $("cfg-job-titles").value.trim(),

      linkedin_email: $("cfg-linkedin-email").value.trim(),
      linkedin_password: $("cfg-linkedin-password").value.trim(),
      linkedin_phone: $("cfg-linkedin-phone").value.trim(),
      reed_email: $("cfg-reed-email").value.trim(),
      reed_password: $("cfg-reed-password").value.trim(),
      ctc_inr: $("cfg-ctc-inr") ? $("cfg-ctc-inr").value.trim() : "",
    };
    // Include per-agent region selections
    ["naukri","linkedin","intl_linkedin","intl_indeed","intl_reed","intl_crawler"].forEach(id => {
      const el = $("region-" + id);
      if (el) payload["region_" + id] = el.value;
    });

    await api("/api/config", { method: "PUT", body: JSON.stringify(payload) });
    setPill($("settingsSaved"), "Saved", "ok");
    setTimeout(() => setPill($("settingsSaved"), "Saved", "muted"), 1500);
    await refreshAll();
    await refreshResumeStatus();
  } catch (e) {
    appendLog({ ts: Date.now() / 1000, task: "ui", kind: "status", line: `Save settings failed: ${e.message}\n` });
    alert(`Save settings failed: ${e.message}`);
  }
}

async function saveScheduleForTask(task) {
  try {
    const keys = SCHEDULE_CONFIG[task];
    if (!keys) return;
    const timesEl = $(`sch-times-${task}`);
    const enabledEl = $(`sch-enabled-${task}`);
    if (!timesEl || !enabledEl) return;

    const payload = {};
    payload[keys.enabled] = enabledEl.checked;
    payload[keys.times] = parseTimes(timesEl.value);

    await api("/api/config", { method: "PUT", body: JSON.stringify(payload) });

    let syncNote = "Saved";
    if (isCloudMode()) {
      syncNote = "Saved (Vercel config only)";
      appendLog({ ts: Date.now() / 1000, task: "scheduler", kind: "status", line: "Schedule saved in serverless storage for this deployment instance. Use vercel.json or the GitHub Actions workflow for durable cloud schedules.\n" });
    } else {
      try {
        await api("/api/schedules/system/sync", { method: "POST", body: "{}" });
        syncNote = "Saved & synced";
        await refreshSystemSchedules();
      } catch (syncErr) {
        // Cron is optional. The in-app scheduler still runs while this dashboard is open/server is running.
        syncNote = "Saved (in-app scheduler)";
        appendLog({ ts: Date.now() / 1000, task: "scheduler", kind: "status", line: `System cron sync skipped: ${syncErr.message}\n` });
      }
    }

    const pill = $(`sch-status-${task}`);
    if (pill) {
      pill.textContent = `✓ ${syncNote}`;
      pill.className = "pill pill--ok";
      setTimeout(() => refreshAll(), 1000);
    }
  } catch (e) {
    alert(`Save schedule failed: ${e.message}`);
  }
}

window.refreshAll = refreshAll;
window.emergencyStopAll = emergencyStopAll;
window.shutdownDashboard = shutdownDashboard;

function bind() {
  if (bindingsInstalled) return;
  bindingsInstalled = true;
  $("deleteSchedule-naukri").addEventListener("click", () => deleteSchedule("naukri"));
  $("deleteSchedule-bot").addEventListener("click", () => deleteSchedule("bot"));
  $("deleteSchedule-linkedin").addEventListener("click", () => deleteSchedule("linkedin"));
  if ($("deleteSchedule-intl_linkedin")) $("deleteSchedule-intl_linkedin").addEventListener("click", () => deleteSchedule("intl_linkedin"));
  $("deleteSchedule-intl_indeed").addEventListener("click", () => deleteSchedule("intl_indeed"));
  $("deleteSchedule-intl_reed").addEventListener("click", () => deleteSchedule("intl_reed"));
  $("deleteSchedule-intl_crawler").addEventListener("click", () => deleteSchedule("intl_crawler"));
  const btnDelLeadScraper = $("deleteSchedule-lead_scraper");
  if (btnDelLeadScraper) btnDelLeadScraper.addEventListener("click", () => deleteSchedule("lead_scraper"));

  $("uploadResume").addEventListener("click", uploadResume);
  $("deleteResume").addEventListener("click", deleteResume);

  const verifyCronBtn = $("verifyCronBtn");
  if (verifyCronBtn) {
    verifyCronBtn.addEventListener("click", async () => {
      if (isCloudMode()) {
        alert("System crontab verification is local-only. Vercel uses vercel.json cron and the GitHub Actions worker for scheduled automation.");
        return;
      }
      try {
        const originalText = verifyCronBtn.textContent;
        verifyCronBtn.textContent = "⏳ Verifying...";
        verifyCronBtn.disabled = true;
        
        const data = await api("/api/schedules/system");
        let msg = "Active System Crontab Entries:\n\n";
        const cron = data && data.cron;
        
        if (!cron) msg += "Cron data not available.";
        else if (!cron.available) msg += (cron.error || "System cron not available.");
        else {
          const tasks = cron.tasks || {};
          const fmt = (arr) => (arr && arr.length ? arr.join(", ") : "None");
          
          msg += `🤖 Naukri Job Applier: ${fmt(tasks.naukri)}\n`;
          msg += `🤖 Naukri Bot: ${fmt(tasks.bot)}\n`;
          msg += `🤖 LinkedIn: ${fmt(tasks.linkedin)}\n`;
          msg += `🤖 Intl Indeed: ${fmt(tasks.intl_indeed)}\n`;
          msg += `🤖 Intl Reed: ${fmt(tasks.intl_reed)}\n`;
          msg += `🤖 Intl Crawler: ${fmt(tasks.intl_crawler)}\n`;
          if (tasks.lead_scraper) msg += `🤖 Lead Scraper: ${fmt(tasks.lead_scraper)}\n`;
          
          if (cron.unparsed && cron.unparsed.length > 0) {
            msg += `\n⚠️ Unparsed or external entries detected (${cron.unparsed.length})`;
          }
        }
        
        verifyCronBtn.textContent = originalText;
        verifyCronBtn.disabled = false;
        alert(msg);
      } catch (e) {
        verifyCronBtn.textContent = "🔍 Verify System Crontab";
        verifyCronBtn.disabled = false;
        alert("Failed to fetch system cron: " + e.message);
      }
    });
  }

  const persistHeadless = async () => {
    try {
      await api("/api/config", {
        method: "PUT",
        body: JSON.stringify({
          ui_headless_naukri: $("headless-naukri").checked,
          ui_headless_bot: $("headless-bot").checked,
          ui_headless_linkedin: $("headless-linkedin").checked,
          ui_headless_intl_linkedin: $("headless-intl_linkedin") ? $("headless-intl_linkedin").checked : true,
          ui_headless_intl_indeed: $("headless-intl_indeed").checked,
          ui_headless_intl_reed: $("headless-intl_reed").checked,
          ui_headless_intl_crawler: $("headless-intl_crawler").checked,
          ui_headless_lead_scraper: $("headless-lead_scraper") ? $("headless-lead_scraper").checked : true,
        }),
      });
    } catch {}
  };
  $("headless-naukri").addEventListener("change", persistHeadless);
  $("headless-bot").addEventListener("change", persistHeadless);
  $("headless-linkedin").addEventListener("change", persistHeadless);
  if ($("headless-intl_linkedin")) $("headless-intl_linkedin").addEventListener("change", persistHeadless);
  $("headless-intl_indeed").addEventListener("change", persistHeadless);
  $("headless-intl_reed").addEventListener("change", persistHeadless);
  $("headless-intl_crawler").addEventListener("change", persistHeadless);
  if ($("headless-lead_scraper")) $("headless-lead_scraper").addEventListener("change", persistHeadless);

  // Auto-save schedule when the "Enable Schedule" toggle is clicked
  document.querySelectorAll("[id^='sch-enabled-']").forEach(el => {
    el.addEventListener("change", () => {
      const task = el.id.replace("sch-enabled-", "");
      saveScheduleForTask(task);
    });
  });

  // Theme Toggle Logic
  const themeToggleBtn = $("themeToggleBtn");
  if (themeToggleBtn) {
    const sunIcon = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="4"/><path d="M12 2v2"/><path d="M12 20v2"/><path d="m4.93 4.93 1.41 1.41"/><path d="m17.66 17.66 1.41 1.41"/><path d="M2 12h2"/><path d="M20 12h2"/><path d="m6.34 17.66-1.41 1.41"/><path d="m19.07 4.93-1.41 1.41"/></svg>';
    const moonIcon = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z"/></svg>';

    const savedTheme = localStorage.getItem("theme");
    if (savedTheme) {
      document.documentElement.setAttribute("data-theme", savedTheme);
      themeToggleBtn.innerHTML = savedTheme === "dark" ? sunIcon : moonIcon;
    }
    
    themeToggleBtn.addEventListener("click", () => {
      const currentTheme = document.documentElement.getAttribute("data-theme");
      const newTheme = currentTheme === "dark" ? "light" : "dark";
      document.documentElement.setAttribute("data-theme", newTheme);
      localStorage.setItem("theme", newTheme);
      themeToggleBtn.innerHTML = newTheme === "dark" ? sunIcon : moonIcon;
    });
  }

  // Per-agent region pickers: auto-save on change + compatibility warnings
  // Naukri = India-only, Reed = UK/Europe-only
  const REGION_COMPAT = {
    intl_reed:    { allowed: ["European"],  badge: "UK only",    warning: "Reed.co.uk is UK/Europe-only" },
  };

  function updateRegionWarnings() {
    document.querySelectorAll(".region-picker").forEach(sel => {
      const task = sel.dataset.task;
      const parentEl = sel.parentElement;
      // Remove existing warning
      const existing = parentEl.querySelector(".region-warn");
      if (existing) existing.remove();

      const rule = REGION_COMPAT[task];
      if (rule && !rule.allowed.includes(sel.value)) {
        const warn = document.createElement("span");
        warn.className = "region-warn pill pill--bad";
        warn.textContent = rule.badge;
        warn.title = rule.warning + " — agent will skip when started with this region. Change to " + rule.allowed.join("/") + ".";
        warn.style.cssText = "cursor:help;font-size:10px;margin-left:6px;padding:2px 6px;";
        parentEl.appendChild(warn);
      }
    });
  }

  document.querySelectorAll(".region-picker").forEach(sel => {
    sel.addEventListener("change", async () => {
      const task = sel.dataset.task;
      try {
        await api("/api/config", {
          method: "PUT",
          body: JSON.stringify({ ["region_" + task]: sel.value }),
        });
      } catch {}
      updateRegionWarnings();
    });
  });

  // Run on page load (deferred so refreshAll() has set the values first)
  setTimeout(updateRegionWarnings, 500);

  if ($("clearDataBtn")) {
    $("clearDataBtn").addEventListener("click", async () => {
      if (confirm("Are you sure you want to clear all settings and logs? This cannot be undone.")) {
        try {
          await api("/api/data", { method: "DELETE" });
          document.querySelectorAll(".log").forEach(el => el.innerHTML = "");
          pending = [];
          seen.clear();
          minTs = Date.now() / 1000;
          lastSeenTs = Math.max(lastSeenTs, minTs);
          await refreshAll();
          alert("Data cleared successfully.");
        } catch (e) {
          alert(`Failed to clear data: ${e.message}`);
        }
      }
    });
  }

  if ($("refreshBtn")) {
    $("refreshBtn").addEventListener("click", async () => {
      try {
        await refreshAll();
        await refreshSystemSchedules();
        await refreshResumeStatus();
      } catch (e) {
        appendLog({ ts: Date.now() / 1000, task: "ui", kind: "status", line: `Refresh failed: ${e.message}\n` });
        alert(`Refresh failed: ${e.message}`);
      }
    });
  }
  document.querySelectorAll(".clear-logs-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      const task = btn.dataset.task;
      pending = pending.filter(evt => evt.task !== task);
      const logEl = $("log-" + task);
      if (logEl) logEl.innerHTML = "";
      triggerHistory[task] = [];
      updateTriggerUI(task);
    });
  });

  $("start-naukri").addEventListener("click", () => startTask("naukri"));
  $("stop-naukri").addEventListener("click", () => stopTask("naukri"));

  $("start-bot").addEventListener("click", () => startTask("bot"));
  $("stop-bot").addEventListener("click", () => stopTask("bot"));

  $("start-linkedin").addEventListener("click", () => startTask("linkedin"));
  $("stop-linkedin").addEventListener("click", () => stopTask("linkedin"));

  if ($("start-intl_linkedin")) $("start-intl_linkedin").addEventListener("click", () => startTask("intl_linkedin"));
  if ($("stop-intl_linkedin")) $("stop-intl_linkedin").addEventListener("click", () => stopTask("intl_linkedin"));

  $("start-intl_indeed").addEventListener("click", () => startTask("intl_indeed"));
  $("stop-intl_indeed").addEventListener("click", () => stopTask("intl_indeed"));
  $("start-intl_reed").addEventListener("click", () => startTask("intl_reed"));
  $("stop-intl_reed").addEventListener("click", () => stopTask("intl_reed"));
  $("start-intl_crawler").addEventListener("click", () => startTask("intl_crawler"));
  $("stop-intl_crawler").addEventListener("click", () => stopTask("intl_crawler"));

  $("start-lead_scraper").addEventListener("click", () => startTask("lead_scraper"));
  $("stop-lead_scraper").addEventListener("click", () => stopTask("lead_scraper"));

  $("saveSettings").addEventListener("click", saveSettings);
  if ($("panicStopBtn")) $("panicStopBtn").addEventListener("click", emergencyStopAll);
  if ($("emergencyStopBtn")) $("emergencyStopBtn").addEventListener("click", emergencyStopAll);
  if ($("quitDashboardBtn")) $("quitDashboardBtn").addEventListener("click", shutdownDashboard);
  // Per-card save schedule buttons
  document.querySelectorAll(".save-schedule-btn").forEach((btn) => {
    btn.addEventListener("click", () => saveScheduleForTask(btn.dataset.task));
  });

  // Low-frequency status poll in case tasks started externally.
  setInterval(refreshTaskStatuses, 8000);

  // Websocket fallback. This stays dormant until login, so the login screen is quiet.
  setInterval(async () => {
    if (!isAuthenticated || wsConnected || document.hidden || logHistoryPollBusy) return;
    logHistoryPollBusy = true;
    try { await fetchHistoryIncremental(200); } catch {}
    finally { logHistoryPollBusy = false; }
  }, 5000);

  // Applications Page Logic
  const appsAgentFilter = $("apps-agent-filter");
  const appsTableBody = $("appsTableBody");
  
  const renderApplications = async (showLoading = false) => {
    if (showLoading && appsTableBody) {
        appsTableBody.innerHTML = '<tr><td colspan="5" style="padding: 16px; text-align: center; color: var(--text-muted);">Loading...</td></tr>';
    }
    
    try {
      const data = await api("/api/applications");
      if (!data || !data.applications) throw new Error("Failed to load");
      
      let logs = data.applications;
      const agentFilter = appsAgentFilter ? appsAgentFilter.value : "All";
      if (agentFilter !== "All") {
        logs = logs.filter(log => log.agent.includes(agentFilter) || log.agent === agentFilter);
      }
      
      if (logs.length === 0) {
         if (appsTableBody) appsTableBody.innerHTML = '<tr><td colspan="5" style="padding: 16px; text-align: center; color: var(--text-muted);">No applications found.</td></tr>';
         return;
      }
      
      if (appsTableBody) {
        appsTableBody.innerHTML = logs.map(log => {
          const dateStr = new Date(log.timestamp).toLocaleString();
          return `
            <tr style="border-bottom: 1px solid var(--border);">
              <td style="padding: 8px;">${dateStr}</td>
              <td style="padding: 8px;">${log.agent}</td>
              <td style="padding: 8px;">${log.company}</td>
              <td style="padding: 8px;">${log.role}</td>
              <td style="padding: 8px;"><a href="${log.url}" target="_blank" style="color: var(--primary);">View Job</a></td>
            </tr>
          `;
        }).join("");
      }
    } catch (err) {
      if (appsTableBody) appsTableBody.innerHTML = `<tr><td colspan="5" style="padding: 16px; text-align: center; color: var(--danger);">${err.message}</td></tr>`;
    }
  };

  if (appsAgentFilter) {
    appsAgentFilter.addEventListener("change", () => renderApplications(true));
  }
  
  const refreshAppsBtn = $("refresh-apps-btn");
  if (refreshAppsBtn) {
    refreshAppsBtn.addEventListener("click", () => renderApplications(true));
  }
  
  // Auto-refresh only when authenticated, visible, and the Applications tab is open.
  setInterval(async () => {
    if (!isAuthenticated || document.hidden || appsPollBusy || !isPageActive("page-applications")) return;
    appsPollBusy = true;
    try { await renderApplications(false); } finally { appsPollBusy = false; }
  }, 15000);
  
  // Hook into tab switching to render when Applications tab is clicked
  document.querySelectorAll(".tab").forEach((tab) => {
    tab.addEventListener("click", () => {
      if (tab.dataset.tab === "applications") {
        renderApplications(true);
      }
    });
  });

  // Outreach Page Logic
  const outreachSearch = $("outreach-search");
  const outreachStatusFilter = $("outreach-status-filter");
  const outreachTableBody = $("outreachTableBody");

  const renderOutreach = async (showLoading = false) => {
    if (showLoading && outreachTableBody) {
        outreachTableBody.innerHTML = '<tr><td colspan="5" style="padding: 16px; text-align: center; color: var(--text-muted);">Loading...</td></tr>';
    }
    
    try {
      const leads = await api("/api/leads");
      if (!Array.isArray(leads)) throw new Error("Failed to load");
      
      let filtered = leads;
      const term = outreachSearch ? outreachSearch.value.toLowerCase() : "";
      if (term) {
        filtered = filtered.filter(l => 
          (l.company || "").toLowerCase().includes(term) || 
          (l.email || "").toLowerCase().includes(term) ||
          (l.content || "").toLowerCase().includes(term)
        );
      }
      
      const statusFilter = outreachStatusFilter ? outreachStatusFilter.value : "All";
      if (statusFilter !== "All") {
        filtered = filtered.filter(l => l.status === statusFilter);
      }
      
      if (filtered.length === 0) {
         if (outreachTableBody) outreachTableBody.innerHTML = '<tr><td colspan="5" style="padding: 16px; text-align: center; color: var(--text-muted);">No leads found.</td></tr>';
         return;
      }
      
      if (outreachTableBody) {
        outreachTableBody.innerHTML = filtered.map((lead, idx) => {
          const dateStr = new Date(lead.date).toLocaleString();
          const truncatedContent = lead.content && lead.content.length > 80 ? lead.content.substring(0, 80) + "..." : (lead.content || "");
          const hasMore = lead.content && lead.content.length > 80;
          const statusColor = lead.status === "Reached" ? "var(--success)" : "var(--accent)";
          const escapedContent = (lead.content || "").replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/\n/g, '<br>');
          const escapedTruncated = truncatedContent.replace(/</g, '&lt;').replace(/>/g, '&gt;');
          
          return `
            <tr style="border-bottom: 1px solid var(--border);">
              <td style="padding: 8px;">${dateStr}</td>
              <td style="padding: 8px;"><strong>${lead.company}</strong><br><span style="font-size:11px;color:var(--muted)">${lead.name}</span></td>
              <td style="padding: 8px;">
                <div class="lead-content-toggle" data-idx="${idx}" style="cursor:${hasMore ? 'pointer' : 'default'};" title="${hasMore ? 'Click to expand/collapse' : ''}">
                  <span class="lead-content-short" id="lead-short-${idx}">${escapedTruncated}</span>
                  <span class="lead-content-full" id="lead-full-${idx}" style="display:none; white-space: pre-wrap;">${escapedContent}</span>
                  ${hasMore ? '<span style="font-size:10px;color:var(--primary);margin-left:4px;" class="lead-toggle-hint" id="lead-hint-${idx}">▶ show</span>' : ''}
                </div>
                <a href="${lead.link}" target="_blank" style="font-size:11px;color:var(--primary);display:inline-block;margin-top:4px;">View Post</a>
              </td>
              <td style="padding: 8px;">${lead.email}</td>
              <td style="padding: 8px; white-space: nowrap;">
                <button class="btn btn--sm btn--primary mail-lead-btn" data-id="${lead.id}" data-email="${lead.email}" data-company="${lead.company}" data-name="${lead.name}" data-status="${lead.status}" style="margin-right: 4px;">✉️ Mail</button>
                <button class="btn btn--sm btn--ghost toggle-lead-btn" data-id="${lead.id}" title="Toggle status" style="margin-right: 4px; padding: 4px 8px;">🔄</button>
                <button class="btn btn--sm btn--ghost delete-lead-btn" data-id="${lead.id}" title="Delete lead" style="margin-right: 4px; padding: 4px 8px; color: var(--danger);">🗑️</button>
                <span class="pill" style="font-size: 10px; padding: 2px 6px; background-color: ${statusColor}1A; color: ${statusColor}; border: 1px solid ${statusColor}4D;">${lead.status}</span>
              </td>
            </tr>
          `;
        }).join("");
        
        // Attach toggle event listeners for expandable content
        document.querySelectorAll(".lead-content-toggle").forEach(toggle => {
          toggle.addEventListener("click", (e) => {
            // Don't toggle if user clicked the link
            if (e.target.tagName === "A") return;
            const idx = toggle.dataset.idx;
            const shortEl = document.getElementById(`lead-short-${idx}`);
            const fullEl = document.getElementById(`lead-full-${idx}`);
            const hintEl = document.getElementById(`lead-hint-${idx}`);
            if (!shortEl || !fullEl) return;
            const isExpanded = fullEl.style.display !== "none";
            shortEl.style.display = isExpanded ? "" : "none";
            fullEl.style.display = isExpanded ? "none" : "";
            if (hintEl) hintEl.textContent = isExpanded ? "▶ show" : "▼ hide";
          });
        });
        
        // Attach event listeners to Mail buttons
        document.querySelectorAll(".mail-lead-btn").forEach(btn => {
          btn.addEventListener("click", async (e) => {
            const id = btn.dataset.id;
            const email = btn.dataset.email;
            const company = btn.dataset.company;
            const name = btn.dataset.name;
            
            const originalText = btn.textContent;
            btn.textContent = "⏳ Drafting...";
            btn.disabled = true;

            try {
              // Call the backend to draft the email with attachment and the correct sender email
              await api(`/api/leads/${id}/draft_email`, {
                method: "POST",
                body: JSON.stringify({ email, company, name })
              });
              
              // After drafting, mark it as reached
              await api(`/api/leads/${id}/reach`, { method: "POST" });
              renderOutreach(false);
            } catch (err) {
              console.error("Failed to draft email or mark as reached", err);
              alert("Failed to open Mail app. Check if Mail is configured properly.");
            } finally {
              btn.textContent = originalText;
              btn.disabled = false;
            }
          });
        });
        
        // Attach event listeners to Toggle buttons
        document.querySelectorAll(".toggle-lead-btn").forEach(btn => {
          btn.addEventListener("click", async () => {
            const id = btn.dataset.id;
            try {
              btn.disabled = true;
              await api(`/api/leads/${id}/toggle_status`, { method: "POST" });
              renderOutreach(false);
            } catch (err) {
              alert("Failed to toggle status: " + err.message);
              btn.disabled = false;
            }
          });
        });
        
        // Attach event listeners to Delete buttons
        document.querySelectorAll(".delete-lead-btn").forEach(btn => {
          btn.addEventListener("click", async () => {
            if (!confirm("Are you sure you want to delete this lead?")) return;
            const id = btn.dataset.id;
            try {
              btn.disabled = true;
              await api(`/api/leads/${id}`, { method: "DELETE" });
              renderOutreach(false);
            } catch (err) {
              alert("Failed to delete lead: " + err.message);
              btn.disabled = false;
            }
          });
        });
      }
    } catch (err) {
      if (outreachTableBody) outreachTableBody.innerHTML = `<tr><td colspan="5" style="padding: 16px; text-align: center; color: var(--danger);">${err.message}</td></tr>`;
    }
  };

  if (outreachSearch) outreachSearch.addEventListener("input", () => renderOutreach(false));
  if (outreachStatusFilter) outreachStatusFilter.addEventListener("change", () => renderOutreach(false));
  
  const refreshOutreachBtn = $("refresh-outreach-btn");
  if (refreshOutreachBtn) {
    refreshOutreachBtn.addEventListener("click", () => renderOutreach(true));
  }

  const mailAllBtn = $("mail-all-reachout-btn");
  if (mailAllBtn) {
    mailAllBtn.addEventListener("click", async () => {
      if (!confirm(`Are you sure you want to trigger Mail drafts for all pending reachouts? This might open multiple windows.`)) return;
      
      const originalText = mailAllBtn.textContent;
      mailAllBtn.textContent = "⏳ Mailing...";
      mailAllBtn.disabled = true;
      
      try {
        await api("/api/leads/mail_all_reachouts", { method: "POST" });
        await renderOutreach(false);
      } catch (err) {
        alert("Failed to mail reachouts: " + err.message);
      } finally {
        mailAllBtn.textContent = originalText;
        mailAllBtn.disabled = false;
      }
    });
  }

  document.querySelectorAll(".tab").forEach((tab) => {
    tab.addEventListener("click", () => {
      if (tab.dataset.tab === "outreach") {
        renderOutreach(true);
      }
    });
  });

  // --- Google Drive Sync Logic ---
  const GOOGLE_DRIVE_API_BASE = 'https://www.googleapis.com/drive/v3/files';
  const UPLOAD_BASE = 'https://www.googleapis.com/upload/drive/v3/files';
  let googleTokenClient;
  let googleClientId = "";

  async function getGoogleClient() {
    if (!googleClientId) {
      const sysInfo = await api("/api/system_info");
      googleClientId = sysInfo.google_client_id || "";
    }
    if (!googleClientId) throw new Error('Google Client ID is not configured on the server. Add GOOGLE_CLIENT_ID to .env.');
    if (!googleTokenClient && window.google) {
      googleTokenClient = google.accounts.oauth2.initTokenClient({
        client_id: googleClientId,
        scope: 'https://www.googleapis.com/auth/drive.appdata',
        callback: (tokenResponse) => {
          if (tokenResponse && tokenResponse.access_token) {
            sessionStorage.setItem('googleToken', tokenResponse.access_token);
            updateDriveUI();
            alert('Connected to Google Drive! ☁️');
          }
        },
      });
    }
    return googleTokenClient;
  }

  function getDriveToken() {
    return sessionStorage.getItem('googleToken');
  }

  function handleExpiredToken() {
    sessionStorage.removeItem('googleToken');
    updateDriveUI();
  }

  function updateDriveUI() {
    const hasToken = !!getDriveToken();
    if ($("googleAuthBtn")) $("googleAuthBtn").style.display = hasToken ? "none" : "inline-block";
    if ($("googleConnectedState")) $("googleConnectedState").style.display = hasToken ? "flex" : "none";
  }

  function setSyncingState(isSyncing) {
  }

  async function findBackupFile(token) {
    const query = new URLSearchParams({
      spaces: 'appDataFolder',
      q: "name='naukri_backup.json'",
      fields: 'files(id, name, modifiedTime)'
    });
    const res = await fetch(`${GOOGLE_DRIVE_API_BASE}?${query.toString()}`, {
      headers: { Authorization: `Bearer ${token}` }
    });
    if (!res.ok) {
      if (res.status === 401) handleExpiredToken();
      throw new Error('Google Drive session expired or search failed.');
    }
    const data = await res.json();
    return data.files && data.files.length > 0 ? data.files[0] : null;
  }

  async function uploadBackup(token, configData) {
    const existingFile = await findBackupFile(token);
    const metadata = { name: 'naukri_backup.json' };
    let url = `${UPLOAD_BASE}?uploadType=multipart`;
    let method = 'POST';
    
    if (existingFile) {
      url = `${UPLOAD_BASE}/${existingFile.id}?uploadType=multipart`;
      method = 'PATCH';
    } else {
      metadata.parents = ['appDataFolder'];
    }
    
    const fileContent = JSON.stringify(configData);
    const formData = new FormData();
    formData.append('metadata', new Blob([JSON.stringify(metadata)], { type: 'application/json' }));
    formData.append('file', new Blob([fileContent], { type: 'application/json' }));

    const res = await fetch(url, {
      method,
      headers: { Authorization: `Bearer ${token}` },
      body: formData
    });
    if (!res.ok) {
      if (res.status === 401) handleExpiredToken();
      throw new Error('Failed to upload backup to Google Drive');
    }
  }

  async function downloadBackup(token) {
    const file = await findBackupFile(token);
    if (!file) return null;
    const res = await fetch(`${GOOGLE_DRIVE_API_BASE}/${file.id}?alt=media`, {
      headers: { Authorization: `Bearer ${token}` }
    });
    if (!res.ok) {
      if (res.status === 401) handleExpiredToken();
      throw new Error('Failed to download backup from Google Drive');
    }
    return await res.json();
  }

  // --- UI Bindings ---
  updateDriveUI();

  if ($("googleAuthBtn")) {
    $("googleAuthBtn").addEventListener("click", async () => {
      try {
        const client = await getGoogleClient();
        if (client) client.requestAccessToken({prompt: 'consent'});
        else alert('Google Identity Services not loaded.');
      } catch (err) {
        alert(err.message || String(err));
      }
    });
  }

  if ($("syncToDriveBtn")) {
    $("syncToDriveBtn").addEventListener("click", async () => {
      const token = getDriveToken();
      if (!token) return;
      const btn = $("syncToDriveBtn");
      const originalText = btn.textContent;
      try {
        btn.textContent = "Backing up...";
        btn.disabled = true;
        setSyncingState(true);
        const configData = await api("/api/config");
        await uploadBackup(token, configData);
        btn.textContent = "Success!";
      } catch (err) {
        alert(err.message);
        btn.textContent = "Failed";
      } finally {
        setSyncingState(false);
        setTimeout(() => { btn.textContent = originalText; btn.disabled = false; }, 2000);
      }
    });
  }

  if ($("syncFromDriveBtn")) {
    $("syncFromDriveBtn").addEventListener("click", async () => {
      const token = getDriveToken();
      if (!token) return;
      if (!confirm("This will overwrite your current settings with the ones from Google Drive. Continue?")) return;
      const btn = $("syncFromDriveBtn");
      const originalText = btn.textContent;
      try {
        btn.textContent = "Restoring...";
        btn.disabled = true;
        setSyncingState(true);
        const configData = await downloadBackup(token);
        if (!configData) {
          throw new Error('No backup found in Google Drive.');
        }
        await api("/api/config", { method: "PUT", body: JSON.stringify(configData) });
        await refreshAll();
        btn.textContent = "Success!";
      } catch (err) {
        alert(err.message);
        btn.textContent = "Failed";
      } finally {
        setSyncingState(false);
        setTimeout(() => { btn.textContent = originalText; btn.disabled = false; }, 2000);
      }
    });
  }

  if ($("googleDisconnectBtn")) {
    $("googleDisconnectBtn").addEventListener("click", () => {
      handleExpiredToken();
      alert('Disconnected from Google Drive.');
    });
  }

  // (Old syncTopbarBtn listener removed to prevent conflict with attach_drive_sync.js)

  if ($("settingsTopbarBtn")) {
    $("settingsTopbarBtn").addEventListener("click", () => switchTab("settings"));
  }
}


async function init() {
  if (initStarted) return;
  initStarted = true;
  loadApiKey();
  bind();

  try {
    await loadRuntimeInfo();
    await refreshAll();
    setAuthenticated(true);
    hideLoginOverlay();
    const logoutBtn = $("logoutBtn");
    if (logoutBtn) logoutBtn.style.display = "inline-block";
    setPill($("serverStatus"), "Connected", "ok");
    connectLogs();
    await refreshSystemSchedules();
    await refreshResumeStatus();

    // Load history even if websocket is blocked by the environment.
    try { await fetchHistoryIncremental(200); } catch {}
  } catch (e) {
    setAuthenticated(false);
    disconnectLogs();
    if (String(e.message || "").includes("Unauthorized")) {
      setPill($("serverStatus"), "Login required", "bad");
      showLoginOverlay();
      return;
    }
    setPill($("serverStatus"), "Error", "bad");
    appendLog({ ts: Date.now() / 1000, task: "ui", line: `Failed to load: ${e.message}\n` });
  }
}


init();
