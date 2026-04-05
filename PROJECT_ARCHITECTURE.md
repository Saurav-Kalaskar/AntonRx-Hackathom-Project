# Time-to-Therapy Prior Authorization Copilot
## Project Architecture Document

### Overview
The Time-to-Therapy Prior Authorization Copilot is a deterministic, enterprise-grade Medical Benefit Drug Policy Tracker engineered to solve an administrative healthcare bottleneck. It allows market access analysts to visualize coverage rules side-by-side (Matrix) and autonomously draft Prior Authorization appeal letters (Copilot) with Explainable AI attribution.

### Core Purpose
- **Problem Solved**: Administrative delays in prior authorization processes for specialty medications
- **Solution**: AI-powered system that provides real-time coverage comparisons and automates PA letter generation
- **Target Users**: Market access analysts, healthcare administrators, clinical pharmacists
- **Key Value Proposition**: Reduces "Time-to-Therapy" by providing instant access to payer policies and automating documentation

### System Architecture

#### 1. Technology Stack
- **Frontend**: Static HTML/CSS/JavaScript with Tailwind CSS
- **Backend**: Python/FastAPI API server
- **Database**: SQLite for persistence (history.db)
- **Vector Database**: Qdrant (in-memory) for RAG implementation
- **Embedding Model**: NVIDIA NIM nv-embedqa-e5-v5 (via API, no local downloads)
- **LLM**: Nvidia Nemotron-3-Super-120B (via NVIDIA API)
- **Document Processing**: PyPDF2 for PDF text extraction

#### 2. Component Breakdown

##### Frontend Components
- **Matrix View** (`site/public/matrix.html`): Cross-payer coverage comparison table
- **Copilot View** (`site/public/copilot.html`): AI-powered PA letter drafting interface
- **History View** (`site/public/history.html`): PA request history tracking
- **Shared Elements**:
  - TopAppBar with navigation
  - BottomNavBar for mobile navigation
  - Consistent design system using Tailwind CSS
  - Custom JavaScript for API interactions and DOM manipulation

##### Backend Components
- **API Server** (`backend/main.py`): FastAPI application serving REST endpoints
- **PA Drafter** (`backend/generator/drafter.py`): LLM-powered PA letter generation
- **RAG Engine** (`backend/pipeline/rag_engine.py`): Vector search over policy documents
- **Document Processor** (`backend/pipeline/document_processor.py`): PDF/TXT text extraction
- **Ingestion Pipeline** (`backend/pipeline/ingestion.py`): Data validation and processing

##### Data Storage
- **SQLite Database** (`history.db`): Stores PA draft history
- **Vector Database** (Qdrant in-memory): Stores embedded policy document chunks
- **Policy Documents**: Stored in `backend/pipeline/documents/` directory

#### 3. Data Flow

##### PA Letter Generation Flow
1. User enters patient context (name, diagnosis, medication, payer) in Copilot interface
2. Frontend sends POST request to `/draft` endpoint with patient context
3. Backend:
   - Creates query from diagnosis + medication
   - Uses RAG engine to search vector database for relevant policy sections
   - Initializes PADrafter with payer name, patient context, and retrieved rules
   - PADrafter constructs prompt for LLM using retrieved rules as context
   - LLM (Nemotron-3-Super-120b) generates PA letter draft
   - Draft saved to SQLite history database
   - Draft returned to frontend for display

##### Matrix Data Flow
1. Frontend loads matrix.html
2. JavaScript fetches data from `/api/matrix` endpoint on page load
3. Backend returns hardcoded matrix data (payer, medication, status, match score)
4. Frontend renders table with status-based styling (color-coded badges)

##### History Data Flow
1. Frontend loads history.html
2. JavaScript fetches data from `/api/history` endpoint on page load
3. Backend queries SQLite database for all PA draft records
4. Returns JSON array of history entries
5. Frontend renders history cards with click-to-expand detail view

#### 4. Key Features Implementation

##### Deterministic Policy Processing
- **Exclusion Filtering**: Heuristic patterns drop Medicare/Medicaid/standard pharmacy benefit data
- **Schema Validation**: Strict validation against medical benefit drug policy JSON schema
- **Dead-Letter Queue**: Failed validations sent to DLQ for manual review
- **Source Attribution**: All AI-generated content includes citations to source documents

##### Explainable AI Attribution
- **Retrieved Context Display**: Shows which policy sections were used for generation
- **Citation Format**: [Source, Page X, Para Y]: [text] format in RAG engine
- **Confidence Indicators**: Match scores in matrix view (0-1 scale converted to percentage)

##### Design System Compliance
- **Color Palette**: 
  - Background: Crisp whites (#f7f9fb)
  - Primary: Soft teals (#00685d, #71f8e4)
  - Secondary: Slate blues (#191c1e, #d5e3fc)
  - Alerts: Amber (#ffbf00) and soft coral (#f88379) for blockers/warnings
- **Typography**: 
  - Headlines: Manrope
  - Body: Inter
- **Components**: shadcn-ui inspired (Cards, Tables, Badges, Buttons)
- **Layout**: Information dense with minimized cognitive load
- **Aesthetics**: Rounded boundaries (`rounded-lg` or `md`), glass-panel effects

#### 5. API Endpoints

##### POST `/draft`
- **Description**: Generate Prior Authorization draft letter
- **Request Body**:
  ```json
  {
    "payer_name": "string",
    "patient_context": {
      "patient_name": "string",
      "diagnosis": "string", 
      "medication": "string"
    },
    "retrieved_rules": []
  }
  ```
- **Response**: 
  ```json
  {
    "draft": "string",
    "retrieved_rules": [
      {
        "text": "string",
        "source": "string",
        "chunk_index": "integer",
        "score": "float (0-1)"
      }
    ],
    "payer_name": "string"
  }
  ```

##### GET `/api/history`
- **Description**: Retrieve PA draft history
- **Response**: 
  ```json
  {
    "history": [
      {
        "id": "integer",
        "payer_name": "string",
        "patient_context": "object",
        "draft_content": "string",
        "retrieved_rules": "array",
        "timestamp": "string"
      }
    ]
  }
  ```

##### GET `/api/matrix`
- **Description**: Get coverage matrix data
- **Response**: 
  ```json
  {
    "matrix": [
      {
        "payer": "string",
        "medication": "string", 
        "indication": "string",
        "status": "string",
        "requirements": "string",
        "score": "number (0-1)"
      }
    ]
  }
  ```

##### GET `/health`
- **Description**: Health check endpoint
- **Response**: 
  ```json
  {
    "status": "string",
    "rag_ready": "boolean",
    "model": "string"
  }
  ```

#### 6. Security & Compliance Considerations
- **Data Privacy**: No PHI stored permanently; demo data only
- **API Security**: CORS enabled for local development only
- **Key Management**: NVIDIA API key configured via environment
- **Audit Trail**: All PA drafts saved with timestamps
- **Explainability**: Source citations provided for all AI-generated content

#### 7. Deployment & Setup
- **Local Development**: 
  - Backend: `uvicorn backend.main:app --host 0.0.0.0 --port 8005`
  - Frontend: Accessible via `/site/public/` path on backend
- **Dependencies**: 
  - Python: fastapi, uvicorn, openai, qdrant-client, sentence-transformers
  - Frontend: Tailwind CSS (via CDN)
- **Environment Variables**:
  - `FASTEMBED_CACHE_PATH`: "./fastembed_cache"
  - `HF_HUB_ENABLE_HF_TRANSFER`: "0"
  - `HF_HUB_DISABLE_FAST_DOWNLOAD`: "1"
  - `NVIDIA_API_KEY`: "your-nvidia-api-key-here"

#### 8. Limitations & Future Improvements
**Current Limitations**:
- Matrix data is hardcoded (not real-time)
- Vector database is in-memory (not persistent)
- LLM API key requires manual configuration
- No user authentication/authorization
- Limited policy document processing (basic text extraction)
- Mock fallback when LLM API unavailable

**Planned Enhancements**:
- Connect to real payer APIs for live matrix data
- Persistent vector database implementation
- Secure key management (environment variables/vault)
- User authentication and role-based access
- Advanced NLP for better policy data extraction
- Feedback loop to improve AI accuracy
- Multi-language support
- Integration with EHR/PM systems

### Conclusion
The Time-to-Therapy Prior Authorization Copilot demonstrates a viable approach to reducing administrative burden in healthcare prior authorization processes. By combining deterministic policy processing with AI-powered document generation, the system provides market access analysts with both visibility into coverage rules and automation of documentation tasks. The architecture follows modern microservices principles with clear separation of concerns between frontend presentation, backend logic, and AI/ML components.

The system is designed to be extensible, allowing for integration with real healthcare data sources and enterprise systems while maintaining the core value proposition of reducing Time-to-Therapy through intelligent automation and explainable AI.