/* ==========================================================================
   AI Agent Dashboard — JavaScript Controller
   ========================================================================== */

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------

let agentRunning = false;
let pollInterval = null;
let dataInterval = null;
let agentInitialized = false;
let agentPollBusy = false;
let agentDataPollBusy = false;
let feedLines = [];
const MAX_FEED_LINES = 200;

function isEmbeddedDashboard() {
    return !!document.getElementById('page-agent');
}

function dashboardAllowsAgentPolling() {
    try {
        if (typeof isAuthenticated !== 'undefined' && !isAuthenticated) return false;
    } catch (e) {}
    const embedded = isEmbeddedDashboard();
    if (!embedded) return true;
    const page = document.getElementById('page-agent');
    return !!(page && page.classList.contains('page--active'));
}

function shouldPollAgent() {
    return !document.hidden && dashboardAllowsAgentPolling();
}

function setText(id, value) {
    const el = document.getElementById(id);
    if (el) el.textContent = value;
}

// ---------------------------------------------------------------------------
// API helpers
// ---------------------------------------------------------------------------

async function agentApi(method, path, body = null) {
    const opts = {
        method,
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
    };
    if (body) opts.body = JSON.stringify(body);
    try {
        const resp = await fetch(path, opts);
        const data = await resp.json().catch(() => ({}));
        if (resp.status === 401) return { ok: false, unauthorized: true, running: false, error: 'Unauthorized' };
        return data;
    } catch (e) {
        console.error(`API error: ${path}`, e);
        return { ok: false, error: e.message };
    }
}

// ---------------------------------------------------------------------------
// Status polling
// ---------------------------------------------------------------------------

async function refreshStatus() {
    if (!shouldPollAgent()) return;
    const data = await agentApi('GET', '/api/agent/status');

    // Nav status
    const dot = document.getElementById('statusDot');
    const text = document.getElementById('statusText');

    if (data.running) {
        if (dot) dot.className = 'status-dot running';
        if (text) text.textContent = 'Running';
        agentRunning = true;
    } else if (data.ollama_connected) {
        if (dot) dot.className = 'status-dot online';
        if (text) text.textContent = 'Ready';
        agentRunning = false;
    } else {
        if (dot) dot.className = 'status-dot error';
        if (text) text.textContent = 'Ollama Offline';
        agentRunning = false;
    }

    // Hero model info
    const modelBadge = document.getElementById('heroModel');
    const ollamaBadge = document.getElementById('ollamaBadge');

    if (data.model && modelBadge) {
        modelBadge.textContent = `🧠 Model: ${data.model}`;
    }

    if (ollamaBadge) {
        if (data.ollama_connected) {
            ollamaBadge.textContent = '✅ Ollama Connected';
            ollamaBadge.className = 'pill pill--ok';
        } else {
            ollamaBadge.textContent = '❌ Ollama Offline';
            ollamaBadge.className = 'pill pill--bad';
        }
    }

    // Activity
    const activityCurrent = document.getElementById('activityCurrent');
    const activityIndicator = document.getElementById('activityIndicator');

    if (activityCurrent && activityIndicator) {
        if (data.running && data.activity) {
            activityCurrent.textContent = data.activity;
            activityIndicator.className = 'pill pill--ok';
            activityIndicator.textContent = 'Active';
        } else if (data.running) {
            activityCurrent.textContent = 'Agent is working...';
            activityIndicator.className = 'pill pill--ok';
            activityIndicator.textContent = 'Active';
        } else {
            activityCurrent.textContent = 'Agent is idle';
            activityIndicator.className = 'pill pill--muted';
            activityIndicator.textContent = 'Idle';
        }
    }

    // Live stats from running agent
    if (data.stats) {
        const s = data.stats;
        // We'll update these from the stats endpoint too, but running stats are more current
        if (data.running) {
            const elApplied = document.getElementById('statApplied');
            const elAnalyzed = document.getElementById('statAnalyzed');
            const elSkipped = document.getElementById('statSkipped');
            if (elApplied) elApplied.textContent = s.jobs_applied || 0;
            if (elAnalyzed) elAnalyzed.textContent = s.jobs_analyzed || 0;
            if (elSkipped) elSkipped.textContent = s.jobs_skipped || 0;
        }
    }

    // Update buttons
    const btnStart = document.getElementById('btnStart');
    const btnStop = document.getElementById('btnStop');
    if (btnStart) btnStart.disabled = agentRunning;
    if (btnStop) btnStop.disabled = !agentRunning;

    // Hero animation
    const hero = document.getElementById('heroSection');
    if (hero) {
        if (data.running) {
            hero.style.borderColor = 'rgba(59, 130, 246, 0.4)';
        } else {
            hero.style.borderColor = 'rgba(148, 163, 184, 0.1)';
        }
    }
}

async function refreshStats() {
    if (!shouldPollAgent()) return;
    const data = await agentApi('GET', '/api/agent/stats');
    if (!data.ok) return;

    setText('statApplied', data.today_applied || 0);
    setText('statAppliedTotal', `${data.total_applied || 0} total`);
    setText('statAnalyzed', data.total_analyzed || 0);
    setText('statSkipped', data.total_skipped || 0);
    setText('statAvgScore', data.avg_match_score > 0 ? `${data.avg_match_score}%` : '—');
    setText('statPending', data.pending_reviews || 0);
}

async function refreshDecisions() {
    if (!shouldPollAgent()) return;
    const data = await agentApi('GET', '/api/agent/decisions?limit=30');
    const container = document.getElementById('decisionsList');
    if (!container) return;

    if (!data.ok || !data.decisions || data.decisions.length === 0) {
        container.innerHTML = '<div class="feed-empty">No decisions yet — start the agent</div>';
        return;
    }

    container.innerHTML = data.decisions.map(d => {
        const badgeClass = d.decision === 'APPLY' ? 'apply' :
                          d.decision === 'SKIP' ? 'skip' : 'review';
        const score = d.match_score || 0;
        const scoreClass = score >= 70 ? 'score-high' :
                          score >= 50 ? 'score-mid' : 'score-low';
        const time = d.created_at ? new Date(d.created_at).toLocaleTimeString() : '';

        return `
            <div class="decision-item">
                <div class="decision-badge ${badgeClass}">${d.decision}</div>
                <div class="decision-info">
                    <div class="decision-title">${escHtml(d.job_title || 'Unknown')}</div>
                    <div class="decision-company">${escHtml(d.company || '')} · ${escHtml(d.platform || '')} · ${time}</div>
                    <div class="decision-reasoning">${escHtml(d.reasoning || '')}</div>
                </div>
                <div class="decision-score ${scoreClass}">
                    <span class="score-value">${Math.round(score)}</span>
                    <span class="score-label">score</span>
                </div>
            </div>
        `;
    }).join('');
}

async function refreshQueue() {
    if (!shouldPollAgent()) return;
    const data = await agentApi('GET', '/api/agent/queue');
    const container = document.getElementById('queueList');
    if (!container) return;

    if (!data.ok || !data.queue || data.queue.length === 0) {
        container.innerHTML = '<div class="feed-empty">No jobs in review queue</div>';
        return;
    }

    container.innerHTML = data.queue.map(q => {
        const score = q.match_score || 0;
        return `
            <div class="queue-item">
                <div class="queue-header">
                    <div>
                        <div class="queue-title">${escHtml(q.job_title || 'Unknown')}</div>
                        <div class="decision-company">${escHtml(q.company || '')} · Score: ${Math.round(score)}% · ${escHtml(q.platform || '')}</div>
                    </div>
                    <div class="queue-actions">
                        <button class="btn-sm btn-approve" onclick="approveJob(${q.id})">✓ Approve</button>
                        <button class="btn-sm btn-reject" onclick="rejectJob(${q.id})">✕ Reject</button>
                    </div>
                </div>
                <div class="decision-reasoning">${escHtml(q.reasoning || '')}</div>
            </div>
        `;
    }).join('');
}

async function refreshApplied() {
    if (!shouldPollAgent()) return;
    const data = await agentApi('GET', '/api/agent/applied?limit=30');
    const container = document.getElementById('appliedList');
    if (!container) return;

    if (!data.ok || !data.jobs || data.jobs.length === 0) {
        container.innerHTML = '<div class="feed-empty">No applications yet</div>';
        return;
    }

    container.innerHTML = data.jobs.map(j => {
        const score = j.match_score || 0;
        const time = j.applied_at ? new Date(j.applied_at).toLocaleString() : '';
        return `
            <div class="applied-item">
                <div class="applied-emoji">✅</div>
                <div class="applied-info">
                    <div class="applied-title">${escHtml(j.title || 'Unknown')}</div>
                    <div class="applied-meta">${escHtml(j.company || '')} · ${escHtml(j.platform || '')} · ${time}</div>
                </div>
                <div class="applied-score">${Math.round(score)}%</div>
            </div>
        `;
    }).join('');
}

// ---------------------------------------------------------------------------
// Actions
// ---------------------------------------------------------------------------

async function startAgent() {
    const platform = document.getElementById('platformSelect').value;
    const target = parseInt(document.getElementById('targetInput').value) || 20;
    const mode = document.getElementById('modeSelect').value;
    const headless = document.getElementById('headlessCheck').checked;

    const body = {
        platform,
        target,
        headless,
        dry_run: mode === 'dry_run',
        mode: mode === 'review' ? 'review' : 'auto',
    };

    const data = await agentApi('POST', '/api/agent/start', body);

    if (data.ok) {
        addFeedLine(`Agent started: ${platform}, target=${target}, mode=${mode}`, 'info');
        agentRunning = true;
        document.getElementById('btnStart').disabled = true;
        document.getElementById('btnStop').disabled = false;
    } else {
        addFeedLine(`Failed to start: ${data.detail || data.error || 'Unknown error'}`, 'warn');
    }
}

async function stopAgent() {
    const data = await agentApi('POST', '/api/agent/stop');
    if (data.ok) {
        addFeedLine('Stop requested — agent will finish current job and stop', 'warn');
    }
}

async function approveJob(id) {
    await agentApi('POST', `/api/agent/queue/${id}/approve`);
    addFeedLine(`Approved job #${id}`, 'apply');
    refreshQueue();
    refreshStats();
}

async function rejectJob(id) {
    await agentApi('POST', `/api/agent/queue/${id}/reject`);
    addFeedLine(`Rejected job #${id}`, 'skip');
    refreshQueue();
}

// ---------------------------------------------------------------------------
// Feed
// ---------------------------------------------------------------------------

function addFeedLine(text, type = '') {
    const feed = document.getElementById('activityFeed');
    if (!feed) return;

    // Remove empty message
    const empty = feed.querySelector('.feed-empty');
    if (empty) empty.remove();

    const line = document.createElement('div');
    line.className = `feed-line ${type}`;
    const time = new Date().toLocaleTimeString();
    line.textContent = `[${time}] ${text}`;

    feed.appendChild(line);
    feedLines.push(line);

    // Trim old lines
    while (feedLines.length > MAX_FEED_LINES) {
        const old = feedLines.shift();
        old.remove();
    }

    // Auto scroll
    feed.scrollTop = feed.scrollHeight;
}

// ---------------------------------------------------------------------------
// Tabs
// ---------------------------------------------------------------------------

function switchAgentTab(tabName) {
    document.querySelectorAll('.agent-tab').forEach(t => {
        t.classList.remove('active');
        t.classList.remove('tab--active');
        t.style.borderBottom = '';
        t.style.color = '';
    });
    document.querySelectorAll('.agent-tab-content, .tab-content').forEach(t => {
        t.classList.remove('active');
        t.style.display = 'none';
    });

    const panel = document.getElementById(`tab-${tabName}`);
    if (panel) {
        panel.classList.add('active');
        panel.style.display = 'block';
    }

    const btn = document.getElementById(`tab-btn-${tabName}`);
    if (btn) {
        btn.classList.add('active');
        btn.classList.add('tab--active');
        btn.style.borderBottom = '2px solid var(--accent)';
        btn.style.color = 'var(--text)';
    }

    if (tabName === 'decisions') refreshDecisions();
    else if (tabName === 'queue') refreshQueue();
    else if (tabName === 'applied') refreshApplied();
}


// ---------------------------------------------------------------------------
// Utilities
// ---------------------------------------------------------------------------

function escHtml(str) {
    if (!str) return '';
    return str.replace(/&/g, '&amp;').replace(/</g, '&lt;')
              .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

// ---------------------------------------------------------------------------
// Initialize
// ---------------------------------------------------------------------------

function stopAgentPanelPolling() {
    if (pollInterval) clearInterval(pollInterval);
    if (dataInterval) clearInterval(dataInterval);
    pollInterval = null;
    dataInterval = null;
    agentInitialized = false;
    agentPollBusy = false;
    agentDataPollBusy = false;
}

async function initAgent() {
    if (agentInitialized || !dashboardAllowsAgentPolling()) return;
    agentInitialized = true;

    await refreshStatus();
    await refreshStats();
    await refreshDecisions();

    pollInterval = setInterval(async () => {
        if (!shouldPollAgent() || agentPollBusy) return;
        agentPollBusy = true;
        try {
            await refreshStatus();
            if (agentRunning) await refreshStats();
        } finally {
            agentPollBusy = false;
        }
    }, 5000);

    dataInterval = setInterval(async () => {
        if (!shouldPollAgent() || agentDataPollBusy) return;
        agentDataPollBusy = true;
        try {
            await refreshStats();
            const activeTab = document.querySelector('.agent-tab-content.active, .tab-content.active');
            if (activeTab) {
                const id = activeTab.id.replace('tab-', '');
                if (id === 'decisions') await refreshDecisions();
                else if (id === 'queue') await refreshQueue();
                else if (id === 'applied') await refreshApplied();
            }
        } finally {
            agentDataPollBusy = false;
        }
    }, 20000);
}


// Embedded dashboards call this only when the AI Agent tab is opened.
window.initAgentPanel = initAgent;
window.stopAgentPanelPolling = stopAgentPanelPolling;
if (!isEmbeddedDashboard()) {
    initAgent();
}
