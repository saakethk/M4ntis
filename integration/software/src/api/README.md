# API client

One module per backend resource (`auth`, `strategies`, `compile`, `backtests`,
`discussions`, `symbols`, `assistant`). Each function returns typed data in the app's
camelCase shape and validates the response, throwing a short user-facing message if
the server sends something unexpected.

`http.ts` holds the shared pieces: `API_BASE` (from `apiBase.ts`), `requestJson` /
`postJson` / `putJson` (always send the session cookie), `ApiError` (carries the
status and body, and uses the server's `detail` as its message), and small readers
(`record`, `list`, `str`, `num`, `id`, ...).

`apiBase.ts` picks where requests go: the page origin in development (Vite proxies
it), otherwise `VITE_API_URL` with local hostnames aligned to the page's host so the
`SameSite=Lax` cookie is sent.
