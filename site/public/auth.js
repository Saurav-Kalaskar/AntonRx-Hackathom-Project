(function () {
  const LOGIN_PATH = "/login";
  const PROTECTED_PATHS = new Set(["/matrix", "/copilot", "/history"]);

  const authState = {
    initialized: false,
    enabled: false,
    configured: false,
    audience: "",
    callbackPath: "/auth/callback",
    logoutReturnPath: "/login",
    client: null,
  };

  async function fetchAuthConfig() {
    const response = await fetch("/auth/config", { credentials: "same-origin" });
    if (!response.ok) {
      throw new Error(`Unable to load auth config: HTTP ${response.status}`);
    }
    return response.json();
  }

  function ensureAuthButtons() {
    const signInBtn = document.getElementById("auth-signin-btn");
    const signUpBtn = document.getElementById("auth-signup-btn");
    const logoutBtn = document.getElementById("auth-logout-btn");

    if (signInBtn) {
      signInBtn.addEventListener("click", () => login(false));
    }
    if (signUpBtn) {
      signUpBtn.addEventListener("click", () => login(true));
    }
    if (logoutBtn) {
      logoutBtn.addEventListener("click", () => logout());
    }
  }

  async function loadAuth0Sdk() {
    if (window.createAuth0Client) {
      return;
    }

    await new Promise((resolve, reject) => {
      const script = document.createElement("script");
      script.src = "https://cdn.auth0.com/js/auth0-spa-js/2.1/auth0-spa-js.production.js";
      script.async = true;
      script.onload = resolve;
      script.onerror = () => reject(new Error("Failed to load Auth0 SDK."));
      document.head.appendChild(script);
    });
  }

  function getPathFromUrl(url) {
    if (!url) return "";
    if (url.startsWith("/")) return url;
    if (url.startsWith(window.location.origin)) {
      return url.slice(window.location.origin.length);
    }
    return "";
  }

  function installApiFetchInterceptor() {
    const originalFetch = window.fetch.bind(window);

    window.fetch = async (input, init = {}) => {
      const requestUrl = typeof input === "string" ? input : input.url;
      const path = getPathFromUrl(requestUrl);
      const protectedApi = path === "/draft" || path.startsWith("/api/");

      if (!authState.enabled || !authState.configured || !protectedApi) {
        return originalFetch(input, init);
      }

      if (window.__authInitPromise) {
        try {
          await window.__authInitPromise;
        } catch (_) {
          // Ignore and let request continue without token.
        }
      }

      if (!authState.client) {
        return originalFetch(input, init);
      }

      const token = await authState.client.getTokenSilently({
        authorizationParams: { audience: authState.audience },
      });

      const headers = new Headers(init.headers || {});
      headers.set("Authorization", `Bearer ${token}`);

      return originalFetch(input, { ...init, headers });
    };
  }

  async function login(signupMode) {
    if (!authState.client) return;

    const appState = {
      returnTo: PROTECTED_PATHS.has(window.location.pathname) ? window.location.pathname : "/matrix",
    };

    const authorizationParams = {
      audience: authState.audience,
    };

    if (signupMode) {
      authorizationParams.screen_hint = "signup";
    }

    await authState.client.loginWithRedirect({
      appState,
      authorizationParams,
    });
  }

  async function logout() {
    if (!authState.client) return;
    const returnTo = `${window.location.origin}${authState.logoutReturnPath || LOGIN_PATH}`;
    await authState.client.logout({ logoutParams: { returnTo } });
  }

  async function hydrateLoginPage() {
    const banner = document.getElementById("auth-status");
    if (!banner) return;

    if (!authState.enabled) {
      banner.textContent = "Authentication is disabled in environment configuration. Continue directly to the app.";
      const goBtn = document.getElementById("auth-continue-btn");
      if (goBtn) {
        goBtn.classList.remove("hidden");
      }
      return;
    }

    if (!authState.configured) {
      banner.textContent = "Authentication is enabled but Auth0 configuration is incomplete. Please set AUTH0_DOMAIN, AUTH0_CLIENT_ID, and AUTH0_AUDIENCE.";
      return;
    }

    banner.textContent = "Secure clinician sign-in is enabled. Choose Sign In or Create Account.";
  }

  async function initAuth() {
    installApiFetchInterceptor();

    const config = await fetchAuthConfig();
    authState.enabled = Boolean(config.enabled);
    authState.configured = Boolean(config.configured);
    authState.audience = config.audience || "";
    authState.callbackPath = config.callbackPath || "/auth/callback";
    authState.logoutReturnPath = config.logoutReturnPath || LOGIN_PATH;

    window.AppAuth = {
      enabled: authState.enabled,
      configured: authState.configured,
      login,
      logout,
    };

    ensureAuthButtons();
    await hydrateLoginPage();

    if (!authState.enabled || !authState.configured) {
      if (window.location.pathname === LOGIN_PATH && !authState.enabled) {
        const goBtn = document.getElementById("auth-continue-btn");
        if (goBtn) {
          goBtn.addEventListener("click", () => {
            window.location.href = "/matrix";
          });
        }
      }
      return;
    }

    await loadAuth0Sdk();

    authState.client = await window.createAuth0Client({
      domain: config.domain,
      clientId: config.clientId,
      authorizationParams: {
        audience: config.audience,
        redirect_uri: `${window.location.origin}${config.callbackPath || "/auth/callback"}`,
      },
      cacheLocation: "localstorage",
      useRefreshTokens: true,
    });

    const params = new URLSearchParams(window.location.search);
    const hasAuthCallback = params.has("code") && params.has("state");
    if (hasAuthCallback) {
      const result = await authState.client.handleRedirectCallback();
      const returnTo = result.appState && result.appState.returnTo ? result.appState.returnTo : "/matrix";
      window.history.replaceState({}, document.title, returnTo);
    }

    const authenticated = await authState.client.isAuthenticated();

    if (window.location.pathname === LOGIN_PATH) {
      if (authenticated) {
        window.location.replace("/matrix");
      }
      return;
    }

    if (PROTECTED_PATHS.has(window.location.pathname) && !authenticated) {
      window.location.replace(LOGIN_PATH);
    }
  }

  window.__authInitPromise = initAuth()
    .catch((error) => {
      console.error("Auth initialization failed", error);
      const banner = document.getElementById("auth-status");
      if (banner) {
        banner.textContent = `Authentication failed to initialize: ${error.message}`;
      }
    })
    .finally(() => {
      authState.initialized = true;
    });
})();
