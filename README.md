# YT Analytics Studio

A work-in-progress web app for analyzing YouTube Studio exports, built with React and FastAPI. It began as two analysis notebooks (`youtubeAnaTest10.ipynb` and `YTRTool.ipynb`, not included in this repo) and is being grown into a fuller analytics platform. The current version holds one dataset in memory at a time.

## Architecture

```
YouTube-Tool/
├── apps/
│   ├── api/
│   │   ├── app.py                    ← FastAPI app: middleware, error handlers, router wiring
│   │   ├── config.py                 ← Settings from environment variables
│   │   ├── deps.py                   ← Service instances, loaded-dataset cache, request guards
│   │   ├── errors.py                 ← All failures returned as {"error": "..."}
│   │   ├── schemas.py                ← Request/response models (pydantic)
│   │   ├── routers/                  ← system, dashboard, analysis, researcher, clients, client_data
│   │   ├── ingest/                   ← export importer: cell parsers, report-type registry, importer
│   │   ├── intake.py                 ← safe upload handling (size cap, hashing)
│   │   ├── security.py               ← Origin/Host guards, upload limits, log redaction
│   │   ├── audit/                    ← the audit engine: findings with evidence and caveats
│   │   ├── youtube/                  ← batched YouTube client, 30-day store, quota count, expiry alerts
│   │   ├── synthetic/                ← seeded fake channels in Studio export format
│   │   ├── db/                       ← SQLAlchemy models, metric catalog + seed data, session
│   │   ├── migrations/               ← Alembic migrations (schema history)
│   │   ├── requirements.txt
│   │   ├── requirements-dev.txt
│   │   ├── .env.example
│   │   ├── services/
│   │   │   ├── client_data.py        ← a client's stored export read back as a table
│   │   │   ├── analytics_service.py  ← DataService, HeatmapService, KeywordService,
│   │   │   │                            DurationService, DescriptionService
│   │   │   └── researcher_service.py ← ResearcherService (search, autocomplete, tag analysis)
│   │   └── tests/                    ← pytest suite
│   └── web/
│       ├── index.html
│       ├── package.json
│       ├── vite.config.js
│       └── src/
│           ├── App.jsx               ← Router + layout shell
│           ├── main.jsx
│           ├── index.css             ← Global styles, Tailwind theme tokens
│           ├── hooks/
│           │   └── useApi.js         ← Axios wrapper (get/post/upload + loading/error)
│           ├── components/
│           │   ├── Sidebar.jsx       ← Fixed sidebar navigation
│           │   ├── DataTable.jsx     ← Sortable + drag-to-reorder columns + thumbnails
│           │   └── ui.jsx            ← MetricCard, TagBar, Skeleton, EmptyState, Badge, Select
│           └── pages/
│               ├── Dashboard.jsx     ← File upload, KPI cards, duration chart, main table
│               ├── Heatmap.jsx       ← Calendar heatmap + day-of-week bar charts
│               ├── Keywords.jsx      ← Weighted tags + top vs bottom comparison
│               ├── Descriptions.jsx  ← Per-video description analysis with filters
│               ├── Researcher.jsx    ← Search, autocomplete ideas, competitor tags
│               └── Settings.jsx      ← API key management + system status
├── docs/concepts/                    ← design notes (start with data-model.md)
├── docker-compose.yml                ← local Postgres
├── .github/workflows/ci.yml          ← lint, tests (with Postgres), audits, frontend build
└── pyproject.toml                    ← ruff, pytest and coverage configuration
```

## API Endpoints

| Method | Route | Description |
|--------|-------|-------------|
| GET    | `/api/settings`                  | Check API key status |
| POST   | `/api/settings`                  | Save API key (runtime) |
| POST   | `/api/dashboard/upload`          | Upload Excel/CSV, enrich with YT API |
| GET    | `/api/dashboard`                 | Return cached dataset |
| GET    | `/api/heatmap?metric=Views`      | Calendar + day-of-week data |
| GET    | `/api/keywords/weighted`         | View-weighted tag scores |
| GET    | `/api/keywords/top-vs-bottom`    | Top 20% vs bottom 20% tag comparison |
| GET    | `/api/duration?metric=Views`     | Duration bucket analysis |
| GET    | `/api/descriptions`              | Per-video description data |
| POST   | `/api/researcher/search`         | YouTube search + tag analysis |
| GET    | `/api/researcher/ideas?topic=X`  | YouTube autocomplete suggestions |
| GET    | `/api/health`                    | Health check |
| POST   | `/api/clients`                   | Create a client |
| GET    | `/api/clients`                   | List clients with upload and video counts |
| GET    | `/api/clients/{id}`              | One client |
| DELETE | `/api/clients/{id}`              | Erase a client and everything it owns |
| POST   | `/api/clients/{id}/uploads`      | Import a Studio export (idempotent per file) |
| GET    | `/api/clients/{id}/uploads`      | List a client's uploads |
| PUT    | `/api/clients/{id}/uploads/{upload_id}/period` | Confirm the date range an upload covers |
| POST   | `/api/clients/{id}/enrich`       | Fetch public YouTube details (tags, descriptions, thumbnails) |
| DELETE | `/api/clients/{id}/public-data`  | Erase a client's stored YouTube details (the export is kept) |
| GET    | `/api/clients/{id}/audit`        | Audit findings (standouts, rhythm, Shorts vs long-form, click-through) |
| GET    | `/api/clients/{id}/audit/report` | The audit as a self-contained HTML download |
| GET    | `/api/quota`                     | YouTube quota used and left today (our own estimate) |
| GET    | `/api/public-data/alerts`        | Clients whose stored YouTube data expired or expires within 7 days |

Per-client analysis reads the stored export from Postgres. Each of these also exists under
`/api/clients/{id}/...` (`dashboard`, `heatmap`, `duration`, `keywords/weighted`, `keywords/top-vs-bottom`,
`descriptions`), with an optional `?upload_id=` (default: the client's latest upload). The UI uses only these.
The unprefixed routes in the table (`/api/dashboard`, `/api/heatmap`, ...) are the older single in-memory dataset
and will be removed. Keywords and descriptions are empty until YouTube API data is stored. Interactive docs: `/docs`.

---

## Setup & Running

The app is two processes: the FastAPI server (port 5000) and the Vite dev server for the UI (port 5173). Run both, each in its own terminal. The API has no page of its own, so opening `/` on port 5000 shows a 404; open http://localhost:5000/docs for the interactive API documentation instead.

### 1. Database

Postgres runs in Docker (start Docker Desktop first):

```bash
docker compose up -d                 # from the repository root
cd apps/api
alembic upgrade head                 # create the tables
python -m db sync-catalog            # load the metric catalog
python -m synthetic seed             # optional: three fake channels to explore
python -m youtube purge              # delete YouTube data older than 30 days (run daily)
```

The `/api/clients` routes use it (create a client, upload exports, erase it). How the database is designed and
why: [docs/concepts/data-model.md](docs/concepts/data-model.md); how exports are imported:
[docs/concepts/importing.md](docs/concepts/importing.md); fake demo data:
[docs/concepts/synthetic-data.md](docs/concepts/synthetic-data.md); the YouTube API and its 30-day rule:
[docs/concepts/youtube-api.md](docs/concepts/youtube-api.md); the audit and its statistics:
[docs/concepts/audit.md](docs/concepts/audit.md).

### 2. Backend

```bash
cd apps/api

# Create & activate virtual environment
python -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env and add your YOUTUBE_API_KEY

# Run the API (add DEBUG=true to .env for auto-reload while developing)
python app.py
# → Runs on http://localhost:5000, API docs at http://localhost:5000/docs
```

### 3. Frontend

```bash
cd apps/web

npm install
npm run dev
# → Runs on http://localhost:5173
```

Open **http://localhost:5173** in your browser.

---

## Development

From the repository root, with the backend virtual environment active:

```bash
pip install -r apps/api/requirements-dev.txt

ruff check .                                    # lint
pytest --cov=apps/api --cov-report=term-missing   # tests (never call the real YouTube API)
```

Database tests need Postgres (`docker compose up -d`); without it they are skipped locally. They use a
throw-away `ytstudio_test` database built from the real migrations and never touch your development data.
After changing `db/models.py`, create a migration with `alembic revision --autogenerate -m "message"` (from
`apps/api`), read it, and commit it; a test fails if the models and migrations disagree.

GitHub Actions runs the same lint and test steps, plus a frontend production build and `npm audit`, on every pull request.

---

## Workflow

1. **Sidebar** → Create a client (or pick one; `python -m synthetic seed` adds three fake ones)
2. **Dashboard** → Upload that client's YouTube Studio `.xlsx` or `.csv` export (Advanced mode, "Table data")
3. **Dashboard** → Browse the sortable table with thumbnails; drag column headers to reorder
4. **Heatmap** → Switch metrics via the dropdown; view month-by-month and day-of-week charts
5. **Keywords** → Explore view-weighted tag scores and the top vs bottom performer comparison
6. **Descriptions** → Search/filter descriptions, see char counts, links, timestamps, hashtags
7. **Audit** → Open it for any client: findings with evidence, strength and caveats
8. **Researcher** → Type any query; autocomplete ideas appear as you type; search returns videos + competitor tag scores

---

## Excel File Format

Your YouTube Studio export should have:
- **Column 1**: Video ID (11-character YouTube IDs)
- **Video publish time**: datetime column for heatmap
- **Duration**: in seconds (will be auto-formatted to m:ss)
- Numeric columns (Views, Impressions, etc.) and percentage columns (CTR, etc.) are auto-detected
- A `Total` footer row is detected and displayed as a pinned row

---

## Feature Mapping from Notebooks

The original notebooks are not included in this repository; this table records where each of their features now lives.

| Notebook Feature | Web App Location |
|-----------------|-----------------|
| `create_html_table()` sortable/drag table | Dashboard → Video Performance Table |
| `display_calendar_heatmap()` | Heatmap → Monthly Calendar |
| Day-of-week bar charts | Heatmap → Day-of-week panels |
| `analyze_duration_vs_metric()` | Dashboard → Duration Bucket chart |
| `create_video_details_table()` | Descriptions page |
| `analyze_video_keywords_top_vs_bottom()` | Keywords → Top vs Bottom tab |
| `analyze_weighted_tags()` (YTRTool) | Keywords → Weighted Tags tab |
| `youtube_search()` | Researcher → Search |
| `get_video_ideas()` autocomplete | Researcher → query autocomplete dropdown |
| `display_videos_html()` | Researcher → Videos grid |
