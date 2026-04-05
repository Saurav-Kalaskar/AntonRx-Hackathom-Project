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
    checks.append(("GET /login", client.get("/login").status_code == 200))
    checks.append(("GET /auth/callback", client.get("/auth/callback").status_code == 200))
    checks.append(("GET /matrix", client.get("/matrix").status_code == 200))
    checks.append(("GET /copilot", client.get("/copilot").status_code == 200))
    checks.append(("GET /history", client.get("/history").status_code == 200))
    checks.append(("GET /static/test.html", client.get("/static/test.html").status_code == 200))

    # Health and indexing
    health = client.get("/health")
    health_json = health.json()
    checks.append(("GET /health 200", health.status_code == 200))
    checks.append(("RAG ready", bool(health_json.get("rag_ready"))))
    checks.append(("Indexed chunks > 0", int(health_json.get("indexed_chunks", 0)) > 0))

    auth_config = client.get("/auth/config")
    auth_config_json = auth_config.json()
    checks.append(("GET /auth/config 200", auth_config.status_code == 200))
    checks.append(("Auth config returns enabled flag", "enabled" in auth_config_json))

    # Matrix API
    matrix_all = client.get("/api/matrix").json().get("matrix", [])
    matrix_key = client.get("/api/matrix?query=Keytruda").json().get("matrix", [])
    matrix_payer = client.get("/api/matrix?payer=Aetna").json().get("matrix", [])
    matrix_none = client.get("/api/matrix?query=ImaginaryDrugXYZ").json().get("matrix", [])
    matrix_compare = client.get("/api/matrix/compare?query=Humira").json()
    categories_resp = client.get("/api/matrix/categories").json().get("categories", [])
    category_name = categories_resp[0]["category"] if categories_resp else ""
    matrix_category = (
        client.get("/api/matrix", params={"category": category_name}).json().get("matrix", [])
        if category_name
        else []
    )

    checks.append(("Matrix rows available", len(matrix_all) > 0))
    checks.append(("Matrix query filter works", len(matrix_key) > 0))
    checks.append(("Matrix payer filter works", len(matrix_payer) > 0 and all(r["payer"].lower() == "aetna" for r in matrix_payer)))
    checks.append(("Matrix no-match returns empty", len(matrix_none) == 0))
    checks.append(("Matrix categories endpoint returns categories", len(categories_resp) > 0))
    if category_name:
        checks.append(("Matrix category filter works", len(matrix_category) > 0 and all(r.get("category") == category_name for r in matrix_category)))
    checks.append(("Matrix compare endpoint returns payers", bool(matrix_compare.get("payers"))))
    checks.append(("Matrix compare endpoint returns comparison rows", bool(matrix_compare.get("comparison"))))

    if matrix_key:
        sample = matrix_key[0]
        source_ok = bool(sample.get("source"))
        source_url_ok = bool(sample.get("source_url"))
        checks.append(("Matrix includes source metadata", source_ok and source_url_ok))
        if source_url_ok:
            checks.append(("Matrix source URL reachable", client.get(sample["source_url"]).status_code == 200))

    # Oncology search endpoint and sanitization
    oncology_direct = client.get("/api/oncology-search?drug=Keytruda")
    oncology_direct_json = oncology_direct.json()
    checks.append(("Oncology search endpoint returns 200", oncology_direct.status_code == 200))
    checks.append(("Oncology search returns direct info URL", bool(oncology_direct_json.get("info_url"))))
    checks.append(("Oncology search direct source tagged", oncology_direct_json.get("source") in {"Local policy index", "DailyMed", "openFDA/DailyMed"}))

    oncology_sanitized = client.get("/api/oncology-search", params={"drug": "<script>alert(1)</script> Keytruda"})
    oncology_sanitized_json = oncology_sanitized.json()
    normalized = oncology_sanitized_json.get("normalized_query", "")
    checks.append(("Oncology query sanitization strips angle brackets", "<" not in normalized and ">" not in normalized))

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
    test_html = client.get("/static/test.html").text

    checks.append(("Matrix page has search input", 'id="matrix-search"' in matrix_html))
    checks.append(("Matrix page loads auth bootstrap", '/static/auth.js' in matrix_html))
    checks.append(("Matrix page title links to matrix", '<a href="/matrix" class="hover:opacity-90 transition-opacity">Time-to-Therapy</a>' in matrix_html))
    checks.append(("Matrix page has mobile hamburger button", 'id="mobile-menu-button"' in matrix_html))
    checks.append(("Matrix page has mobile nav menu", 'id="mobile-nav-menu"' in matrix_html))
    checks.append(("Matrix page hides legacy bottom nav", 'id="mobile-bottom-nav" class="hidden' in matrix_html))
    checks.append(("Matrix page has history nav link", 'href="/history"' in matrix_html))
    checks.append(("Matrix page uses standardized desktop nav cluster", 'ml-auto items-center gap-8 font-headline text-sm font-semibold tracking-tight' in matrix_html))
    checks.append(("Matrix page routes to Copilot", "window.location.href = `/copilot?${params.toString()}`" in matrix_html))
    checks.append(("Matrix page has drug info card", 'id="drug-info-result"' in matrix_html))
    checks.append(("Matrix page calls oncology search API", '/api/oncology-search?drug=' in matrix_html))
    checks.append(("Matrix page has category filter", 'id="category-filter"' in matrix_html))
    checks.append(("Matrix page calls category API", '/api/matrix/categories' in matrix_html))
    checks.append(("Matrix page has export button", 'id="export-btn"' in matrix_html))
    checks.append(("Matrix page includes xlsx library", 'xlsx.full.min.js' in matrix_html))
    checks.append(("Matrix page wires export click handler", 'exportFilteredRowsToExcel' in matrix_html))
    checks.append(("Matrix page has save file helper", 'saveBlobToFile' in matrix_html))
    checks.append(("Matrix page has scroll-to-bottom arrow button", 'id="scroll-detailed-bottom-btn"' in matrix_html))
    checks.append(("Matrix page has detailed rows end anchor", 'id="detailed-policy-end"' in matrix_html))
    checks.append(("Matrix page wires scroll arrow visibility", 'updateScrollToBottomVisibility' in matrix_html))
    checks.append(("Matrix page has result table body", 'id="matrix-tbody"' in matrix_html))
    checks.append(("Matrix page has comparison table body", 'id="compare-tbody"' in matrix_html))
    checks.append(("Matrix page calls matrix compare API", '/api/matrix/compare' in matrix_html))
    checks.append(("Copilot page posts to /draft", 'fetch("/draft"' in copilot_html))
    checks.append(("Copilot page loads auth bootstrap", '/static/auth.js' in copilot_html))
    checks.append(("Copilot body title links to matrix", '<a href="/matrix" class="hover:opacity-90 transition-opacity">Time-to-Therapy</a>' in copilot_html))
    checks.append(("Copilot page has mobile hamburger button", 'id="mobile-menu-button"' in copilot_html))
    checks.append(("Copilot page has mobile nav menu", 'id="mobile-nav-menu"' in copilot_html))
    checks.append(("Copilot page hides legacy bottom nav", 'id="mobile-bottom-nav" class="hidden' in copilot_html))
    checks.append(("Copilot page has history nav link", 'href="/history"' in copilot_html))
    checks.append(("Copilot page uses standardized desktop nav cluster", 'ml-auto items-center gap-8 font-headline text-sm font-semibold tracking-tight' in copilot_html))
    checks.append(("Copilot page removed gear icon", 'data-icon="settings"' not in copilot_html))
    checks.append(("Copilot page removed model label", 'Nemotron-3-Super-120B' not in copilot_html))
    checks.append(("Copilot page removed top header title", '<h1 class="text-xl font-bold tracking-tight text-teal-800 dark:text-teal-300 font-headline">Time-to-Therapy</h1>' not in copilot_html))
    checks.append(("Copilot page keeps title in body", '<h2 class="text-4xl font-headline font-extrabold tracking-tight text-teal-900"><a href="/matrix" class="hover:opacity-90 transition-opacity">Time-to-Therapy</a></h2>' in copilot_html))
    checks.append(("Copilot patient name uses placeholder", 'id="patient-name-input"' in copilot_html and 'placeholder="Enter patient name"' in copilot_html))
    checks.append(("Copilot diagnosis uses placeholder", 'id="diagnosis-input"' in copilot_html and 'placeholder="Enter diagnosis or indication"' in copilot_html))
    checks.append(("Copilot payer uses placeholder", 'id="payer-input"' in copilot_html and 'placeholder="Enter payer (e.g. Aetna)"' in copilot_html))
    checks.append(("Copilot medication uses placeholder", 'id="drug-input"' in copilot_html and 'placeholder="Enter medication name"' in copilot_html))
    checks.append(("Copilot page has context form", 'id="context-form"' in copilot_html))
    checks.append(("Copilot page has draft output area", 'id="draft-result-area"' in copilot_html))
    checks.append(("Copilot page has warning panel", 'id="warning-title"' in copilot_html))
    checks.append(("Copilot page has export button id", 'id="export-draft-btn"' in copilot_html))
    checks.append(("Copilot page includes jsPDF library", 'jspdf.umd.min.js' in copilot_html))
    checks.append(("Copilot page supports PDF export", 'exportDraftAsPdf' in copilot_html))
    checks.append(("Copilot page supports CSV export", 'exportDraftAsCsv' in copilot_html))
    checks.append(("History page fetches /api/history", 'fetch("/api/history"' in history_html))
    checks.append(("History page loads auth bootstrap", '/static/auth.js' in history_html))
    checks.append(("History page title links to matrix", '<a href="/matrix" class="hover:opacity-90 transition-opacity">Time-to-Therapy</a>' in history_html))
    checks.append(("History page has mobile hamburger button", 'id="mobile-menu-button"' in history_html))
    checks.append(("History page has mobile nav menu", 'id="mobile-nav-menu"' in history_html))
    checks.append(("History page hides legacy bottom nav", 'id="mobile-bottom-nav" class="hidden' in history_html))
    checks.append(("History page has matrix nav link", 'href="/matrix"' in history_html))
    checks.append(("History page has copilot nav link", 'href="/copilot"' in history_html))
    checks.append(("History page uses standardized desktop nav cluster", 'ml-auto items-center gap-8 font-headline text-sm font-semibold tracking-tight' in history_html))
    checks.append(("History page removed top search icon", 'data-icon="search">search</button>' not in history_html))
    checks.append(("History page FAB links to PA drafter", 'id="history-drafter-fab" href="/copilot"' in history_html))
    checks.append(("History page has list container", 'id="history-list"' in history_html))
    checks.append(("History page has detail rules area", 'id="detail-rules"' in history_html))
    checks.append(("History page has detail draft area", 'id="detail-draft"' in history_html))
    checks.append(("Test page content exists", "Test Static File" in test_html))

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
