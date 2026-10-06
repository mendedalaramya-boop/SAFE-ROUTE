// SafeRoute -- Phase F4: notifications page.
//
//   GET   /api/notifications?unread_only=&limit=&offset=   (auth)
//        -> { notifications: [...], count, unread_count }
//   PATCH /api/notifications/<id>/read                     (auth)
//        -> { notification: {...} }
//
// Notification shape (app/models/notification_model.py):
//   id, user_id, hazard_id, notification_type, title, message, is_read, created_at

(function () {
  if (!SafeRouteAPI.isLoggedIn()) {
    window.location.href = 'login.html';
    return;
  }

  const TYPE_META = {
    hazard_submitted:   { label: 'Report submitted', tone: 'pending' },
    hazard_verified:    { label: 'Report verified',  tone: 'verified' },
    hazard_rejected:    { label: 'Report rejected',  tone: 'rejected' },
    hazard_resolved:    { label: 'Hazard resolved',  tone: 'verified' },
    hazard_update:      { label: 'Update',           tone: 'pending' },
    route_hazard_alert: { label: 'Route alert',      tone: 'pending' },
  };

  const state = { filter: 'all' }; // 'all' | 'unread'

  function escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = str == null ? '' : String(str);
    return div.innerHTML;
  }

  function formatWhen(iso) {
    if (!iso) return '';
    const d = new Date(iso);
    if (isNaN(d.getTime())) return escapeHtml(iso);
    const mins = Math.round((Date.now() - d.getTime()) / 60000);
    if (mins < 1) return 'just now';
    if (mins < 60) return `${mins}m ago`;
    const hrs = Math.round(mins / 60);
    if (hrs < 24) return `${hrs}h ago`;
    const days = Math.round(hrs / 24);
    if (days < 7) return `${days}d ago`;
    return d.toLocaleDateString();
  }

  // ---- nav / session ---------------------------------------------------

  function loadNavUser() {
    const cached = SafeRouteAPI.getUser();
    if (cached) paintNavUser(cached);
    SafeRouteAPI.request('/profile', { auth: true })
      .then((result) => paintNavUser(result.data.user))
      .catch(() => {
        SafeRouteAPI.clearSession();
        window.location.href = 'login.html';
      });
  }

  function paintNavUser(user) {
    const nameEl = document.getElementById('nav-user-name');
    const badgeEl = document.getElementById('nav-user-badge');
    if (nameEl) nameEl.textContent = user.name || user.email || 'Account';
    if (badgeEl) {
      badgeEl.className = 'badge ' + (user.role === 'admin' ? 'badge--admin' : 'badge--user');
      badgeEl.textContent = user.role === 'admin' ? 'ADMIN' : 'USER';
    }
    const adminLink = document.getElementById('nav-admin-link');
    if (adminLink) adminLink.hidden = user.role !== 'admin';
  }

  document.getElementById('logout-btn').addEventListener('click', async () => {
    try {
      await SafeRouteAPI.request('/auth/logout', { method: 'POST', auth: true });
    } catch { /* clear locally regardless */ }
    SafeRouteAPI.clearSession();
    window.location.href = 'login.html';
  });

  // ---- filter chips -----------------------------------------------------

  document.querySelectorAll('[data-filter]').forEach((chip) => {
    chip.addEventListener('click', () => {
      state.filter = chip.getAttribute('data-filter');
      document.querySelectorAll('[data-filter]').forEach((c) => c.classList.toggle('is-active', c === chip));
      fetchNotifications();
    });
  });

  // ---- fetch & render -----------------------------------------------------

  const listEl = document.getElementById('notifications-list');
  const loadingEl = document.getElementById('notifications-loading');
  const emptyEl = document.getElementById('empty-state');
  const errorEl = document.getElementById('list-error');
  const countEl = document.getElementById('results-count');
  const navDot = document.getElementById('nav-unread-dot');

  function updateNavDot(unreadCount) {
    if (navDot) navDot.hidden = unreadCount === 0;
  }

  function fetchNotifications() {
    loadingEl.hidden = false;
    errorEl.hidden = true;
    emptyEl.hidden = true;
    listEl.innerHTML = '';

    const params = new URLSearchParams();
    if (state.filter === 'unread') params.set('unread_only', 'true');

    SafeRouteAPI.request(`/notifications?${params.toString()}`, { auth: true })
      .then((result) => {
        loadingEl.hidden = true;
        const { notifications, unread_count } = result.data;
        updateNavDot(unread_count);

        countEl.textContent = notifications.length
          ? `${notifications.length} notification${notifications.length === 1 ? '' : 's'}${unread_count ? ` · ${unread_count} unread` : ''}`
          : '';

        if (!notifications.length) {
          emptyEl.hidden = false;
          emptyEl.textContent = state.filter === 'unread'
            ? "You're all caught up -- no unread notifications."
            : "Nothing here yet -- you'll see updates on your reports and hazards along your recent routes.";
          return;
        }

        listEl.innerHTML = notifications.map(renderCard).join('');
      })
      .catch((err) => {
        loadingEl.hidden = true;
        errorEl.textContent = err.message || 'Could not load notifications right now.';
        errorEl.hidden = false;
      });
  }

  function renderCard(n) {
    const meta = TYPE_META[n.notification_type] || { label: n.notification_type, tone: 'pending' };
    const unreadClass = n.is_read ? '' : ' notification-card--unread';
    return `
      <article class="notification-card${unreadClass}" data-id="${escapeHtml(n.id)}">
        <div class="notification-card__top">
          <span class="badge badge--status-${meta.tone}">${escapeHtml(meta.label)}</span>
          <span class="notification-card__time">${formatWhen(n.created_at)}</span>
        </div>
        <h4 class="notification-card__title">${escapeHtml(n.title)}</h4>
        <p class="notification-card__message">${escapeHtml(n.message)}</p>
        ${!n.is_read ? `<button type="button" class="link-btn" data-mark-read="${escapeHtml(n.id)}">Mark as read</button>` : ''}
      </article>
    `;
  }

  listEl.addEventListener('click', async (event) => {
    const btn = event.target.closest('[data-mark-read]');
    if (!btn) return;
    const id = btn.getAttribute('data-mark-read');
    btn.disabled = true;
    btn.textContent = 'Marking…';
    try {
      await SafeRouteAPI.request(`/notifications/${encodeURIComponent(id)}/read`, {
        method: 'PATCH',
        auth: true,
      });
      fetchNotifications();
    } catch (err) {
      btn.disabled = false;
      btn.textContent = 'Mark as read';
      errorEl.textContent = err.message || 'Could not mark this as read.';
      errorEl.hidden = false;
    }
  });

  // "Mark all as read" -- the backend has no bulk endpoint, so this marks
  // each currently-unread notification one at a time.
  document.getElementById('mark-all-read-btn').addEventListener('click', async (event) => {
    const button = event.currentTarget;
    button.disabled = true;
    const originalText = button.textContent;
    button.textContent = 'Marking all…';

    try {
      const result = await SafeRouteAPI.request('/notifications?unread_only=true&limit=100', { auth: true });
      const unread = result.data.notifications;
      for (const n of unread) {
        await SafeRouteAPI.request(`/notifications/${n.id}/read`, { method: 'PATCH', auth: true });
      }
      fetchNotifications();
    } catch (err) {
      errorEl.textContent = err.message || 'Could not mark all as read.';
      errorEl.hidden = false;
    } finally {
      button.disabled = false;
      button.textContent = originalText;
    }
  });

  // ---- go -------------------------------------------------------------

  loadNavUser();
  fetchNotifications();
})();
