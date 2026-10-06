// SafeRoute -- login & register form handling.
// Both pages load this same file; each block below only runs if
// its form actually exists on the current page.

// If someone who's already logged in lands on login/register, send
// them straight to the session screen instead of showing the form.
if (SafeRouteAPI.isLoggedIn() &&
    (window.location.pathname.endsWith('login.html') || window.location.pathname.endsWith('register.html'))) {
  window.location.href = 'index.html';
}

// Check if user reached login.html after registration or with prefilled params
function showRegisteredBannerIfPresent() {
  const params = new URLSearchParams(window.location.search);
  const emailParam = params.get('email');
  if (emailParam) {
    const emailInput = document.getElementById('email');
    if (emailInput && !emailInput.value) {
      emailInput.value = emailParam;
    }
  }

  if (params.get('registered') === '1') {
    const banner = document.getElementById('form-banner');
    const bannerText = document.getElementById('form-banner-text');
    if (banner && bannerText) {
      banner.classList.remove('banner--error');
      banner.classList.add('banner--success');
      bannerText.textContent = 'Account created successfully! Please enter your password to log in.';
      banner.classList.add('is-visible');
    }
    const passwordInput = document.getElementById('password');
    if (passwordInput) {
      passwordInput.focus();
    }
  }
}

if (window.location.pathname.endsWith('login.html')) {
  if (document.readyState === 'loading') {
    window.addEventListener('DOMContentLoaded', showRegisteredBannerIfPresent);
  } else {
    showRegisteredBannerIfPresent();
  }
}

function setBanner(text) {
  const banner = document.getElementById('form-banner');
  const bannerText = document.getElementById('form-banner-text');
  if (!banner) return;
  if (text) {
    bannerText.textContent = text;
    banner.classList.add('is-visible');
  } else {
    banner.classList.remove('is-visible');
  }
}

function setFieldInvalid(fieldId, invalid) {
  const field = document.getElementById(fieldId);
  if (!field) return;
  field.classList.toggle('field--invalid', invalid);
}

function setLoading(button, loading) {
  button.classList.toggle('is-loading', loading);
  button.disabled = loading;
}

// ------------------------------------------------------------
// Login form
// ------------------------------------------------------------

const loginForm = document.getElementById('login-form');

if (loginForm) {
  loginForm.addEventListener('submit', async (event) => {
    event.preventDefault();
    setBanner(null);

    const email = document.getElementById('email').value.trim();
    const password = document.getElementById('password').value;

    let hasError = false;
    setFieldInvalid('field-email', !email);
    setFieldInvalid('field-password', !password);
    if (!email || !password) hasError = true;
    if (hasError) return;

    const button = document.getElementById('submit-btn');
    setLoading(button, true);

    try {
      const result = await SafeRouteAPI.request('/auth/login', {
        method: 'POST',
        body: { email, password },
      });
      SafeRouteAPI.setSession(result.data.token, result.data.user);
      window.location.href = 'index.html';
    } catch (err) {
      setBanner(err.message);
    } finally {
      setLoading(button, false);
    }
  });
}

// ------------------------------------------------------------
// Register form
// ------------------------------------------------------------

const registerForm = document.getElementById('register-form');

if (registerForm) {
  registerForm.addEventListener('submit', async (event) => {
    event.preventDefault();
    setBanner(null);

    const name = document.getElementById('name').value.trim();
    const email = document.getElementById('email').value.trim();
    const password = document.getElementById('password').value;

    let hasError = false;
    setFieldInvalid('field-name', !name);
    setFieldInvalid('field-email', !email);
    setFieldInvalid('field-password', password.length < 8);
    if (!name || !email || password.length < 8) hasError = true;
    if (hasError) return;

    const button = document.getElementById('submit-btn');
    setLoading(button, true);

    try {
      const result = await SafeRouteAPI.request('/auth/register', {
        method: 'POST',
        body: { name, email, password },
      });

      if (result && result.data && result.data.token) {
        // Instant seamless auto-login on registration
        SafeRouteAPI.setSession(result.data.token, result.data.user);
        window.location.href = 'index.html';
      } else {
        // Fallback: redirect to login with pre-filled email
        window.location.href = `login.html?registered=1&email=${encodeURIComponent(email)}`;
      }
    } catch (err) {
      // EMAIL_ALREADY_EXISTS is common enough to call out specifically.
      if (err.body && err.body.error === 'EMAIL_ALREADY_EXISTS') {
        setBanner('An account with this email already exists. Try logging in instead.');
      } else {
        setBanner(err.message || 'An error occurred during registration.');
      }
    } finally {
      setLoading(button, false);
    }
  });
}
