// SafeRoute -- High-Accuracy Route Search & Hazard Collision Visualizer

(function () {
  'use strict';

  if (!SafeRouteAPI.isLoggedIn()) {
    window.location.href = 'login.html';
    return;
  }

  const SEVERITY_LABELS = { low: 'Low', medium: 'Medium', high: 'High', critical: 'Critical' };

  function escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = str == null ? '' : String(str);
    return div.innerHTML;
  }

  // ---- nav / session ----------------------------------------------------

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

  // ---- Leaflet Map Setup ------------------------------------------------

  if (typeof L === 'undefined') {
    console.error('Leaflet map library is not loaded.');
    const mapEl = document.getElementById('route-map');
    if (mapEl) {
      mapEl.innerHTML = '<div style="padding:40px; text-align:center; color:#C6432B; font-weight:600;">Leaflet map library could not be loaded. Please check your network connection and refresh.</div>';
    }
    return;
  }

  // Default coordinate center (Vijayawada / AP corridor)
  const map = L.map('route-map', {
    zoomControl: true,
    scrollWheelZoom: true,
  }).setView([16.5062, 80.6480], 10);

  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    maxZoom: 19,
  }).addTo(map);

  // Guarantee Leaflet recalculates dimensions immediately
  setTimeout(() => { map.invalidateSize(); }, 200);
  window.addEventListener('resize', () => { map.invalidateSize(); });

  let routeLine = null;
  let routeOutline = null;
  let hazardLayer = L.layerGroup().addTo(map);
  let endpointLayer = L.layerGroup().addTo(map);
  const hazardMarkersMap = new Map();


  // Custom high-visibility SVG pin icons
  function createPinIcon(label, color) {
    const svg = `
      <svg width="32" height="42" viewBox="0 0 32 42" fill="none" xmlns="http://www.w3.org/2000/svg">
        <path d="M16 0C7.163 0 0 7.163 0 16c0 11.2 14.2 24.8 15.1 25.6.5.5 1.3.5 1.8 0C17.8 40.8 32 27.2 32 16 32 7.163 24.837 0 16 0z" fill="${color}"/>
        <circle cx="16" cy="15" r="9" fill="#ffffff"/>
        <text x="16" y="19" font-family="sans-serif" font-weight="bold" font-size="12" fill="${color}" text-anchor="middle">${label}</text>
      </svg>
    `;
    return L.divIcon({
      html: svg,
      className: 'custom-map-pin',
      iconSize: [32, 42],
      iconAnchor: [16, 42],
      popupAnchor: [0, -38],
    });
  }

  function createHazardIcon(severity, title) {
    const colorMap = {
      critical: '#C6432B',
      high: '#E06D14',
      medium: '#E8A33D',
      low: '#5C7080',
    };
    const col = colorMap[severity] || '#E06D14';
    const shortTitle = title ? (title.length > 20 ? title.substring(0, 18) + '…' : title) : 'Hazard';
    const html = `
      <div class="hazard-pin-container">
        <div class="hazard-pin-bubble" style="background:${col};">
          <span style="font-size:14px; line-height:1;">⚠️</span>
          <span class="hazard-pin-label">${escapeHtml(shortTitle)}</span>
        </div>
        <div class="hazard-pin-pointer" style="border-top-color:${col};"></div>
      </div>
    `;
    return L.divIcon({
      html: html,
      className: 'custom-hazard-map-pin',
      iconSize: [160, 42],
      iconAnchor: [80, 42],
      popupAnchor: [0, -42],
    });
  }

  // ---- Geocoding with Offline Knowledge & Fallbacks --------------------

  const KNOWN_LOCATIONS = {
    'vijayawada': { latitude: 16.5062, longitude: 80.6480, displayName: 'Vijayawada, Andhra Pradesh, India' },
    'vijayawada railway station': { latitude: 16.5186, longitude: 80.6198, displayName: 'Vijayawada Junction Railway Station, AP' },
    'guntur': { latitude: 16.3067, longitude: 80.4365, displayName: 'Guntur, Andhra Pradesh, India' },
    'guntur bus stand': { latitude: 16.3015, longitude: 80.4430, displayName: 'NTR Bus Station, Guntur, AP' },
    'benz circle': { latitude: 16.5020, longitude: 80.6510, displayName: 'Benz Circle, Vijayawada, AP' },
    'benz circle, vijayawada': { latitude: 16.5020, longitude: 80.6510, displayName: 'Benz Circle, Vijayawada, AP' },
    'auto nagar': { latitude: 16.4950, longitude: 80.6720, displayName: 'Auto Nagar Industrial Area, Vijayawada' },
    'auto nagar, vijayawada': { latitude: 16.4950, longitude: 80.6720, displayName: 'Auto Nagar Industrial Area, Vijayawada' },
    'hyderabad': { latitude: 17.3850, longitude: 78.4867, displayName: 'Hyderabad, Telangana, India' },
    'visakhapatnam': { latitude: 17.6868, longitude: 83.2185, displayName: 'Visakhapatnam, Andhra Pradesh, India' },
    'amaravati': { latitude: 16.5730, longitude: 80.3575, displayName: 'Amaravati Capital City, AP' },
    'mangalagiri': { latitude: 16.4300, longitude: 80.5700, displayName: 'Mangalagiri, Guntur District, AP' },
    'tadepalli': { latitude: 16.4800, longitude: 80.6000, displayName: 'Tadepalli, Guntur District, AP' },
    'gannavaram': { latitude: 16.5390, longitude: 80.8030, displayName: 'Gannavaram Airport Road, AP' },
    'gannavaram airport': { latitude: 16.5390, longitude: 80.8030, displayName: 'Gannavaram Airport Road, AP' },
    'kanaka durga temple': { latitude: 16.5152, longitude: 80.6050, displayName: 'Sri Durga Malleswara Swamy Temple, Indrakeeladri, Vijayawada' },
    'tenali': { latitude: 16.2430, longitude: 80.6400, displayName: 'Tenali, Guntur District, AP' },
    'eluru': { latitude: 16.7107, longitude: 81.0952, displayName: 'Eluru, Andhra Pradesh, India' },
    'chennai': { latitude: 13.0827, longitude: 80.2707, displayName: 'Chennai, Tamil Nadu, India' },
    'bengaluru': { latitude: 12.9716, longitude: 77.5946, displayName: 'Bengaluru, Karnataka, India' },
    'delhi': { latitude: 28.6139, longitude: 77.2090, displayName: 'New Delhi, Delhi, India' },
    'mumbai': { latitude: 19.0760, longitude: 72.8777, displayName: 'Mumbai, Maharashtra, India' },
    'kolkata': { latitude: 22.5726, longitude: 88.3639, displayName: 'Kolkata, West Bengal, India' },
  };

  async function geocodeAddress(text) {
    const raw = text.trim();

    // 1. Check if input is direct coordinates: e.g. "16.5186, 80.6198" or "16.5186 80.6198"
    const coordMatch = raw.match(/^(-?\d+(\.\d+)?)\s*[, ]\s*(-?\d+(\.\d+)?)$/);
    if (coordMatch) {
      return {
        latitude: parseFloat(coordMatch[1]),
        longitude: parseFloat(coordMatch[3]),
        displayName: `${coordMatch[1]}, ${coordMatch[3]}`,
      };
    }

    // 2. Check local preset dictionary for immediate match
    const key = raw.toLowerCase().replace(/[,\.]/g, ' ').replace(/\s+/g, ' ').trim();
    if (KNOWN_LOCATIONS[key]) {
      return KNOWN_LOCATIONS[key];
    }
    for (const [k, loc] of Object.entries(KNOWN_LOCATIONS)) {
      if (key.includes(k) || k.includes(key)) return loc;
    }

    // 3. Query SafeRoute backend geocoding proxy (never blocked by CORS)
    try {
      const backendRes = await SafeRouteAPI.request(`/routes/geocode?q=${encodeURIComponent(raw)}`, { auth: true });
      if (backendRes && backendRes.data && typeof backendRes.data.latitude === 'number') {
        return {
          latitude: backendRes.data.latitude,
          longitude: backendRes.data.longitude,
          displayName: backendRes.data.displayName || raw,
        };
      }
    } catch {}

    // 4. Query OpenStreetMap Nominatim directly
    const url = `https://nominatim.openstreetmap.org/search?format=json&limit=1&addressdetails=1&q=${encodeURIComponent(raw)}`;
    try {
      const resp = await fetch(url, {
        headers: { 'Accept-Language': 'en' },
      });
      if (resp.ok) {
        const results = await resp.json();
        if (results && results.length > 0) {
          return {
            latitude: parseFloat(results[0].lat),
            longitude: parseFloat(results[0].lon),
            displayName: results[0].display_name,
          };
        }
      }
    } catch {}

    throw new Error(`Could not find coordinates for "${text}". Try specifying city (e.g. "Vijayawada").`);
  }

  // ---- Form Submission & Quick Presets ---------------------------------

  function setBanner(text) {
    const banner = document.getElementById('route-banner');
    const bannerText = document.getElementById('route-banner-text');
    if (text) {
      bannerText.textContent = text;
      banner.classList.add('is-visible');
    } else {
      banner.classList.remove('is-visible');
    }
  }

  function setLoading(loading, label) {
    const button = document.getElementById('route-submit-btn');
    button.classList.toggle('is-loading', loading);
    button.disabled = loading;
    const labelEl = button.querySelector('.btn__label');
    if (labelEl) labelEl.textContent = label || 'Search route';
  }

  let originResult = null;
  let destResult = null;

  // Preset route quick buttons
  document.querySelectorAll('.preset-route-btn').forEach((btn) => {
    btn.addEventListener('click', () => {
      document.getElementById('origin-address').value = btn.getAttribute('data-from');
      document.getElementById('dest-address').value = btn.getAttribute('data-to');
      document.getElementById('route-form').dispatchEvent(new Event('submit'));
    });
  });

  // "Use My Location" GPS button
  const myLocationBtn = document.getElementById('use-my-location-btn');
  if (myLocationBtn) {
    myLocationBtn.addEventListener('click', () => {
      if (!navigator.geolocation) {
        setBanner('Geolocation is not supported by your browser.');
        return;
      }
      myLocationBtn.disabled = true;
      myLocationBtn.textContent = 'Locating…';
      navigator.geolocation.getCurrentPosition(
        (pos) => {
          myLocationBtn.disabled = false;
          myLocationBtn.textContent = '📍 My location';
          const lat = pos.coords.latitude;
          const lng = pos.coords.longitude;
          document.getElementById('origin-address').value = `${lat.toFixed(5)}, ${lng.toFixed(5)}`;
          map.setView([lat, lng], 13);
        },
        () => {
          myLocationBtn.disabled = false;
          myLocationBtn.textContent = '📍 My location';
          setBanner('Could not retrieve your current location. Please type an address.');
        },
        { timeout: 8000 }
      );
    });
  }

  // Map Click Interactive Selection
  map.on('click', async (e) => {
    const lat = e.latlng.lat;
    const lng = e.latlng.lng;
    let placeLabel = `${lat.toFixed(4)}, ${lng.toFixed(4)}`;

    try {
      const geo = await SafeRouteAPI.reverseGeocode(lat, lng);
      if (geo && geo.displayName) placeLabel = geo.displayName;
    } catch {}

    const popupContent = document.createElement('div');
    popupContent.style.fontFamily = 'var(--font-body)';
    popupContent.style.fontSize = '13px';
    popupContent.style.textAlign = 'center';
    popupContent.style.minWidth = '200px';
    popupContent.innerHTML = `
      <strong style="color:var(--ink);">Selected Location</strong><br>
      <span style="font-size:11.5px; color:#5C7080;">📍 ${escapeHtml(placeLabel)}</span>
      <div style="display:flex; flex-direction:column; gap:6px; margin-top:8px;">
        <button type="button" class="btn btn-primary btn--compact" id="click-set-from" style="font-size:12px; padding:6px 10px;">📍 Set as Starting Point (A)</button>
        <button type="button" class="btn btn--compact" id="click-set-to" style="font-size:12px; padding:6px 10px; background:#E8ECEF; color:#12213A; border:1px solid #D5DBE1;">🏁 Set as Destination (B)</button>
      </div>
    `;

    const popup = L.popup()
      .setLatLng(e.latlng)
      .setContent(popupContent)
      .openOn(map);

    setTimeout(() => {
      const setFromBtn = document.getElementById('click-set-from');
      const setToBtn = document.getElementById('click-set-to');
      if (setFromBtn) {
        setFromBtn.onclick = () => {
          document.getElementById('origin-address').value = placeLabel;
          map.closePopup();
        };
      }
      if (setToBtn) {
        setToBtn.onclick = () => {
          document.getElementById('dest-address').value = placeLabel;
          map.closePopup();
        };
      }
    }, 50);
  });

  document.getElementById('route-form').addEventListener('submit', async (event) => {
    event.preventDefault();
    setBanner(null);

    const originText = document.getElementById('origin-address').value.trim();
    const destText = document.getElementById('dest-address').value.trim();

    if (!originText || !destText) {
      setBanner('Please enter both a starting point and a destination.');
      return;
    }

    setLoading(true, 'Finding locations…');
    try {
      originResult = await geocodeAddress(originText);
      destResult = await geocodeAddress(destText);
    } catch (err) {
      setLoading(false);
      setBanner(err.message || 'Could not locate that address.');
      return;
    }

    setLoading(true, 'Calculating road route…');
    try {
      const result = await SafeRouteAPI.request('/routes/search', {
        method: 'POST',
        auth: true,
        body: {
          origin: { latitude: originResult.latitude, longitude: originResult.longitude },
          destination: { latitude: destResult.latitude, longitude: destResult.longitude },
          radius_km: 1.5,
        },
      });
      renderRoute(result.data);
    } catch (err) {
      setBanner(err.message || 'Could not compute route. Please try again.');
    } finally {
      setLoading(false);
    }
  });

  // ---- Map Rendering ---------------------------------------------------

  function extractHazardMatch(data) {
    if (data.hazard_matching && Array.isArray(data.hazard_matching.hazards)) {
      return {
        hazards: data.hazard_matching.hazards,
        count: data.hazard_matching.count != null ? data.hazard_matching.count : data.hazard_matching.hazards.length,
      };
    }
    if (Array.isArray(data.hazards)) {
      return { hazards: data.hazards, count: data.hazard_count != null ? data.hazard_count : data.hazards.length };
    }
    return { hazards: [], count: 0 };
  }

  function renderRoute(data) {
    document.getElementById('route-empty').hidden = true;
    document.getElementById('route-output').hidden = false;

    // Clear previous layers & markers registry
    if (routeLine) map.removeLayer(routeLine);
    if (routeOutline) map.removeLayer(routeOutline);
    endpointLayer.clearLayers();
    hazardLayer.clearLayers();
    hazardMarkersMap.clear();

    // 1. Draw route polyline with road outline effect
    if (Array.isArray(data.geometry) && data.geometry.length > 1) {
      routeOutline = L.polyline(data.geometry, {
        color: '#154734',
        weight: 8,
        opacity: 0.6,
        lineCap: 'round',
        lineJoin: 'round',
      }).addTo(map);

      routeLine = L.polyline(data.geometry, {
        color: '#28A745',
        weight: 5,
        opacity: 0.95,
        lineCap: 'round',
        lineJoin: 'round',
      }).addTo(map);

      map.fitBounds(routeLine.getBounds(), { padding: [40, 40], maxZoom: 16 });
    } else {
      map.setView([data.origin.latitude, data.origin.longitude], 12);
    }

    // 2. Add Start & Destination Pins
    const originLabel = originResult ? originResult.displayName : 'Starting Point';
    const destLabel = destResult ? destResult.displayName : 'Destination';

    L.marker([data.origin.latitude, data.origin.longitude], {
      icon: createPinIcon('A', '#2F7D5C'),
    })
      .bindPopup(`<strong>From (A):</strong><br>${escapeHtml(originLabel)}`)
      .addTo(endpointLayer);

    L.marker([data.destination.latitude, data.destination.longitude], {
      icon: createPinIcon('B', '#2B3B5C'),
    })
      .bindPopup(`<strong>To (B):</strong><br>${escapeHtml(destLabel)}`)
      .addTo(endpointLayer);

    // 3. Render hazards detected along corridor
    const matchResult = extractHazardMatch(data);
    const hazards = matchResult.hazards;
    const count = matchResult.count;

    hazards.forEach((h) => {
      const lat = parseFloat(h.latitude);
      const lng = parseFloat(h.longitude);
      if (isNaN(lat) || isNaN(lng)) return;

      const hazardTitle = h.title || h.hazard_type || 'Hazard';

      const marker = L.marker([lat, lng], {
        icon: createHazardIcon(h.severity, hazardTitle),
        zIndexOffset: 2000,
      }).addTo(hazardLayer);

      const distInfo = h.distance_from_route != null ? `<br><small>${h.distance_from_route.toFixed(2)} km from road</small>` : '';
      const initialLoc = [h.address, h.city].filter(Boolean).join(', ') || `${lat.toFixed(4)}, ${lng.toFixed(4)}`;

      marker.bindPopup(`
        <div style="font-family: var(--font-body); min-width: 190px;">
          <strong style="font-size:13.5px; color:#12213A; display:block; margin-bottom:4px;">${escapeHtml(hazardTitle)}</strong>
          <span id="marker-loc-${h.id}" style="font-size:11.5px; color:#5C7080; display:block; margin-bottom:4px;">📍 ${escapeHtml(initialLoc)}</span>
          <span class="hazard-card__meta-item--${h.severity}" style="font-size:11.5px; font-weight:700;">${SEVERITY_LABELS[h.severity] || h.severity} Severity</span>
          ${distInfo}
        </div>
      `);

      SafeRouteAPI.reverseGeocode(lat, lng).then((geo) => {
        if (!geo || !geo.displayName) return;
        const locEl = document.getElementById(`marker-loc-${h.id}`);
        if (locEl) locEl.textContent = `📍 ${geo.displayName}`;
      }).catch(() => {});

      // Register marker in map lookup
      hazardMarkersMap.set(String(h.id), { marker, data: h, lat, lng });

      // On map pin click: focus map on pin, open popup & highlight card below
      marker.on('click', () => {
        map.setView([lat, lng], 16, { animate: true });
        setTimeout(() => { marker.openPopup(); }, 120);
        const listEl = document.getElementById('route-hazards-list');
        if (!listEl) return;
        listEl.querySelectorAll('.hazard-card').forEach((c) => c.classList.remove('is-selected'));
        const matchingCard = listEl.querySelector(`[data-hazard-card-id="${h.id}"]`);
        if (matchingCard) {
          matchingCard.classList.add('is-selected');
          matchingCard.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
        }
      });
    });

    // 4. Update Status Overlay
    const statusOverlay = document.getElementById('map-status-text');
    if (statusOverlay) {
      statusOverlay.textContent = `Route displayed: ${data.distance_km} km (${Math.round(data.duration_minutes)} min). ${count} hazard(s) along corridor.`;
    }

    // 5. Update Statistics Row
    const statsEl = document.getElementById('route-stats');
    statsEl.innerHTML = `
      <div class="route-stat">
        <div class="route-stat__value">${data.distance_km != null ? data.distance_km : '—'} km</div>
        <div class="route-stat__label">Road Distance</div>
      </div>
      <div class="route-stat">
        <div class="route-stat__value">${data.duration_minutes != null ? Math.round(data.duration_minutes) : '—'} min</div>
        <div class="route-stat__label">Estimated Driving Time</div>
      </div>
      <div class="route-stat">
        <div class="route-stat__value" style="${count > 0 ? 'color:var(--danger);' : ''}">${count}</div>
        <div class="route-stat__label">Hazards on Corridor</div>
      </div>
    `;

    // 6. Provider tag & Safety disclaimer
    document.getElementById('provider-tag').textContent = (data.provider || 'OSRM').toUpperCase();
    document.getElementById('safety-note-text').textContent = data.note
      ? data.note
      : (count > 0
        ? `Caution: ${count} verified hazard${count === 1 ? ' was' : 's were'} detected along or near this route. SafeRoute does not guarantee the route is safe.`
        : 'No active verified hazards were detected along this highway corridor. SafeRoute does not guarantee the route is safe — always exercise caution.');

    // 7. Hazard cards list
    const heading = document.getElementById('route-hazards-heading');
    const listEl = document.getElementById('route-hazards-list');
    heading.textContent = count > 0 ? `Hazards near this route (${count})` : 'Hazards near this route';

    if (hazards.length === 0) {
      listEl.innerHTML = '<p class="field__hint" style="grid-column: 1/-1;">No verified hazards are currently reported along this driving route.</p>';
    } else {
      listEl.innerHTML = hazards.map((h) => {
        const distBit = typeof h.distance_from_route === 'number'
          ? `<span class="hazard-card__meta-item">${h.distance_from_route.toFixed(2)} km from route</span>`
          : '';
        const fallbackLoc = [h.address, h.city].filter(Boolean).join(', ') || (typeof h.latitude === 'number' ? `📍 ${h.latitude.toFixed(4)}, ${h.longitude.toFixed(4)}` : '');
        return `
          <article class="hazard-card hazard-card--clickable" data-hazard-card-id="${escapeHtml(h.id)}">
            <div class="hazard-card__accent hazard-card__accent--${h.severity || 'medium'}"></div>
            <div class="hazard-card__body">
              <div class="hazard-card__top">
                <span class="hazard-type">${escapeHtml((h.hazard_type || '').replace(/_/g, ' '))}</span>
              </div>
              <h4 class="hazard-card__title">${escapeHtml(h.title || 'Hazard')}</h4>
              <div class="hazard-card__meta">
                <span class="hazard-card__meta-item hazard-card__meta-item--${h.severity}">${SEVERITY_LABELS[h.severity] || h.severity}</span>
                ${distBit}
                <span class="hazard-card__meta-item" data-route-loc-id="${h.id}">${escapeHtml(fallbackLoc)}</span>
              </div>
              <div style="margin-top: 10px;">
                <span class="link-btn" style="font-size:12.5px; display:inline-flex; align-items:center; gap:4px;">📍 Focus on map &rarr;</span>
              </div>
            </div>
          </article>
        `;
      }).join('');

      hazards.forEach((h) => {
        const lat = parseFloat(h.latitude);
        const lng = parseFloat(h.longitude);
        if (!isNaN(lat) && !isNaN(lng)) {
          SafeRouteAPI.reverseGeocode(lat, lng).then((geo) => {
            if (!geo || !geo.displayName) return;
            const badgeEl = listEl.querySelector(`[data-route-loc-id="${h.id}"]`);
            if (badgeEl) badgeEl.textContent = `📍 ${geo.displayName}`;
          }).catch(() => {});
        }
      });
    }

    // Attach card click event listener to focus hazard on map
    listEl.onclick = (event) => {
      const card = event.target.closest('[data-hazard-card-id]');
      if (!card) return;
      const hazardId = card.getAttribute('data-hazard-card-id');
      const match = hazardMarkersMap.get(String(hazardId));
      if (match && match.marker) {
        listEl.querySelectorAll('.hazard-card').forEach((c) => c.classList.remove('is-selected'));
        card.classList.add('is-selected');

        map.setView([match.lat, match.lng], 16, { animate: true });

        setTimeout(() => {
          match.marker.openPopup();
        }, 150);

        const mapEl = document.getElementById('route-map');
        if (mapEl) {
          mapEl.scrollIntoView({ behavior: 'smooth', block: 'center' });
        }
      }
    };

    // Re-invalidate size to ensure crisp rendering
    setTimeout(() => { map.invalidateSize(); }, 150);
  }

  loadNavUser();
})();
