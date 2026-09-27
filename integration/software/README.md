# Mantis web app

React 19 + Vite + React Flow. Run `npm install` then `npm run dev` (port
`FRONTEND_PORT`, default 8002). In development Vite proxies the API paths to the
backend (`BACKEND_PORT`) so the session cookie stays first-party; see `devProxy.ts`.
A production build (`npm run build`) calls `VITE_API_URL` instead.

## Layout

```
src/
  main.tsx, App.tsx     entry point; session check and screen selection
  routes.ts             URL <-> screen (History API, no router library)
  api/                  typed client for every endpoint         -> api/README.md
  blocks/               block catalog, types, hardware limits
  flow/                 pure graph logic (no React)              -> flow/README.md
  features/
    auth/               sign in and create account
    portfolio/          strategy cards, visibility filter, JSON import and download
    editor/             the block editor                         -> editor/README.md
    assistant/          AI assistant panel and model choice
    discussions/        feed, composer, replies, likes, AI thread summaries
    backtest/           backtest report page
  components/           app shell, icons, popover dismissal
  lib/                  formatting and browser file helpers
  styles/               base, pages, discussions, editor, blocks
tests/                  node:test unit tests for the non-React modules
```

## Screens

| URL | Screen |
| --- | --- |
| `/` | My Strategies: open, download as JSON, import JSON, filter by visibility |
| `/strategy/new`, `/strategy/:id` | Editor |
| `/backtest/:id` | Backtest report |
| `/discussions` | Discussions feed |

## Scripts

| Command | Does |
| --- | --- |
| `npm run dev` | Dev server with API proxy |
| `npm test` | Unit tests (`node --test`, no browser needed) |
| `npm run build` | Type-check (app and tests) and production build |
| `npm run preview` | Serve the build with the same proxy |
