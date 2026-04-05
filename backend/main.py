import sqlite3
import json
import os
import re
import base64
import hashlib
import hmac
from pathlib import Path
from urllib.parse import quote_plus
import httpx

try:
    from .env_loader import load_env_once
except ImportError as exc:
    if "attempted relative import with no known parent package" not in str(exc):
        raise
    from env_loader import load_env_once

load_env_once()

# ── Environment must be set BEFORE any fastembed/qdrant imports ──────────────
_BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
os.environ["FASTEMBED_CACHE_PATH"] = os.path.join(_BACKEND_DIR, "fastembed_cache")
os.environ["FASTEMBED_MODEL_PATH"] = os.path.join(_BACKEND_DIR, "fastembed_cache")
os.environ["HF_HUB_ENABLE_HF_TRANSFER"] = "0"
os.environ["HF_HUB_DISABLE_FAST_DOWNLOAD"] = "1"
# ─────────────────────────────────────────────────────────────────────────────

from fastapi import FastAPI, HTTPException, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, RedirectResponse, JSONResponse
from pydantic import BaseModel
from typing import List, Dict, Any, Optional

try:
    from .generator.drafter import PADrafter
    from .pipeline.rag_engine import RAGEngine
    from .auth import (
        require_auth,
        get_auth_public_config,
        get_auth_settings,
        has_valid_app_session,
        get_app_session_user,
        issue_app_session_token,
        set_app_session_cookie,
        clear_app_session_cookie,
    )
except ImportError as exc:
    if "attempted relative import with no known parent package" not in str(exc):
        raise
    # Fallback for running this file directly from backend/.
    from generator.drafter import PADrafter
    from pipeline.rag_engine import RAGEngine
    from auth import (
        require_auth,
        get_auth_public_config,
        get_auth_settings,
        has_valid_app_session,
        get_app_session_user,
        issue_app_session_token,
        set_app_session_cookie,
        clear_app_session_cookie,
    )

app = FastAPI(
    title="Time-to-Therapy API",
    description="Prior Authorization Copilot — RAG + Nemotron-3-Super-120B",
    version="2.0.0",
)

# Serve static files from the site directory
frontend_dir = str(Path(_BACKEND_DIR).parent / "site" / "public")
app.mount("/static", StaticFiles(directory=frontend_dir), name="static")
policy_docs_dir = str(Path(_BACKEND_DIR) / "pipeline" / "documents")
app.mount("/policies", StaticFiles(directory=policy_docs_dir), name="policies")
print(f"Serving static files from: {frontend_dir} at /static path")

allowed_origins = [
    origin.strip()
    for origin in os.getenv(
        "ALLOWED_ORIGINS",
        "http://localhost:8005,http://127.0.0.1:8005",
    ).split(",")
    if origin.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def protect_static_html_routes(request: Request, call_next):
    settings = get_auth_settings()
    path = request.url.path.lower()
    if settings.get("enabled") and path.startswith("/static/") and path.endswith(".html"):
        if not has_valid_app_session(request):
            return RedirectResponse(url="/login")
    return await call_next(request)

# ── Singleton RAG Engine (initializes on startup) ────────────────────────────
rag_engine = RAGEngine()

# ── SQLite History Database ───────────────────────────────────────────────────
_DB_PATH = os.path.join(_BACKEND_DIR, "history.db")
conn = sqlite3.connect(_DB_PATH, check_same_thread=False)
cursor = conn.cursor()


def _ensure_history_schema() -> None:
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS pa_drafts (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            payer_name      TEXT,
            patient_context TEXT,
            draft_content   TEXT,
            retrieved_rules TEXT,
            timestamp       DATETIME DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    cursor.execute("PRAGMA table_info(pa_drafts)")
    existing_columns = {row[1] for row in cursor.fetchall()}

    # Backward-compatible migrations for older local DB files.
    if "retrieved_rules" not in existing_columns:
        cursor.execute("ALTER TABLE pa_drafts ADD COLUMN retrieved_rules TEXT")

    conn.commit()


_ensure_history_schema()


def _ensure_user_schema() -> None:
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS app_users (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            name          TEXT NOT NULL,
            email         TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            created_at    DATETIME DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.commit()


_ensure_user_schema()


def _normalize_email(email: str) -> str:
    return (email or "").strip().lower()


def _hash_password(password: str) -> str:
    iterations = 240000
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    salt_b64 = base64.urlsafe_b64encode(salt).decode("ascii")
    digest_b64 = base64.urlsafe_b64encode(digest).decode("ascii")
    return f"pbkdf2_sha256${iterations}${salt_b64}${digest_b64}"


def _verify_password(password: str, password_hash: str) -> bool:
    try:
        algo, iteration_raw, salt_b64, digest_b64 = (password_hash or "").split("$", 3)
        if algo != "pbkdf2_sha256":
            return False
        iterations = int(iteration_raw)
        salt = base64.urlsafe_b64decode(salt_b64.encode("ascii"))
        expected = base64.urlsafe_b64decode(digest_b64.encode("ascii"))
        actual = hashlib.pbkdf2_hmac("sha256", (password or "").encode("utf-8"), salt, iterations)
        return hmac.compare_digest(actual, expected)
    except Exception:
        return False


def _issue_local_user_session(user_id: int, name: str, email: str) -> JSONResponse:
    settings = get_auth_settings()
    session_user = {
        "sub": f"local:{user_id}",
        "name": name,
        "email": email,
        "auth_provider": "local",
    }
    session_token = issue_app_session_token(session_user, settings)
    response = JSONResponse(
        {
            "status": "ok",
            "user": {
                "id": user_id,
                "name": name,
                "email": email,
            },
        }
    )
    set_app_session_cookie(response, session_token)
    return response

def _sanitize_search_term(term: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9\s\-()+/]", "", (term or ""))
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned[:80]


def _normalize_medication_name(raw_name: str) -> str:
    value = " ".join((raw_name or "").split())
    if not value:
        return "Unknown Drug"

    primary = re.split(r"\band\b", value, maxsplit=1, flags=re.IGNORECASE)[0].strip()
    primary = re.sub(r"\bbiosimilars?\b", "", primary, flags=re.IGNORECASE).strip(" -,:;/")
    if not primary:
        return value

    paren = re.search(r"([^()]+)\(([^()]+)\)", primary)
    if paren:
        left = paren.group(1).strip()
        right = paren.group(2).strip()
        if left and right:
            return f"{left} / {right}"

    return primary


def _tokenize_term(text: str) -> List[str]:
    return [tok for tok in re.split(r"[^A-Za-z0-9]+", (text or "").lower()) if tok]


def _status_rank(status: str) -> int:
    lowered = (status or "").lower()
    if "non-preferred" in lowered:
        return 3
    if "step" in lowered or "block" in lowered:
        return 2
    if "covered" in lowered:
        return 1
    return 0


def _compact_requirements(requirements: str) -> str:
    compact = " ".join((requirements or "").split())
    if len(compact) <= 160:
        return compact
    return compact[:157] + "..."


def _build_dailymed_search_url(term: str) -> str:
    return f"https://dailymed.nlm.nih.gov/dailymed/search.cfm?query={quote_plus(term)}"


async def _lookup_openfda_drug_info(term: str) -> Dict[str, str] | None:
    search = f'(openfda.brand_name:"{term}" OR openfda.generic_name:"{term}")'
    endpoint = "https://api.fda.gov/drug/label.json"

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(endpoint, params={"search": search, "limit": 1})

        if response.status_code != 200:
            return None

        payload = response.json()
        results = payload.get("results") or []
        if not results:
            return None

        openfda = results[0].get("openfda", {})
        set_id = (openfda.get("set_id") or [None])[0]
        brand_name = (openfda.get("brand_name") or [None])[0]
        generic_name = (openfda.get("generic_name") or [None])[0]

        display_name = brand_name or generic_name or term
        if set_id:
            info_url = f"https://dailymed.nlm.nih.gov/dailymed/drugInfo.cfm?setid={quote_plus(set_id)}"
        else:
            info_url = _build_dailymed_search_url(display_name)

        return {
            "display_name": display_name,
            "info_url": info_url,
            "source": "openFDA/DailyMed",
        }
    except Exception:
        return None

# ── Request / Response Models ─────────────────────────────────────────────────

class DraftRequest(BaseModel):
    payer_name: str
    patient_context: Dict[str, Any]
    retrieved_rules: List[Dict[str, Any]] = []


class DraftResponse(BaseModel):
    draft: str
    retrieved_rules: List[Dict[str, Any]]
    payer_name: str


class SignInRequest(BaseModel):
    email: str
    password: str


class SignUpRequest(BaseModel):
    name: str
    email: str
    password: str


# ── Frontend Page Routes ─────────────────────────────────────────────────────

@app.get("/", include_in_schema=False)
async def index():
    auth_settings = get_auth_settings()
    if auth_settings.get("enabled"):
        return RedirectResponse(url="/login")
    return RedirectResponse(url="/matrix")


@app.get("/login", include_in_schema=False)
async def login_page(request: Request):
    auth_settings = get_auth_settings()
    if auth_settings.get("enabled") and has_valid_app_session(request):
        return RedirectResponse(url="/matrix")
    return FileResponse(os.path.join(frontend_dir, "login.html"))


@app.get("/auth/callback", include_in_schema=False)
async def auth_callback_page():
    return FileResponse(os.path.join(frontend_dir, "login.html"))


@app.get("/matrix", include_in_schema=False)
async def matrix_page(request: Request):
    auth_settings = get_auth_settings()
    if auth_settings.get("enabled") and not has_valid_app_session(request):
        return RedirectResponse(url="/login")
    return FileResponse(os.path.join(frontend_dir, "matrix.html"))


@app.get("/copilot", include_in_schema=False)
async def copilot_page(request: Request):
    auth_settings = get_auth_settings()
    if auth_settings.get("enabled") and not has_valid_app_session(request):
        return RedirectResponse(url="/login")
    return FileResponse(os.path.join(frontend_dir, "copilot.html"))


@app.get("/history", include_in_schema=False)
async def history_page(request: Request):
    auth_settings = get_auth_settings()
    if auth_settings.get("enabled") and not has_valid_app_session(request):
        return RedirectResponse(url="/login")
    return FileResponse(os.path.join(frontend_dir, "history.html"))


@app.get("/auth/config")
async def auth_config():
    return get_auth_public_config()


@app.get("/auth/me")
async def auth_me(request: Request):
    settings = get_auth_settings()
    if not settings.get("enabled"):
        return {"authenticated": False, "provider": "none"}

    user = get_app_session_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated.")

    return {
        "authenticated": True,
        "provider": settings.get("provider"),
        "user": {
            "sub": user.get("sub"),
            "name": user.get("name"),
            "email": user.get("email"),
        },
    }


@app.post("/auth/login")
async def auth_login(payload: SignInRequest):
    settings = get_auth_settings()
    if not settings.get("enabled"):
        raise HTTPException(status_code=400, detail="Authentication is disabled.")
    if settings.get("provider") != "local":
        raise HTTPException(status_code=400, detail="Local credential login is not enabled.")

    email = _normalize_email(payload.email)
    password = payload.password or ""
    if not email or not password:
        raise HTTPException(status_code=400, detail="Email and password are required.")

    cursor.execute(
        "SELECT id, name, email, password_hash FROM app_users WHERE email = ?",
        (email,),
    )
    row = cursor.fetchone()
    if not row or not _verify_password(password, row[3]):
        raise HTTPException(status_code=401, detail="Invalid email or password.")

    return _issue_local_user_session(user_id=int(row[0]), name=row[1], email=row[2])


@app.post("/auth/register")
async def auth_register(payload: SignUpRequest):
    settings = get_auth_settings()
    if not settings.get("enabled"):
        raise HTTPException(status_code=400, detail="Authentication is disabled.")
    if settings.get("provider") != "local":
        raise HTTPException(status_code=400, detail="Local registration is not enabled.")

    name = " ".join((payload.name or "").split()).strip()
    email = _normalize_email(payload.email)
    password = payload.password or ""

    if len(name) < 2:
        raise HTTPException(status_code=400, detail="Name must be at least 2 characters.")
    if "@" not in email or "." not in email.split("@")[-1]:
        raise HTTPException(status_code=400, detail="Please enter a valid email address.")
    if len(password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters.")

    cursor.execute("SELECT id FROM app_users WHERE email = ?", (email,))
    if cursor.fetchone():
        raise HTTPException(status_code=409, detail="An account with this email already exists.")

    cursor.execute(
        "INSERT INTO app_users (name, email, password_hash) VALUES (?, ?, ?)",
        (name, email, _hash_password(password)),
    )
    conn.commit()
    user_id = int(cursor.lastrowid)
    return _issue_local_user_session(user_id=user_id, name=name, email=email)


@app.post("/auth/session")
async def create_auth_session(request: Request, _user: Optional[Dict[str, Any]] = Depends(require_auth)):
    settings = get_auth_settings()
    if not settings.get("enabled"):
        return {"status": "auth-disabled"}

    if settings.get("provider") != "auth0":
        if not get_app_session_user(request):
            raise HTTPException(status_code=401, detail="Missing authenticated user.")
        return {"status": "ok"}

    if not _user:
        raise HTTPException(status_code=401, detail="Missing authenticated user.")

    session_token = issue_app_session_token(_user, settings)
    response = JSONResponse({"status": "ok"})
    set_app_session_cookie(response, session_token)
    return response


@app.post("/auth/logout")
async def clear_auth_session():
    response = JSONResponse({"status": "ok"})
    clear_app_session_cookie(response)
    return response


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/health")
async def health_check():
    return {
        "status": "ok",
        "rag_ready": rag_engine._ready,
        "indexed_chunks": rag_engine.indexed_chunks,
        "indexed_policies": len(rag_engine.policy_records),
        "model": "nvidia/nemotron-3-super-120b-a12b",
    }


@app.post("/draft", response_model=DraftResponse)
async def create_draft(request: DraftRequest, _user: Dict[str, Any] | None = Depends(require_auth)):
    try:
        # Semantic search to retrieve relevant policy clauses
        query_text = (
            f"{request.patient_context.get('diagnosis', '')} "
            f"{request.patient_context.get('medication', '')} "
            f"prior authorization requirements step therapy"
        ).strip()

        retrieved_rules = rag_engine.search(
            query_text,
            top_k=6,
            payer_name=request.payer_name,
            medication=request.patient_context.get("medication", ""),
        )

        # Merge user-supplied rules (if any) with RAG results — RAG wins on content
        rules_to_use = retrieved_rules if retrieved_rules else request.retrieved_rules

        if not rules_to_use:
            draft_content = "Policy data not found in current coverage index."
        else:
            drafter = PADrafter(
                payer_name=request.payer_name,
                patient_context=request.patient_context,
                retrieved_rules=rules_to_use,
            )
            draft_content = drafter.generate_draft()

        # Persist to history
        cursor.execute(
            "INSERT INTO pa_drafts (payer_name, patient_context, draft_content, retrieved_rules) VALUES (?, ?, ?, ?)",
            (
                request.payer_name,
                json.dumps(request.patient_context),
                draft_content,
                json.dumps(rules_to_use),
            ),
        )
        conn.commit()

        return DraftResponse(
            draft=draft_content,
            retrieved_rules=rules_to_use,
            payer_name=request.payer_name,
        )

    except RuntimeError as e:
        # Real LLM or pipeline errors — return 502 so frontend shows real error
        raise HTTPException(status_code=502, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@app.get("/api/history")
async def get_history(_user: Dict[str, Any] | None = Depends(require_auth)):
    try:
        cursor.execute(
            "SELECT id, payer_name, patient_context, draft_content, retrieved_rules, timestamp "
            "FROM pa_drafts ORDER BY timestamp DESC"
        )
        rows = cursor.fetchall()
        history = []
        for row in rows:
            history.append({
                "id": row[0],
                "payer_name": row[1],
                "patient_context": json.loads(row[2]) if row[2] else {},
                "draft_content": row[3],
                "retrieved_rules": json.loads(row[4]) if row[4] else [],
                "timestamp": row[5],
            })
        return {"history": history}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/matrix")
async def get_matrix(
    query: str = "",
    payer: str = "",
    category: str = "",
    _user: Dict[str, Any] | None = Depends(require_auth),
):
    matrix = rag_engine.build_matrix(query=query, payer=payer, category=category)
    return {"matrix": matrix}


@app.get("/api/matrix/categories")
async def get_matrix_categories(_user: Dict[str, Any] | None = Depends(require_auth)):
    return {"categories": rag_engine.list_categories()}


@app.get("/api/matrix/compare")
async def get_matrix_compare(
    query: str = "",
    category: str = "",
    limit: int = 8,
    _user: Dict[str, Any] | None = Depends(require_auth),
):
    rows = rag_engine.build_matrix(query=query, payer="", category=category)
    if not rows:
        return {"payers": [], "comparison": [], "total_medications": 0}

    payers = sorted({row.get("payer", "Unknown") for row in rows if row.get("payer")})
    grouped: Dict[str, Dict[str, Any]] = {}

    for row in rows:
        medication = _normalize_medication_name(row.get("medication", ""))
        score = float(row.get("score") or 0.0)
        payer_name = row.get("payer", "Unknown")

        group = grouped.setdefault(
            medication,
            {
                "medication": medication,
                "indication": row.get("indication", "General policy criteria"),
                "requirements": _compact_requirements(row.get("requirements", "")),
                "best_score": score,
                "by_payer": {},
            },
        )

        if score > group["best_score"]:
            group["best_score"] = score
            group["indication"] = row.get("indication", "General policy criteria")
            group["requirements"] = _compact_requirements(row.get("requirements", ""))

        payer_entry = group["by_payer"].get(payer_name)
        if not payer_entry or score > float(payer_entry.get("score") or 0.0):
            group["by_payer"][payer_name] = {
                "status": row.get("status", "Unknown"),
                "score": round(score, 4),
                "source": row.get("source"),
                "source_url": row.get("source_url"),
                "requirements": _compact_requirements(row.get("requirements", "")),
            }

    comparison = []
    for _, group in grouped.items():
        blocker_count = sum(
            1 for entry in group["by_payer"].values() if _status_rank(entry.get("status", "")) >= 2
        )
        comparison.append(
            {
                "medication": group["medication"],
                "indication": group["indication"],
                "requirements": group["requirements"],
                "blocker_count": blocker_count,
                "by_payer": group["by_payer"],
            }
        )

    comparison.sort(key=lambda item: (-item["blocker_count"], item["medication"]))
    safe_limit = max(1, min(20, int(limit)))

    return {
        "payers": payers,
        "comparison": comparison[:safe_limit],
        "total_medications": len(comparison),
    }


@app.get("/api/oncology-search")
async def oncology_search(drug: str = "", _user: Dict[str, Any] | None = Depends(require_auth)):
    sanitized = _sanitize_search_term(drug)
    if not sanitized:
        return {
            "query": drug,
            "normalized_query": "",
            "info_url": None,
            "source": None,
        }

    query_tokens = set(_tokenize_term(sanitized))
    local_rows = rag_engine.build_matrix(query=sanitized)
    local_matches = [
        row
        for row in local_rows
        if query_tokens & set(_tokenize_term(str(row.get("medication", ""))))
    ]
    if local_matches:
        best = max(local_matches, key=lambda row: float(row.get("score") or 0.0))
        return {
            "query": drug,
            "normalized_query": sanitized,
            "info_url": best.get("source_url"),
            "source": "Local policy index",
            "matched_name": best.get("medication"),
        }

    dynamic_result = await _lookup_openfda_drug_info(sanitized)
    if dynamic_result:
        return {
            "query": drug,
            "normalized_query": sanitized,
            "info_url": dynamic_result["info_url"],
            "source": dynamic_result["source"],
            "matched_name": dynamic_result["display_name"],
        }

    return {
        "query": drug,
        "normalized_query": sanitized,
        "info_url": _build_dailymed_search_url(sanitized),
        "source": "DailyMed",
    }


@app.get("/api/draft/test-cases")
async def get_draft_test_cases(
    payer: str = "",
    medication: str = "",
    _user: Dict[str, Any] | None = Depends(require_auth),
):
    payer_filter = (payer or "").strip().lower()
    medication_filter = (medication or "").strip().lower()

    seen = set()
    cases: List[Dict[str, Any]] = []

    for policy in rag_engine.policy_records:
        policy_payer = policy.get("payer", "Unknown")
        policy_med = policy.get("drug_name", "Unknown Drug")

        if payer_filter and payer_filter not in policy_payer.lower():
            continue
        if medication_filter and medication_filter not in policy_med.lower():
            continue

        indications = policy.get("covered_indications") or ["General policy criteria"]
        diagnosis = indications[0] if indications else "General policy criteria"

        key = (policy_payer.lower(), policy_med.lower(), diagnosis.lower())
        if key in seen:
            continue
        seen.add(key)

        cases.append(
            {
                "payer_name": policy_payer,
                "patient_context": {
                    "patient_name": "Demo Patient",
                    "diagnosis": diagnosis,
                    "medication": policy_med,
                },
                "drug_category": policy.get("drug_category", "Specialty"),
                "source": policy.get("source"),
                "source_url": f"/policies/{policy.get('source')}" if policy.get("source") else None,
            }
        )

    cases.sort(key=lambda item: (item["payer_name"], item["patient_context"]["medication"]))

    return {
        "total": len(cases),
        "cases": cases,
    }


if __name__ == "__main__":
    import uvicorn
    # Print registered routes for debugging
    print("Registered routes:")
    for route in app.routes:
        print(f"  {route.path} -> {getattr(route, 'name', 'unnamed')}")
    uvicorn.run(app, host="0.0.0.0", port=8005, reload=False)
