# Repository Guidelines

## Project Structure & Module Organization
- `frontend/`: Vite + React + TypeScript client. Routes live in `src/routes`, shared UI in `src/components`, integration helpers in `src/integrations`, and global styles in `src/styles.css`.
- `backend/`: `main.py` exposes a FastAPI app for playlist summaries; keep request/response shapes stable for the frontend.
- `public/` (inside `frontend/`): static assets served by Vite; prefer importing assets via ES modules in `src/`.
- Utility scripts: `fetcher-v2.py` (ad-hoc Spotify fetching) and `playlist_artists.html` (standalone HTML) should remain isolated from the main app paths.

## Build, Test, and Development Commands
- Install frontend deps: `cd frontend && npm install`.
- Run the client: `npm run dev` (serves on port 3000 by default).
- Preview production build: `npm run serve` after `npm run build`.
- Type-check and build: `npm run build` (Vite build + `tsc`).
- Tests: `npm run test` (Vitest, JSDOM).
- Lint/format: `npm run lint`, `npm run format`, `npm run check` (formats + fixes).
- Backend dev: run `uvicorn backend.main:app --reload --port 8000` after installing FastAPI/uvicorn/requests in your Python env.

## Coding Style & Naming Conventions
- Frontend: Prettier (`semi: false`, `singleQuote: true`, `trailingComma: all`) and TanStack ESLint config. Use 2-space indent, PascalCase for React components, camelCase for vars/hooks, and `*.tsx` for UI files.
- Backend: Follow PEP 8; keep request models in `BaseModel` classes and avoid hard-coding secrets in source (use env vars or `.env`).
- Filenames: route files mirror paths (`src/routes/dashboard.tsx` -> `/dashboard`); co-locate component-specific styles or hooks near usage.

## Testing Guidelines
- Prefer component tests with Testing Library + Vitest; place alongside source as `*.test.tsx`.
- Mock network calls; avoid hitting the real Spotify API in unit tests.
- Aim for coverage on loaders, hooks, and API adapters; add regression tests for parsing and sorting logic.

## Commit & Pull Request Guidelines
- Use imperative, scoped commit messages (e.g., `feat: add playlist summary chart`, `fix(api): guard empty playlists`).
- Keep PRs focused; include a brief summary, testing notes (`npm run test`, `npm run lint`), and screenshots for UI changes.
- Link issues or TODOs when applicable and flag any breaking API changes between backend and frontend contracts.

## Security & Configuration Tips
- Store `CLIENT_ID`/`CLIENT_SECRET` in environment variables; never commit new secrets. For local dev, export them before running `uvicorn`.
- CORS is limited to `http://localhost:5173`; update carefully if adding deployments or alternate dev ports.
