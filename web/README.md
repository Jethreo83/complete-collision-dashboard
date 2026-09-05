# Complete Collision Dashboard — Frontend (`web/`)

React + TypeScript + Vite, mirroring `vls-dashboard/web`'s conventions
(same repo family). See root `README.md`/`docs/ADR-001-complete-collision.md`
for backend scope and the CCC ONE license constraint this UI respects
(it only reads/writes Complete Collision's own `collision`-schema data,
never CCC ONE).

## Run locally

```bash
# 1. Backend (repo root) — check for a stale exported DATABASE_URL first:
env | grep -i DATABASE   # unset DATABASE_URL / DATABASE_URL_UNPOOLED if unexpected
cp .env.example .env     # fill in the staging connection string
export DATABASE_URL=...  # or rely on the .env if nothing pre-exported
uvicorn app.api:app --reload --port 8002

# 2. Frontend
cd web
cp .env.example .env     # VITE_API_BASE_URL=http://localhost:8002
npm install
npm run dev              # http://localhost:5182 (strictPort — pinned, will NOT drift)
```

Dev server ports across this Neon project's sibling dashboards, so
bookmarks never silently point at the wrong app:

| App | Port |
|---|---|
| shell-dashboard | 5173 |
| vls-dashboard | 5180 |
| elektrica-dashboard | 5181 |
| **complete-collision-dashboard (this app)** | **5182** |

Backend API port: **8002** (not 8000 — collided with a concurrently
running sibling backend on this shared dev machine during this build).

## Auth (read before assuming this works like VLS)

`app/api.py` has **no authentication** yet — every route is
unauthenticated by design (see its module docstring). This frontend
does **not** do real Google OAuth; `src/auth.tsx` is a lightweight
"pick your own already-provisioned staff record" login (backed by
`GET /staff/{email}`), used only to attribute writes (`actor` field) —
**not a security boundary**. See the project handoff for the real-auth
open item.

## Screens

- **Jobs** (`/`) — list/filter/search repair orders (RO), with a
  "+ New Job" action.
- **New Job** (`/jobs/new`) — RO intake (`POST /jobs`); requires an
  existing `platform.person` id (this app cannot create new people —
  see `app/api.py`'s `JobIntakeCreateRequest` docstring).
- **Job Detail** (`/jobs/:roNumber`) — overview, financials, payment
  summary/history + record-payment form, itemized cost entries +
  add-cost form, status history, and the forward-only status
  transition button.
- **Look Up RO** (`/lookup`) — jump straight to a job by RO number.
- **PDR Settlement** (`/settlement`) — draft-only PDR Crew monthly
  settlement calculator preview. Never sends/finalizes anything.
- **Staff** (`/staff`, owner/manager only) — provision/deactivate staff
  users for existing `platform.person` rows.
