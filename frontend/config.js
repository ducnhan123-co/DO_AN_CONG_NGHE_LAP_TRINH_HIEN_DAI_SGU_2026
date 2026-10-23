// Render Static Site can connect to the Mac-hosted Kiệt CLI gateway through HTTPS.
// Browser JS cannot execute a local CLI: only the Mac backend can spawn kiet_cli.py.
// Credentials remain in sessionStorage, never the URL, Git repository or localStorage.
(function () {
  'use strict';
  const DEFAULT_API = 'https://do-an-cong-nghe-lap-trinh-hien-dai-sgu.onrender.com';
  const API_KEY = 'matchpdf_tunnel_api';
  const AUTH_KEY = 'matchpdf_tunnel_basic';
  const validate = value => {
    try {
      const url = new URL(value);
      if (url.username || url.password || url.search || url.hash) return null;
      const isDev = url.protocol === 'http:' && ['127.0.0.1', 'localhost'].includes(url.hostname);
      if (url.protocol !== 'https:' && !isDev) return null;
      return url.origin;
    } catch (e) { return null; }
  };
  let chosen = null;
  try {
    const params = new URLSearchParams(window.location.search);
    const supplied = params.get('api');
    if (supplied) {
      chosen = validate(supplied);
      if (chosen) sessionStorage.setItem(API_KEY, chosen);
    }
    chosen = chosen || validate(sessionStorage.getItem(API_KEY) || '');
  } catch (e) {}
  const remote = !window.MATCHPDF_FORCE_ORIGIN && chosen;
  const base = window.MATCHPDF_FORCE_ORIGIN ? location.origin : remote || DEFAULT_API;
  window.MATCHPDF_API_BASE = base;
  window.MATCHPDF_LIB_BASE = base;
  window.MATCHPDF_API_AUTH = {};

  function askCredentials() {
    const username = prompt('Username của Mac Tunnel (ví dụ: demo):', 'demo');
    if (username === null) return false;
    const password = prompt('Password Mac Tunnel (không nhập mật khẩu vào URL):');
    if (!password) return false;
    try {
      const token = btoa(username + ':' + password);
      sessionStorage.setItem(AUTH_KEY, token);
      window.MATCHPDF_API_AUTH = {Authorization: 'Basic ' + token};
      return true;
    } catch (e) { return false; }
  }
  function credential() {
    try { return sessionStorage.getItem(AUTH_KEY); } catch (e) { return null; }
  }
  if (remote) {
    let token = credential();
    if (!token && askCredentials()) token = credential();
    if (token) window.MATCHPDF_API_AUTH = {Authorization: 'Basic ' + token};
    const nativeFetch = window.fetch.bind(window);
    window.fetch = function (input, init) {
      const candidate = typeof input === 'string' || input instanceof URL ? String(input) : input && input.url;
      try {
        const dest = new URL(candidate, location.href);
        if (dest.origin === new URL(base).origin && dest.pathname.startsWith('/api/')) {
          const options = Object.assign({}, init || {});
          const headers = new Headers(options.headers || (input instanceof Request ? input.headers : undefined));
          if (credential()) headers.set('Authorization', 'Basic ' + credential());
          options.headers = headers;
          return nativeFetch(input, options);
        }
      } catch (e) {}
      return nativeFetch(input, init);
    };
  }
  window.matchpdfConnectMac = function () {
    if (window.MATCHPDF_FORCE_ORIGIN) {
      alert('Bạn đang sử dụng giao diện cùng origin với Mac Server.');
      return;
    }
    const raw = prompt('Nhập URL HTTPS của Cloudflare Tunnel đang chạy trên Mac:', chosen || '');
    if (raw === null) return;
    const url = validate(raw);
    if (!url) {
      alert('URL phải là https://... hoặc http://localhost khi phát triển.');
      return;
    }
    try {
      sessionStorage.setItem(API_KEY, url);
      sessionStorage.removeItem(AUTH_KEY);
    } catch (e) {}
    if (!askCredentials()) return;
    window.location.reload();
  };
  window.matchpdfRemoteMode = !!remote;
})();
