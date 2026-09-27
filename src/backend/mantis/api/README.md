# HTTP layer

Turns HTTP requests into service calls and service results into JSON.

- `app.py`: `create_app()` adds CORS (any localhost origin, with credentials) and the
  error handlers, then includes every router. `MantisError` subclasses become
  `{"detail"}` with their `status_code`; any `psycopg.Error` becomes 503; a rejected
  compile becomes 400 with diagnostics.
- `deps.py`: `CurrentUser` (reads the `session` cookie, 401 without it) and the
  cookie settings (HttpOnly, SameSite=Lax, host-only).
- `schemas.py`: request bodies. Most forbid unknown fields. `GraphBody` accepts raw
  React Flow nodes and edges and keeps only ids, types, params, and handles.
- `routes/`: one router per resource. Handlers are a few lines: validate, call a
  service, return its dict.

To add an endpoint: add a schema if it takes a body, add the function to a service,
and add a route that calls it. Raise `mantis.errors` for failures; do not catch them.
