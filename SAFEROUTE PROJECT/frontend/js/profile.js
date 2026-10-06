// SafeRoute -- User Profile Management (View & Edit)

(function () {
  'use strict';

  if (!SafeRouteAPI.isLoggedIn()) {
    window.location.href = 'login.html';
    return;
  }

  function escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = str == null ? '' : String(str);
    return div.innerHTML;
  }

  function formatDate(isoStr) {
    if (!isoStr) return '—';
    try {
      const d = new Date(isoStr);
      return d.toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' });
    } catch {
      return isoStr;
    }
  }

  // ---- Notifications / Alerts -------------------------------------------

  const errorBanner = document.getElementById('profile-error');
  const successBanner = document.getElementById('profile-success');

  function showMessage(type, text) {
    if (type === 'error') {
      if (errorBanner) {
        errorBanner.textContent = text;
        errorBanner.classList.add('is-visible');
      }
      if (successBanner) successBanner.classList.remove('is-visible');
    } else {
      if (successBanner) {
        successBanner.textContent = text;
        successBanner.classList.add('is-visible');
      }
      if (errorBanner) errorBanner.classList.remove('is-visible');
    }
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }

  function clearMessages() {
    if (errorBanner) errorBanner.classList.remove('is-visible');
    if (successBanner) successBanner.classList.remove('is-visible');
  }

  function setLoading(btn, loading) {
    if (!btn) return;
    btn.classList.toggle('is-loading', loading);
    btn.disabled = loading;
  }

  // ---- Nav User Setup ---------------------------------------------------

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

  // Unread notifications indicator
  SafeRouteAPI.request('/notifications?unread_only=true&limit=1', { auth: true })
    .then((result) => {
      const dot = document.getElementById('nav-unread-dot');
      if (dot) dot.hidden = (result.data.unread_count || 0) === 0;
    })
    .catch(() => {});

  document.getElementById('logout-btn').addEventListener('click', async () => {
    try {
      await SafeRouteAPI.request('/auth/logout', { method: 'POST', auth: true });
    } catch {}
    SafeRouteAPI.clearSession();
    window.location.href = 'login.html';
  });

  // ---- Profile Loading --------------------------------------------------

  const loadingEl = document.getElementById('profile-loading');
  const contentEl = document.getElementById('profile-content');
  let currentUserData = null;

  async function loadProfile() {
    clearMessages();
    if (loadingEl) loadingEl.hidden = false;
    if (contentEl) contentEl.hidden = true;

    try {
      const res = await SafeRouteAPI.request('/profile', { auth: true });
      currentUserData = res.data.user;
      renderProfile(currentUserData);
      paintNavUser(currentUserData);
    } catch (err) {
      showMessage('error', err.message || 'Could not load profile details.');
    } finally {
      if (loadingEl) loadingEl.hidden = true;
      if (contentEl) contentEl.hidden = false;
    }
  }

  function renderProfile(user) {
    // Overview elements
    const avatarEl = document.getElementById('profile-avatar');
    const overviewNameEl = document.getElementById('overview-name');
    const overviewEmailEl = document.getElementById('overview-email');
    const roleBadgeEl = document.getElementById('overview-role-badge');
    const statusBadgeEl = document.getElementById('overview-status-badge');
    const createdAtEl = document.getElementById('overview-created-at');
    const roleTagEl = document.getElementById('profile-role-tag');

    const initial = (user.name || user.email || 'U').charAt(0).toUpperCase();
    if (avatarEl) avatarEl.textContent = initial;
    if (overviewNameEl) overviewNameEl.textContent = user.name || 'User';
    if (overviewEmailEl) overviewEmailEl.textContent = user.email || '';
    if (roleBadgeEl) {
      roleBadgeEl.className = 'badge ' + (user.role === 'admin' ? 'badge--admin' : 'badge--user');
      roleBadgeEl.textContent = (user.role || 'USER').toUpperCase();
    }
    if (statusBadgeEl) {
      statusBadgeEl.className = 'badge ' + (user.account_status === 'active' ? 'badge--status-verified' : 'badge--status-pending');
      statusBadgeEl.textContent = (user.account_status || 'active').toUpperCase();
    }
    if (createdAtEl) createdAtEl.textContent = 'Member since ' + formatDate(user.created_at);
    if (roleTagEl) roleTagEl.textContent = `${(user.role || 'user').toUpperCase()} ACCOUNT`;

    // Form inputs
    const nameInput = document.getElementById('profile-name');
    const emailInput = document.getElementById('profile-email');
    if (nameInput) nameInput.value = user.name || '';
    if (emailInput) emailInput.value = user.email || '';
  }

  // ---- Form Submission: Details (Name & Email) -------------------------

  const detailsForm = document.getElementById('profile-details-form');
  const detailsBtn = document.getElementById('save-details-btn');

  if (detailsForm) {
    detailsForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      clearMessages();

      const name = document.getElementById('profile-name').value.trim();
      const email = document.getElementById('profile-email').value.trim();

      if (!name) {
        showMessage('error', 'Full name is required.');
        return;
      }
      if (!email || !email.includes('@')) {
        showMessage('error', 'A valid email address is required.');
        return;
      }

      setLoading(detailsBtn, true);
      try {
        const res = await SafeRouteAPI.request('/profile', {
          method: 'PATCH',
          auth: true,
          body: { name, email },
        });

        const updatedUser = res.data.user;
        currentUserData = updatedUser;

        // Keep local session updated
        const token = SafeRouteAPI.getToken();
        SafeRouteAPI.setSession(token, updatedUser);

        renderProfile(updatedUser);
        paintNavUser(updatedUser);
        showMessage('success', res.message || 'Profile details updated successfully.');
      } catch (err) {
        showMessage('error', err.message || 'Failed to update profile details.');
      } finally {
        setLoading(detailsBtn, false);
      }
    });
  }

  // ---- Form Submission: Password Change ---------------------------------

  const passwordForm = document.getElementById('profile-password-form');
  const passwordBtn = document.getElementById('save-password-btn');

  if (passwordForm) {
    passwordForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      clearMessages();

      const currentPassword = document.getElementById('current-password').value;
      const newPassword = document.getElementById('new-password').value;
      const confirmPassword = document.getElementById('confirm-password').value;

      if (!newPassword || newPassword.length < 8) {
        showMessage('error', 'New password must be at least 8 characters long.');
        return;
      }
      if (newPassword !== confirmPassword) {
        showMessage('error', 'New passwords do not match. Please verify.');
        return;
      }

      setLoading(passwordBtn, true);
      try {
        const payload = { new_password: newPassword };
        if (currentPassword) payload.current_password = currentPassword;

        const res = await SafeRouteAPI.request('/profile', {
          method: 'PATCH',
          auth: true,
          body: payload,
        });

        document.getElementById('current-password').value = '';
        document.getElementById('new-password').value = '';
        document.getElementById('confirm-password').value = '';

        showMessage('success', 'Password updated successfully. Your new credentials are now active.');
      } catch (err) {
        showMessage('error', err.message || 'Failed to update password.');
      } finally {
        setLoading(passwordBtn, false);
      }
    });
  }

  loadProfile();
})();
