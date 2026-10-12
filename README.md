# YT Analytics Studio

A work-in-progress web app for analyzing YouTube Studio exports, built with React and Flask. It began as two analysis notebooks (`youtubeAnaTest10.ipynb` and `YTRTool.ipynb`, not included in this repo) and is being grown into a fuller analytics platform. The current version holds one dataset in memory at a time.

## Architecture

```
YouTube-Tool/
├── apps/
│   ├── api/
│   │   ├── app.py                    ← Flask REST API (12 endpoints)
│   │   ├── requirements.txt
│   │   ├── requirements-dev.txt
│   │   ├── .env.example
│   │   ├── services/
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
├── .github/workflows/ci.yml          ← lint, tests, frontend build
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

---

## Setup & Running

The app is two processes: the Flask API (port 5000) and the Vite dev server for the UI (port 5173). Run both, each in its own terminal. The API has no page of its own, so opening port 5000 in a browser shows a 404.

### 1. Backend

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

# Run the API
python app.py
# → Runs on http://localhost:5000
```

### 2. Frontend

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

GitHub Actions runs the same lint and test steps, plus a frontend production build and `npm audit`, on every pull request.

---

## Workflow

1. **Settings** → Enter your YouTube Data API key
2. **Dashboard** → Upload your YouTube Studio `.xlsx` export (Advanced mode, "Table data")
3. **Dashboard** → Browse the sortable table with thumbnails; drag column headers to reorder
4. **Heatmap** → Switch metrics via the dropdown; view month-by-month and day-of-week charts
5. **Keywords** → Explore view-weighted tag scores and the top vs bottom performer comparison
6. **Descriptions** → Search/filter descriptions, see char counts, links, timestamps, hashtags
7. **Researcher** → Type any query; autocomplete ideas appear as you type; search returns videos + competitor tag scores

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
