// SafeRoute -- Phase F2: hazard dashboard (report, view, search).
//
// Matches the real backend in app/routes/hazards.py + app/schemas/hazard_schemas.py.
//
//   GET  /api/hazards?type=&severity=&city=&status=&limit=&offset=   (auth)
//        -> public search. Non-admins ALWAYS see only verified+visible
//           hazards; `status` is silently ignored for them.
//   GET  /api/hazards/my?limit=&offset=                              (auth)
//        -> the current user's own reports, at any status.
//   GET  /api/hazards/nearby?latitude=&longitude=&radius_km=&type=&severity=  (auth)
//        -> verified+visible hazards near a point, each with distance_km.
//   POST /api/hazards                                                (auth)
//        body: { hazard_type, title, description, address?, city?,
//                latitude, longitude, severity, start_time, expected_end_time? }
//        -> new hazard, always starts status="reported", visibility="hidden".
//   GET  /api/hazards/<id>                                           (auth)
//   PATCH /api/hazards/<id>                                          (auth)
//        Only the reporter, only while status="reported". Body: any of
//        { title, description, hazard_type, severity, address, city, expected_end_time }.
//
// Hazard shape (app/models/hazard_model.py::_row_to_hazard_dict):
//   id, reporter_id, hazard_type, title, description, address, city,
//   latitude, longitude, severity, start_time, expected_end_time,
//   status, visibility, is_potential_duplicate, duplicate_of_hazard_id,
//   verified_by, verified_at, verification_note,
//   resolved_by, resolved_at, resolution_note, created_at, updated_at

(function () {
  if (!SafeRouteAPI.isLoggedIn()) {
    window.location.href = 'login.html';
    return;
  }

  const HAZARD_TYPES = [
    ['road_closure', 'Road closure'],
    ['flooding', 'Flooding'],
    ['waterlogging', 'Waterlogging'],
    ['construction', 'Construction'],
    ['blocked_road', 'Blocked road'],
    ['accident', 'Accident'],
    ['temporary_restriction', 'Temporary restriction'],
    ['other', 'Other'],
  ];
  const TYPE_LABELS = Object.fromEntries(HAZARD_TYPES);

  const SEVERITY_LABELS = { low: 'Low', medium: 'Medium', high: 'High', critical: 'Critical' };

  const STATUS_LABELS = {
    reported: 'Reported',
    under_review: 'Under review',
    verified: 'Verified',
    rejected: 'Rejected',
    resolved: 'Resolved',
    expired: 'Expired',
  };
  const STATUS_TONE = {
    reported: 'pending', under_review: 'pending',
    verified: 'verified', resolved: 'verified',
    rejected: 'rejected', expired: 'rejected',
  };

  const state = {
    view: 'public',       // 'public' | 'mine' | 'nearby'
    types: new Set(),
    severity: '',
    city: '',
    nearbyCoords: null,
  };

  let cityDebounce = null;

  // ---- utilities ----------------------------------------------------

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

  // datetime-local inputs give "2026-09-08T14:30" (no seconds/zone);
  // the backend needs a real ISO string.
  function localInputToIso(value) {
    if (!value) return null;
    const d = new Date(value);
    return isNaN(d.getTime()) ? null : d.toISOString();
  }

  function isoToLocalInput(iso) {
    if (!iso) return '';
    const d = new Date(iso);
    if (isNaN(d.getTime())) return '';
    const pad = (n) => String(n).padStart(2, '0');
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
  }

  // ---- nav / session --------------------------------------------------

  function loadNavUser() {
    const cached = SafeRouteAPI.getUser();
    if (cached) paintNavUser(cached);

    SafeRouteAPI.request('/profile', { auth: true })
      .then((result) => paintNavUser(result.data.user)) // nested under "user"
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

  // Unread notifications dot in the nav -- best-effort, never blocks the page.
  SafeRouteAPI.request('/notifications?unread_only=true&limit=1', { auth: true })
    .then((result) => {
      const dot = document.getElementById('nav-unread-dot');
      if (dot) dot.hidden = (result.data.unread_count || 0) === 0;
    })
    .catch(() => { /* non-critical -- ignore */ });

  document.getElementById('logout-btn').addEventListener('click', async () => {
    try {
      await SafeRouteAPI.request('/auth/logout', { method: 'POST', auth: true });
    } catch {
      // Clear locally regardless -- an expired token shouldn't trap the user.
    }
    SafeRouteAPI.clearSession();
    window.location.href = 'login.html';
  });

  // ---- tabs -----------------------------------------------------------

  document.querySelectorAll('[data-view-tab]').forEach((tab) => {
    tab.addEventListener('click', () => {
      state.view = tab.getAttribute('data-view-tab');
      document.querySelectorAll('[data-view-tab]').forEach((t) => t.classList.toggle('is-active', t === tab));
      document.getElementById('nearby-panel').hidden = state.view !== 'nearby';
      document.getElementById('city-filter-group').hidden = state.view !== 'public';
      fetchHazards();
    });
  });

  document.getElementById('locate-btn').addEventListener('click', () => {
    const status = document.getElementById('nearby-status');
    if (!navigator.geolocation) {
      status.textContent = "This browser can't share your location. Enter coordinates in the report form manually instead.";
      return;
    }
    status.textContent = 'Locating…';
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        state.nearbyCoords = { latitude: pos.coords.latitude, longitude: pos.coords.longitude };
        status.textContent = `Using your location (${pos.coords.latitude.toFixed(3)}, ${pos.coords.longitude.toFixed(3)}).`;
        fetchHazards();
      },
      () => { status.textContent = 'Could not get your location. Check browser location permissions.'; }
    );
  });

  // ---- fetching & rendering the list ------------------------------------

  const listEl = document.getElementById('hazards-list');
  const emptyEl = document.getElementById('empty-state');
  const errorEl = document.getElementById('list-error');
  const countEl = document.getElementById('results-count');

  function fetchHazards() {
    if (state.view === 'nearby' && !state.nearbyCoords) {
      listEl.innerHTML = '';
      countEl.textContent = '';
      emptyEl.hidden = true;
      errorEl.hidden = true;
      return;
    }

    listEl.setAttribute('aria-busy', 'true');
    errorEl.hidden = true;
    emptyEl.hidden = true;

    let path;
    if (state.view === 'mine') {
      path = '/hazards/my';
    } else if (state.view === 'nearby') {
      const params = new URLSearchParams({
        latitude: state.nearbyCoords.latitude,
        longitude: state.nearbyCoords.longitude,
        radius_km: '5',
      });
      if (state.types.size === 1) params.set('type', Array.from(state.types)[0]);
      if (state.severity) params.set('severity', state.severity);
      path = `/hazards/nearby?${params.toString()}`;
    } else {
      const params = new URLSearchParams();
      if (state.types.size === 1) params.set('type', Array.from(state.types)[0]);
      if (state.severity) params.set('severity', state.severity);
      if (state.city) params.set('city', state.city);
      const qs = params.toString();
      path = `/hazards${qs ? `?${qs}` : ''}`;
    }

    SafeRouteAPI.request(path, { auth: true })
      .then((result) => {
        let hazards = result.data.hazards || [];
        // The backend's `type` filter is single-value; if the user picked
        // more than one type chip, narrow client-side to the selection.
        if (state.types.size > 1) {
          hazards = hazards.filter((h) => state.types.has(h.hazard_type));
        }
        renderHazards(hazards);
      })
      .catch((err) => {
        listEl.innerHTML = '';
        countEl.textContent = '';
        errorEl.textContent = err.message || 'Could not load hazards right now.';
        errorEl.hidden = false;
      })
      .finally(() => listEl.removeAttribute('aria-busy'));
  }

  function renderHazards(hazards) {
    countEl.textContent = hazards.length
      ? `${hazards.length} hazard${hazards.length === 1 ? '' : 's'}`
      : '';

    if (!hazards.length) {
      listEl.innerHTML = '';
      emptyEl.hidden = false;
      return;
    }
    listEl.innerHTML = hazards.map(renderHazardCard).join('');

    // Asynchronously resolve exact OpenStreetMap village, district & street names
    hazards.forEach((h) => {
      if (typeof h.latitude === 'number' && typeof h.longitude === 'number') {
        SafeRouteAPI.reverseGeocode(h.latitude, h.longitude).then((geo) => {
          if (!geo || !geo.displayName) return;
          const badgeEl = listEl.querySelector(`[data-loc-id="${h.id}"]`);
          if (badgeEl) {
            badgeEl.textContent = `📍 ${geo.displayName}`;
          }
        }).catch(() => {});
      }
    });
  }

  function renderHazardCard(h) {
    const severity = h.severity || 'medium';
    const status = h.status || 'reported';
    const tone = STATUS_TONE[status] || 'pending';
    const canEdit = state.view === 'mine' && status === 'reported';

    const fallbackLoc = [h.address, h.city].filter(Boolean).join(', ') || (typeof h.latitude === 'number' ? `📍 ${h.latitude.toFixed(4)}, ${h.longitude.toFixed(4)}` : 'Location not given');

    return `
      <article class="hazard-card" data-id="${escapeHtml(h.id)}">
        <div class="hazard-card__accent hazard-card__accent--${severity}"></div>
        <div class="hazard-card__body">
          <div class="hazard-card__top">
            <span class="hazard-type">${TYPE_LABELS[h.hazard_type] || escapeHtml(h.hazard_type)}</span>
            <span class="badge badge--status-${tone}">${STATUS_LABELS[status] || escapeHtml(status)}</span>
          </div>
          <h4 class="hazard-card__title">${escapeHtml(h.title || '')}</h4>
          <p class="hazard-card__desc">${escapeHtml(h.description || '')}</p>
          <div class="hazard-card__meta">
            <span class="hazard-card__meta-item" data-loc-id="${escapeHtml(h.id)}">${escapeHtml(fallbackLoc)}</span>
            <span class="hazard-card__meta-item hazard-card__meta-item--${severity}">${SEVERITY_LABELS[severity] || severity} severity</span>
            ${typeof h.distance_km === 'number' ? `<span class="hazard-card__meta-item">${h.distance_km.toFixed(1)} km away</span>` : ''}
            <span class="hazard-card__meta-item">${formatWhen(h.created_at)}</span>
          </div>
          <div class="hazard-card__actions">
            <button type="button" class="link-btn" data-view-id="${escapeHtml(h.id)}">View details →</button>
            ${canEdit ? `<button type="button" class="link-btn" data-edit-id="${escapeHtml(h.id)}">Edit</button>` : ''}
          </div>
        </div>
      </article>
    `;
  }

  listEl.addEventListener('click', (event) => {
    const viewBtn = event.target.closest('[data-view-id]');
    if (viewBtn) return openDetailModal(viewBtn.getAttribute('data-view-id'));
    const editBtn = event.target.closest('[data-edit-id]');
    if (editBtn) return openEditModal(editBtn.getAttribute('data-edit-id'));
  });

  // ---- filters ------------------------------------------------------

  document.querySelectorAll('[data-filter-type]').forEach((chip) => {
    chip.addEventListener('click', () => {
      const val = chip.getAttribute('data-filter-type');
      if (state.types.has(val)) {
        state.types.delete(val);
        chip.classList.remove('is-active');
      } else {
        state.types.add(val);
        chip.classList.add('is-active');
      }
      fetchHazards();
    });
  });

  function wireSingleSelectGroup(selector, stateKey) {
    document.querySelectorAll(selector).forEach((chip) => {
      chip.addEventListener('click', () => {
        state[stateKey] = chip.getAttribute('data-value');
        document.querySelectorAll(selector).forEach((c) => c.classList.toggle('is-active', c === chip));
        fetchHazards();
      });
    });
  }
  wireSingleSelectGroup('[data-filter-severity]', 'severity');

  document.getElementById('city-input').addEventListener('input', (event) => {
    clearTimeout(cityDebounce);
    const value = event.target.value.trim();
    cityDebounce = setTimeout(() => {
      state.city = value;
      fetchHazards();
    }, 300);
  });

  document.getElementById('clear-filters').addEventListener('click', () => {
    state.types.clear();
    state.severity = '';
    state.city = '';
    document.getElementById('city-input').value = '';
    document.querySelectorAll('.filter-chip').forEach((c) => c.classList.remove('is-active'));
    document.querySelectorAll('[data-filter-severity][data-value=""]').forEach((c) => c.classList.add('is-active'));
    fetchHazards();
  });

  // ---- report / edit modal --------------------------------------------

  const reportModal = document.getElementById('report-modal');
  const reportForm = document.getElementById('report-form');
  let editingId = null;

  (function populateTypeSelect() {
    const select = document.getElementById('report-type');
    select.innerHTML = HAZARD_TYPES.map(([val, label]) => `<option value="${val}">${label}</option>`).join('');
  })();

  function openReportModal() {
    editingId = null;
    reportForm.reset();
    setReportBanner(null);
    document.getElementById('report-modal-title').textContent = 'Report a hazard';
    document.getElementById('report-submit-label').textContent = 'Submit report';
    document.getElementById('report-latlng-group').hidden = false;
    document.getElementById('report-starttime-group').hidden = false;
    document.getElementById('report-start-time').value = isoToLocalInput(new Date().toISOString());
    reportModal.hidden = false;
  }

  function openEditModal(id) {
    editingId = id;
    setReportBanner(null);
    document.getElementById('report-modal-title').textContent = 'Edit your report';
    document.getElementById('report-submit-label').textContent = 'Save changes';
    // Lat/lng and start_time are not editable via PATCH -- hide them.
    document.getElementById('report-latlng-group').hidden = true;
    document.getElementById('report-starttime-group').hidden = true;
    reportModal.hidden = false;

    SafeRouteAPI.request(`/hazards/${encodeURIComponent(id)}`, { auth: true })
      .then((result) => {
        const h = result.data.hazard;
        document.getElementById('report-type').value = h.hazard_type;
        document.getElementById('report-severity').value = h.severity;
        document.getElementById('report-title').value = h.title || '';
        document.getElementById('report-description').value = h.description || '';
        document.getElementById('report-address').value = h.address || '';
        document.getElementById('report-city').value = h.city || '';
        document.getElementById('report-end-time').value = isoToLocalInput(h.expected_end_time);
      })
      .catch((err) => { setReportBanner(err.message || 'Could not load this report.'); });
  }

  function closeReportModal() {
    reportModal.hidden = true;
    editingId = null;
  }

  function setReportBanner(text) {
    const banner = document.getElementById('report-banner');
    const bannerText = document.getElementById('report-banner-text');
    if (text) {
      bannerText.textContent = text;
      banner.classList.add('is-visible');
    } else {
      banner.classList.remove('is-visible');
    }
  }

  document.getElementById('report-btn').addEventListener('click', openReportModal);
  document.getElementById('report-modal-close').addEventListener('click', closeReportModal);
  reportModal.addEventListener('click', (e) => { if (e.target === reportModal) closeReportModal(); });

  document.getElementById('use-my-location-btn').addEventListener('click', () => {
    if (!navigator.geolocation) {
      setReportBanner("This browser can't share your location -- enter coordinates manually.");
      return;
    }
    const btn = document.getElementById('use-my-location-btn');
    btn.disabled = true;
    btn.textContent = 'Locating…';
    navigator.geolocation.getCurrentPosition(
      async (pos) => {
        const lat = pos.coords.latitude;
        const lng = pos.coords.longitude;
        document.getElementById('report-latitude').value = lat.toFixed(6);
        document.getElementById('report-longitude').value = lng.toFixed(6);
        btn.disabled = false;
        btn.textContent = 'Use my location';

        // Auto reverse-geocode address & city
        try {
          const geo = await SafeRouteAPI.reverseGeocode(lat, lng);
          if (geo) {
            const addrInput = document.getElementById('report-address');
            const cityInput = document.getElementById('report-city');
            if (addrInput && (!addrInput.value || addrInput.dataset.autofilled === 'true')) {
              addrInput.value = [geo.road, geo.village].filter(Boolean).join(', ') || geo.displayName || '';
              addrInput.dataset.autofilled = 'true';
            }
            if (cityInput && (!cityInput.value || cityInput.dataset.autofilled === 'true')) {
              cityInput.value = [geo.city, geo.district].filter(Boolean).join(', ') || geo.city || '';
              cityInput.dataset.autofilled = 'true';
            }
          }
        } catch {}
      },
      () => {
        btn.disabled = false;
        btn.textContent = 'Use my location';
        setReportBanner('Could not get your location. Enter coordinates manually.');
      }
    );
  });

  reportForm.addEventListener('submit', async (event) => {
    event.preventDefault();
    setReportBanner(null);

    const hazard_type = document.getElementById('report-type').value;
    const severity = document.getElementById('report-severity').value;
    const title = document.getElementById('report-title').value.trim();
    const description = document.getElementById('report-description').value.trim();
    const address = document.getElementById('report-address').value.trim();
    const city = document.getElementById('report-city').value.trim();

    if (!title || !description) {
      setReportBanner('Title and description are required.');
      return;
    }

    const button = document.getElementById('report-submit-btn');
    button.disabled = true;
    button.classList.add('is-loading');

    try {
      if (editingId) {
        await SafeRouteAPI.request(`/hazards/${encodeURIComponent(editingId)}`, {
          method: 'PATCH',
          auth: true,
          body: {
            hazard_type, severity, title, description,
            address: address || null,
            city: city || null,
            expected_end_time: localInputToIso(document.getElementById('report-end-time').value),
          },
        });
      } else {
        const latitude = parseFloat(document.getElementById('report-latitude').value);
        const longitude = parseFloat(document.getElementById('report-longitude').value);
        const start_time = localInputToIso(document.getElementById('report-start-time').value);

        if (Number.isNaN(latitude) || Number.isNaN(longitude)) {
          setReportBanner('Latitude and longitude are required -- use "Use my location" or enter them manually.');
          button.disabled = false;
          button.classList.remove('is-loading');
          return;
        }
        if (!start_time) {
          setReportBanner('Start time is required.');
          button.disabled = false;
          button.classList.remove('is-loading');
          return;
        }

        await SafeRouteAPI.request('/hazards', {
          method: 'POST',
          auth: true,
          body: {
            hazard_type, severity, title, description,
            address: address || null,
            city: city || null,
            latitude, longitude, start_time,
            expected_end_time: localInputToIso(document.getElementById('report-end-time').value),
          },
        });
      }
      closeReportModal();
      fetchHazards();
    } catch (err) {
      setReportBanner(err.message || 'Could not save this report. Try again.');
    } finally {
      button.disabled = false;
      button.classList.remove('is-loading');
    }
  });

  // ---- detail modal -----------------------------------------------------

  const detailModal = document.getElementById('detail-modal');
  const detailBody = document.getElementById('detail-modal-body');

  function openDetailModal(id) {
    detailBody.innerHTML = '<p class="session-loading">Loading hazard…</p>';
    detailModal.hidden = false;

    SafeRouteAPI.request(`/hazards/${encodeURIComponent(id)}`, { auth: true })
      .then(async (result) => {
        const h = result.data.hazard;
        detailBody.innerHTML = renderHazardDetail(h);
        if (typeof h.latitude === 'number' && typeof h.longitude === 'number') {
          try {
            const geo = await SafeRouteAPI.reverseGeocode(h.latitude, h.longitude);
            const locEl = document.getElementById('detail-loc-text');
            if (locEl && geo && geo.displayName) {
              locEl.textContent = `📍 ${geo.displayName}`;
            }
          } catch {}
        }
      })
      .catch((err) => {
        detailBody.innerHTML = `<p class="banner banner--error is-visible"><span>${escapeHtml(err.message || 'Could not load this hazard.')}</span></p>`;
      });
  }

  function renderHazardDetail(h) {
    const severity = h.severity || 'medium';
    const status = h.status || 'reported';
    const tone = STATUS_TONE[status] || 'pending';
    const initialLoc = [h.address, h.city].filter(Boolean).join(', ') || (typeof h.latitude === 'number' ? `📍 ${h.latitude.toFixed(4)}, ${h.longitude.toFixed(4)}` : '—');
    return `
      <h3>${escapeHtml(h.title || '')}</h3>
      <p class="field__hint" style="margin:-4px 0 16px;">${TYPE_LABELS[h.hazard_type] || escapeHtml(h.hazard_type)}</p>
      <dl class="detail-list">
        <div class="detail-list__row"><dt>Status</dt><dd><span class="badge badge--status-${tone}">${STATUS_LABELS[status] || escapeHtml(status)}</span></dd></div>
        <div class="detail-list__row"><dt>Severity</dt><dd>${SEVERITY_LABELS[severity] || escapeHtml(severity)}</dd></div>
        <div class="detail-list__row"><dt>Location</dt><dd id="detail-loc-text">${escapeHtml(initialLoc)}</dd></div>
        <div class="detail-list__row"><dt>Starts</dt><dd>${formatWhen(h.start_time)}</dd></div>
        ${h.expected_end_time ? `<div class="detail-list__row"><dt>Expected end</dt><dd>${formatWhen(h.expected_end_time)}</dd></div>` : ''}
        <div class="detail-list__row"><dt>Reported</dt><dd>${formatWhen(h.created_at)}</dd></div>
        ${h.verification_note ? `<div class="detail-list__row"><dt>Reviewer note</dt><dd>${escapeHtml(h.verification_note)}</dd></div>` : ''}
        ${h.is_potential_duplicate ? `<div class="detail-list__row"><dt>Note</dt><dd>Flagged as a possible duplicate of hazard #${escapeHtml(h.duplicate_of_hazard_id)}.</dd></div>` : ''}
      </dl>
      <p class="detail-desc">${escapeHtml(h.description || '')}</p>
    `;
  }

  document.getElementById('detail-modal-close').addEventListener('click', () => { detailModal.hidden = true; });
  detailModal.addEventListener('click', (e) => { if (e.target === detailModal) detailModal.hidden = true; });

  // ---- go -------------------------------------------------------------

  loadNavUser();
  fetchHazards();
})();
