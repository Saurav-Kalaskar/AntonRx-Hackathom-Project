import json
import os
import time
from typing import Any, Dict, Optional

import httpx
from fastapi import HTTPException, Request, Response, status

_JWKS_CACHE: Dict[str, Any] = {"domain": None, "fetched_at": 0.0, "jwks": None}
_JWKS_TTL_SECONDS = 3600
SESSION_COOKIE_NAME = "ttt_session"
DEFAULT_SESSION_TTL_SECONDS = 60 * 60 * 8


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def get_auth_settings() -> Dict[str, Any]:
    enabled = _env_bool("AUTH_ENABLED", False)
    domain = (os.getenv("AUTH0_DOMAIN") or "").strip()
    client_id = (os.getenv("AUTH0_CLIENT_ID") or "").strip()
    audience = (os.getenv("AUTH0_AUDIENCE") or "").strip()
    callback_path = (os.getenv("AUTH0_CALLBACK_PATH") or "/auth/callback").strip()
    logout_return_path = (os.getenv("AUTH0_LOGOUT_RETURN_PATH") or "/login").strip()

    if callback_path and not callback_path.startswith("/"):
        callback_path = f"/{callback_path}"
    if logout_return_path and not logout_return_path.startswith("/"):
        logout_return_path = f"/{logout_return_path}"

    configured = bool(domain and client_id and audience)

    return {
        "enabled": enabled,
        "configured": configured,
        "domain": domain,
        "client_id": client_id,
        "audience": audience,
        "callback_path": callback_path,
        "logout_return_path": logout_return_path,
        "issuer": f"https://{domain}/" if domain else "",
    }


def get_auth_public_config() -> Dict[str, Any]:
    settings = get_auth_settings()
    return {
        "enabled": settings["enabled"],
        "configured": settings["configured"],
        "domain": settings["domain"],
        "clientId": settings["client_id"],
        "audience": settings["audience"],
        "callbackPath": settings["callback_path"],
        "logoutReturnPath": settings["logout_return_path"],
    }


def _get_session_ttl_seconds() -> int:
    raw = (os.getenv("SESSION_TTL_SECONDS") or "").strip()
    if not raw:
        return DEFAULT_SESSION_TTL_SECONDS
    try:
        value = int(raw)
        return max(300, value)
    except ValueError:
        return DEFAULT_SESSION_TTL_SECONDS


def _get_session_secret(settings: Dict[str, Any]) -> str:
    explicit = (os.getenv("APP_SESSION_SECRET") or "").strip()
    if explicit:
        return explicit

    # Deterministic fallback so environments without explicit secret still work.
    # For production, APP_SESSION_SECRET should always be set.
    base = f"{settings.get('domain', '')}|{settings.get('client_id', '')}|time-to-therapy"
    if base.replace("|", "").strip():
        return base

    return "time-to-therapy-dev-session-secret"


def issue_app_session_token(user_claims: Dict[str, Any], settings: Dict[str, Any]) -> str:
    try:
        import jwt
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Session token dependency missing: {exc}",
        )

    now = int(time.time())
    ttl_seconds = _get_session_ttl_seconds()

    payload = {
        "sub": user_claims.get("sub", "unknown"),
        "email": user_claims.get("email"),
        "aud": settings.get("audience", ""),
        "iat": now,
        "exp": now + ttl_seconds,
        "iss": "time-to-therapy-app",
    }

    token = jwt.encode(payload, _get_session_secret(settings), algorithm="HS256")
    return token


def verify_app_session_token(session_token: str, settings: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    try:
        import jwt
        from jwt.exceptions import InvalidTokenError
    except Exception:
        return None

    if not session_token:
        return None

    try:
        payload = jwt.decode(
            session_token,
            _get_session_secret(settings),
            algorithms=["HS256"],
            options={"verify_aud": False},
        )
        return payload
    except InvalidTokenError:
        return None
    except Exception:
        return None


def has_valid_app_session(request: Request) -> bool:
    settings = get_auth_settings()
    if not settings.get("enabled"):
        return True

    token = request.cookies.get(SESSION_COOKIE_NAME) or ""
    payload = verify_app_session_token(token, settings)
    if not payload:
        return False

    request.state.user = payload
    return True


def set_app_session_cookie(response: Response, session_token: str) -> None:
    secure_cookie = _env_bool("SESSION_COOKIE_SECURE", False)
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=session_token,
        httponly=True,
        secure=secure_cookie,
        samesite="lax",
        max_age=_get_session_ttl_seconds(),
        path="/",
    )


def clear_app_session_cookie(response: Response) -> None:
    response.delete_cookie(key=SESSION_COOKIE_NAME, path="/")


async def _fetch_jwks(domain: str) -> Dict[str, Any]:
    now = time.time()
    if (
        _JWKS_CACHE.get("domain") == domain
        and _JWKS_CACHE.get("jwks")
        and (now - float(_JWKS_CACHE.get("fetched_at", 0.0)) < _JWKS_TTL_SECONDS)
    ):
        return _JWKS_CACHE["jwks"]

    jwks_url = f"https://{domain}/.well-known/jwks.json"
    async with httpx.AsyncClient(timeout=8.0) as client:
        response = await client.get(jwks_url)
        response.raise_for_status()
        payload = response.json()

    _JWKS_CACHE["domain"] = domain
    _JWKS_CACHE["jwks"] = payload
    _JWKS_CACHE["fetched_at"] = now
    return payload


async def verify_auth0_token(token: str, settings: Dict[str, Any]) -> Dict[str, Any]:
    try:
        import jwt
        from jwt.algorithms import RSAAlgorithm
        from jwt.exceptions import InvalidTokenError
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"JWT verification dependencies are missing: {exc}",
        )

    if not settings.get("configured"):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Auth is enabled but Auth0 configuration is incomplete.",
        )

    try:
        unverified_header = jwt.get_unverified_header(token)
        kid = unverified_header.get("kid")
        if not kid:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token header: missing key id.",
            )

        jwks = await _fetch_jwks(settings["domain"])
        keys = jwks.get("keys") or []
        key_match = next((key for key in keys if key.get("kid") == kid), None)
        if not key_match:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Unable to find signing key for token.",
            )

        public_key = RSAAlgorithm.from_jwk(json.dumps(key_match))
        payload = jwt.decode(
            token,
            public_key,
            algorithms=["RS256"],
            audience=settings["audience"],
            issuer=settings["issuer"],
        )
        return payload

    except HTTPException:
        raise
    except InvalidTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid or expired token: {exc}",
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Token verification failed: {exc}",
        )


async def require_auth(request: Request) -> Optional[Dict[str, Any]]:
    settings = get_auth_settings()
    if not settings["enabled"]:
        return None

    authorization = request.headers.get("Authorization") or ""
    if not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Bearer token.",
        )

    token = authorization.split(" ", 1)[1].strip()
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Bearer token.",
        )

    payload = await verify_auth0_token(token, settings)
    request.state.user = payload
    return payload
