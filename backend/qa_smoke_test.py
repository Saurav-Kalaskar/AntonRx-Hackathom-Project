"""End-to-end smoke checks for Time-to-Therapy backend + frontend wiring.

Run:
  python backend/qa_smoke_test.py
"""

from pathlib import Path
import sys

from fastapi.testclient import TestClient

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

try:
    from backend.main import app
except ModuleNotFoundError:
    from main import app


def run() -> None:
    client = TestClient(app)

    checks = []

    # Core routes
    checks.append(("GET /", client.get("/", follow_redirects=False).status_code == 307))
    checks.append(("GET /matrix", client.get("/matrix").status_code == 200))
    checks.append(("GET /copilot", client.get("/copilot").status_code == 200))
    checks.append(("GET /history", client.get("/history").status_code == 200))

    # Health and indexing
    health = client.get("/health")
    health_json = health.json()
    checks.append(("GET /health 200", health.status_code == 200))
    checks.append(("RAG ready", bool(health_json.get("rag_ready"))))
    checks.append(("Indexed chunks > 0", int(health_json.get("indexed_chunks", 0)) > 0))

    # Matrix API
    matrix_all = client.get("/api/matrix").json().get("matrix", [])
    matrix_key = client.get("/api/matrix?query=Keytruda").json().get("matrix", [])
    matrix_payer = client.get("/api/matrix?payer=Aetna").json().get("matrix", [])
    matrix_none = client.get("/api/matrix?query=ImaginaryDrugXYZ").json().get("matrix", [])

    checks.append(("Matrix rows available", len(matrix_all) > 0))
    checks.append(("Matrix query filter works", len(matrix_key) > 0))
    checks.append(("Matrix payer filter works", len(matrix_payer) > 0 and all(r["payer"].lower() == "aetna" for r in matrix_payer)))
    checks.append(("Matrix no-match returns empty", len(matrix_none) == 0))

    if matrix_key:
        sample = matrix_key[0]
        source_ok = bool(sample.get("source"))
        source_url_ok = bool(sample.get("source_url"))
        checks.append(("Matrix includes source metadata", source_ok and source_url_ok))
        if source_url_ok:
            checks.append(("Matrix source URL reachable", client.get(sample["source_url"]).status_code == 200))

    # Draft API known/unknown cases
    known = client.post(
        "/draft",
        json={
            "payer_name": "Aetna",
            "patient_context": {
                "patient_name": "QA",
                "diagnosis": "NSCLC",
                "medication": "Keytruda",
            },
        },
    )
    unknown = client.post(
        "/draft",
        json={
            "payer_name": "Aetna",
            "patient_context": {
                "patient_name": "QA",
                "diagnosis": "Unknown Dx",
                "medication": "ImaginaryDrugXYZ",
            },
        },
    )

    known_json = known.json()
    unknown_json = unknown.json()

    checks.append(("Draft known returns 200", known.status_code == 200))
    checks.append(("Draft known has retrieved rules", len(known_json.get("retrieved_rules", [])) > 0))
    checks.append(("Draft unknown returns no-data sentinel", unknown_json.get("draft") == "Policy data not found in current coverage index."))

    # History API persistence
    history = client.get("/api/history")
    history_rows = history.json().get("history", [])
    checks.append(("History endpoint returns 200", history.status_code == 200))
    checks.append(("History has at least one row", len(history_rows) > 0))
    if history_rows:
        latest = history_rows[0]
        checks.append(("History row includes retrieved_rules", "retrieved_rules" in latest))

    # Frontend wiring assertions
    matrix_html = client.get("/matrix").text
    copilot_html = client.get("/copilot").text
    history_html = client.get("/history").text

    checks.append(("Matrix page has search input", 'id="matrix-search"' in matrix_html))
    checks.append(("Matrix page routes to Copilot", "window.location.href = `/copilot?${params.toString()}`" in matrix_html))
    checks.append(("Copilot page posts to /draft", 'fetch("/draft"' in copilot_html))
    checks.append(("History page fetches /api/history", 'fetch("/api/history"' in history_html))

    failures = [name for name, ok in checks if not ok]

    print("\nQA Smoke Test Results")
    print("=" * 60)
    for name, ok in checks:
        print(f"{'PASS' if ok else 'FAIL'}  {name}")

    print("=" * 60)
    if failures:
        print(f"FAILED: {len(failures)} checks")
        for name in failures:
            print(f" - {name}")
        raise SystemExit(1)

    print(f"SUCCESS: {len(checks)} checks passed")


if __name__ == "__main__":
    run()
