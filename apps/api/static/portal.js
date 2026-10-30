'use strict';
function newId() {
  if (typeof crypto.randomUUID === 'function') return crypto.randomUUID();
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  bytes[6] = (bytes[6] & 15) | 64;
  bytes[8] = (bytes[8] & 63) | 128;
  const hex = Array.from(bytes, value => value.toString(16).padStart(2, '0')).join('');
  return [hex.slice(0,8), hex.slice(8,12), hex.slice(12,16), hex.slice(16,20), hex.slice(20)].join('-');
}
let token = '', session = sessionStorage.getItem('cookieai-session') || newId();
sessionStorage.setItem('cookieai-session', session);
let policyState = null, skills = [], inspectedMemory = null, timer = null, taskCursor = null, noticeTimer = null;
let debugOpen = false, debugSection = 'process', latestTurn = null, runtimeConfig = null, chatBusy = false;
let historyOpen = false;
let activeTurnId = null;
const $ = id => document.getElementById(id);
function notice(message) { $('notice').textContent = message; clearTimeout(noticeTimer); noticeTimer = setTimeout(() => { $('notice').textContent = ''; }, 4500); }
function effectiveTheme() {
  const attr = document.documentElement?.getAttribute?.('data-theme');
  if (attr === 'dark' || attr === 'light') return attr;
  try { if (typeof matchMedia === 'function' && matchMedia('(prefers-color-scheme: dark)').matches) return 'dark'; } catch {}
  return 'light';
}
function syncThemeIcons() {
  const dark = effectiveTheme() === 'dark';
  if ($('icon-sun')) $('icon-sun').hidden = dark;
  if ($('icon-moon')) $('icon-moon').hidden = !dark;
  $('theme-toggle').setAttribute?.('aria-pressed', String(dark));
}
try { const stored = localStorage.getItem('cookieai-theme'); if (stored === 'dark' || stored === 'light') document.documentElement?.setAttribute('data-theme', stored); } catch {}
syncThemeIcons();
$('theme-toggle').onclick = () => {
  const next = effectiveTheme() === 'dark' ? 'light' : 'dark';
  document.documentElement?.setAttribute('data-theme', next);
  try { localStorage.setItem('cookieai-theme', next); } catch {}
  syncThemeIcons();
};
function textNode(tag, value, className) { const el = document.createElement(tag); el.textContent = value; if (className) el.className = className; return el; }
function fragmentNode(tag, className, children) { const el = document.createElement(tag); if (className) el.className = className; for (const child of children || []) el.append(child); return el; }
function relativeTime(iso) {
  if (!iso) return '';
  const seconds = (Date.now() - new Date(iso).getTime()) / 1000;
  if (seconds < 60) return 'just now';
  if (seconds < 3600) return Math.round(seconds / 60) + 'm ago';
  if (seconds < 86400) return Math.round(seconds / 3600) + 'h ago';
  return Math.round(seconds / 86400) + 'd ago';
}
async function api(path, body, method) {
  const response = await fetch(path, {method: method || (body === undefined ? 'GET' : 'POST'), headers: {'Authorization': 'Bearer ' + token, 'X-Session-ID': session, 'X-Purpose': 'personal assistant workspace', 'Content-Type': 'application/json'}, ...(body === undefined ? {} : {body: JSON.stringify(body)})});
  if (!response.ok) { let message = 'Request failed (' + response.status + ')'; try { const data = await response.json(); message = typeof data.detail === 'string' ? data.detail : message; } catch {} throw new Error(message); }
  return response.status === 204 ? null : response.json();
}
function formAction(id, action) { $(id).addEventListener('submit', async event => { event.preventDefault(); const button = event.submitter; if (button) button.disabled = true; try { await action(new FormData(event.target)); } catch (error) { notice(error.message); } finally { if (button) button.disabled = false; } }); }
function show(view) { for (const section of document.querySelectorAll('.view')) { const active = section.id === 'view-' + view; section.hidden = !active; if (active) section.setAttribute('aria-current', 'page'); else section.removeAttribute('aria-current'); } for (const button of document.querySelectorAll('.rail-item')) { if (button.dataset.view === view) button.setAttribute('aria-current', 'page'); else button.removeAttribute('aria-current'); } }
for (const button of document.querySelectorAll('.rail-item')) button.addEventListener('click', () => show(button.dataset.view));

async function loadSources() { const rows = await api('/v1/portal/sources'); $('sources').replaceChildren(); if (!rows.length) $('sources').append(textNode('p', 'Add a note to begin. Nothing is selected automatically.')); for (const row of rows) { const label = textNode('label', '', 'check source-item'); const input = document.createElement('input'); input.type = 'checkbox'; input.value = row.source_id; input.disabled = row.status !== 'ACTIVE'; label.append(input, textNode('span', row.title + ' · ' + row.disclosure.replaceAll('_', ' ').toLowerCase() + ' · r' + row.revision)); $('sources').append(label); } }
async function loadGoals() { const rows = await api('/v1/goals'); $('goals').replaceChildren(); for (const row of rows.filter(row => row.status === 'ACTIVE')) { const option = textNode('option', row.title || row.goal_id); option.value = row.goal_id; $('goals').append(option); } }
async function loadPrivacy() { policyState = await api('/v1/privacy'); $('privacy-state').textContent = JSON.stringify(policyState, null, 2); $('privacy-form').elements.mode.value = policyState.mode; }
async function loadSkills() { skills = await api('/v1/portal/skills'); $('skills').replaceChildren(); $('skill-select').replaceChildren(new Option('Use my explicit instructions', '')); $('confirm-select').replaceChildren(); for (const item of skills) { const card = textNode('article', '', 'card'); card.append(textNode('h3', item.procedure.name), textNode('p', item.status + ' · revision ' + item.revision), textNode('pre', JSON.stringify({conditions: item.procedure.preconditions, exceptions: item.procedure.known_failure_modes, contract: item.procedure.skill_contract}, null, 2))); $('skills').append(card); if (item.procedure.skill_contract) $('skill-select').append(new Option(item.procedure.name, item.skill_id)); if (item.procedure.tools.length === 1 && item.procedure.tools[0] === 'cookieai_handoff') $('confirm-select').append(new Option(item.procedure.name, item.skill_id)); } if (!skills.length) $('skills').append(textNode('p', 'No evidence-backed procedures yet. Successful observed runs feed the existing learning pipeline.')); }
async function loadTasks(append = false) { const result = await api('/v1/tasks' + (append && taskCursor ? '?after=' + encodeURIComponent(taskCursor) : '')); if (!append) $('tasks').replaceChildren(); taskCursor = result.next_cursor; for (const row of result.items) { const card = textNode('article', '', 'card'); card.append(textNode('p', row.task_id, 'task-title'), textNode('p', row.status + ' · revision ' + row.revision)); const actions = textNode('div', '', 'task-actions'); const open = textNode('button', 'Inspect result', 'secondary'); open.onclick = () => inspectTask(row.task_id).catch(error => notice(error.message)); actions.append(open); if (!['COMPLETED','FAILED','CANCELLED','EXHAUSTED','UNCERTAIN'].includes(row.status)) { for (const action of row.status === 'PAUSED' ? ['RESUME','CANCEL'] : ['PAUSE','CANCEL']) { const button = textNode('button', action.toLowerCase(), 'secondary'); button.onclick = async () => { try { await api('/v1/tasks/' + row.task_id + '/control', {action, expected_revision: row.revision}); await loadTasks(); } catch (error) { notice(error.message); } }; actions.append(button); } } card.append(actions); $('tasks').append(card); } if (taskCursor) { const more = textNode('button', 'Load more', 'secondary'); more.onclick = () => { more.remove(); loadTasks(true).catch(error => notice(error.message)); }; $('tasks').append(more); } }
async function inspectTask(id) { const task = await api('/v1/tasks/' + id); $('receipt').hidden = false; $('receipt-content').textContent = JSON.stringify(task, null, 2); $('artifact').replaceChildren(); for (const run of task.runs) { if (run.payload.verification?.criterion === 'HANDOFF' && run.payload.verification.verdict === 'PASS') { const button = textNode('button', 'Open handoff · run ' + run.sequence, 'secondary'); button.onclick = async () => { try { const artifact = await api('/v1/portal/tasks/' + id + '/artifacts/' + run.run_id); $('artifact').replaceChildren(textNode('h3', artifact.project), textNode('pre', artifact.markdown), textNode('h3', 'Disclosure receipt'), textNode('pre', JSON.stringify(artifact.disclosure, null, 2))); } catch (error) { notice(error.message); } }; $('artifact').append(button); } } }
async function health() { const status = await api('/v1/operations/status'); const ok = status.workers?.some(worker => !worker.stalled); $('health').className = 'status-dot' + (ok ? ' ok' : ' warn'); $('health').title = (ok ? 'Worker reporting progress' : 'Worker heartbeat unavailable') + ' · Last successful job: ' + (status.last_successful_job_at || 'not recorded') + ' · Redis: ' + status.redis; }

function switchSession(id) { clearTimeout(timer); session = id; sessionStorage.setItem('cookieai-session', session); }

async function loadConversations() {
  const rows = await api('/v1/portal/conversations');
  $('conversation-list').replaceChildren();
  if (!rows.length) { $('conversation-list').append(textNode('p', 'No conversations yet. Say something to start one.', 'conversation-empty')); return; }
  for (const row of rows) {
    const button = document.createElement('button');
    button.className = 'conversation-item' + (row.session_id === session ? ' active' : '');
    button.type = 'button';
    button.append(textNode('span', row.label, 'conversation-label'), textNode('span', row.turn_count + ' messages · ' + relativeTime(row.last_active_at), 'conversation-meta'));
    button.onclick = () => openConversation(row.session_id).catch(error => notice(error.message));
    $('conversation-list').append(button);
  }
}

async function openConversation(id, force = false) {
  if (chatBusy && !force) { notice('Wait for this reply before switching conversations.'); return; }
  if (id === session && !force) return;
  switchSession(id);
  const requestToken = token;
  setHistoryOpen(false);
  latestTurn = null;
  show('chat');
  resetCorrelationPanel();
  $('messages').replaceChildren(textNode('p', 'Loading this conversation…', 'empty-chat'));
  const turns = await api('/v1/portal/conversations/' + id + '/turns');
  if (!token || token !== requestToken || session !== id) return;
  $('messages').replaceChildren();
  $('chat-suggestions').hidden = turns.length > 0;
  if (!turns.length) $('messages').append(textNode('p', 'This conversation has no messages yet.', 'empty-chat'));
  for (const turn of turns) {
    $('messages').append(fragmentNode('div', 'msg msg-user', [document.createTextNode(turn.message)]));
    if (turn.answer) $('messages').append(fragmentNode('div', 'msg msg-assistant', [document.createTextNode(turn.answer)]));
    else if (['FAILED', 'CANCELLED', 'UNCERTAIN'].includes(turn.status)) $('messages').append(fragmentNode('div', 'msg msg-assistant failed', [document.createTextNode('This request did not complete.')]));
  }
  await loadConversations();
}

function newConversation() {
  if (chatBusy) { notice('Wait for this reply before starting another conversation.'); return; }
  latestTurn = null;
  $('chat-suggestions').hidden = false;
  show('chat');
  switchSession(newId());
  setHistoryOpen(false);
  $('messages').replaceChildren(textNode('p', "Ask about anything you've shared with CookieAI. Related moments from every past conversation are correlated automatically — no session token required.", 'empty-chat'));
  resetCorrelationPanel();
  loadConversations().catch(error => notice(error.message));
}
$('new-conversation').onclick = newConversation;

let correlationEverOpened = false;
function setCorrelationOpen(open) {
  $('correlation-panel').hidden = !open;
  $('toggle-correlation').setAttribute?.('aria-pressed', String(open));
  if (open) correlationEverOpened = true;
}
$('toggle-correlation').onclick = () => setCorrelationOpen($('correlation-panel').hidden);
$('close-correlation').onclick = () => setCorrelationOpen(false);
function setCorrelationCount(count) {
  $('correlation-count').textContent = String(count);
  $('correlation-count').hidden = !count;
}

function resetCorrelationPanel() {
  correlationEverOpened = false;
  setCorrelationOpen(false);
  setCorrelationCount(0);
  $('correlation-note').textContent = "Send a message to see which past sessions relate to it.";
  $('correlation-results').replaceChildren();
}

function renderCorrelation(result) {
  $('correlation-note').textContent = result.note;
  $('correlation-results').replaceChildren();
  if (!result.sessions.length) { $('correlation-results').append(textNode('p', 'No related memories found yet.', 'correlation-empty')); return; }
  for (const entry of result.sessions) {
    const card = textNode('article', '', 'correlation-card' + (entry.is_current_session ? ' current' : ''));
    const head = textNode('div', '', 'correlation-card-head');
    head.append(textNode('span', entry.is_current_session ? 'This conversation' : 'Session ' + entry.session_id.slice(0, 8), 'correlation-session'), textNode('span', Math.round(entry.relevance * 100) + '% match', 'correlation-score'));
    card.append(head);
    if (entry.shared_terms.length || entry.entities.length) {
      const chips = textNode('div', '', 'chip-row');
      for (const term of entry.shared_terms.slice(0, 4)) chips.append(textNode('span', term, 'chip'));
      for (const entity of entry.entities.slice(0, 3)) chips.append(textNode('span', entity, 'chip'));
      card.append(chips);
    }
    const snippets = textNode('div', '', 'correlation-snippets');
    for (const memory of entry.memories.slice(0, 3)) snippets.append(textNode('p', memory.text, 'correlation-snippet'));
    card.append(snippets);
    $('correlation-results').append(card);
  }
}

async function runCorrelation(message) {
  $('correlation-note').textContent = 'Searching your past conversations…';
  try {
    const result = await api('/v1/portal/correlate', {query: message});
    setCorrelationCount(result.sessions.length);
    renderCorrelation(result);
    // Evidence stays in the inspector; never open a technical panel over chat.
  } catch (error) {
    $('correlation-note').textContent = error.message;
  }
}

formAction('connect-form', async () => {
  token = $('token').value.trim();
  const config = await api('/v1/portal/config');
  runtimeConfig = config;
  $('environment-note').hidden = !config.synthetic_demo && config.embedding_model !== 'hash-test';
  $('environment-note').textContent = config.synthetic_demo ? 'SYNTHETIC DEMO · test embeddings · no cloud inference or claimed learned skills' : 'Test embeddings · semantic retrieval quality is unverified';
  $('chat-demo-note').hidden = !config.synthetic_demo;
  await loadPrivacy();
  await loadConversations();
  $('token').value = '';
  $('connect-panel').hidden = true;
  $('workspace').hidden = false;
  $('disconnect').hidden = false;
  $('health').hidden = false;
  $('debug-toggle').hidden = false;
  $('model-label').hidden = false;
  $('model-label').textContent = config.model;
  await openConversation(session, true);
  notice('Connected. Review your workspace disclosure choice before adding information.');
});
$('disconnect').onclick = () => {
  token = '';
  clearTimeout(timer);
  clearTimeout(noticeTimer);
  policyState = null; inspectedMemory = null; skills = [];
  latestTurn = null; runtimeConfig = null; chatBusy = false;
  activeTurnId = null;
  setDebugOpen(false);
  $('debug-toggle').hidden = true;
  $('model-label').hidden = true;
  $('workspace').hidden = true;
  $('connect-panel').hidden = false;
  $('disconnect').hidden = true;
  $('health').hidden = true;
  for (const id of ['sources', 'skills', 'tasks', 'messages', 'artifact', 'receipt-content', 'memory-detail', 'privacy-state', 'goals', 'confirm-select', 'skill-select', 'conversation-list', 'correlation-results']) $(id).replaceChildren();
  for (const id of ['source-form', 'brief-form', 'chat-form', 'goal-form', 'memory-find', 'memory-correct']) $(id).reset();
  $('receipt').hidden = true;
  $('chat-demo-note').hidden = true;
  resetCorrelationPanel();
  $('notice').textContent = '';
};
formAction('source-form', async data => { await api('/v1/portal/sources', {title: data.get('title'), content: data.get('content'), disclosure: data.get('disclosure')}); $('source-form').reset(); await loadSources(); notice('Source registered. Select it explicitly for a task.'); });
formAction('goal-form', async data => { await api('/v1/goals', {title: data.get('title')}); $('goal-form').reset(); await loadGoals(); notice('Goal created.'); });
formAction('brief-form', async data => { const skill = skills.find(item => item.skill_id === data.get('skill_id')); const source_ids = [...$('sources').querySelectorAll('input:checked')].map(input => input.value); if (!source_ids.length) throw new Error('Select at least one approved source.'); const body = {project: data.get('project'), goal_id: data.get('goal_id'), source_ids, idempotency_key: newId(), mode: data.get('mode'), disclosure: data.get('disclosure'), repeat_seconds: data.get('repeat_seconds') ? Number(data.get('repeat_seconds')) : null, max_runs: data.get('repeat_seconds') ? 7 : 1, skill_id: skill?.skill_id || null, skill_revision: skill?.revision || null}; const check = await api('/v1/portal/briefs/check', body); if (check.decision !== 'applicable') throw new Error(check.reasons.join('; ')); if (!window.confirm('Approve this task? It may read the selected notes, create handoff artifacts, and use the selected disclosure and schedule settings.')) return; const task = await api('/v1/portal/briefs', body); notice('Approved and queued. The background worker will execute it.'); await loadTasks(); show('runs'); await inspectTask(task.task_id); });
formAction('privacy-form', async data => { await api('/v1/privacy', {mode: data.get('mode'), expected_revision: policyState.revision}, 'PUT'); await loadPrivacy(); notice('Privacy choice saved. Previously sent data is not recalled.'); });
formAction('skill-form', async data => { const skill = skills.find(item => item.skill_id === data.get('skill_id')); if (!skill) throw new Error('Choose an observed handoff procedure.'); const split = value => value.split(',').map(item => item.trim()).filter(Boolean); await api('/v1/portal/skills/' + skill.skill_id + '/confirm', {expected_revision: skill.revision, explicitly_confirmed: true, contract: {required_prefixes: split(data.get('prefixes')), forbidden_phrases: split(data.get('exceptions'))}}); await loadSkills(); notice('Contract confirmed. New tasks must pin its current revision.'); });
$('refresh').onclick = () => loadTasks().catch(error => notice(error.message));

function setBubbleText(element, text, failed) {
  element.textContent = text;
  if (element.classList) { element.classList.remove('pending'); element.classList.toggle('failed', !!failed); }
}
function showTyping(element) {
  if (element.classList) element.classList.add('pending');
  if (typeof element.replaceChildren === 'function') element.replaceChildren(fragmentNode('span', 'typing-dots', [document.createElement('span'), document.createElement('span'), document.createElement('span')]));
}
async function pollTurn(id, element, attempts = 0) {
  if (!token || !element.isConnected) return;
  let turn;
  try { turn = await api('/v1/agent/turn/' + id); }
  catch (error) { setBubbleText(element, 'Could not refresh this reply: ' + error.message + '. Use Check reply to try again.', true); addReplyRefresh(id, element); return; }
  if (!token || !element.isConnected) return;
  // The turn endpoint flattens its response: answer is a top-level string.
  const isCurrentTurn = !activeTurnId || activeTurnId === id;
  if (isCurrentTurn) {
    latestTurn = {...turn, turn_id: id};
    $('cancel-reply').hidden = ['COMPLETED', 'FAILED', 'CANCELLED', 'UNCERTAIN'].includes(turn.status);
    if (debugOpen && debugSection === 'process') renderDebugValue(latestTurn);
  }
  const answer = typeof turn.answer === 'string' ? turn.answer : '';
  const failed = ['FAILED', 'CANCELLED', 'UNCERTAIN'].includes(turn.status) || ['FAILED', 'CANCELLED'].includes(turn.job_status);
  const finished = turn.status === 'COMPLETED' || failed;
  if (finished && isCurrentTurn) { chatBusy = false; $('new-conversation').disabled = false; const send = $('chat-form').querySelector?.('button[type="submit"]'); if (send) send.disabled = false; }
  let message = answer;
  if (failed) message += (message ? '\n\n' : '') + (turn.status === 'CANCELLED' || turn.job_status === 'CANCELLED' ? 'This request was cancelled.' : 'This request could not complete. No new request was submitted.');
  if (!message) message = finished ? 'The request completed without an answer.' : turn.job_status === 'RUNNING' || turn.status === 'EXECUTING' ? 'CookieAI is preparing your reply…' : 'Queued. Waiting for the worker…';
  if (!finished && attempts >= 120) message += '\n\nThis request is taking longer than expected. Use Check reply to check the existing request.';
  setBubbleText(element, message, failed);
  if (!finished && attempts < 120) timer = setTimeout(() => pollTurn(id, element, attempts + 1), 2500);
  else if (!finished) addReplyRefresh(id, element);
  if (finished) loadConversations().catch(() => {});
}
function addReplyRefresh(id, element) {
  const button = textNode('button', 'Check reply', 'secondary');
  button.onclick = () => { button.remove(); showTyping(element); pollTurn(id, element); };
  element.append(document.createElement('br'), button);
}

function renderDebugValue(value) {
  $('debug-content').replaceChildren(textNode('pre', JSON.stringify(value, null, 2)));
}
function setHistoryOpen(open) {
  historyOpen = !!open;
  document.documentElement?.setAttribute('data-history-open', String(historyOpen));
  $('history-toggle').setAttribute?.('aria-expanded', String(historyOpen));
}
$('history-toggle').onclick = () => setHistoryOpen(!historyOpen);
let debugRequest = 0;
function setDebugOpen(open) {
  debugOpen = !!open;
  $('debug-panel').hidden = !debugOpen;
  $('tools-nav').hidden = !debugOpen;
  $('debug-toggle').setAttribute?.('aria-expanded', String(debugOpen));
  document.documentElement?.setAttribute('data-debug-open', String(debugOpen));
  if (debugOpen) {
    Promise.allSettled([loadSources(), loadGoals(), loadSkills(), loadTasks(), health()]);
    refreshDebug();
  } else { show('chat'); $('debug-toggle').focus?.(); }
}
async function refreshDebug() {
  if (!debugOpen || !token) return;
  const request = ++debugRequest, currentSession = session, section = debugSection;
  $('debug-section-title').textContent = section.charAt(0).toUpperCase() + section.slice(1);
  $('debug-content').replaceChildren(textNode('p', 'Loading authorized workspace state…'));
  try {
    if (latestTurn?.turn_id && ['process', 'memory', 'retrieval', 'transfer'].includes(section)) latestTurn = await api('/v1/agent/turn/' + latestTurn.turn_id);
    let value;
    if (section === 'sessions') value = {active_session: session, conversations: await api('/v1/portal/conversations')};
    else if (section === 'sharing') {
      const results = await Promise.all([api('/v1/sharing/grants'), api('/v1/sharing/incoming')]);
      value = {outgoing: results[0], incoming: results[1], policy: 'Cross-session knowledge stays in your authorized namespace. Cross-user access requires explicit grants and SHARED-marked memories.'};
    } else if (section === 'connections') {
      value = {configuration: await api('/v1/portal/config'), worker: await api('/v1/operations/status'), note: 'Configured routes are not proof of a successful live inference. Provider keys stay on the server. External services require their own integration and authorization.'};
    } else if (section === 'memory') {
      const ids = (latestTurn?.context_memory_ids || []).slice(0, 12);
      const memories = await Promise.allSettled(ids.map(id => api('/v1/memory/' + encodeURIComponent(id))));
      value = {memories: memories.filter(item => item.status === 'fulfilled').map(item => item.value), note: 'These are the currently authorized memories referenced by the latest reply. Search below to inspect more.'};
    } else if (section === 'retrieval') value = {memory_ids: latestTurn?.context_memory_ids || [], related_sessions: latestTurn?.pipeline?.related_sessions || [], budget: latestTurn?.pipeline?.context_budget || {}, method: latestTurn?.pipeline?.correlation_method || 'No completed context snapshot yet', context_requires_revalidation: latestTurn?.context_requires_revalidation};
    else if (section === 'transfer') value = {session_id: session, pipeline: latestTurn?.pipeline || null, retained_memories: latestTurn?.memory_ids || [], note: 'Context is assembled from authorized sources. Session changes do not grant access to another user. No cross-agent transfer is invented by this view.'};
    else value = latestTurn || {state: 'Ready for a message', model: runtimeConfig?.model, layers: runtimeConfig?.layers, correlation: 'Heuristic grouping over existing retrieval; no extra reasoning call', active_session: session};
    if (!token || !debugOpen || request !== debugRequest || currentSession !== session) return;
    renderDebugValue(value);
    if (section === 'sessions') {
      for (const conversation of value.conversations) {
        const button = textNode('button', conversation.label, 'secondary');
        button.onclick = () => { setDebugOpen(false); openConversation(conversation.session_id, true).catch(error => notice(error.message)); };
        $('debug-content').append(button);
      }
    }
    if (section === 'memory') {
      for (const memory of value.memories.filter(item => ['USER', 'SHARED'].includes(item.owner_type))) {
        const button = textNode('button', (memory.owner_type === 'SHARED' ? 'Keep private: ' : 'Mark shareable: ') + memory.memory_id.slice(0, 8), 'secondary');
        button.onclick = async () => {
          const owner_type = memory.owner_type === 'SHARED' ? 'USER' : 'SHARED';
          button.disabled = true;
          try { await api('/v1/memory/' + memory.memory_id, {owner_type, expected_revision: memory.revision}, 'PATCH'); await refreshDebug(); }
          catch (error) { notice(error.message); button.disabled = false; }
        };
        $('debug-content').append(button);
      }
    }
    if (section === 'sharing') {
      for (const share of value.outgoing.filter(item => item.active)) {
        const button = textNode('button', 'Revoke access for ' + share.grantee_user_id.slice(0, 8), 'secondary');
        button.onclick = async () => {
          button.disabled = true;
          try { await api('/v1/sharing/grants/' + share.share_id, undefined, 'DELETE'); await refreshDebug(); }
          catch (error) { notice(error.message); button.disabled = false; }
        };
        $('debug-content').append(button);
      }
    }
  } catch (error) {
    if (request === debugRequest && currentSession === session) $('debug-content').replaceChildren(textNode('p', error.message));
  }
}
$('debug-toggle').onclick = () => setDebugOpen(!debugOpen);
$('debug-close').onclick = () => setDebugOpen(false);
$('debug-refresh').onclick = refreshDebug;
for (const button of document.querySelectorAll('[data-debug]')) button.onclick = () => {
  debugSection = button.dataset.debug;
  for (const tab of document.querySelectorAll('[data-debug]')) tab.setAttribute('aria-pressed', String(tab === button));
  refreshDebug();
};
for (const button of document.querySelectorAll('[data-prompt]')) button.onclick = () => { $('message').value = button.dataset.prompt; $('message').focus(); };
document.addEventListener?.('keydown', event => { if (event.key === 'Escape' && debugOpen) setDebugOpen(false); });
formAction('debug-search-form', async data => {
  const result = await api('/v1/memory/search', {query: data.get('query'), top_k: 12});
  if (debugOpen) renderDebugValue({retrieved: result});
});
formAction('debug-share-form', async data => {
  await api('/v1/sharing/grants', {grantee_user_id: data.get('user_id'), can_read: true});
  debugSection = 'sharing'; await refreshDebug(); notice('Explicit sharing grant saved. Only marked memories are eligible.');
});
$('cancel-reply').onclick = async () => {
  if (!latestTurn?.turn_id) return;
  try {
    await api('/v1/agent/turn/' + latestTurn.turn_id + '/cancel', {});
    activeTurnId = 'cancelled-' + latestTurn.turn_id;
    chatBusy = false; $('new-conversation').disabled = false; $('cancel-reply').hidden = true;
    notice('Cancellation requested. Existing actions may already have completed.');
  } catch (error) { notice(error.message); }
};
const messageInput = $('message');
messageInput.addEventListener('input', () => { messageInput.style.height = 'auto'; messageInput.style.height = Math.min(messageInput.scrollHeight, 180) + 'px'; });
messageInput.addEventListener('keydown', event => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); $('chat-form').requestSubmit(); } });
formAction('chat-form', async data => {
  if (chatBusy) { notice('A reply is already in progress.'); return; }
  chatBusy = true; latestTurn = null;
  activeTurnId = 'submitting-' + newId();
  $('new-conversation').disabled = true;
  $('chat-suggestions').hidden = true;
  const message = data.get('message');
  const requestSession = session, requestToken = token;
  $('messages').querySelectorAll('.empty-chat').forEach(node => node.remove());
  $('messages').append(fragmentNode('div', 'msg msg-user', [document.createTextNode(message)]));
  const reply = fragmentNode('div', 'msg msg-assistant pending', []);
  showTyping(reply);
  $('messages').append(reply);
  $('messages').scrollTop = $('messages').scrollHeight;
  $('chat-form').reset();
  messageInput.style.height = 'auto';
  try {
    const result = await api('/v1/agent/turn', {message, idempotency_key: newId(), mode: 'raw'});
    if (!token || token !== requestToken || session !== requestSession || !reply.isConnected) return;
    latestTurn = result;
    activeTurnId = result.turn_id || null;
    $('cancel-reply').hidden = !result.turn_id;
    if (typeof result.answer === 'string') { chatBusy = false; $('new-conversation').disabled = false; setBubbleText(reply, result.answer, false); loadConversations().catch(() => {}); }
    else await pollTurn(result.turn_id, reply);
  } catch (error) { chatBusy = false; $('new-conversation').disabled = false; setBubbleText(reply, 'Could not submit your message: ' + error.message, true); }
});
formAction('memory-find', async data => { inspectedMemory = await api('/v1/memory/' + encodeURIComponent(data.get('id'))); $('memory-detail').textContent = JSON.stringify(inspectedMemory, null, 2); $('memory-correct').elements.text.value = inspectedMemory.text; });
formAction('memory-correct', async data => { if (!inspectedMemory) throw new Error('Inspect a memory first.'); await api('/v1/memory/mutate', {operation: 'CORRECTION', target_id: inspectedMemory.memory_id, expected_revision: inspectedMemory.revision, candidate: {text: data.get('text'), type: inspectedMemory.type, disclosure: inspectedMemory.disclosure, allowed_agent_ids: inspectedMemory.allowed_agent_ids, allowed_project_ids: inspectedMemory.allowed_project_ids, privacy_class: inspectedMemory.privacy_class}}); inspectedMemory = null; notice('Correction recorded. Dependent tasks and skills require review.'); await loadSkills(); });
$('forget').onclick = async () => { try { if (!inspectedMemory) throw new Error('Inspect a memory first.'); if (!window.confirm('Forget this memory and invalidate dependent information in the active store?')) return; await api('/v1/memory/' + inspectedMemory.memory_id, undefined, 'DELETE'); inspectedMemory = null; $('memory-detail').textContent = 'Forgotten from the active store.'; notice('Forgetting completed.'); await loadSources(); } catch (error) { notice(error.message); } };
