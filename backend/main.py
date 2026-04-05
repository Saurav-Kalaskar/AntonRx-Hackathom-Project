import sqlite3
import json
import os
from pathlib import Path

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

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, RedirectResponse
from pydantic import BaseModel
from typing import List, Dict, Any

try:
    from .generator.drafter import PADrafter
    from .pipeline.rag_engine import RAGEngine
except ImportError as exc:
    if "attempted relative import with no known parent package" not in str(exc):
        raise
    # Fallback for running this file directly from backend/.
    from generator.drafter import PADrafter
    from pipeline.rag_engine import RAGEngine

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

# ── Request / Response Models ─────────────────────────────────────────────────

class DraftRequest(BaseModel):
    payer_name: str
    patient_context: Dict[str, Any]
    retrieved_rules: List[Dict[str, Any]] = []


class DraftResponse(BaseModel):
    draft: str
    retrieved_rules: List[Dict[str, Any]]
    payer_name: str


# ── Frontend Page Routes ─────────────────────────────────────────────────────

@app.get("/", include_in_schema=False)
async def index():
    return RedirectResponse(url="/matrix")


@app.get("/matrix", include_in_schema=False)
async def matrix_page():
    return FileResponse(os.path.join(frontend_dir, "matrix.html"))


@app.get("/copilot", include_in_schema=False)
async def copilot_page():
    return FileResponse(os.path.join(frontend_dir, "copilot.html"))


@app.get("/history", include_in_schema=False)
async def history_page():
    return FileResponse(os.path.join(frontend_dir, "history.html"))


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
async def create_draft(request: DraftRequest):
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
async def get_history():
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
async def get_matrix(query: str = "", payer: str = ""):
    matrix = rag_engine.build_matrix(query=query, payer=payer)
    return {"matrix": matrix}


if __name__ == "__main__":
    import uvicorn
    # Print registered routes for debugging
    print("Registered routes:")
    for route in app.routes:
        print(f"  {route.path} -> {getattr(route, 'name', 'unnamed')}")
    uvicorn.run(app, host="0.0.0.0", port=8005, reload=False)
