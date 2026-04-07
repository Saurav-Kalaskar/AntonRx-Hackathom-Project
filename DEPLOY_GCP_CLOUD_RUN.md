# Deploy Time-to-Therapy to Production (Google Cloud Run)

This project is best deployed as a single containerized web app (FastAPI + static frontend served by the same backend).

## Why Cloud Run for this project

- Works well with Python/FastAPI and your existing Docker workflow.
- You already have Google Cloud credits.
- Gives you a public HTTPS URL you can submit to Devpost.
- No need to split frontend/backend into separate platforms.

## Vercel/Netlify fit for your app

- `Vercel`/`Netlify` are great for static frontend, but not ideal for this backend because your app includes stateful auth/session flow and runtime RAG indexing.
- If you still want Vercel/Netlify, use them only for frontend and host backend elsewhere (Cloud Run/Render/Railway).
- Simplest and most reliable setup for demo + judging: one Cloud Run service.

## 1) Prerequisites

- Install Google Cloud CLI (`gcloud`) and authenticate:

```bash
gcloud auth login
gcloud auth application-default login
```

- Set your project:

```bash
gcloud config set project YOUR_GCP_PROJECT_ID
```

- Enable required services:

```bash
gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com
```

## 2) Deploy from repository root

Run this from the project root (where `Dockerfile` exists):

```bash
gcloud run deploy antorx-time-to-therapy \
  --source . \
  --region us-central1 \
  --allow-unauthenticated \
  --port 8080 \
  --set-env-vars AUTH_ENABLED=true,SESSION_COOKIE_SECURE=true,STRICT_LLM_MODE=true
```

After deployment, Cloud Run prints the public URL.

## 3) Set production env vars

Set secrets/env vars in Cloud Run service settings (Console or CLI):

- `NVIDIA_API_KEY` = your NVIDIA key
- `APP_SESSION_SECRET` = long random string (at least 32 chars)
- `ALLOWED_ORIGINS` = your Cloud Run URL (for example `https://antorx-time-to-therapy-xxxxx-uc.a.run.app`)

Optional Auth0 vars (if using Auth0 in production):

- `AUTH0_DOMAIN`
- `AUTH0_CLIENT_ID`
- `AUTH0_AUDIENCE`
- `AUTH0_CALLBACK_PATH=/auth/callback`
- `AUTH0_LOGOUT_RETURN_PATH=/login`

## 4) Auth0 production callback setup

In Auth0 application settings, add your Cloud Run URL:

- Allowed Callback URLs: `https://<cloud-run-url>/auth/callback`
- Allowed Logout URLs: `https://<cloud-run-url>/login`
- Allowed Web Origins: `https://<cloud-run-url>`

## 5) Important production note (history persistence)

The app currently stores draft history in local SQLite (`backend/history.db`). On Cloud Run, local filesystem is ephemeral, so history can reset on instance restart.

For a true production-grade persistent setup:

- Migrate history storage to Cloud SQL (PostgreSQL) or another managed DB.
- Keep current SQLite for hackathon demo if needed.

## 6) Quick smoke check after deploy

1. Open `https://<cloud-run-url>/login`
2. Sign up/sign in
3. Generate a draft in Copilot
4. Verify History and Matrix pages load
5. Validate `/health`

## 7) Devpost link strategy

- Submit Cloud Run URL as your working app link.
- Include one test login in private notes (if judges need quick access).
- Mention that backend and frontend are both live in one managed service.