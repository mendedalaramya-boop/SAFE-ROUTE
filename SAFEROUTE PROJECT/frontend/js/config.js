// SafeRoute frontend configuration.
//
// Dynamically resolves the backend API origin from the current host/port,
// avoiding port collisions with other local dev servers.
const API_BASE_URL = (typeof window !== 'undefined' && window.location && window.location.origin && window.location.origin.startsWith('http'))
  ? `${window.location.origin}/api`
  : 'http://127.0.0.1:5001/api';

