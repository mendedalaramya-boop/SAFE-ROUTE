// SafeRoute -- Admin Panel Management Script
// Handles moderator verification queues, verified hazard management,
// system metrics & analytics, and audit logging.

(function () {
  'use strict';

  // 1. Check Authentication & Admin Role
  if (!SafeRouteAPI.isLoggedIn()) {
    window.location.href = 'login.html';
    return;
  }

  const currentUser = SafeRouteAPI.getUser();
  const forbiddenBanner = document.getElementById('admin-forbidden-banner');
  const adminContent = document.getElementById('admin-content');

  if (!currentUser || currentUser.role !== 'admin') {
    forbiddenBanner.hidden = false;
    adminContent.hidden = true;
    return;
  }

  // Admin access confirmed
  forbiddenBanner.hidden = true;
  adminContent.hidden = false;

  // Utilities
  function escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = str == null ? '' : String(str);
    return div.innerHTML;
  }

  function formatDateTime(iso) {
    if (!iso) return '—';
    const d = new Date(iso);
    return isNaN(d.getTime()) ? escapeHtml(iso) : d.toLocaleString();
  }

  function formatTimeAgo(iso) {
    if (!iso) return '';
    const d = new Date(iso);
    if (isNaN(d.getTime())) return escapeHtml(iso);
    const mins = Math.round((Date.now() - d.getTime()) / 60000);
    if (mins < 1) return 'just now';
    if (mins < 60) return `${mins}m ago`;
    const hrs = Math.round(mins / 60);
    if (hrs < 24) return `${hrs}h ago`;
    const days = Math.round(hrs / 24);
    return `${days}d ago`;
  }

  const TYPE_LABELS = {
    road_closure: 'Road closure',
    flooding: 'Flooding',
    waterlogging: 'Waterlogging',
    construction: 'Construction',
    blocked_road: 'Blocked road',
    accident: 'Accident',
    temporary_restriction: 'Temporary restriction',
    other: 'Other',
  };

  const SEVERITY_LABELS = {
    low: 'Low',
    medium: 'Medium',
    high: 'High',
    critical: 'Critical',
  };

  // Nav & Profile Setup
  function initNav() {
    const nameEl = document.getElementById('nav-user-name');
    const badgeEl = document.getElementById('nav-user-badge');
    if (nameEl) nameEl.textContent = currentUser.name || currentUser.email || 'Admin';
    if (badgeEl) {
      badgeEl.className = 'badge badge--admin';
      badgeEl.textContent = 'ADMIN';
    }

    document.getElementById('logout-btn').addEventListener('click', async () => {
      try {
        await SafeRouteAPI.request('/auth/logout', { method: 'POST', auth: true });
      } catch {}
      SafeRouteAPI.clearSession();
      window.location.href = 'login.html';
    });

    // Unread notifications check
    SafeRouteAPI.request('/notifications?unread_only=true&limit=1', { auth: true })
      .then((res) => {
        const dot = document.getElementById('nav-unread-dot');
        if (dot) dot.hidden = (res.data.unread_count || 0) === 0;
      })
      .catch(() => {});
  }

  // Banners
  const errorBanner = document.getElementById('admin-error');
  const successBanner = document.getElementById('admin-success');

  function showMessage(type, text) {
    if (type === 'error') {
      errorBanner.textContent = text;
      errorBanner.classList.add('is-visible');
      successBanner.classList.remove('is-visible');
      setTimeout(() => errorBanner.classList.remove('is-visible'), 5000);
    } else {
      successBanner.textContent = text;
      successBanner.classList.add('is-visible');
      errorBanner.classList.remove('is-visible');
      setTimeout(() => successBanner.classList.remove('is-visible'), 4000);
    }
  }

  // Reason Modal Manager
  const modalOverlay = document.getElementById('reason-modal');
  const modalTitle = document.getElementById('reason-modal-title');
  const modalForm = document.getElementById('reason-form');
  const modalBanner = document.getElementById('reason-banner');
  const modalNote = document.getElementById('reason-note');
  const modalLabel = document.getElementById('reason-note-label');
  const modalHint = document.getElementById('reason-note-hint');
  const modalClose = document.getElementById('reason-modal-close');
  const modalSubmitBtn = document.getElementById('reason-submit-btn');
  const modalSubmitLabel = document.getElementById('reason-submit-label');

  let currentModalAction = null; // { type: 'reject'|'resolve', hazardId: N, callback: fn }

  function openReasonModal({ title, label, hint, submitText, isRequired, onConfirm }) {
    modalTitle.textContent = title;
    modalLabel.textContent = label || 'Note';
    modalHint.textContent = hint || '';
    modalSubmitLabel.textContent = submitText || 'Confirm';
    modalNote.value = '';
    modalBanner.textContent = '';
    modalBanner.classList.remove('is-visible');
    currentModalAction = { isRequired, onConfirm };
    modalOverlay.hidden = false;
    modalNote.focus();
  }

  function closeReasonModal() {
    modalOverlay.hidden = true;
    currentModalAction = null;
  }

  modalClose.addEventListener('click', closeReasonModal);
  modalOverlay.addEventListener('click', (e) => {
    if (e.target === modalOverlay) closeReasonModal();
  });

  modalForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    if (!currentModalAction) return;

    const note = modalNote.value.trim();
    if (currentModalAction.isRequired && !note) {
      modalBanner.textContent = 'Please provide a reason note before proceeding.';
      modalBanner.classList.add('is-visible');
      modalNote.focus();
      return;
    }

    modalSubmitBtn.disabled = true;
    modalSubmitBtn.classList.add('is-loading');

    try {
      await currentModalAction.onConfirm(note);
      closeReasonModal();
    } catch (err) {
      modalBanner.textContent = err.message || 'Operation failed.';
      modalBanner.classList.add('is-visible');
    } finally {
      modalSubmitBtn.disabled = false;
      modalSubmitBtn.classList.remove('is-loading');
    }
  });

  // Tab Navigation
  const tabs = document.querySelectorAll('.admin-tab');
  const panes = {
    pending: document.getElementById('pane-pending'),
    verified: document.getElementById('pane-verified'),
    reports: document.getElementById('pane-reports'),
    audit: document.getElementById('pane-audit'),
  };

  tabs.forEach((tab) => {
    tab.addEventListener('click', () => {
      const target = tab.getAttribute('data-admin-tab');
      tabs.forEach((t) => t.classList.toggle('is-active', t === tab));
      Object.entries(panes).forEach(([k, pane]) => {
        pane.hidden = k !== target;
      });

      if (target === 'pending') loadPendingReview();
      if (target === 'verified') loadVerifiedHazards();
      if (target === 'reports') loadReportsData();
      if (target === 'audit') loadAuditLogs();
    });
  });

  // =========================================================================
  // 1. PENDING REVIEW TAB
  // =========================================================================
  const pendingList = document.getElementById('pending-list');
  const pendingEmpty = document.getElementById('pending-empty');
  const pendingCountBadge = document.getElementById('pending-count');

  async function loadPendingReview() {
    pendingList.innerHTML = '<p class="session-loading">Loading pending reports…</p>';
    pendingEmpty.hidden = true;

    try {
      const res = await SafeRouteAPI.request('/admin/hazards/pending', { auth: true });
      const hazards = res.data.hazards || [];
      pendingCountBadge.textContent = hazards.length ? String(hazards.length) : '';

      if (!hazards.length) {
        pendingList.innerHTML = '';
        pendingEmpty.hidden = false;
        return;
      }

      pendingList.innerHTML = hazards.map(renderPendingCard).join('');
      wirePendingActions();
    } catch (err) {
      pendingList.innerHTML = `<p class="banner banner--error is-visible"><span>${escapeHtml(err.message || 'Failed to load pending queue.')}</span></p>`;
    }
  }

  function renderPendingCard(h) {
    const sev = h.severity || 'medium';
    return `
      <article class="review-card" data-hazard-id="${escapeHtml(h.id)}">
        <div class="review-card__main">
          <div class="hazard-card__top">
            <span class="hazard-type">${escapeHtml(TYPE_LABELS[h.hazard_type] || h.hazard_type)}</span>
            <span class="badge badge--status-pending">PENDING REVIEW</span>
            ${h.is_potential_duplicate ? `<span class="badge badge--admin" title="Possible duplicate of #${h.duplicate_of_hazard_id}">DUPLICATE DETECTED</span>` : ''}
          </div>
          <h4 style="margin:6px 0 4px; font-size:1.05rem;">${escapeHtml(h.title)}</h4>
          <p style="margin:0 0 10px; color:var(--text-secondary); font-size:0.92rem;">${escapeHtml(h.description)}</p>
          <div class="hazard-card__meta">
            <span class="hazard-card__meta-item"><strong>Location:</strong> ${escapeHtml([h.address, h.city].filter(Boolean).join(', ') || 'Not specified')}</span>
            <span class="hazard-card__meta-item hazard-card__meta-item--${sev}">${SEVERITY_LABELS[sev] || sev} severity</span>
            <span class="hazard-card__meta-item"><strong>Reporter:</strong> ${escapeHtml(h.reporter_name || h.reporter_email || `User #${h.reporter_id}`)}</span>
            <span class="hazard-card__meta-item">Reported ${formatTimeAgo(h.created_at)}</span>
          </div>
        </div>
        <div class="review-card__actions">
          <button type="button" class="btn btn-primary btn--compact" data-action="verify" data-id="${escapeHtml(h.id)}">Verify & Publish</button>
          <button type="button" class="link-btn link-btn--danger" data-action="reject" data-id="${escapeHtml(h.id)}">Reject</button>
        </div>
      </article>
    `;
  }

  function wirePendingActions() {
    pendingList.querySelectorAll('[data-action="verify"]').forEach((btn) => {
      btn.addEventListener('click', () => {
        const id = btn.getAttribute('data-id');
        openReasonModal({
          title: `Verify Hazard #${id}`,
          label: 'Verification Note (Optional)',
          hint: 'Add context or official validation details if available.',
          submitText: 'Verify & Publish',
          isRequired: false,
          onConfirm: async (note) => {
            await SafeRouteAPI.request(`/hazards/${id}/verify`, {
              method: 'POST',
              auth: true,
              body: { verification_note: note },
            });
            showMessage('success', `Hazard #${id} verified and published.`);
            loadPendingReview();
          },
        });
      });
    });

    pendingList.querySelectorAll('[data-action="reject"]').forEach((btn) => {
      btn.addEventListener('click', () => {
        const id = btn.getAttribute('data-id');
        openReasonModal({
          title: `Reject Hazard #${id}`,
          label: 'Rejection Reason (Required)',
          hint: 'The reporter will be notified of this reason.',
          submitText: 'Confirm Rejection',
          isRequired: true,
          onConfirm: async (note) => {
            await SafeRouteAPI.request(`/hazards/${id}/reject`, {
              method: 'POST',
              auth: true,
              body: { verification_note: note },
            });
            showMessage('success', `Hazard #${id} rejected.`);
            loadPendingReview();
          },
        });
      });
    });
  }

  // =========================================================================
  // 2. VERIFIED HAZARDS TAB
  // =========================================================================
  const verifiedTbody = document.getElementById('verified-tbody');
  const verifiedEmpty = document.getElementById('verified-empty');
  const expireOverdueBtn = document.getElementById('expire-overdue-btn');

  async function loadVerifiedHazards() {
    verifiedTbody.innerHTML = '<tr><td colspan="7" class="session-loading">Loading verified hazards…</td></tr>';
    verifiedEmpty.hidden = true;

    try {
      const res = await SafeRouteAPI.request('/admin/hazards/verified', { auth: true });
      const hazards = res.data.hazards || [];

      if (!hazards.length) {
        verifiedTbody.innerHTML = '';
        verifiedEmpty.hidden = false;
        return;
      }

      verifiedTbody.innerHTML = hazards.map(renderVerifiedRow).join('');
      wireVerifiedActions();
    } catch (err) {
      verifiedTbody.innerHTML = `<tr><td colspan="7"><p class="banner banner--error is-visible"><span>${escapeHtml(err.message || 'Failed to load verified hazards.')}</span></p></td></tr>`;
    }
  }

  function renderVerifiedRow(h) {
    const isVisible = h.visibility === 'visible';
    return `
      <tr data-hazard-id="${escapeHtml(h.id)}">
        <td><strong>${escapeHtml(h.title)}</strong><br><span class="field__hint" style="margin:0;">#${h.id}</span></td>
        <td>${escapeHtml(TYPE_LABELS[h.hazard_type] || h.hazard_type)}</td>
        <td><span class="hazard-card__meta-item--${h.severity}">${escapeHtml(SEVERITY_LABELS[h.severity] || h.severity)}</span></td>
        <td>${escapeHtml(h.city || '—')}</td>
        <td>
          <span class="badge ${isVisible ? 'badge--status-verified' : 'badge--status-pending'}">
            ${isVisible ? 'VISIBLE' : 'HIDDEN'}
          </span>
        </td>
        <td>${formatTimeAgo(h.verified_at || h.created_at)}</td>
        <td>
          <div style="display:flex; gap:8px; align-items:center;">
            <button type="button" class="link-btn" data-action="toggle-vis" data-id="${escapeHtml(h.id)}" data-vis="${isVisible ? 'hidden' : 'visible'}">
              ${isVisible ? 'Hide' : 'Show'}
            </button>
            <button type="button" class="link-btn" data-action="resolve" data-id="${escapeHtml(h.id)}">
              Resolve
            </button>
          </div>
        </td>
      </tr>
    `;
  }

  function wireVerifiedActions() {
    verifiedTbody.querySelectorAll('[data-action="toggle-vis"]').forEach((btn) => {
      btn.addEventListener('click', async () => {
        const id = btn.getAttribute('data-id');
        const nextVis = btn.getAttribute('data-vis');
        try {
          await SafeRouteAPI.request(`/hazards/${id}/visibility`, {
            method: 'POST',
            auth: true,
            body: { visibility: nextVis },
          });
          showMessage('success', `Hazard #${id} visibility set to ${nextVis}.`);
          loadVerifiedHazards();
        } catch (err) {
          showMessage('error', err.message || 'Could not update visibility.');
        }
      });
    });

    verifiedTbody.querySelectorAll('[data-action="resolve"]').forEach((btn) => {
      btn.addEventListener('click', () => {
        const id = btn.getAttribute('data-id');
        openReasonModal({
          title: `Resolve Hazard #${id}`,
          label: 'Resolution Note',
          hint: 'Describe how the road hazard was cleared or resolved.',
          submitText: 'Mark Resolved',
          isRequired: false,
          onConfirm: async (note) => {
            await SafeRouteAPI.request(`/hazards/${id}/resolve`, {
              method: 'POST',
              auth: true,
              body: { resolution_note: note },
            });
            showMessage('success', `Hazard #${id} resolved.`);
            loadVerifiedHazards();
          },
        });
      });
    });
  }

  expireOverdueBtn.addEventListener('click', async () => {
    expireOverdueBtn.disabled = true;
    try {
      const res = await SafeRouteAPI.request('/hazards/expire-overdue', { method: 'POST', auth: true });
      showMessage('success', res.message || 'Overdue hazards expired.');
      loadVerifiedHazards();
    } catch (err) {
      showMessage('error', err.message || 'Could not expire overdue hazards.');
    } finally {
      expireOverdueBtn.disabled = false;
    }
  });

  // =========================================================================
  // 3. REPORTS & ANALYTICS TAB
  // =========================================================================
  const reportsBody = document.getElementById('reports-body');

  async function loadReportsData() {
    reportsBody.innerHTML = '<p class="session-loading">Loading platform reports and telemetry…</p>';

    try {
      let res;
      try {
        res = await SafeRouteAPI.request('/admin/reports/dashboard', { auth: true });
      } catch {
        res = await SafeRouteAPI.request('/admin/reports', { auth: true });
      }

      const { summary, by_type, by_severity, by_city, top_reporters = [], top_searchers = [] } = res.data;

      reportsBody.innerHTML = `
        <div class="route-stats" style="margin-bottom:var(--space-6);">
          <div class="route-stat">
            <div class="route-stat__value">${summary.total_hazards}</div>
            <div class="route-stat__label">Total Hazards Filed</div>
          </div>
          <div class="route-stat">
            <div class="route-stat__value" style="color:var(--tone-verified-text);">${summary.verified}</div>
            <div class="route-stat__label">Active Verified</div>
          </div>
          <div class="route-stat">
            <div class="route-stat__value" style="color:var(--tone-pending-text);">${summary.pending_review}</div>
            <div class="route-stat__label">Pending Review</div>
          </div>
          <div class="route-stat">
            <div class="route-stat__value">${summary.total_users}</div>
            <div class="route-stat__label">Registered Users</div>
          </div>
          <div class="route-stat">
            <div class="route-stat__value">${summary.total_searches}</div>
            <div class="route-stat__label">Route Searches</div>
          </div>
          <div class="route-stat">
            <div class="route-stat__value" style="color:var(--danger);">${summary.total_hazards_intercepted || 0}</div>
            <div class="route-stat__label">Hazards Intercepted</div>
          </div>
        </div>

        <div style="display:grid; grid-template-columns:repeat(auto-fit, minmax(280px, 1fr)); gap:var(--space-5); margin-bottom:var(--space-6);">
          <!-- By Severity -->
          <div class="review-card" style="flex-direction:column; align-items:flex-start;">
            <h4 style="margin:0 0 12px;">Hazards by Severity</h4>
            <div style="width:100%; display:flex; flex-direction:column; gap:8px;">
              ${by_severity.map((s) => `
                <div style="display:flex; justify-content:space-between; align-items:center; font-size:0.92rem;">
                  <span class="hazard-card__meta-item--${s.severity}">● ${SEVERITY_LABELS[s.severity] || s.severity}</span>
                  <strong>${s.cnt}</strong>
                </div>
              `).join('')}
            </div>
          </div>

          <!-- By Type -->
          <div class="review-card" style="flex-direction:column; align-items:flex-start;">
            <h4 style="margin:0 0 12px;">Top Hazard Types</h4>
            <div style="width:100%; display:flex; flex-direction:column; gap:8px;">
              ${by_type.slice(0, 5).map((t) => `
                <div style="display:flex; justify-content:space-between; align-items:center; font-size:0.92rem;">
                  <span>${TYPE_LABELS[t.hazard_type] || t.hazard_type}</span>
                  <strong>${t.cnt}</strong>
                </div>
              `).join('')}
            </div>
          </div>

          <!-- By City -->
          <div class="review-card" style="flex-direction:column; align-items:flex-start;">
            <h4 style="margin:0 0 12px;">Top Reported Locations</h4>
            <div style="width:100%; display:flex; flex-direction:column; gap:8px;">
              ${by_city.slice(0, 5).map((c) => `
                <div style="display:flex; justify-content:space-between; align-items:center; font-size:0.92rem;">
                  <span>${escapeHtml(c.city_name)}</span>
                  <strong>${c.cnt}</strong>
                </div>
              `).join('')}
            </div>
          </div>
        </div>

        <!-- Top Reporters & Top Searchers Tables -->
        <div style="display:grid; grid-template-columns:repeat(auto-fit, minmax(320px, 1fr)); gap:var(--space-6); margin-top:var(--space-6);">
          <div>
            <div class="hazards-main__head" style="margin-bottom:var(--space-3);">
              <h3>Top Hazard Reporters</h3>
            </div>
            <div class="data-table-wrap table-scroll">
              <table class="data-table">
                <thead>
                  <tr>
                    <th>Reporter</th>
                    <th>Email</th>
                    <th style="text-align:right;">Total Reports</th>
                    <th style="text-align:right;">Verified</th>
                  </tr>
                </thead>
                <tbody>
                  ${top_reporters.length === 0 ? '<tr><td colspan="4" class="empty-state">No hazard reports recorded yet.</td></tr>' : top_reporters.map((r) => `
                    <tr>
                      <td><strong>${escapeHtml(r.name || 'User #' + r.id)}</strong></td>
                      <td>${escapeHtml(r.email || '—')}</td>
                      <td style="text-align:right;"><strong>${r.report_count}</strong></td>
                      <td style="text-align:right;"><span style="color:var(--tone-verified-text); font-weight:600;">${r.verified_count}</span></td>
                    </tr>
                  `).join('')}
                </tbody>
              </table>
            </div>
          </div>

          <div>
            <div class="hazards-main__head" style="margin-bottom:var(--space-3);">
              <h3>Top Route Searchers</h3>
            </div>
            <div class="data-table-wrap table-scroll">
              <table class="data-table">
                <thead>
                  <tr>
                    <th>Driver</th>
                    <th>Email</th>
                    <th style="text-align:right;">Searches</th>
                    <th style="text-align:right;">Distance</th>
                    <th style="text-align:right;">Hazards Found</th>
                  </tr>
                </thead>
                <tbody>
                  ${top_searchers.length === 0 ? '<tr><td colspan="5" class="empty-state">No route searches recorded yet.</td></tr>' : top_searchers.map((s) => `
                    <tr>
                      <td><strong>${escapeHtml(s.name || 'User #' + s.id)}</strong></td>
                      <td>${escapeHtml(s.email || '—')}</td>
                      <td style="text-align:right;"><strong>${s.search_count}</strong></td>
                      <td style="text-align:right;">${s.total_distance_km} km</td>
                      <td style="text-align:right;"><span style="color:${s.total_hazards_intercepted > 0 ? 'var(--danger)' : 'var(--slate)'}; font-weight:600;">${s.total_hazards_intercepted}</span></td>
                    </tr>
                  `).join('')}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      `;
    } catch (err) {
      reportsBody.innerHTML = `<p class="banner banner--error is-visible"><span>${escapeHtml(err.message || 'Could not load reports.')}</span></p>`;
    }
  }

  // =========================================================================
  // 4. AUDIT LOG TAB
  // =========================================================================
  const auditTbody = document.getElementById('audit-tbody');
  const auditEmpty = document.getElementById('audit-empty');
  const auditForm = document.getElementById('audit-filter-form');
  const auditActionInput = document.getElementById('audit-action');
  const auditUserIdInput = document.getElementById('audit-user-id');
  const auditClearBtn = document.getElementById('audit-clear-btn');
  const auditPrevBtn = document.getElementById('audit-prev-btn');
  const auditNextBtn = document.getElementById('audit-next-btn');
  const auditPageLabel = document.getElementById('audit-page-label');

  let auditOffset = 0;
  const AUDIT_LIMIT = 20;

  async function loadAuditLogs() {
    auditTbody.innerHTML = '<tr><td colspan="5" class="session-loading">Loading audit records…</td></tr>';
    auditEmpty.hidden = true;

    const params = new URLSearchParams({
      limit: String(AUDIT_LIMIT),
      offset: String(auditOffset),
    });

    const actionVal = auditActionInput.value.trim();
    const userIdVal = auditUserIdInput.value.trim();
    if (actionVal) params.set('action', actionVal);
    if (userIdVal) params.set('user_id', userIdVal);

    try {
      const res = await SafeRouteAPI.request(`/admin/audit-logs?${params.toString()}`, { auth: true });
      const { logs, total } = res.data;

      if (!logs.length) {
        auditTbody.innerHTML = '';
        auditEmpty.hidden = false;
        auditPrevBtn.disabled = auditOffset === 0;
        auditNextBtn.disabled = true;
        auditPageLabel.textContent = '';
        return;
      }

      auditTbody.innerHTML = logs.map(renderAuditRow).join('');

      // Pagination Controls
      auditPrevBtn.disabled = auditOffset === 0;
      auditNextBtn.disabled = auditOffset + AUDIT_LIMIT >= total;
      const start = auditOffset + 1;
      const end = Math.min(auditOffset + AUDIT_LIMIT, total);
      auditPageLabel.textContent = `Showing ${start}–${end} of ${total}`;
    } catch (err) {
      auditTbody.innerHTML = `<tr><td colspan="5"><p class="banner banner--error is-visible"><span>${escapeHtml(err.message || 'Could not load audit log.')}</span></p></td></tr>`;
    }
  }

  function renderAuditRow(log) {
    const userName = log.user_name || log.user_email || (log.user_id ? `User #${log.user_id}` : 'System');
    return `
      <tr>
        <td><span class="field__hint" style="margin:0;">${formatDateTime(log.created_at)}</span></td>
        <td><code>${escapeHtml(log.action)}</code></td>
        <td>${escapeHtml(log.resource_type || '')} ${log.resource_id ? `#${log.resource_id}` : ''}</td>
        <td>${escapeHtml(userName)}</td>
        <td>${escapeHtml(log.description || '—')}</td>
      </tr>
    `;
  }

  auditForm.addEventListener('submit', (e) => {
    e.preventDefault();
    auditOffset = 0;
    loadAuditLogs();
  });

  auditClearBtn.addEventListener('click', () => {
    auditActionInput.value = '';
    auditUserIdInput.value = '';
    auditOffset = 0;
    loadAuditLogs();
  });

  auditPrevBtn.addEventListener('click', () => {
    if (auditOffset > 0) {
      auditOffset = Math.max(0, auditOffset - AUDIT_LIMIT);
      loadAuditLogs();
    }
  });

  auditNextBtn.addEventListener('click', () => {
    auditOffset += AUDIT_LIMIT;
    loadAuditLogs();
  });

  // Init
  initNav();
  loadPendingReview();
})();
