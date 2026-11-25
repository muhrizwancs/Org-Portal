/* Org Portal front end. Plain JavaScript, no build step.
   Every piece of text that came from the server goes through esc() before it is put into the page. */
const $ = s => document.querySelector(s);
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let token = localStorage.getItem('portal_token') || sessionStorage.getItem('portal_token');
let me = null, catalog = {}, cfg = {}, defaultPerms = [], users = [], jobRoles = [], editing = null, asgDraft = [], editingJobRole = null;
let chatId = null, notifTimer = null, current = null;

async function api(path, opts = {}) {
  const isForm = opts.body instanceof FormData;
  const res = await fetch('/api' + path, {
    method: opts.method || 'GET',
    headers: { ...(isForm ? {} : { 'Content-Type': 'application/json' }), ...(token ? { Authorization: 'Bearer ' + token } : {}) },
    body: opts.body ? (isForm ? opts.body : JSON.stringify(opts.body)) : undefined
  });
  if (opts.blob && res.ok) return res.blob();
  const data = await res.json().catch(() => ({}));
  if (res.status === 401 && token && path !== '/auth/login') { signOut(); throw new Error(data.error || 'Signed out.'); }
  if (!res.ok) throw new Error(data.error || 'Request failed.');
  return data;
}
function toast(t) { const d = document.createElement('div'); d.className = 'toast'; d.textContent = t; document.body.appendChild(d); setTimeout(() => d.remove(), 2400); }
const isAdmin = () => me && me.role === 'admin';
const can = p => isAdmin() || (me.permissions || []).includes(p);
const D = (s) => s ? new Date(/^\d{4}-\d{2}-\d{2}$/.test(s) ? s + 'T00:00:00' : s) : null;
const fmtDate = s => { const d = D(s); return d && !isNaN(d) ? d.toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' }) : '-'; };
const fmtDT = s => { const d = D(s); return d && !isNaN(d) ? d.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' }) : '-'; };
function ago(s) {
  const m = Math.round((Date.now() - new Date(s)) / 60000);
  if (m < 1) return 'just now'; if (m < 60) return m + ' min ago';
  const h = Math.round(m / 60); if (h < 24) return h + ' h ago';
  return fmtDate(s);
}
const size = n => n > 1048576 ? (n / 1048576).toFixed(1) + ' MB' : Math.max(1, Math.round(n / 1024)) + ' KB';
function fill(sel, pairs, value) { sel.innerHTML = pairs.map(([v, l]) => `<option value="${esc(v)}">${esc(l)}</option>`).join(''); if (value !== undefined) sel.value = value; }
const deptOpts = (first) => [...(first ? [first] : []), ...(cfg.departments || []).map(d => [d, d])];
const tagFor = { Approved: 'ok', Rejected: 'bad', Pending: 'warn', Cancelled: '', approved: 'ok', rejected: 'bad', pending: 'warn', draft: 'info' };
const prioTag = { High: 'bad', Medium: 'warn', Low: 'info' };
const statusTag = { Assigned: 'info', 'In Progress': 'warn', Completed: 'ok' };
function bars(items, cls) {   // items: [label, number]
  const max = Math.max(1, ...items.map(i => i[1]));
  return items.map(([l, n]) => `<div class="hbar"><span class="t" title="${esc(l)}">${esc(l)}</span><span class="b"><i class="${cls || ''}" style="width:${Math.round(100 * n / max)}%"></i></span><span class="n">${n}</span></div>`).join('') || '<p class="muted">Nothing yet.</p>';
}

/* ---------- auth ---------- */
$('#loginForm').addEventListener('submit', async e => {
  e.preventDefault(); $('#lErr').textContent = '';
  try {
    const d = await api('/auth/login', { method: 'POST', body: { email: $('#lEmail').value, password: $('#lPass').value, remember: $('#lRemember').checked } });
    const remember = $('#lRemember').checked;
    localStorage.removeItem('portal_token'); sessionStorage.removeItem('portal_token');
    token = d.token; (remember ? localStorage : sessionStorage).setItem('portal_token', token);
    if (remember) localStorage.setItem('portal_email', $('#lEmail').value.trim()); else localStorage.removeItem('portal_email');
    $('#lPass').value = ''; hidePasswords(); boot();
  } catch (err) { $('#lErr').textContent = err.message; }
});
function signOut() {
  token = null; me = null; current = null; clearInterval(notifTimer);
  localStorage.removeItem('portal_token'); sessionStorage.removeItem('portal_token');
  $('#app').classList.add('hidden'); $('#login').classList.remove('hidden'); hidePasswords();
}
$('#logout').addEventListener('click', signOut);

/* ---------- pages, menu and access ---------- */
const PAGES = [
  // key, label, group, who may open it
  ['dashboard', 'Dashboard', 'Workspace', () => can('view_dashboard')],
  ['assistant', 'Assistant', 'Workspace', () => true],
  ['tasks', 'My Tasks', 'Workspace', () => can('view_tasks') && (!isAdmin() || me.assignments.length > 0)],
  ['announcements', 'Announcements', 'Workspace', () => can('view_announcements')],
  ['documents', 'Documents', 'Workspace', () => can('access_documents')],
  ['requests', 'Requests', 'Workspace', () => isAdmin() || can('submit_requests')],
  ['team-tasks', 'Team tasks', 'Administration', () => isAdmin()],
  ['job-roles', 'Job roles', 'Administration', () => isAdmin()],
  ['users', 'Users', 'Administration', () => isAdmin()],
  ['knowledge', 'Knowledge', 'Administration', () => isAdmin()],
  ['feedback', 'Feedback', 'Administration', () => isAdmin()],
  ['analytics', 'Analytics', 'Administration', () => isAdmin()],
  ['profile', 'Profile', 'Me', () => true],
  ['account', 'Account', 'Me', () => true],
];
const LOADERS = {
  dashboard: loadDashboard, assistant: openAssistant, tasks: loadTasks, announcements: loadAnnouncements,
  documents: loadDocuments, requests: loadRequests, 'team-tasks': loadTeamTasks, 'job-roles': loadJobRoles, users: loadUsers,
  knowledge: loadKnow, feedback: loadFeedback, analytics: loadAnalytics, profile: renderProfile, account: () => {}
};
const allowed = () => PAGES.filter(p => p[3]());

async function boot() {
  if (!token) return;
  try {
    const d = await api('/me'); me = d.user; catalog = d.permissionCatalog; cfg = d.config; defaultPerms = d.defaultPerms;
  } catch { return; }
  $('#login').classList.add('hidden'); $('#app').classList.remove('hidden');
  $('#meName').textContent = me.name;
  $('#meRole').textContent = isAdmin() ? (me.superAdmin ? 'Super admin' : 'Admin') : (me.jobRole || me.jobTitle || 'User');
  $('#meRole').className = 'badge' + (isAdmin() ? ' admin' : '');
  document.querySelectorAll('.admin-only').forEach(e => e.classList.toggle('hidden', !isAdmin()));
  document.querySelectorAll('.user-only').forEach(e => e.classList.toggle('hidden', isAdmin()));
  fill($('#annCat'), [['', 'All categories'], ...cfg.announcementCategories.map(c => [c, c])]);
  fill($('#docCat'), [['', 'All categories'], ...cfg.docCategories.map(c => [c, c])]);
  buildNav();
  startChat();
  loadNotifs(); clearInterval(notifTimer); notifTimer = setInterval(loadNotifs, 60000);
  const want = location.hash.slice(1);
  show(allowed().some(p => p[0] === want) ? want : allowed()[0][0]);
}
function buildNav(pending) {
  let html = '', last = '';
  for (const [k, l, g] of allowed()) {
    if (g !== last) { html += `<div class="nav-group">${g}</div>`; last = g; }
    const label = k === 'requests' && isAdmin() ? 'Approvals' : l;
    const pill = k === 'requests' && isAdmin() && pending ? `<span class="pill">${pending}</span>` : '';
    html += `<button data-v="${k}">${esc(label)}${pill}</button>`;
  }
  $('#nav').innerHTML = html;
  $('#nav').querySelectorAll('button').forEach(b => b.onclick = () => show(b.dataset.v));
  if (current) markNav();
}
function markNav() {
  $('#nav').querySelectorAll('button').forEach(b => b.removeAttribute('aria-current'));
  const cur = $(`#nav button[data-v="${current}"]`); if (cur) cur.setAttribute('aria-current', 'page');
}
async function show(v) {
  if (!allowed().some(p => p[0] === v)) v = allowed()[0][0];
  current = v; history.replaceState(null, '', '#' + v);
  PAGES.forEach(([k]) => $('#v-' + k).classList.toggle('hidden', k !== v));
  markNav(); closeNotifs();
  try { await LOADERS[v](); } catch (e) { toast(e.message); }
}
window.addEventListener('hashchange', () => { const v = location.hash.slice(1); if (me && v !== current && allowed().some(p => p[0] === v)) show(v); });

/* ---------- notifications (bell) ---------- */
let notifItems = [];
async function loadNotifs() {
  try {
    const d = await api('/notifications'); notifItems = d.items;
    $('#bellCount').textContent = d.unread > 99 ? '99+' : d.unread; $('#bellCount').classList.toggle('hidden', !d.unread);
    $('#bell').setAttribute('aria-label', `Notifications, ${d.unread} unread`);
    if (!$('#notifPanel').classList.contains('hidden')) drawNotifs();
  } catch { /* keep the old list */ }
  if (isAdmin()) { try { buildNav((await api('/admin/requests?status=Pending')).requests.length); } catch { /* ignore */ } }
}
function drawNotifs() {
  const unread = notifItems.filter(n => !n.read).length;
  $('#notifPanel').innerHTML = `<div class="notif-head"><b>Notifications</b>${unread ? '<button class="btn ghost small" id="readAll">Mark all read</button>' : ''}</div>` +
    (notifItems.length ? notifItems.map(n => `<button class="notif ${n.read ? '' : 'unread'}" data-id="${n.id}" data-link="${esc(n.link || '')}">${esc(n.text)}<small>${esc(ago(n.createdAt))}</small></button>`).join('') : '<div class="empty">No notifications yet.</div>');
  const ra = $('#readAll'); if (ra) ra.onclick = async () => { await api('/notifications/read', { method: 'POST', body: { all: true } }); loadNotifs(); };
  $('#notifPanel').querySelectorAll('.notif').forEach(b => b.onclick = async () => {
    await api('/notifications/read', { method: 'POST', body: { ids: [b.dataset.id] } }).catch(() => {});
    const link = b.dataset.link; loadNotifs();
    if (link && allowed().some(p => p[0] === link)) show(link); else closeNotifs();
  });
}
function closeNotifs() { $('#notifPanel').classList.add('hidden'); $('#bell').setAttribute('aria-expanded', 'false'); }
$('#bell').onclick = e => {
  e.stopPropagation(); const open = $('#notifPanel').classList.contains('hidden');
  if (open) { drawNotifs(); $('#notifPanel').classList.remove('hidden'); } else $('#notifPanel').classList.add('hidden');
  $('#bell').setAttribute('aria-expanded', String(open));
};
document.addEventListener('click', e => { if (!e.target.closest('#notifPanel') && !e.target.closest('#bell')) closeNotifs(); });
document.addEventListener('keydown', e => { if (e.key === 'Escape') closeNotifs(); });

/* ---------- dashboard ---------- */
async function loadDashboard() {
  const d = await api('/dashboard'); const first = me.name.split(' ')[0];
  const go = k => `data-go="${k}"`;
  let cards = `
    <div class="stat"><div class="k">My role</div><div class="v sm">${esc(isAdmin() ? (me.superAdmin ? 'Super admin' : 'Admin') : (me.jobRole || me.jobTitle || 'User'))}</div><div class="s">${esc(me.department || 'No department set')}</div></div>
    <div class="stat"><div class="k">My department</div><div class="v sm">${esc(me.department || 'Not set')}</div><div class="s">${me.managerName ? 'Manager: ' + esc(me.managerName) : 'No manager set'}</div></div>`;
  if (d.tasks && (!isAdmin() || d.tasks.total)) cards += `
    <button class="stat" ${go('tasks')}><div class="k">Assigned tasks</div><div class="v">${d.tasks.total}</div><div class="s">${d.tasks.completed} completed</div></button>
    <button class="stat" ${go('tasks')}><div class="k">Pending tasks</div><div class="v">${d.tasks.pending}</div><div class="s">${d.tasks.overdue ? `<span style="color:var(--danger);font-weight:700">${d.tasks.overdue} overdue</span>` : 'None overdue'}</div></button>`;
  if (d.documents !== null) cards += `<button class="stat" ${go('documents')}><div class="k">Documents available</div><div class="v">${d.documents}</div><div class="s">Open the Document Center</div></button>`;
  if (d.requests && !isAdmin()) cards += `<button class="stat" ${go('requests')}><div class="k">My requests</div><div class="v">${d.requests.pending}</div><div class="s">pending of ${d.requests.total}</div></button>`;
  let admin = '';
  if (d.admin) admin = `<h3 class="sec">Organization</h3><div class="grid-cards">
    <button class="stat" ${go('users')}><div class="k">Users</div><div class="v">${d.admin.users}</div></button>
    <button class="stat" ${go('requests')}><div class="k">Requests to approve</div><div class="v">${d.admin.pendingRequests}</div></button>
    <button class="stat" ${go('knowledge')}><div class="k">Knowledge to approve</div><div class="v">${d.admin.pendingKnowledge}</div></button>
    <button class="stat" ${go('analytics')}><div class="k">Questions (24 h)</div><div class="v">${d.admin.questions24h}</div></button>
    <button class="stat" ${go('feedback')}><div class="k">Answer feedback</div><div class="v sm">${d.admin.helpful} helpful &middot; ${d.admin.notHelpful} not</div></button></div>`;
  let ann = '';
  if (d.announcements) ann = `<h3 class="sec">Recent announcements</h3><div class="panel">${d.announcements.length ? d.announcements.map(a => `<button class="notif" ${go('announcements')}><b>${esc(a.title)}</b><small>${esc(a.category)} &middot; ${esc(fmtDate(a.createdAt))}</small></button>`).join('') : '<div class="empty">No announcements yet.</div>'}</div>`;
  $('#v-dashboard').innerHTML = `<div class="hello"><h2>Welcome ${esc(first)}${me.jobTitle ? ' (' + esc(me.jobTitle) + ')' : ''}</h2><p>${d.unreadNotifications ? `You have ${d.unreadNotifications} unread notification${d.unreadNotifications > 1 ? 's' : ''}.` : 'You are all caught up.'}</p></div>
    <div class="grid-cards">${cards}</div>${ann}${admin}
    <h3 class="sec">Ask the assistant</h3><div class="suggest" id="dashSug">${suggestions().map(s => `<button type="button">${esc(s)}</button>`).join('')}</div>`;
  $('#v-dashboard').querySelectorAll('[data-go]').forEach(b => b.onclick = () => show(b.dataset.go));
  $('#dashSug').querySelectorAll('button').forEach(b => b.onclick = async () => { await show('assistant'); startChat(); ask(b.textContent); });
}

/* ---------- assistant, chat history, feedback ---------- */
function suggestions() {
  const s = [];
  if (can('view_tasks')) s.push('What are my assigned tasks?');
  s.push('What is the leave policy?');
  if (can('view_announcements')) s.push('Show company holidays');
  s.push('Who is my manager?');
  if (can('access_documents')) s.push('What documents are relevant to my department?');
  s.push('What is my role?');
  if (isAdmin()) s.push('Who are the users?', 'How do I manage access?');
  return s;
}
function render(text) {
  const lines = esc(text).split('\n'); let html = '', inList = false;
  for (const l of lines) {
    const li = l.match(/^- (.*)/);
    if (li) { if (!inList) { html += '<ul>'; inList = true; } html += '<li>' + li[1] + '</li>'; }
    else { if (inList) { html += '</ul>'; inList = false; } html += l + '<br>'; }
  }
  if (inList) html += '</ul>';
  return html.replace(/\*\*(.+?)\*\*/g, '<b>$1</b>').replace(/(<br>)+$/, '').replace(/<\/ul><br>/g, '</ul>');
}
function chip(s) {
  if (s.file) return `<span class="chip doc">Document: ${esc(s.file)}${s.page ? ' &middot; page ' + esc(s.page) : ''}</span>`;
  return `<span class="chip ${s.personal ? 'personal' : ''}">${s.personal ? 'Your record' : 'Organization'}: ${esc(s.title)}</span>`;
}
function addMine(t) { const d = document.createElement('div'); d.className = 'msg me-msg'; d.textContent = t; $('#log').appendChild(d); scrollLog(); }
function addBot(r, question) {
  const d = document.createElement('div'); d.className = 'msg';
  d.innerHTML = render(r.answer) + (r.sources && r.sources.length ? '<div class="src">' + r.sources.map(chip).join('') + '</div>' : '');
  if (r.messageId && r.confidence !== 0 && question) {
    const fb = document.createElement('div'); fb.className = 'fb';
    fb.innerHTML = '<span>Was this helpful?</span><button type="button" data-r="up" aria-label="Helpful">&#128077; Helpful</button><button type="button" class="down" data-r="down" aria-label="Not helpful">&#128078; Not helpful</button>';
    const mark = v => fb.querySelectorAll('button').forEach(b => b.classList.toggle('on', b.dataset.r === v));
    if (r.feedback) mark(r.feedback);
    fb.querySelectorAll('button').forEach(b => b.onclick = async () => {
      try {
        await api('/feedback', { method: 'POST', body: { rating: b.dataset.r, question, answer: r.answer, messageId: r.messageId, chatId,
          sources: (r.sources || []).map(s => s.file ? s.file + (s.page ? ' p.' + s.page : '') : s.title) } });
        mark(b.dataset.r); toast('Thanks for the feedback');
      } catch (e) { toast(e.message); }
    });
    d.appendChild(fb);
  }
  $('#log').appendChild(d); scrollLog();
}
function scrollLog() { const l = $('#log'); l.scrollTop = l.scrollHeight; }
function startChat() {
  chatId = null; $('#log').innerHTML = '';
  addBot({ answer: `Hi ${me.name.split(' ')[0]}. Ask me about your tasks, your manager, company documents or policies, or how things work here.`, sources: [] });
  $('#suggest').innerHTML = suggestions().map(s => `<button type="button">${esc(s)}</button>`).join('');
  $('#suggest').querySelectorAll('button').forEach(b => b.onclick = () => ask(b.textContent));
  drawHist();
}
async function ask(text) {
  text = text.trim(); if (!text) return;
  addMine(text); $('#q').value = '';
  try {
    const r = await api('/chat', { method: 'POST', body: { message: text, chatId } });
    if (r.chatId) { const isNew = r.chatId !== chatId; chatId = r.chatId; if (isNew) loadHist(); }
    addBot(r, text);
  } catch (err) { addBot({ answer: err.message, sources: [] }); }
}
$('#askForm').addEventListener('submit', e => { e.preventDefault(); ask($('#q').value); });
$('#newChat').onclick = startChat;
let chats = [];
function openAssistant() { $('#assist').classList.toggle('no-hist', !can('chat_history')); $('#hist').classList.toggle('hidden', !can('chat_history')); if (can('chat_history')) loadHist(); }
async function loadHist() { if (!can('chat_history')) return; try { chats = (await api('/chats')).chats; drawHist(); } catch { /* ignore */ } }
function drawHist() {
  $('#histList').innerHTML = chats.map(c => `<div class="hist-item ${c.id === chatId ? 'on' : ''}"><button class="open" data-id="${c.id}" title="${esc(c.title)}">${esc(c.title)}</button><button class="x" data-del="${c.id}" aria-label="Delete chat">&#10005;</button></div>`).join('') || '<p class="muted note" style="margin:4px">No saved chats yet.</p>';
  $('#histList').querySelectorAll('.open').forEach(b => b.onclick = () => openChat(b.dataset.id));
  $('#histList').querySelectorAll('[data-del]').forEach(b => b.onclick = async () => {
    if (!confirm('Delete this conversation?')) return;
    await api('/chats/' + b.dataset.del, { method: 'DELETE' }); if (chatId === b.dataset.del) startChat(); loadHist();
  });
}
async function openChat(id) {
  try {
    const c = (await api('/chats/' + id)).chat; chatId = c.id; $('#log').innerHTML = ''; let q = '';
    for (const m of c.messages) { if (m.role === 'user') { addMine(m.text); q = m.text; } else addBot({ answer: m.text, sources: m.sources, messageId: m.id, feedback: m.feedback, confidence: 1 }, q); }
    drawHist();
  } catch (e) { toast(e.message); }
}

/* ---------- my tasks (board) ---------- */
const COLS = ['Assigned', 'In Progress', 'Completed'];
async function loadTasks() {
  const tasks = (await api('/tasks')).tasks;
  const pending = tasks.filter(t => t.status !== 'Completed').length, late = tasks.filter(t => t.overdue).length;
  $('#tasksSub').textContent = tasks.length ? `${tasks.length} task${tasks.length > 1 ? 's' : ''}, ${pending} pending${late ? ', ' + late + ' overdue' : ''}. Change the status or drag the progress bar as you work.` : 'Nothing has been assigned to you yet.';
  $('#board').innerHTML = COLS.map(c => {
    const list = tasks.filter(t => t.status === c);
    return `<div class="col"><h3>${c}<span>${list.length}</span></h3>${list.map(taskCard).join('') || '<p class="muted note">Nothing here.</p>'}</div>`;
  }).join('');
  $('#board').querySelectorAll('.tcard').forEach(card => {
    const id = card.dataset.id, range = card.querySelector('input[type=range]'), out = card.querySelector('.pv');
    range.oninput = () => { out.textContent = range.value + '%'; };
    range.onchange = () => saveTask(id, { progress: +range.value });
    card.querySelector('select').onchange = e => saveTask(id, { status: e.target.value });
  });
}
function taskCard(t) {
  return `<div class="tcard ${esc(t.priority)}" data-id="${esc(t.id)}"><h4>${esc(t.title)}</h4>${t.description ? `<p>${esc(t.description)}</p>` : ''}
    <div class="meta"><span class="tag ${prioTag[t.priority]}">${esc(t.priority)}</span>${t.dueDate ? `<span class="due ${t.overdue ? 'late' : ''}">Due ${esc(fmtDate(t.dueDate))}${t.overdue ? ' (overdue)' : ''}</span>` : '<span class="due">No due date</span>'}</div>
    <input type="range" min="0" max="100" step="5" value="${t.progress}" aria-label="Progress for ${esc(t.title)}"><div class="meta"><b class="pv">${t.progress}%</b>
    <select aria-label="Status">${cfg.taskStatuses.map(s => `<option ${s === t.status ? 'selected' : ''}>${esc(s)}</option>`).join('')}</select></div></div>`;
}
async function saveTask(id, body) {
  try { await api('/tasks/' + id, { method: 'PATCH', body }); await loadTasks(); me.assignments = (await api('/me')).user.assignments; } catch (e) { toast(e.message); loadTasks(); }
}

/* ---------- announcements ---------- */
let anns = [];
async function loadAnnouncements() { anns = (await api('/announcements')).announcements; drawAnns(); }
function drawAnns() {
  const cat = $('#annCat').value, list = anns.filter(a => !cat || a.category === cat);
  $('#annList').innerHTML = list.map(a => `<article class="panel ann ${a.pinned ? 'pinned' : ''}"><h3>${a.pinned ? '&#128204; ' : ''}${esc(a.title)}</h3>
    <div class="meta"><span class="tag info">${esc(a.category)}</span>${a.department !== 'all' ? `<span class="tag">${esc(a.department)} only</span>` : ''}<span>${esc(fmtDate(a.createdAt))} &middot; ${esc(a.createdByName)}</span></div>
    <p class="body">${esc(a.body)}</p>${isAdmin() ? `<div class="row-gap" style="margin-top:10px"><button class="btn ghost small" data-pin="${a.id}" data-to="${!a.pinned}">${a.pinned ? 'Unpin' : 'Pin'}</button><button class="btn danger small" data-del="${a.id}">Delete</button></div>` : ''}</article>`).join('') || '<div class="panel empty">No announcements.</div>';
  $('#annList').querySelectorAll('[data-pin]').forEach(b => b.onclick = async () => { await api('/admin/announcements/' + b.dataset.pin, { method: 'PATCH', body: { pinned: b.dataset.to === 'true' } }); loadAnnouncements(); });
  $('#annList').querySelectorAll('[data-del]').forEach(b => b.onclick = async () => { if (confirm('Delete this announcement?')) { await api('/admin/announcements/' + b.dataset.del, { method: 'DELETE' }); loadAnnouncements(); } });
}
$('#annCat').onchange = drawAnns;
$('#addAnn').onclick = () => { $('#annForm').reset(); $('#aErr').textContent = ''; fill($('#aCat'), cfg.announcementCategories.map(c => [c, c])); fill($('#aDept'), deptOpts(['all', 'Everyone'])); $('#annDlg').showModal(); };
$('#aCancel').onclick = () => $('#annDlg').close();
$('#annForm').addEventListener('submit', async e => {
  e.preventDefault(); $('#aErr').textContent = '';
  try {
    await api('/admin/announcements', { method: 'POST', body: { title: $('#aTitle').value, category: $('#aCat').value, department: $('#aDept').value, body: $('#aBody').value, pinned: $('#aPin').checked } });
    $('#annDlg').close(); toast('Announcement published'); loadAnnouncements();
  } catch (err) { $('#aErr').textContent = err.message; }
});

/* ---------- documents ---------- */
let docs = [], docEditing = null;
async function loadDocuments() {
  const [documentData, roleData] = await Promise.all([
    api('/documents'),
    isAdmin() ? api('/admin/job-roles') : Promise.resolve({ roles: [] })
  ]);
  docs = documentData.documents;
  if (isAdmin()) jobRoles = roleData.roles;
  drawDocs();
}
function drawDocs() {
  const q = $('#docSearch').value.trim().toLowerCase(), cat = $('#docCat').value;
  const list = docs.filter(d => (!cat || d.category === cat) && (!q || (d.title + ' ' + d.filename).toLowerCase().includes(q)));
  $('#docRows').innerHTML = list.map(d => `<tr>
    <td><b>${esc(d.title)}</b>${d.version > 1 ? ` <span class="tag">v${d.version}</span>` : ''}<br><span class="muted">${esc(d.filename)} &middot; ${esc(size(d.size))}</span>
      ${isAdmin() ? `<br>${d.indexed ? `<span class="tag ok" title="${d.chunkCount} text pieces indexed">Searchable by assistant</span>` : `<span class="tag warn" title="${esc(d.indexNote)}">Not searchable</span>`}` : ''}</td>
    <td>${esc(d.category)}</td><td>${d.jobRoles?.length ? esc(d.jobRoles.join(', ')) + (d.department === 'all' ? '' : ` · ${esc(d.department)} department`) : (d.department === 'all' ? 'Everyone' : esc(d.department))}</td><td>${esc(fmtDate(d.updatedAt))}</td>
    <td style="white-space:nowrap"><button class="btn small" data-dl="${d.id}">Download</button>
      ${isAdmin() ? `<button class="btn ghost small" data-ed="${d.id}">Edit</button><button class="btn danger small" data-rm="${d.id}">Delete</button>` : ''}</td></tr>`).join('') || '<tr><td colspan="5" class="empty">No documents found.</td></tr>';
  $('#docRows').querySelectorAll('[data-dl]').forEach(b => b.onclick = () => download(docs.find(d => d.id === b.dataset.dl)));
  $('#docRows').querySelectorAll('[data-ed]').forEach(b => b.onclick = () => openDoc(docs.find(d => d.id === b.dataset.ed)));
  $('#docRows').querySelectorAll('[data-rm]').forEach(b => b.onclick = async () => {
    if (!confirm('Delete this document? The assistant will stop using it.')) return;
    try { await api('/admin/documents/' + b.dataset.rm, { method: 'DELETE' }); toast('Document deleted'); loadDocuments(); } catch (e) { toast(e.message); }
  });
}
async function download(d) {
  try {
    const blob = await api(`/documents/${d.id}/download`, { blob: true });
    const a = document.createElement('a'); a.href = URL.createObjectURL(blob); a.download = d.filename; document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 5000);
  } catch (e) { toast(e.message); }
}
$('#docSearch').oninput = drawDocs; $('#docCat').onchange = drawDocs;
function openDoc(d) {
  docEditing = d || null; $('#docForm').reset(); $('#dErr').textContent = '';
  fill($('#dCat'), cfg.docCategories.map(c => [c, c]), d ? d.category : 'Policy'); fill($('#dDept'), deptOpts(['all', 'Everyone']), d ? d.department : 'all');
  const allowed = d?.jobRoleIds || [];
  $('#dRoles').innerHTML = jobRoles.filter(r => r.active || allowed.includes(r.id)).map(r =>
    `<label><input type="checkbox" value="${esc(r.id)}" ${allowed.includes(r.id) ? 'checked' : ''}><span>${esc(r.name)}<small>${esc(r.department)}${r.active ? '' : ' · inactive'}</small></span></label>`
  ).join('') || '<span class="muted">No active job roles. Define a role first.</span>';
  $('#docDlgTitle').textContent = d ? 'Edit document' : 'Upload document';
  $('#dFileLabel').textContent = d ? 'Replace file (optional, becomes the next version)' : 'File';
  $('#dTitle').value = d ? d.title : ''; $('#dSave').textContent = d ? 'Save changes' : 'Upload'; $('#docDlg').showModal();
}
$('#addDoc').onclick = () => openDoc(null);
$('#dCancel').onclick = () => $('#docDlg').close();
$('#docForm').addEventListener('submit', async e => {
  e.preventDefault(); $('#dErr').textContent = '';
  const f = $('#dFile').files[0];
  if (!docEditing && !f) { $('#dErr').textContent = 'Choose a file to upload.'; return; }
  const fd = new FormData(); fd.append('title', $('#dTitle').value); fd.append('category', $('#dCat').value); fd.append('department', $('#dDept').value);
  $('#dRoles').querySelectorAll('input:checked').forEach(input => fd.append('jobRoleIds', input.value));
  if (f) fd.append('file', f);
  $('#dSave').disabled = true;
  try {
    await api(docEditing ? '/admin/documents/' + docEditing.id : '/admin/documents', { method: docEditing ? 'PATCH' : 'POST', body: fd });
    $('#docDlg').close(); toast(docEditing ? 'Document updated' : 'Document uploaded'); loadDocuments();
  } catch (err) { $('#dErr').textContent = err.message; } finally { $('#dSave').disabled = false; }
});

/* ---------- requests / approvals ---------- */
let reqs = [], deciding = null;
function flow(r) {
  const s = r.status, steps = ['Submitted', 'Admin review'];
  let end = 'Approved / Rejected', endCls = '';
  if (s === 'Approved') { end = 'Approved'; endCls = 'done'; } else if (s === 'Rejected') { end = 'Rejected'; endCls = 'bad'; } else if (s === 'Cancelled') { end = 'Cancelled'; endCls = 'bad'; }
  const mid = s === 'Pending' ? 'now' : (s === 'Cancelled' ? '' : 'done');
  return `<ol class="flow"><li class="done">${steps[0]}</li><li class="${mid}">${steps[1]}</li><li class="${endCls}">${end}</li></ol>`;
}
async function loadRequests() {
  if (isAdmin()) {
    $('#reqTitle').textContent = 'Approvals'; $('#reqSub').textContent = 'Review leave, access, training and equipment requests.';
    const statusFilter = $('#reqStatus');
    const selectedStatus = statusFilter.options.length ? statusFilter.value : 'Pending';
    fill(statusFilter, [['Pending', 'Pending'], ['Approved', 'Approved'], ['Rejected', 'Rejected'], ['Cancelled', 'Cancelled'], ['', 'All']], selectedStatus);
    reqs = (await api('/admin/requests' + ($('#reqStatus').value ? '?status=' + $('#reqStatus').value : ''))).requests;
  } else {
    $('#reqTitle').textContent = 'Requests'; $('#reqSub').textContent = 'Send a request and follow it until the admin decides.';
    reqs = (await api('/requests')).requests;
  }
  $('#reqList').innerHTML = reqs.map(r => `<article class="panel req"><div class="bar" style="margin:0"><h3>${esc(r.title)}</h3><span class="tag ${tagFor[r.status] || ''}">${esc(r.status)}</span></div>
    <div class="muted" style="font-size:.85rem">${esc(r.type)}${isAdmin() ? ' &middot; ' + esc(r.userName) + (r.department ? ' (' + esc(r.department) + ')' : '') : ''} &middot; ${esc(fmtDate(r.createdAt))}${r.startDate ? ` &middot; ${esc(fmtDate(r.startDate))} to ${esc(fmtDate(r.endDate))}` : ''}</div>
    ${r.details ? `<p style="margin:8px 0 0;white-space:pre-wrap">${esc(r.details)}</p>` : ''}${flow(r)}
    ${r.adminNote ? `<div class="note">Admin note${r.decidedByName ? ' (' + esc(r.decidedByName) + ')' : ''}: ${esc(r.adminNote)}</div>` : ''}
    <div class="row-gap" style="margin-top:8px">${isAdmin() && r.status === 'Pending' ? `<button class="btn small" data-rev="${r.id}">Review</button>` : ''}${!isAdmin() && r.status === 'Pending' ? `<button class="btn danger small" data-cancel="${r.id}">Cancel request</button>` : ''}</div></article>`).join('')
    || `<div class="panel empty">${isAdmin() ? 'No requests with this status.' : 'You have not sent any requests yet.'}</div>`;
  $('#reqList').querySelectorAll('[data-cancel]').forEach(b => b.onclick = async () => { if (confirm('Cancel this request?')) { await api(`/requests/${b.dataset.cancel}/cancel`, { method: 'POST' }); loadRequests(); } });
  $('#reqList').querySelectorAll('[data-rev]').forEach(b => b.onclick = () => {
    deciding = reqs.find(r => r.id === b.dataset.rev); $('#decNote').value = ''; $('#decErr').textContent = '';
    $('#decInfo').innerHTML = `<p><b>${esc(deciding.title)}</b><br><span class="muted">${esc(deciding.type)} request from ${esc(deciding.userName)}${deciding.startDate ? ', ' + esc(fmtDate(deciding.startDate)) + ' to ' + esc(fmtDate(deciding.endDate)) : ''}</span></p>${deciding.details ? `<p style="white-space:pre-wrap">${esc(deciding.details)}</p>` : ''}`;
    $('#decDlg').showModal();
  });
}
$('#reqStatus').onchange = loadRequests;
async function decide(status) {
  try { await api('/admin/requests/' + deciding.id, { method: 'PATCH', body: { status, note: $('#decNote').value } }); $('#decDlg').close(); toast('Request ' + status.toLowerCase()); loadRequests(); loadNotifs(); }
  catch (e) { $('#decErr').textContent = e.message; }
}
$('#decApprove').onclick = () => decide('Approved'); $('#decReject').onclick = () => decide('Rejected'); $('#decCancel').onclick = () => $('#decDlg').close();
$('#addReq').onclick = () => { $('#reqForm').reset(); $('#rErr').textContent = ''; fill($('#rType'), cfg.requestTypes.map(t => [t, t])); syncReqDates(); $('#reqDlg').showModal(); };
function syncReqDates() { $('#rDates').classList.toggle('hidden', $('#rType').value !== 'Leave'); }
$('#rType').onchange = syncReqDates; $('#rCancel').onclick = () => $('#reqDlg').close();
$('#reqForm').addEventListener('submit', async e => {
  e.preventDefault(); $('#rErr').textContent = '';
  try {
    await api('/requests', { method: 'POST', body: { type: $('#rType').value, title: $('#rTitle').value, details: $('#rDetails').value, startDate: $('#rStart').value, endDate: $('#rEnd').value } });
    $('#reqDlg').close(); toast('Request sent to the admin'); loadRequests();
  } catch (err) { $('#rErr').textContent = err.message; }
});

/* ---------- profile / account ---------- */
function renderProfile() {
  const rows = [['Name', me.name], ['Employee ID', me.employeeId || '-'], ['Email', me.email], ['Role', isAdmin() ? (me.superAdmin ? 'Super admin' : 'Admin') : 'User'],
    ['Job title', me.jobTitle || '-'], ['Department', me.department || '-'], ['Manager', me.managerName || '-'], ['Joining date', me.joiningDate ? fmtDate(me.joiningDate) : '-'],
    ['Account created', fmtDate(me.createdAt)], ['Access', isAdmin() ? 'All features' : (me.permissions.map(p => catalog[p]?.label || p).join(', ') || 'None granted yet')]];
  $('#profList').innerHTML = rows.map(([k, v]) => `<dt>${esc(k)}</dt><dd>${esc(v)}</dd>`).join('');
}
$('#pwForm').addEventListener('submit', async e => {
  e.preventDefault(); $('#pwErr').textContent = ''; $('#pwOk').textContent = '';
  try {
    await api('/me/password', { method: 'POST', body: { currentPassword: $('#pwCur').value, newPassword: $('#pwNew').value } });
    $('#pwOk').textContent = 'Password saved.'; $('#pwCur').value = ''; $('#pwNew').value = ''; hidePasswords(); loadNotifs();
  } catch (err) { $('#pwErr').textContent = err.message; }
});

/* ---------- admin: team tasks ---------- */
let teamTasks = [];
async function loadTeamTasks() {
  teamTasks = (await api('/admin/tasks')).tasks;
  const names = [...new Set(teamTasks.map(t => t.userName))].sort();
  const keep = [$('#ttStatus').value, $('#ttPrio').value, $('#ttUser').value];
  fill($('#ttStatus'), [['', 'Any status'], ...cfg.taskStatuses.map(s => [s, s])], keep[0] || '');
  fill($('#ttPrio'), [['', 'Any priority'], ...cfg.taskPriorities.map(s => [s, s])], keep[1] || '');
  fill($('#ttUser'), [['', 'Everyone'], ...names.map(n => [n, n])], keep[2] || '');
  drawTeamTasks();
}
function drawTeamTasks() {
  const s = $('#ttStatus').value, p = $('#ttPrio').value, u = $('#ttUser').value;
  const list = teamTasks.filter(t => (!s || t.status === s) && (!p || t.priority === p) && (!u || t.userName === u));
  $('#ttRows').innerHTML = list.map(t => `<tr><td><b>${esc(t.title)}</b>${t.description ? `<br><span class="muted">${esc(t.description)}</span>` : ''}</td>
    <td>${esc(t.userName)}${t.department ? `<br><span class="muted">${esc(t.department)}</span>` : ''}</td>
    <td><span class="tag ${prioTag[t.priority]}">${esc(t.priority)}</span></td><td><span class="tag ${statusTag[t.status]}">${esc(t.status)}</span></td>
    <td style="min-width:120px"><div class="pbar ${t.status === 'Completed' ? 'done' : ''}"><i style="width:${t.progress}%"></i></div><span class="muted">${t.progress}%</span></td>
    <td><span class="due ${t.overdue ? 'late' : ''}">${t.dueDate ? esc(fmtDate(t.dueDate)) + (t.overdue ? ' (overdue)' : '') : '-'}</span></td></tr>`).join('') || '<tr><td colspan="6" class="empty">No tasks match.</td></tr>';
}
['#ttStatus', '#ttPrio', '#ttUser'].forEach(s => $(s).onchange = drawTeamTasks);

/* ---------- admin: users ---------- */
async function loadUsers() {
  jobRoles = (await api('/admin/job-roles')).roles;
  users = (await api('/admin/users')).users;
  $('#userRows').innerHTML = users.map(u => `<tr>
    <td><b>${esc(u.name)}</b><br><span class="muted">${esc(u.email)}${u.jobRole || u.jobTitle ? ' &middot; ' + esc(u.jobRole || u.jobTitle) : ''}<br>${esc(u.employeeId)}</span></td>
    <td><span class="badge ${u.role === 'admin' ? 'admin' : ''}">${u.role === 'admin' ? (u.superAdmin ? 'Super admin' : 'Admin') : 'User'}</span>${u.active ? '' : ' <span class="badge off">Disabled</span>'}</td>
    <td>${esc(u.department || '-')}${u.managerName ? `<br><span class="muted">Mgr: ${esc(u.managerName)}</span>` : ''}</td>
    <td>${u.role === 'admin' ? 'All features' : (u.permissions.length ? u.permissions.map(p => esc(catalog[p]?.label || p)).join(', ') : '<span class="muted">None granted</span>')}</td>
    <td>${u.assignments.length ? u.assignments.map(a => esc(a.title) + ' (' + a.progress + '%)').join(', ') : '<span class="muted">None</span>'}</td>
    <td style="white-space:nowrap"><button class="btn ghost small" data-edit="${u.id}">Edit</button>
      ${u.id === me.id ? '' : `<button class="btn danger small" data-del="${u.id}">Delete</button>`}</td></tr>`).join('');
  document.querySelectorAll('[data-edit]').forEach(b => b.onclick = () => openUser(users.find(u => u.id === b.dataset.edit)));
  document.querySelectorAll('#userRows [data-del]').forEach(b => b.onclick = async () => {
    const u = users.find(x => x.id === b.dataset.del);
    if (!confirm(`Delete ${u.name}? This cannot be undone.`)) return;
    try { await api('/admin/users/' + u.id, { method: 'DELETE' }); toast('User deleted'); loadUsers(); } catch (e) { toast(e.message); }
  });
}
async function loadJobRoles() {
  jobRoles = (await api('/admin/job-roles')).roles;
  $('#jobRoleRows').innerHTML = jobRoles.map(r => `<tr><td><b>${esc(r.name)}</b>${r.predefined ? ' <span class="tag info">Starter role</span>' : ''}${r.active ? '' : ' <span class="badge off">Inactive</span>'}</td><td>${esc(r.department)}</td><td>${r.permissions.map(p => esc(catalog[p]?.label || p)).join(', ') || 'None'}</td><td><button class="btn ghost small" data-jredit="${r.id}">Edit</button> <button class="btn danger small" data-jrdel="${r.id}">Delete</button></td></tr>`).join('') || '<tr><td colspan="4" class="empty">No job roles defined yet.</td></tr>';
  document.querySelectorAll('[data-jredit]').forEach(b => b.onclick = () => openJobRole(jobRoles.find(r => r.id === b.dataset.jredit)));
  document.querySelectorAll('[data-jrdel]').forEach(b => b.onclick = async () => { const r = jobRoles.find(x => x.id === b.dataset.jrdel); if (!confirm(`Delete ${r.name}? Users keep their current access. Reassign documents restricted to this role first.`)) return; try { await api('/admin/job-roles/' + r.id, {method:'DELETE'}); toast('Role deleted'); loadJobRoles(); } catch(e) { toast(e.message); } });
}
function openJobRole(r) {
  editingJobRole = r || null; $('#jobRoleTitle').textContent = r ? 'Edit ' + r.name : 'Define job role';
  $('#jrName').value = r?.name || ''; fill($('#jrDept'), deptOpts(), r?.department || cfg.departments[0]);
  $('#jrPredefined').checked = !!r?.predefined;
  const have = r?.permissions || defaultPerms;
  $('#jrPerms').innerHTML = Object.entries(catalog).map(([k,p]) => `<label><input type="checkbox" value="${k}" ${have.includes(k) ? 'checked' : ''}><span>${esc(p.label)}<small>${esc(p.description)}</small></span></label>`).join('');
  $('#jrErr').textContent = ''; $('#jobRoleDlg').showModal();
}
$('#addJobRole').onclick = () => openJobRole(null);
$('#jrCancel').onclick = () => $('#jobRoleDlg').close();
$('#jobRoleForm').addEventListener('submit', async e => { e.preventDefault(); $('#jrErr').textContent = ''; const body = {name:$('#jrName').value, department:$('#jrDept').value, permissions:[...$('#jrPerms').querySelectorAll('input:checked')].map(x=>x.value), predefined:$('#jrPredefined').checked}; try { await api('/admin/job-roles' + (editingJobRole ? '/' + editingJobRole.id : ''), {method:editingJobRole?'PATCH':'POST', body}); $('#jobRoleDlg').close(); toast('Job role saved'); await loadJobRoles(); } catch(err) { $('#jrErr').textContent = err.message; } });
function drawAsg() {
  const opt = (list, v) => list.map(x => `<option ${x === v ? 'selected' : ''}>${esc(x)}</option>`).join('');
  $('#uAsg').innerHTML = asgDraft.map((a, i) => `<div class="asg-card">
    <div class="asg-grid"><label>Title<input type="text" value="${esc(a.title)}" data-i="${i}" data-f="title"></label>
      <label>Description<input type="text" value="${esc(a.description)}" data-i="${i}" data-f="description"></label></div>
    <div class="asg-grid4"><label>Due date<input type="date" value="${esc(a.dueDate || '')}" data-i="${i}" data-f="dueDate"></label>
      <label>Priority<select data-i="${i}" data-f="priority">${opt(cfg.taskPriorities, a.priority || 'Medium')}</select></label>
      <label>Status<select data-i="${i}" data-f="status">${opt(cfg.taskStatuses, a.status || 'Assigned')}</select></label>
      <label>Progress %<input type="number" min="0" max="100" value="${a.progress || 0}" data-i="${i}" data-f="progress"></label></div>
    <div><button type="button" class="btn danger small" data-rm="${i}">Remove task</button></div></div>`).join('') || '<p class="muted" style="margin:0 0 8px">No tasks assigned yet.</p>';
  $('#uAsg').querySelectorAll('[data-f]').forEach(el => el.oninput = el.onchange = () => { asgDraft[el.dataset.i][el.dataset.f] = el.value; });
  $('#uAsg').querySelectorAll('[data-rm]').forEach(b => b.onclick = () => { asgDraft.splice(+b.dataset.rm, 1); drawAsg(); });
}
function syncAdminNote() {
  const isAd = $('#uRole').value === 'admin';
  $('#uJobRole').required = !isAd && !editing;
  $('#uJobRole').disabled = isAd && !!editing;
  $('#userRoleAccessNote').textContent = isAd ? 'Admins always have access to every feature.' : 'Access is defined by the selected job role. Configure it under Job roles.';
  $('#uSuperWrap').classList.toggle('hidden', !(isAd && me.superAdmin));
}
$('#uRole').addEventListener('change', syncAdminNote);
function openUser(u) {
  editing = u || null; $('#uErr').textContent = '';
  $('#userDlgTitle').textContent = u ? 'Edit ' + u.name : 'Add user';
  $('#uName').value = u?.name || ''; $('#uEmail').value = u?.email || ''; $('#uEmp').value = u?.employeeId || '';
  fill($('#uDept'), deptOpts(['', 'Not set']), u?.department || '');
  const availableRoles = jobRoles.filter(r => r.active || r.id === u?.jobRoleId);
  const roleOptions = roles => roles.map(r =>
    `<option value="${esc(r.id)}">${esc(r.name)} · ${esc(r.department)}${r.active ? '' : ' (inactive)'}</option>`
  ).join('');
  const roleGroups = [
    ['Starter roles', availableRoles.filter(r => r.predefined)],
    ['Other roles', availableRoles.filter(r => !r.predefined)]
  ].filter(([, roles]) => roles.length)
    .map(([label, roles]) => `<optgroup label="${label}">${roleOptions(roles)}</optgroup>`).join('');
  $('#uJobRole').innerHTML = `<option value="">No predefined role</option>${roleGroups}`;
  $('#uJobRole').value = u?.jobRoleId || '';
  fill($('#uMgr'), [['', 'None'], ...users.filter(x => !u || x.id !== u.id).map(x => [x.id, x.name + (x.jobTitle ? ' (' + x.jobTitle + ')' : '')])], u?.managerId || '');
  $('#uJoin').value = u?.joiningDate || '';
  $('#uEmail').disabled = !!u; $('#uRole').value = u?.role || 'user'; $('#uActive').checked = u ? u.active : true; $('#uSuper').checked = !!u?.superAdmin;
  $('#uJobRole').onchange = () => { const role = jobRoles.find(r => r.id === $('#uJobRole').value); if (role) $('#uDept').value = role.department; };
  $('#uActive').disabled = !!u && u.id === me.id; $('#uRole').disabled = !!u && u.id === me.id;
  $('#uPass').value = ''; $('#uPass').required = !u;
  $('#uPassLabel').textContent = u ? 'New password (leave blank to keep)' : 'Starting password (8+ characters)';
  asgDraft = (u?.assignments || []).map(a => ({ ...a })); drawAsg(); syncAdminNote();
  hidePasswords(); $('#userDlg').showModal();
}
$('#addUser').onclick = () => openUser(null);
$('#addAsg').onclick = () => { asgDraft.push({ title: '', description: '', dueDate: '', priority: 'Medium', status: 'Assigned', progress: 0 }); drawAsg(); };
$('#uCancel').onclick = () => $('#userDlg').close();
$('#userForm').addEventListener('submit', async e => {
  e.preventDefault(); $('#uErr').textContent = '';
  const body = {
    name: $('#uName').value, jobRoleId: $('#uJobRole').value || null, role: $('#uRole').value, active: $('#uActive').checked,
    department: $('#uDept').value, managerId: $('#uMgr').value || null, joiningDate: $('#uJoin').value || null, employeeId: $('#uEmp').value,
    assignments: asgDraft
  };
  if (me.superAdmin && $('#uRole').value === 'admin') body.superAdmin = $('#uSuper').checked;
  if ($('#uPass').value) body.password = $('#uPass').value;
  try {
    if (editing) await api('/admin/users/' + editing.id, { method: 'PATCH', body });
    else await api('/admin/users', { method: 'POST', body: { ...body, email: $('#uEmail').value } });
    $('#userDlg').close(); toast(editing ? 'Changes saved' : 'User added'); loadUsers();
    if (editing && editing.id === me.id) { me = (await api('/me')).user; buildNav(); }
  } catch (err) { $('#uErr').textContent = err.message; }
});

/* ---------- admin: knowledge (with approval workflow) ---------- */
let entries = [], reviewing = null;
async function loadKnow() {
  entries = (await api('/admin/knowledge')).entries;
  $('#knowRows').innerHTML = entries.map(k => {
    const mine = k.createdBy === me.email, live = k.status === 'approved';
    const acts = [];
    if (me.superAdmin && !live) acts.push(`<button class="btn small" data-rev="${k.id}">${k.status === 'pending' ? 'Review' : 'Approve'}</button>`);
    if (!me.superAdmin && mine && (k.status === 'draft' || k.status === 'rejected')) acts.push(`<button class="btn small" data-sub="${k.id}">Submit</button>`);
    if (me.superAdmin || (mine && !live)) acts.push(`<button class="btn danger small" data-kd="${k.id}">Delete</button>`);
    return `<tr><td><b>${esc(k.title)}</b>${k.createdByName ? `<br><span class="muted">by ${esc(k.createdByName)}</span>` : ''}</td>
      <td><span class="tag ${tagFor[k.status] || ''}">${esc(k.status)}</span>${k.status === 'rejected' && k.reviewNote ? `<br><span class="note">${esc(k.reviewNote)}</span>` : ''}</td>
      <td>${k.department === 'all' ? 'All' : esc(k.department)}</td>
      <td><span class="badge ${k.audience === 'admin' ? 'admin' : ''}">${k.audience === 'admin' ? 'Admin only' : 'Everyone'}</span></td>
      <td class="muted clip">${esc(k.text.length > 120 ? k.text.slice(0, 120) + '...' : k.text)}</td>
      <td style="white-space:nowrap">${acts.join(' ')}</td></tr>`;
  }).join('');
  $('#knowRows').querySelectorAll('[data-kd]').forEach(b => b.onclick = async () => {
    if (!confirm('Delete this entry? The assistant will stop using it.')) return;
    try { await api('/admin/knowledge/' + b.dataset.kd, { method: 'DELETE' }); toast('Entry deleted'); loadKnow(); } catch (e) { toast(e.message); }
  });
  $('#knowRows').querySelectorAll('[data-sub]').forEach(b => b.onclick = async () => {
    try { await api('/admin/knowledge/' + b.dataset.sub, { method: 'PATCH', body: { action: 'submit' } }); toast('Submitted for approval'); loadKnow(); } catch (e) { toast(e.message); }
  });
  $('#knowRows').querySelectorAll('[data-rev]').forEach(b => b.onclick = () => {
    reviewing = entries.find(k => k.id === b.dataset.rev); $('#revNote').value = '';
    $('#revInfo').innerHTML = `<p><b>${esc(reviewing.title)}</b> <span class="tag ${tagFor[reviewing.status]}">${esc(reviewing.status)}</span><br><span class="muted">by ${esc(reviewing.createdByName || 'unknown')} &middot; ${reviewing.department === 'all' ? 'all departments' : esc(reviewing.department)}</span></p><p style="white-space:pre-wrap">${esc(reviewing.text)}</p>`;
    $('#revReject').classList.toggle('hidden', reviewing.status !== 'pending'); $('#revDlg').showModal();
  });
}
async function review(action) {
  try { await api('/admin/knowledge/' + reviewing.id, { method: 'PATCH', body: { action, note: $('#revNote').value } }); $('#revDlg').close(); toast(action === 'approve' ? 'Entry approved' : 'Entry rejected'); loadKnow(); }
  catch (e) { toast(e.message); }
}
$('#revApprove').onclick = () => review('approve'); $('#revReject').onclick = () => review('reject'); $('#revCancel').onclick = () => $('#revDlg').close();
$('#addKnow').onclick = () => {
  $('#kErr').textContent = ''; $('#knowForm').reset(); fill($('#kDept'), deptOpts(['all', 'All departments']));
  $('#kButtons').innerHTML = me.superAdmin ? '<button class="btn" type="submit" value="publish">Publish</button>'
    : '<button class="btn ghost" type="submit" value="draft">Save draft</button><button class="btn" type="submit" value="submit">Submit for approval</button>';
  $('#knowDlg').showModal();
};
$('#kCancel').onclick = () => $('#knowDlg').close();
$('#knowForm').addEventListener('submit', async e => {
  e.preventDefault(); $('#kErr').textContent = '';
  try {
    await api('/admin/knowledge', { method: 'POST', body: { title: $('#kTitle').value, keywords: $('#kKeys').value, audience: $('#kAud').value, department: $('#kDept').value, text: $('#kText').value, submit: e.submitter?.value === 'submit' } });
    $('#knowDlg').close(); toast(me.superAdmin ? 'Entry published' : (e.submitter?.value === 'submit' ? 'Submitted for approval' : 'Draft saved')); loadKnow();
  } catch (err) { $('#kErr').textContent = err.message; }
});

/* ---------- admin: feedback ---------- */
async function loadFeedback() {
  fill($('#fbFilter'), [['', 'All feedback'], ['down', 'Not helpful only'], ['up', 'Helpful only']], $('#fbFilter').value || '');
  const d = await api('/admin/feedback' + ($('#fbFilter').value ? '?rating=' + $('#fbFilter').value : ''));
  const tot = d.up + d.down;
  $('#fbStats').innerHTML = `<div class="stat"><div class="k">Helpful</div><div class="v">${d.up}</div></div><div class="stat"><div class="k">Not helpful</div><div class="v">${d.down}</div></div>
    <div class="stat"><div class="k">Satisfaction</div><div class="v">${tot ? Math.round(100 * d.up / tot) + '%' : '-'}</div></div>`;
  $('#fbRows').innerHTML = d.items.map(f => `<tr><td><b>${esc(f.question)}</b></td><td>${f.rating === 'up' ? '&#128077;' : '&#128078;'}</td>
    <td class="muted clip">${esc(f.answer.length > 160 ? f.answer.slice(0, 160) + '...' : f.answer)}${f.sources.length ? `<br><span class="note">Sources: ${esc(f.sources.join(', '))}</span>` : ''}</td>
    <td>${esc(f.userName)}${f.department ? ' (' + esc(f.department) + ')' : ''}<br><span class="muted">${esc(fmtDate(f.createdAt))}</span></td></tr>`).join('') || '<tr><td colspan="4" class="empty">No feedback yet.</td></tr>';
}
$('#fbFilter').onchange = loadFeedback;

/* ---------- admin: analytics ---------- */
async function loadAnalytics() {
  const a = await api('/admin/analytics'), st = (k, v, s) => `<div class="stat"><div class="k">${k}</div><div class="v">${v}</div>${s ? `<div class="s">${s}</div>` : ''}</div>`;
  const days = [...Array(7)].map((_, i) => { const d = new Date(); d.setHours(0, 0, 0, 0); d.setDate(d.getDate() - (6 - i)); return d; });
  const counts = days.map(() => 0);
  a.questions.times7d.forEach(t => { const d = new Date(t); d.setHours(0, 0, 0, 0); const i = days.findIndex(x => x.getTime() === d.getTime()); if (i >= 0) counts[i]++; });
  const mx = Math.max(1, ...counts), pct = v => v === null ? '-' : v + '%';
  $('#anBody').innerHTML = `<div class="grid-cards">
    ${st('Total users', a.users.total, a.users.active + ' active accounts')}${st('Active users (7 days)', a.users.active7d, a.users.activeToday + ' in the last 24 h')}
    ${st('Questions (24 h)', a.questions.last24h, a.questions.total + ' in 90 days')}${st('Answered', pct(a.questions.answeredPct), 'found something relevant')}
    ${st('Documents uploaded', a.documents.total, a.documents.searchable + ' searchable by the assistant')}${st('Announcements', a.documents.announcements)}
    ${st('Satisfaction', pct(a.feedback.satisfactionPct), a.feedback.up + ' helpful, ' + a.feedback.down + ' not')}</div>
    <div class="cols-2"><div class="panel pad"><h3>Most asked questions</h3>${bars(a.questions.top.map(q => [q.question, q.count]))}</div>
    <div class="panel pad"><h3>Questions with no answer</h3><p class="note">Good candidates for new knowledge entries or documents.</p>${bars(a.questions.unanswered.map(q => [q.question, q.count]), 'bad')}</div></div>
    <div class="panel pad" style="margin-top:16px"><h3>Questions per day (last 7 days)</h3><div class="daybars">${counts.map((n, i) => `<div><b>${n}</b><i style="height:${Math.max(3, Math.round(90 * n / mx))}px"></i><span>${days[i].toLocaleDateString(undefined, { weekday: 'short' })}</span></div>`).join('')}</div></div>
    <div class="cols-2" style="margin-top:16px"><div class="panel pad"><h3>Requests</h3>${bars(Object.entries(a.requests))}</div>
    <div class="panel pad"><h3>Tasks</h3>${bars([['Assigned', a.tasks.Assigned], ['In Progress', a.tasks['In Progress']], ['Completed', a.tasks.Completed], ['Overdue', a.tasks.overdue]])}</div>
    <div class="panel pad"><h3>Knowledge entries</h3>${bars(Object.entries(a.knowledge))}</div>
    <div class="panel pad"><h3>Users by department</h3>${bars(Object.entries(a.users.byDepartment))}</div></div>`;
}

/* ---------- theme (light / dark) ---------- */
function themeLabels() {
  const label = document.documentElement.dataset.theme === 'dark' ? 'Light mode' : 'Dark mode';
  $('#themeBtn').textContent = label; $('#themeLogin').textContent = label;
}
function toggleTheme() {
  const next = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark';
  document.documentElement.dataset.theme = next; localStorage.setItem('portal_theme', next); themeLabels();
}
$('#themeBtn').onclick = toggleTheme; $('#themeLogin').onclick = toggleTheme; themeLabels();

/* ---------- show / hide password on every password field ---------- */
function enhancePasswords() {
  document.querySelectorAll('input[type=password]').forEach(inp => {
    if (inp.parentElement.classList.contains('pw')) return;
    const wrap = document.createElement('div'); wrap.className = 'pw';
    inp.parentNode.insertBefore(wrap, inp); wrap.appendChild(inp);
    const b = document.createElement('button');
    b.type = 'button'; b.className = 'pw-toggle'; b.textContent = 'Show';
    b.setAttribute('aria-label', 'Show password'); b.setAttribute('aria-pressed', 'false');
    b.onclick = () => {
      const show = inp.type === 'password';
      inp.type = show ? 'text' : 'password'; b.textContent = show ? 'Hide' : 'Show';
      b.setAttribute('aria-pressed', String(show)); b.setAttribute('aria-label', show ? 'Hide password' : 'Show password');
    };
    wrap.appendChild(b);
  });
}
function hidePasswords() {
  document.querySelectorAll('.pw input').forEach(i => { i.type = 'password'; });
  document.querySelectorAll('.pw-toggle').forEach(b => { b.textContent = 'Show'; b.setAttribute('aria-pressed', 'false'); b.setAttribute('aria-label', 'Show password'); });
}
enhancePasswords();

/* ---------- remember me: pre-fill the email ---------- */
const savedEmail = localStorage.getItem('portal_email');
if (savedEmail) { $('#lEmail').value = savedEmail; $('#lRemember').checked = true; }

boot();
