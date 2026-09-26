# Backend Server
This is the code to expose the backend code like the FPGA interface and such to the frontend website.

## Endpoints
- /symbols?q=[query]&limit=[limit]
  - query: user can search either a symbol or stock
  - limit: the max number of results to return
  - result: output a list of the relevant results
- POST /auth/register and POST /auth/login with `{ "email", "password" }`
  - sets an HttpOnly `session` cookie for 14 days
- POST /auth/logout clears that cookie
- GET /auth/me returns the signed-in user
- POST /strategies with `{ "name", "document", "ir"?, "visibility"? }` saves a strategy for the signed-in user. `visibility` is `private` or `public` (default `private`). Returns `{ "id", "name", "visibility", "updated_at" }`
- GET /strategies lists strategies the signed-in user owns (`id`, `name`, `visibility`, `updated_at`)
- GET /strategies/{id} returns `document` and `ir` when the user owns the strategy or it is public, plus `owned`
- PUT /strategies/{id} lets the owner update `name`, `document`, `ir`, or `visibility` (`private` or `public`) and returns `{ "id", "name", "visibility", "updated_at" }`
- POST /strategies/{id}/copy creates a private copy owned by the signed-in user when they can view the original

## To Run
1. cd software/backend
2. python main.py