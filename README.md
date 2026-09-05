# Puma Energy Pakistan — Document Management System

Enterprise DMS: Microsoft Entra ID authentication + SharePoint storage (Phase 2)
+ PostgreSQL metadata/RBAC + OCR + full-text search + version control + audit
trail. See the full specification for the complete vision.

## Status: Phases 4-6 — OCR, Search, Audit Logging & Dashboard ✅

Built and genuinely tested (not mocked — neither Tesseract nor PostgreSQL
full-text search has an external network dependency, so these were run for
real):

**Phase 4 — OCR** (`app/ocr/`)
- Real Tesseract 5.3.4 extraction, abstracted behind an `OCRProvider`
  interface (Section 13's "should later be replaced with Azure AI Document
  Intelligence" — the swap point is exactly this interface)
- Text-layer PDFs get direct extraction via PyMuPDF (fast, exact); scanned/
  image-only PDFs get rasterized per-page and OCR'd; raw images go straight
  to Tesseract
- Runs via FastAPI `BackgroundTasks` after upload/new-version commits —
  the user's request never waits on it
- `/ocr/status` (monitor pending/failed) and `/ocr/{id}/retry` (Section 13's
  admin controls)

**Phase 5 — Search** (`app/search/`)
- Real PostgreSQL full-text search (`to_tsvector`/`plainto_tsquery`) across
  filename, document number, description, and OCR-extracted text — no
  extra migration needed, built as an inline tsvector expression
- Filters: folder, document type, date range, uploader, tags, OCR status
- **Known tokenization behavior** (not a bug, confirmed by direct testing):
  PostgreSQL's `english` search config splits punctuated numbers like
  `450,000` into separate lexemes (`450`, `000`). Searching `450,000`
  matches; searching `450000` (no comma) does not, because the query itself
  gets tokenized as one lexeme while the indexed text was tokenized as two.
  Worth knowing before someone reports this as a bug.

**Phase 6 — Audit logging + dashboard** (`app/audit/`, `app/api/`)
- `AuditLog` model covering the full Section 19 action list, written via a
  `log_audit()` helper that runs in its own independent transaction (a
  logging failure never blocks the real action; an audit FAILURE entry
  survives even if the main request's transaction rolls back)
- Wired into login/logout, upload, download, delete, restore, permanent-
  delete, version-create, folder-create/archive, department-create,
  role-change, and OCR completion/failure
- `/audit-logs` (filterable by user/department/action/document/date
  range/result) and `/dashboard` (org-wide for Super Admin, department-
  scoped for everyone else)

**Known gap, flagged honestly**: audit logging currently covers
*successful* actions and a few explicit failure paths (login failures), but
does **not** yet log FAILURE entries for ordinary RBAC denials (403s) across
every endpoint — Section 19's "Result: SUCCESS/FAILURE" tracking is
therefore partial. Retrofitting every 403 path with audit calls is
straightforward but wasn't done in this pass; worth doing before this goes
in front of a security review.

**End-to-end proof**: uploaded a real PDF with real embedded text, watched
OCR complete asynchronously, confirmed full-text search matched terms that
existed ONLY in the OCR-extracted text (not the filename or metadata) —
proving the whole pipeline works together, not just each piece in
isolation. This is now a permanent test
(`tests/test_ocr_search_integration.py`), not just a one-off script.

## Status: Phase 3 — Document Management ✅ (core lifecycle, no OCR/search yet)

Built and tested on top of Phase 2:

- `Document`, `DocumentVersion`, `Tag` models (Section 11 metadata fields,
  Section 17 version control, Section 28 database design)
- `/documents` API: upload (with file-type allowlist, size limit, and a
  magic-byte content check per Section 26's "never trust the extension
  alone"), metadata retrieval, download (streamed), new-version upload,
  version history listing
- Recycle bin lifecycle (Section 18): soft-delete / restore / permanent-
  delete, with PostgreSQL as authoritative and the SharePoint recycle-bin
  call as a best-effort *effect* — exactly the Step-2 architecture decision
  in practice. A failed Graph call during delete/restore doesn't corrupt DB
  state; it's silently accepted for now (proper handling — retry queue,
  audit log entry — is Phase 6 territory)
- Every document endpoint checks RBAC against the document's own
  `department_id` (denormalized onto the row), proven with dedicated tests
  in `test_documents_rbac.py`
- A real false-positive caught and diagnosed during manual testing: an
  ad-hoc script reused one HTTP client's cookie jar across two different
  forged user sessions, and the server's own `Set-Cookie` response left two
  `session` cookies with different domain attributes both in the jar —
  which one wins isn't guaranteed. Re-tested with an isolated client per
  identity and confirmed the RBAC enforcement itself was correct all along;
  added `test_documents_rbac.py` so this class of scenario is now pinned
  down by a real automated test instead of an ad-hoc script.

**Not yet built:** OCR processing (Phase 4), full-text/OCR search (Phase 5),
audit logging + admin dashboard (Phase 6), version *restore* to a previous
version's content (the Graph call for this — `restore_item` — is written
but still unverified against a real tenant — see the Phase 2 update below;
folder creation and login *have* since been verified live, restore hasn't),
and files over 4MB (needs Graph's chunked upload-session API).

## Status: Phase 2 — SharePoint Integration ✅ (verified against a real Entra ID tenant + live SharePoint site)

Built and tested on top of Phase 1:

- `app/sharepoint/client.py` — async Microsoft Graph client, **app-only**
  auth (client credentials, `Sites.Selected` scope — see the Step-2
  architecture decision above for why over delegated auth)
- Typed errors (`SharePointAuthError`, `SharePointNotFoundError`,
  `SharePointConflictError`, `SharePointRateLimitedError`) so calling code
  and future audit logging can distinguish failure modes
- `Folder` model + `/folders` API — one-way sync (DMS creates the
  SharePoint folder immediately after the RBAC check passes; there's no
  reverse sync job, per the Step-2 decision)
- `Department.sharepoint_item_id` — each department's root SharePoint
  folder is created at department-creation time; if that Graph call fails,
  the department row is never created (no orphaned "department with
  nowhere to store documents")
- 9 unit tests against a **mocked** Graph transport (`httpx.MockTransport`)
  proving request construction and error-code mapping are correct, plus a
  live end-to-end run through the real FastAPI app + real RBAC + real
  Postgres, with only the Graph HTTP layer mocked

### ✅ Verified end-to-end against a real tenant (2026-09-05)

The original build sandbox had no network access to `login.microsoftonline.com`
or `graph.microsoft.com`, so none of this had been proven against a live
tenant. That gap is now closed:

- Registered a real app (`DMS Portal - Service Account`) in Puma Pakistan's
  Entra ID tenant, added the `Web` redirect URI, created a client secret,
  and — the step that actually matters — added the **`Sites.Selected`**
  **application** permission and granted admin consent for it (an earlier
  attempt had `Files.ReadWrite.All` sitting ungranted instead; the token's
  `roles` claim came back empty until `Sites.Selected` was properly added
  and consented — worth knowing if this ever needs redoing).
- Created a real SharePoint team site (`https://pumapk.sharepoint.com/sites/PumaDMS`)
  and granted the app `write` access to just that one site via
  `POST /sites/{site-id}/permissions` (Graph Explorer, delegated
  `Sites.FullControl.All`, scoped to the admin's own session — there's no
  portal UI for this specific call).
- Ran the full OAuth2 login flow for real: `/auth/login` → Microsoft's
  actual login page → `/auth/callback` → a real DMS session cookie. (Hit
  and fixed an `Invalid OAuth state` error along the way — caused by
  testing `/auth/login` on `127.0.0.1` while the registered redirect URI
  was `localhost`; browsers treat those as different origins, so the
  session cookie carrying the OAuth `state` never made it back. Use
  whichever host is in `ENTRA_REDIRECT_URI` consistently.)
- Bootstrapped the first Super Admin via the manual SQL step (see below),
  then called `POST /departments` for real and confirmed a **"Finance"
  folder actually appeared** in the SharePoint document library —
  `departments.sharepoint_item_id` now holds a real Graph drive-item ID,
  not a mock.
- One operational gotcha worth flagging: `SharePointGraphClient` is a
  process-lifetime singleton (`app/sharepoint/dependencies.py`) wrapping
  one `msal.ConfidentialClientApplication`. MSAL caches the app-only token
  in memory and only refreshes it on expiry — it has no way to know a
  permission was newly consented. If you grant/change Graph API
  permissions while the server is already running, you'll keep getting
  `SharePointAuthError` / Graph `401`s from the *old* cached token until
  you **restart the process**, even though the permission fix is correct.

**Still not verified / not built:**
- Only files **under 4MB** are supported for upload right now
  (`upload_small_file`) — larger files need Graph's chunked upload-session
  API, not yet implemented.
- Version *restore* to a previous version's content (`restore_item`) is
  written but still unexercised against the live tenant.

## Status: Phase 1 — Foundation ✅

Built, tested, and verified end-to-end against a real PostgreSQL instance:

- Project structure (`backend/app/{auth,users,roles,departments,...}`)
- Core config (env-var driven, no hard-coded secrets)
- Database layer (async SQLAlchemy + Alembic migrations)
- Models: `Department` (admin-manageable, never hard-coded), `Role` /
  `Permission` (fixed 4-role catalog: Super Admin, Department Admin,
  Department User, Read-Only, each with fine-grained permissions),
  `User` (mirrors Entra ID identity — no password storage), `UserRole`
  (department-scoped role assignment — one user can hold different roles in
  different departments simultaneously)
- **Server-side RBAC enforcement** (`app/auth/rbac.py`) — the piece the spec
  calls non-negotiable. Verified with a full pytest suite proving the exact
  Section 37 test matrix (Finance→Finance ALLOW, Finance→HR DENY, HR→Finance
  DENY, Super Admin→anything ALLOW), plus a live HTTP smoke test confirming a
  Department User gets a real `403` trying to manage departments.
- Microsoft Entra ID OAuth2 login flow (backend-for-frontend pattern — Entra
  tokens never reach the browser, only FastAPI's own signed session cookie
  does)
- Department management API (Super Admin: create/rename/disable/reactivate)
- User + department-scoped role assignment API

**Not yet built:** SharePoint integration (Phase 2), folders/documents/OCR/
search (Phases 3–5), audit logging + admin dashboard (Phase 6), the Next.js
frontend, and AI/workflow features (Phase 7). Per the spec's own phasing,
these come next, in order — SharePoint is next since that's what was
requested.

## Running it locally

### 1. Database

```bash
# You need PostgreSQL 16+ running. Then:
createuser puma_dms --pwprompt   # set password to match .env
createdb puma_dms -O puma_dms
```

### 2. Backend

```bash
cd backend
cp .env.example .env
# Edit .env: set APP_SECRET_KEY, DATABASE_URL, DATABASE_URL_SYNC, and the
# ENTRA_* values from your Entra ID App Registration (Azure Portal ->
# App registrations -> New registration -> note Tenant ID, Client ID; then
# Certificates & secrets -> New client secret).

# System dependency for OCR (Phase 4) — install via your OS package manager:
#   Ubuntu/Debian: apt-get install tesseract-ocr
#   macOS: brew install tesseract
pip install -r requirements.txt

python -m alembic upgrade head    # create tables
python -m app.core.seed            # seed the 4 roles + baseline permissions

uvicorn app.main:app --reload      # http://localhost:8000
```

Visit `http://localhost:8000/docs` for interactive API docs (Swagger UI).

### 3. First login

The very first person to sign in via `/auth/login` is provisioned as a DMS
user with **no roles at all** — role/department assignment is a deliberate
separate admin action (spec Section 7), so a brand-new account can't
self-grant access. You'll need to manually insert the first Super Admin's
`user_roles` row directly in the database once, after their first login:

```sql
INSERT INTO user_roles (id, user_id, role_id, department_id, created_at, updated_at)
SELECT gen_random_uuid(), '<their user id from the users table>', roles.id, NULL, now(), now()
FROM roles WHERE name = 'super_admin';
```

After that, they can manage all further role assignments through the API.

### 4. Tests

```bash
cd backend
createdb puma_dms_test -O puma_dms   # separate from the dev DB — see .env.test
pytest tests/ -v
```

## Project structure

See `docs/` (added as later phases build it out) for architecture, ERD, and
API documentation. For now, the structure mirrors spec Section 36:

```
puma-dms/
├── backend/
│   ├── app/
│   │   ├── core/        # config, database, shared model mixins, RBAC seed
│   │   ├── auth/         # Entra ID OAuth2 flow + RBAC enforcement
│   │   ├── users/        # user listing, role assignment
│   │   ├── roles/        # Role, Permission, UserRole models
│   │   ├── departments/  # department CRUD (Super Admin only)
│   │   ├── folders/      # Phase 2 — folder CRUD + SharePoint one-way sync
│   │   ├── documents/    # Phase 3 — upload/download/versions/recycle bin
│   │   ├── search/       # Phase 5 — full-text search (to_tsvector)
│   │   ├── ocr/          # Phase 4 — real Tesseract extraction + retry
│   │   ├── sharepoint/   # Phase 2 — Graph client, app-only auth
│   │   └── audit/        # Phase 6 — audit log model + query API
│   ├── migrations/       # Alembic
│   └── tests/
├── frontend/             # Next.js — not yet built
├── docker/
└── docs/
```
