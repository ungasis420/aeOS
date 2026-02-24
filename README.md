# aeOS

**Offline-first PWA intelligence system**

aeOS is a browser-based intelligence layer that stores, links, and surfaces structured knowledge entirely within the browser using IndexedDB — no server required.

## Features

- **Offline-first** — Service Worker + IndexedDB means full functionality with zero connectivity
- **13 data schemas** — agents, sessions, memories, tasks, notes, thoughts, connections, tags, projects, events, goals, insights, settings
- **Dark-theme dashboard** — live stats across all collections, recent activity panels, system health
- **Modular architecture** — each intelligence domain is an isolated ES module
- **PWA-installable** — ships with `manifest.json` and a Workbox-powered service worker

## Tech Stack

| Layer | Technology |
|---|---|
| Build | Vite 5 |
| Storage | IndexedDB via Dexie.js v3 |
| Offline | Workbox (via vite-plugin-pwa) |
| UI | Vanilla JS + CSS custom properties |
| Styling | Dark theme design token system |

## Quick Start

```bash
npm install
npm run dev
```

Open [http://localhost:3000](http://localhost:3000).

## Data Schemas (13)

| # | Table | Purpose |
|---|---|---|
| 1 | `agents` | AI/automation agent configurations |
| 2 | `sessions` | Runtime session records |
| 3 | `memories` | Long-term memory with importance scoring |
| 4 | `tasks` | Priority task queue |
| 5 | `notes` | Free-form knowledge notes |
| 6 | `thoughts` | Stream-of-consciousness captures |
| 7 | `connections` | Directed relationship graph |
| 8 | `tags` | Shared taxonomy nodes |
| 9 | `projects` | Grouping containers |
| 10 | `events` | Timestamped timeline |
| 11 | `goals` | Goal tracking with progress |
| 12 | `insights` | Generated analysis with confidence scores |
| 13 | `settings` | System configuration key-value store |

## Project Structure

```
aeOS/
├── public/
│   ├── manifest.json          # PWA manifest
│   ├── service-worker.js      # Workbox offline SW
│   └── icons/                 # App icons (SVG + PNG)
├── src/
│   ├── db/
│   │   ├── schemas.js         # 13 Dexie schema definitions + metadata
│   │   └── index.js           # DB instance + initDatabase()
│   ├── modules/
│   │   ├── agents.js          # Agent CRUD + lifecycle
│   │   ├── memories.js        # Memory store + recall + pruning
│   │   ├── tasks.js           # Task queue + dequeue
│   │   ├── notes.js           # Note CRUD + search
│   │   ├── insights.js        # Insight recording + generation
│   │   └── projects.js        # Project containers + stats
│   ├── ui/
│   │   ├── router.js          # Client-side view router
│   │   ├── toast.js           # Notification system
│   │   └── views/
│   │       ├── dashboard.js   # Intelligence dashboard
│   │       ├── generic.js     # Generic list view for any table
│   │       └── settings.js    # Settings read/write view
│   ├── styles/
│   │   ├── variables.css      # Design token layer (dark theme)
│   │   └── main.css           # Global base styles
│   └── main.js                # Boot sequence + SW registration
├── scripts/
│   └── gen-icons.js           # PNG icon generation from SVG
├── index.html
├── vite.config.js
└── package.json
```

## Building

```bash
npm run build   # Outputs to dist/
npm run preview # Preview production build
```

## Generating Icons

```bash
npm install -D sharp
node scripts/gen-icons.js
```
