// SafeRoute -- shared API helper.
//
// Every SafeRoute backend response follows the same envelope:
//   success:  { success: true,  message: "...", data: {...} }
//   failure:  { success: false, message: "...", error: "CODE" }
// This wrapper always returns that parsed body (or throws with it
// attached), so every page can handle both shapes the same way.

const SafeRouteAPI = (() => {
  const TOKEN_KEY = 'saferoute_token';
  const USER_KEY = 'saferoute_user';

  function getToken() {
    return localStorage.getItem(TOKEN_KEY);
  }

  function getUser() {
    const raw = localStorage.getItem(USER_KEY);
    return raw ? JSON.parse(raw) : null;
  }

  function setSession(token, user) {
    localStorage.setItem(TOKEN_KEY, token);
    localStorage.setItem(USER_KEY, JSON.stringify(user));
  }

  function clearSession() {
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(USER_KEY);
  }

  function isLoggedIn() {
    return Boolean(getToken());
  }

  /**
   * Calls the SafeRoute API and always resolves to the parsed JSON body.
   * On a non-2xx response, throws an Error whose `.body` holds that
   * same parsed envelope, so callers can read `.body.error` /
   * `.body.message` for the exact reason instead of a generic failure.
   */
  async function request(path, { method = 'GET', body, auth = false } = {}) {
    const headers = { 'Content-Type': 'application/json' };

    if (auth) {
      const token = getToken();
      if (!token) {
        throw new Error('Not authenticated -- no token in this session.');
      }
      headers['Authorization'] = `Bearer ${token}`;
    }

    let response;
    try {
      response = await fetch(`${API_BASE_URL}${path}`, {
        method,
        headers,
        body: body ? JSON.stringify(body) : undefined,
      });
    } catch (networkErr) {
      // The server is down, wrong port, or CORS is blocking the request.
      const err = new Error(
        'Could not reach the SafeRoute server. Is it running on ' + API_BASE_URL + '?'
      );
      err.network = true;
      throw err;
    }

    let parsed;
    try {
      parsed = await response.json();
    } catch {
      parsed = { success: false, message: 'The server sent back something that was not valid JSON.' };
    }

    if (!response.ok || parsed.success === false) {
      const err = new Error(parsed.message || 'Request failed.');
      err.body = parsed;
      err.status = response.status;
      throw err;
    }

    return parsed;
  }

  const geocodeCache = new Map();

  /**
   * Reverse geocodes lat/lng into village, street, district, and city names using OpenStreetMap Nominatim.
   */
  async function reverseGeocode(latitude, longitude) {
    if (latitude == null || longitude == null || isNaN(latitude) || isNaN(longitude)) {
      return null;
    }
    const latNum = Number(latitude);
    const lngNum = Number(longitude);
    const key = `${latNum.toFixed(4)},${lngNum.toFixed(4)}`;
    if (geocodeCache.has(key)) {
      return geocodeCache.get(key);
    }

    // 1. Try backend proxy
    try {
      const res = await request(`/routes/reverse-geocode?latitude=${latNum}&longitude=${lngNum}`, { auth: true });
      if (res && res.data && res.data.displayName) {
        geocodeCache.set(key, res.data);
        return res.data;
      }
    } catch {}

    // 2. Direct fallback to OpenStreetMap Nominatim
    try {
      const url = `https://nominatim.openstreetmap.org/reverse?format=json&lat=${latNum}&lon=${lngNum}&zoom=18&addressdetails=1`;
      const resp = await fetch(url, { headers: { 'Accept-Language': 'en' } });
      if (resp.ok) {
        const data = await resp.json();
        const address = data.address || {};
        const road = address.road || address.pedestrian || address.suburb || address.neighbourhood || address.highway || '';
        const village = address.village || address.suburb || address.neighbourhood || address.town || address.city_district || '';
        const district = address.state_district || address.county || address.district || '';
        const city = address.city || address.town || address.municipality || '';
        const state = address.state || '';

        const parts = [];
        [road, village, city, district, state].forEach((p) => {
          if (p && !parts.includes(p)) parts.push(p);
        });

        const formatted = parts.length ? parts.join(', ') : (data.display_name || `${latNum.toFixed(4)}, ${lngNum.toFixed(4)}`);
        const resultObj = {
          displayName: formatted,
          road, village, district, city, state,
          latitude: latNum, longitude: lngNum
        };
        geocodeCache.set(key, resultObj);
        return resultObj;
      }
    } catch {}

    const fallbackObj = {
      displayName: `Location (${latNum.toFixed(4)}, ${lngNum.toFixed(4)})`,
      latitude: latNum, longitude: lngNum
    };
    geocodeCache.set(key, fallbackObj);
    return fallbackObj;
  }

  return { request, getToken, getUser, setSession, clearSession, isLoggedIn, reverseGeocode };
})();

