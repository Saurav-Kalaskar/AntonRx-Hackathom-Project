(function () {
  const LOGIN_PATH = "/login";
  const PROTECTED_PATHS = new Set(["/matrix", "/copilot", "/history"]);

  const authState = {
    initialized: false,
    enabled: false,
    provider: "local",
    configured: false,
    audience: "",
    callbackPath: "/auth/callback",
    logoutReturnPath: "/login",
    client: null,
    localMode: "signin",
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
    const logoutButtons = [
      ...document.querySelectorAll("[data-auth-logout]"),
      ...document.querySelectorAll("#auth-logout-btn"),
    ];

    if (signInBtn) {
      signInBtn.addEventListener("click", () => {
        if (authState.provider === "local") {
          setLocalMode("signin");
          return;
        }
        login(false);
      });
    }
    if (signUpBtn) {
      signUpBtn.addEventListener("click", () => {
        if (authState.provider === "local") {
          setLocalMode("signup");
          return;
        }
        login(true);
      });
    }
    logoutButtons.forEach((btn) => {
      if (!btn || btn.dataset.logoutWired === "1") return;
      btn.addEventListener("click", () => logout());
      btn.dataset.logoutWired = "1";
    });
  }

  function setBanner(message, tone) {
    const banner = document.getElementById("auth-status");
    if (!banner) return;

    banner.textContent = message;
    banner.classList.remove(
      "bg-slate-100",
      "text-slate-700",
      "bg-red-50",
      "text-red-700",
      "bg-emerald-50",
      "text-emerald-800"
    );

    if (tone === "error") {
      banner.classList.add("bg-red-50", "text-red-700");
    } else if (tone === "success") {
      banner.classList.add("bg-emerald-50", "text-emerald-800");
    } else {
      banner.classList.add("bg-slate-100", "text-slate-700");
    }
  }

  function setPoweredByLabel(message) {
    const label = document.getElementById("auth-powered-label");
    if (!label) return;
    label.textContent = message;
  }

  function setFormError(message) {
    const node = document.getElementById("auth-form-error");
    if (!node) return;
    if (!message) {
      node.textContent = "";
      node.classList.add("hidden");
      return;
    }
    node.textContent = message;
    node.classList.remove("hidden");
  }

  function setLocalMode(mode) {
    authState.localMode = mode === "signup" ? "signup" : "signin";

    const signInBtn = document.getElementById("auth-signin-btn");
    const signUpBtn = document.getElementById("auth-signup-btn");
    const signInForm = document.getElementById("auth-signin-form");
    const signUpForm = document.getElementById("auth-signup-form");

    if (signInBtn && signUpBtn) {
      const signInActive = authState.localMode === "signin";
      signInBtn.classList.toggle("bg-teal-700", signInActive);
      signInBtn.classList.toggle("text-white", signInActive);
      signInBtn.classList.toggle("border", !signInActive);
      signInBtn.classList.toggle("border-teal-700", !signInActive);
      signInBtn.classList.toggle("text-teal-700", !signInActive);

      signUpBtn.classList.toggle("bg-teal-700", !signInActive);
      signUpBtn.classList.toggle("text-white", !signInActive);
      signUpBtn.classList.toggle("border", signInActive);
      signUpBtn.classList.toggle("border-teal-700", signInActive);
      signUpBtn.classList.toggle("text-teal-700", signInActive);
    }

    if (signInForm) {
      signInForm.classList.toggle("hidden", authState.localMode !== "signin");
    }
    if (signUpForm) {
      signUpForm.classList.toggle("hidden", authState.localMode !== "signup");
    }

    setFormError("");
  }

  async function postJson(path, payload) {
    const response = await fetch(path, {
      method: "POST",
      credentials: "same-origin",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(payload),
    });

    const body = await response.json().catch(() => ({}));
    if (!response.ok) {
      const detail = body.detail || `Request failed with HTTP ${response.status}`;
      throw new Error(detail);
    }
    return body;
  }

  async function handleLocalSignIn(event) {
    event.preventDefault();
    const emailInput = document.getElementById("signin-email");
    const passwordInput = document.getElementById("signin-password");

    const email = (emailInput && emailInput.value ? emailInput.value : "").trim();
    const password = passwordInput && passwordInput.value ? passwordInput.value : "";

    if (!email || !password) {
      setFormError("Please enter both email and password.");
      return;
    }

    setFormError("");
    setBanner("Signing you in...", "info");

    try {
      await postJson("/auth/login", { email, password });
      setBanner("Signed in successfully. Redirecting...", "success");
      window.location.replace("/matrix");
    } catch (error) {
      setBanner("Sign in failed. Please check your credentials.", "error");
      setFormError(error.message || "Unable to sign in.");
    }
  }

  async function handleLocalSignUp(event) {
    event.preventDefault();
    const nameInput = document.getElementById("signup-name");
    const emailInput = document.getElementById("signup-email");
    const passwordInput = document.getElementById("signup-password");

    const name = (nameInput && nameInput.value ? nameInput.value : "").trim();
    const email = (emailInput && emailInput.value ? emailInput.value : "").trim();
    const password = passwordInput && passwordInput.value ? passwordInput.value : "";

    if (!name || !email || !password) {
      setFormError("Please enter name, email, and password.");
      return;
    }

    setFormError("");
    setBanner("Creating your account...", "info");

    try {
      await postJson("/auth/register", { name, email, password });
      setBanner("Account created successfully. Redirecting...", "success");
      window.location.replace("/matrix");
    } catch (error) {
      setBanner("Account creation failed. Please review your details.", "error");
      setFormError(error.message || "Unable to create account.");
    }
  }

  function wireLocalForms() {
    const signInForm = document.getElementById("auth-signin-form");
    const signUpForm = document.getElementById("auth-signup-form");

    if (signInForm && !signInForm.dataset.wired) {
      signInForm.addEventListener("submit", handleLocalSignIn);
      signInForm.dataset.wired = "1";
    }
    if (signUpForm && !signUpForm.dataset.wired) {
      signUpForm.addEventListener("submit", handleLocalSignUp);
      signUpForm.dataset.wired = "1";
    }
  }

  async function hasLocalSession() {
    try {
      const response = await fetch("/auth/me", { credentials: "same-origin" });
      return response.ok;
    } catch (_) {
      return false;
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
      const nextInit = { ...init };

      if (!nextInit.credentials) {
        nextInit.credentials = "same-origin";
      }

      if (!protectedApi || !authState.enabled) {
        return originalFetch(input, nextInit);
      }

      if (authState.provider !== "auth0" || !authState.configured) {
        return originalFetch(input, nextInit);
      }

      if (window.__authInitPromise) {
        try {
          await window.__authInitPromise;
        } catch (_) {
          // Ignore and let request continue without token.
        }
      }

      if (!authState.client) {
        return originalFetch(input, nextInit);
      }

      const token = await authState.client.getTokenSilently({
        authorizationParams: { audience: authState.audience },
      });

      const headers = new Headers(nextInit.headers || {});
      headers.set("Authorization", `Bearer ${token}`);

      return originalFetch(input, { ...nextInit, headers });
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

  async function establishBackendSession() {
    if (!authState.client) return;

    const token = await authState.client.getTokenSilently({
      authorizationParams: { audience: authState.audience },
    });

    const response = await fetch("/auth/session", {
      method: "POST",
      credentials: "same-origin",
      headers: {
        Authorization: `Bearer ${token}`,
      },
    });

    if (!response.ok) {
      throw new Error(`Failed to establish app session: HTTP ${response.status}`);
    }
  }

  async function clearBackendSession() {
    try {
      await fetch("/auth/logout", {
        method: "POST",
        credentials: "same-origin",
      });
    } catch (_) {
      // Ignore network failures while logging out.
    }
  }

  async function logout() {
    await clearBackendSession();

    if (authState.provider === "local") {
      window.location.replace(LOGIN_PATH);
      return;
    }

    if (!authState.client) return;
    const returnTo = `${window.location.origin}${authState.logoutReturnPath || LOGIN_PATH}`;
    await authState.client.logout({ logoutParams: { returnTo } });
  }

  async function hydrateLoginPage() {
    if (!authState.enabled) {
      setBanner("Authentication is disabled in environment configuration. Continue directly to the app.", "info");
      const goBtn = document.getElementById("auth-continue-btn");
      if (goBtn) {
        goBtn.classList.remove("hidden");
      }
      return;
    }

    if (authState.provider === "local") {
      setBanner("Secure clinician sign-in is enabled. Sign in or create your account to continue.", "info");
      return;
    }

    if (!authState.configured) {
      setBanner("Authentication is enabled but Auth0 configuration is incomplete. Please set AUTH0_DOMAIN, AUTH0_CLIENT_ID, and AUTH0_AUDIENCE.", "error");
      return;
    }

    setBanner("Secure clinician sign-in is enabled. Choose Sign In or Create Account.", "info");
  }

  async function initAuth() {
    installApiFetchInterceptor();

    const config = await fetchAuthConfig();
    authState.enabled = Boolean(config.enabled);
    authState.provider = config.provider || (config.configured ? "auth0" : "local");
    authState.configured = Boolean(config.configured);
    authState.audience = config.audience || "";
    authState.callbackPath = config.callbackPath || "/auth/callback";
    authState.logoutReturnPath = config.logoutReturnPath || LOGIN_PATH;

    if (!authState.enabled) {
      setPoweredByLabel("Authorization powered by Auth0");
    } else if (authState.provider === "auth0") {
      setPoweredByLabel("Authorization powered by Auth0");
    } else {
      setPoweredByLabel("Authorization powered by Auth0 (local fallback active)");
    }

    window.AppAuth = {
      enabled: authState.enabled,
      configured: authState.configured,
      login,
      logout,
    };

    ensureAuthButtons();
    wireLocalForms();
    await hydrateLoginPage();

    if (!authState.enabled) {
      if (window.location.pathname === LOGIN_PATH || window.location.pathname === `${LOGIN_PATH}/`) {
        const goBtn = document.getElementById("auth-continue-btn");
        if (goBtn) {
          goBtn.addEventListener("click", () => {
            window.location.href = "/matrix";
          });
        }
      }
      return;
    }

    if (authState.provider === "local") {
      const path = window.location.pathname;
      const onLoginPage = path === LOGIN_PATH || path === `${LOGIN_PATH}/`;
      const sessionActive = await hasLocalSession();

      if (onLoginPage && sessionActive) {
        window.location.replace("/matrix");
        return;
      }

      if (onLoginPage && !sessionActive) {
        setLocalMode("signin");
      }

      if (PROTECTED_PATHS.has(path) && !sessionActive) {
        window.location.replace(LOGIN_PATH);
      }
      return;
    }

    if (!authState.configured) {
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
      await establishBackendSession();
      window.location.replace(returnTo);
      return;
    }

    const authenticated = await authState.client.isAuthenticated();

    if (authenticated) {
      await establishBackendSession();
    }

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
      setBanner(`Authentication failed to initialize: ${error.message}`, "error");
    })
    .finally(() => {
      authState.initialized = true;
    });
})();
