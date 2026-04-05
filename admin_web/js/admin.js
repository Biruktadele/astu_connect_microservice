const API = window.location.origin;
const token = () => localStorage.getItem('admin_token');
if (!token()) window.location.href = 'login.html';

const headers = () => ({
  'Authorization': `Bearer ${token()}`,
  'Content-Type': 'application/json'
});

async function api(path, opts = {}) {
  const res = await fetch(`${API}${path}`, { headers: headers(), ...opts });
  if (res.status === 401 || res.status === 403) {
    localStorage.removeItem('admin_token');
    window.location.href = 'login.html';
    return null;
  }
  return res;
}

function fmtDate(d) {
  return new Date(d).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
}

// Navigation
document.querySelectorAll('.sidebar nav a').forEach(link => {
  link.addEventListener('click', e => {
    e.preventDefault();
    const page = link.dataset.page;
    document.querySelectorAll('.sidebar nav a').forEach(a => a.classList.remove('active'));
    link.classList.add('active');
    document.querySelectorAll('.section').forEach(s => s.classList.remove('active'));
    document.getElementById(`page-${page}`).classList.add('active');
    loadPage(page);
  });
});

document.getElementById('logoutBtn').addEventListener('click', () => {
  localStorage.removeItem('admin_token');
  localStorage.removeItem('admin_refresh');
  window.location.href = 'login.html';
});

function loadPage(page) {
  if (page === 'overview') loadOverview();
  else if (page === 'users') loadUsers();
  else if (page === 'flagged') loadFlagged();
  else if (page === 'posts') loadPosts();
  else if (page === 'communities') loadCommunities();
}

// ---------- Overview ----------
async function loadOverview() {
  const el = document.getElementById('overviewStats');
  el.innerHTML = '<p class="loading">Loading...</p>';

  const [userRes, feedRes, communityRes] = await Promise.all([
    api('/api/v1/admin/stats'),
    api('/api/v1/feed/admin/stats'),
    api('/api/v1/communities/admin/stats'),
  ]);

  const u = userRes ? await userRes.json() : {};
  const f = feedRes ? await feedRes.json() : {};
  const c = communityRes ? await communityRes.json() : {};

  el.innerHTML = `
    <div class="stat-card"><div class="label">Total Users</div><div class="value">${u.total_users || 0}</div></div>
    <div class="stat-card success"><div class="label">Active Users</div><div class="value">${u.active_users || 0}</div></div>
    <div class="stat-card danger"><div class="label">Banned Users</div><div class="value">${u.banned_users || 0}</div></div>
    <div class="stat-card"><div class="label">New Today</div><div class="value">${u.new_today || 0}</div></div>
    <div class="stat-card"><div class="label">Total Posts</div><div class="value">${f.total_posts || 0}</div></div>
    <div class="stat-card flagged"><div class="label">Flagged Posts</div><div class="value">${f.flagged_count || 0}</div></div>
    <div class="stat-card danger"><div class="label">Rejected Posts</div><div class="value">${f.rejected_count || 0}</div></div>
    <div class="stat-card"><div class="label">Communities</div><div class="value">${c.total_communities || 0}</div></div>
    <div class="stat-card"><div class="label">Community Members</div><div class="value">${c.total_members || 0}</div></div>
  `;
}

// ---------- Users ----------
let usersOffset = 0;
const LIMIT = 30;

async function loadUsers(offset = 0) {
  usersOffset = offset;
  const q = document.getElementById('userSearch').value;
  const st = document.getElementById('userStatusFilter').value;
  let url = `/api/v1/admin/users?limit=${LIMIT}&offset=${offset}`;
  if (q) url += `&q=${encodeURIComponent(q)}`;
  if (st) url += `&status=${st}`;
  const res = await api(url);
  if (!res) return;
  const data = await res.json();
  const tbody = document.getElementById('usersTable');
  tbody.innerHTML = data.users.map(u => `
    <tr>
      <td><strong>${esc(u.username)}</strong><br><small>${esc(u.display_name)}</small></td>
      <td>${esc(u.email)}</td>
      <td>${u.roles.map(r => `<span class="badge ${r}">${r}</span>`).join(' ')}</td>
      <td><span class="badge ${u.status}">${u.status}</span></td>
      <td>${fmtDate(u.created_at)}</td>
      <td>
        ${u.status === 'banned'
          ? `<button class="btn btn-success btn-sm" onclick="unbanUser('${u.id}')">Unban</button>`
          : `<button class="btn btn-danger btn-sm" onclick="banUser('${u.id}')">Ban</button>`}
        <button class="btn btn-primary btn-sm" onclick="promptRoles('${u.id}','${u.roles.join(',')}')">Roles</button>
      </td>
    </tr>
  `).join('');
  renderPagination('usersPagination', data.total, offset, o => loadUsers(o));
}

document.getElementById('userSearch').addEventListener('input', debounce(() => loadUsers(0), 400));
document.getElementById('userStatusFilter').addEventListener('change', () => loadUsers(0));

window.banUser = async (id) => {
  if (!confirm('Ban this user?')) return;
  await api(`/api/v1/admin/users/${id}/ban`, { method: 'PUT' });
  loadUsers(usersOffset);
};
window.unbanUser = async (id) => {
  await api(`/api/v1/admin/users/${id}/unban`, { method: 'PUT' });
  loadUsers(usersOffset);
};
window.promptRoles = async (id, current) => {
  const input = prompt('Set roles (comma-separated, e.g. student,admin):', current);
  if (input === null) return;
  const roles = input.split(',').map(r => r.trim()).filter(Boolean);
  await api(`/api/v1/admin/users/${id}/roles`, { method: 'PUT', body: JSON.stringify({ roles }) });
  loadUsers(usersOffset);
};

// ---------- Flagged Content ----------
let flaggedOffset = 0;

async function loadFlagged(offset = 0) {
  flaggedOffset = offset;
  const res = await api(`/api/v1/feed/admin/posts?moderation_status=flagged&limit=${LIMIT}&offset=${offset}`);
  if (!res) return;
  const data = await res.json();
  const tbody = document.getElementById('flaggedTable');
  tbody.innerHTML = data.posts.length === 0
    ? '<tr><td colspan="6" style="text-align:center;color:var(--muted)">No flagged content</td></tr>'
    : data.posts.map(p => `
    <tr>
      <td>${p.media_refs.length ? p.media_refs.map(u => `<img src="${esc(u)}" class="media-thumb" onerror="this.style.display='none'">`).join('') : '—'}</td>
      <td class="post-body">${esc(p.body)}</td>
      <td>${esc(p.author_id).substring(0,8)}...</td>
      <td><span class="badge flagged">flagged</span></td>
      <td>${fmtDate(p.created_at)}</td>
      <td>
        <button class="btn btn-success btn-sm" onclick="approvePost('${p.id}')">Approve</button>
        <button class="btn btn-danger btn-sm" onclick="rejectPost('${p.id}')">Reject</button>
      </td>
    </tr>
  `).join('');
  renderPagination('flaggedPagination', data.total, offset, o => loadFlagged(o));
}

window.approvePost = async (id) => {
  await api(`/api/v1/feed/admin/posts/${id}/approve`, { method: 'PUT' });
  loadFlagged(flaggedOffset);
  loadOverview();
};
window.rejectPost = async (id) => {
  if (!confirm('Reject this post? It will be hidden from all feeds.')) return;
  await api(`/api/v1/feed/admin/posts/${id}/reject`, { method: 'PUT' });
  loadFlagged(flaggedOffset);
  loadOverview();
};

// ---------- All Posts ----------
let postsOffset = 0;

async function loadPosts(offset = 0) {
  postsOffset = offset;
  const res = await api(`/api/v1/feed/admin/posts?limit=${LIMIT}&offset=${offset}`);
  if (!res) return;
  const data = await res.json();
  const tbody = document.getElementById('postsTable');
  tbody.innerHTML = data.posts.map(p => `
    <tr>
      <td class="post-body">${esc(p.body)}</td>
      <td>${esc(p.author_id).substring(0,8)}...</td>
      <td><span class="badge ${p.moderation_status}">${p.moderation_status}</span></td>
      <td>${p.comment_count}</td>
      <td>${fmtDate(p.created_at)}</td>
      <td>
        <button class="btn btn-danger btn-sm" onclick="deletePost('${p.id}')">Delete</button>
        ${p.moderation_status === 'flagged' ? `<button class="btn btn-success btn-sm" onclick="approvePost('${p.id}')">Approve</button>` : ''}
      </td>
    </tr>
  `).join('');
  renderPagination('postsPagination', data.total, offset, o => loadPosts(o));
}

window.deletePost = async (id) => {
  if (!confirm('Delete this post permanently?')) return;
  await api(`/api/v1/feed/admin/posts/${id}`, { method: 'DELETE' });
  loadPosts(postsOffset);
};

// ---------- Communities ----------
let communitiesOffset = 0;

async function loadCommunities(offset = 0) {
  communitiesOffset = offset;
  const q = document.getElementById('communitySearch').value;
  let url = `/api/v1/communities/admin/list?limit=${LIMIT}&offset=${offset}`;
  if (q) url += `&q=${encodeURIComponent(q)}`;
  const res = await api(url);
  if (!res) return;
  const data = await res.json();
  const tbody = document.getElementById('communitiesTable');
  tbody.innerHTML = data.communities.map(c => `
    <tr>
      <td><strong>${esc(c.name)}</strong></td>
      <td>${esc(c.slug)}</td>
      <td>${c.member_count}</td>
      <td>${c.visibility}</td>
      <td>${fmtDate(c.created_at)}</td>
      <td>
        <button class="btn btn-danger btn-sm" onclick="archiveCommunity('${c.id}')">Archive</button>
      </td>
    </tr>
  `).join('');
  renderPagination('communitiesPagination', data.total, offset, o => loadCommunities(o));
}

document.getElementById('communitySearch').addEventListener('input', debounce(() => loadCommunities(0), 400));

window.archiveCommunity = async (id) => {
  if (!confirm('Archive this community?')) return;
  await api(`/api/v1/communities/admin/${id}`, { method: 'DELETE' });
  loadCommunities(communitiesOffset);
};

// ---------- Helpers ----------
function esc(s) {
  const d = document.createElement('div');
  d.textContent = s || '';
  return d.innerHTML;
}

function debounce(fn, ms) {
  let t;
  return (...args) => { clearTimeout(t); t = setTimeout(() => fn(...args), ms); };
}

function renderPagination(elId, total, offset, loadFn) {
  const el = document.getElementById(elId);
  const pages = Math.ceil(total / LIMIT);
  const current = Math.floor(offset / LIMIT);
  if (pages <= 1) { el.innerHTML = ''; return; }
  let html = '';
  html += `<button ${current === 0 ? 'disabled' : ''} onclick="void(0)">Prev</button>`;
  for (let i = 0; i < Math.min(pages, 7); i++) {
    html += `<button class="${i === current ? 'current' : ''}" data-offset="${i * LIMIT}">${i + 1}</button>`;
  }
  html += `<button ${current >= pages - 1 ? 'disabled' : ''} onclick="void(0)">Next</button>`;
  el.innerHTML = html;
  el.querySelectorAll('button[data-offset]').forEach(btn => {
    btn.addEventListener('click', () => loadFn(parseInt(btn.dataset.offset)));
  });
  const btns = el.querySelectorAll('button');
  btns[0].addEventListener('click', () => { if (current > 0) loadFn((current - 1) * LIMIT); });
  btns[btns.length - 1].addEventListener('click', () => { if (current < pages - 1) loadFn((current + 1) * LIMIT); });
}

// Initial load
loadOverview();
