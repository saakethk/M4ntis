# Issue backlog

Ordered so each issue can be solved on its own, and later issues sit on earlier ones. Numbering is the suggested solve order.

Product order follows `planning/framework.png`: identity first, then the backtesting loop (database, API, React Flow UI), then discussion, then the FPGA path that replaces the dummy backtest. Discussion and the hardware lane are real product surfaces, but a user can define a strategy and see a backtest without them.

GitHub issue creation is not available to the integration token on this repo (`Issues` returns 403). File these in order when that permission is available. Suggested labels are listed on each issue.

## Critical path

```
1 User schema
  └─ 2 User API
       └─ 3 Owner-only access
            ├─ 6 Algorithm API ──┬─ 7 Backtest schema ── 8 Dummy backtest ──┬─ 10 Results UI
            │                    │                                          ├─ 11 Algorithm home
            │                    │                                          └─ 18 FPGA-backed backtest
            ├─ 12 Discussion API ┘
            └─ 9 Sandbox UI ─────┴─ 14 AI assist
                                 └─ 15 Placebo deploy

4 Block catalog ─┬─ 6 Algorithm API
                 ├─ 9 Sandbox UI
                 └─ 16 JSON → assembly ── 17 FPGA run ── 18 FPGA-backed backtest

5 Market data ─── 8 Dummy backtest
```

Issues 4 and 5 can be done in parallel with 1–3.

---

## 1. Initialize the database and user schema

**Priority:** P0  
**Labels:** `priority: P0`, `area: database`  
**Depends on:** none  
**Blocks:** 2, 5

**Why now:** Every lane in the framework sits on a database, and user records are the root of authentication and private strategies.

**Scope:**
- Add a database initializer under `software/database`.
- Use Postgres, as called out in the task list.
- Define the user schema needed for create, authenticate, and delete (identifier, login name, password hash, timestamps).

**Done when:**
- A fresh database can be created from the repo.
- The user table exists and can store a user without keeping a plaintext password.

---

## 2. User management API

**Priority:** P0  
**Labels:** `priority: P0`, `area: backend`  
**Depends on:** 1  
**Blocks:** 3

**Why now:** Login and signup are the top of the User Authentication lane. Nothing private can be enforced until these routes exist.

**Scope:**
- `POST /create_user`
- `POST /authenticate_user`
- `DELETE /delete_user`
- Return a session or token that later routes can use to identify the caller.

**Done when:**
- A client can create a user, authenticate, and delete that user.
- A wrong password is rejected.
- Deleting a user removes that user's credentials.

---

## 3. Keep strategies private to their owner

**Priority:** P0  
**Labels:** `priority: P0`, `area: backend`  
**Depends on:** 2  
**Blocks:** 6, 8, 12

**Why now:** The task list calls out confidential strategies. The rule has to exist before algorithm, backtest, or share routes are added, or private strategies leak by default.

**Scope:**
- Require a signed-in user on protected routes.
- Provide a single ownership check: the caller may read or change only their own strategies.
- Define the exception for an explicit share (used by issue 6). Unauthenticated callers and other users get no access.

**Done when:**
- A request with no session is rejected on a protected route.
- User A cannot read or change User B's strategy.
- The check is something later algorithm and backtest routes call, rather than a one-off condition in a single handler.

---

## 4. Lock the React Flow block catalog and strategy document

**Priority:** P1  
**Labels:** `priority: P1`, `area: frontend`  
**Depends on:** none  
**Blocks:** 6, 9, 16

**Why now:** The sandbox, stored algorithms, dummy backtest, and FPGA assembly all consume the same strategy JSON. The block list should be decided before those pieces invent different shapes. This can proceed alongside issues 1–3.

**Scope:**
- Finalize the blocks a user can place on the React Flow canvas.
- Write the JSON shape of a strategy graph (nodes, edges, parameters).
- Note which blocks must be expressible as assembly later, so the catalog does not include blocks the hardware path cannot represent.

**Done when:**
- The catalog and an example strategy document live in the repo.
- Issue 6 can store that document without inventing a second schema.

---

## 5. Market data schema and historical bars

**Priority:** P1  
**Labels:** `priority: P1`, `area: database`  
**Depends on:** 1  
**Blocks:** 8, 12

**Why now:** Backtest is the core lane, and it needs bars before a run can produce orders. Discussion posts also need a stock to reference.

**Scope:**
- Schema for tickers.
- Schema for historical bars.
- Load a subset of relevant stocks into Postgres.

**Done when:**
- Tickers and bars for that subset are queryable by symbol and time range.
- The load can be repeated against a fresh database.

---

## 6. Algorithm storage schema and API

**Priority:** P1  
**Labels:** `priority: P1`, `area: backend`  
**Depends on:** 3, 4  
**Blocks:** 7, 9, 11, 12, 16

**Why now:** The sandbox, backtests, sharing, and discussion references all point at a stored algorithm. This is the center of the backtesting lane's API.

**Scope:**
- Schema for an algorithm owned by a user, including the strategy document from issue 4.
- `POST /create_algorithm`
- `POST /update_algorithm`
- `POST /publish_algorithm`
- `POST /share_algorithm`
- Enforce issue 3 on every route. Share grants one other user access. Publish makes the algorithm referenceable without opening every private draft.

**Done when:**
- The owner can create and update an algorithm.
- Another user cannot read it until it is shared or published, according to the rules above.
- A published algorithm has a stable id that a discussion post can reference.

---

## 7. Backtest result schema

**Priority:** P1  
**Labels:** `priority: P1`, `area: database`  
**Depends on:** 6  
**Blocks:** 8, 11

**Why now:** Orders, balance, and metrics are the records the backtest API and the results UI read. The task list treats performance numbers as derived from orders and balance, so those two are stored and the rest are computed.

**Scope:**
- Store orders and balance for one backtest of one algorithm revision.
- Derive and store:
  - max drawdown
  - CAGR
  - Sharpe ratio, assuming a constant risk-free rate
  - number of trades, trades won, trades lost
  - expected win/loss per trade
  - average win amount, average loss amount
  - gross P&L
  - distribution of trade returns
- Leave alpha optional; it needs a Treasury risk-free series and can be omitted.
- Revisions that have not been backtested are not result rows. Issue 11 shows only backtested iterations.

**Done when:**
- A backtest row is tied to an algorithm and an owner.
- Given sample orders and a balance series, the metrics above are populated.
- Alpha is absent rather than a fake number.

---

## 8. Dummy backtest and backtest read API

**Priority:** P1  
**Labels:** `priority: P1`, `area: backend`  
**Depends on:** 5, 7  
**Blocks:** 10, 11, 18

**Why now:** This is the first end-to-end version of the product loop: saved strategy in, orders and metrics out. The FPGA run replaces the executor later (issue 18) and should not block the UI.

**Scope:**
- `POST /backtest_algorithm`
- `GET /view_backtest_orders`
- `GET /view_backtest_balance`
- `GET /view_backtest_metrics`
- A dummy executor reads stored bars and the saved strategy document, writes orders and balance, and fills the issue 7 metrics.
- Owner-only access, including shared viewers if issue 6 granted access.

**Done when:**
- Backtesting an owned algorithm persists orders, balance, and metrics.
- The three read routes return that run and reject other users.
- The executor is a replaceable function, so issue 18 can swap in the FPGA without changing the read API.

---

## 9. Algorithm sandbox UI

**Priority:** P2  
**Labels:** `priority: P2`, `area: frontend`  
**Depends on:** 4, 6  
**Blocks:** 10, 11, 14, 15

**Why now:** Once algorithms can be stored, the React Flow canvas is the way a user builds one. Results, history, and AI assistance attach to this screen.

**Scope:**
- React Flow canvas using the issue 4 catalog.
- Create and edit a sandbox, saving through the issue 6 API.
- A control that starts a backtest (results rendering is issue 10).

**Done when:**
- A signed-in user can build a graph from the catalog and save it.
- Reloading the sandbox shows the saved graph.
- Another user's private algorithm is not editable here.

---

## 10. Backtest results UI

**Priority:** P2  
**Labels:** `priority: P2`, `area: frontend`  
**Depends on:** 8, 9  
**Blocks:** 14

**Why now:** The sandbox is incomplete until the user can inspect the run. The task list requires orders, balance, max drawdown, and the other stored metrics.

**Scope:**
- After a backtest, show orders, balance, and the issue 7 metrics for that run.
- Scope the view to the selected backtested revision.

**Done when:**
- Running a backtest from the sandbox shows that run's orders, balance, and metrics.
- Opening an older backtested revision shows that revision's results, not the latest run.

---

## 11. Algorithm home, revision history, and summary stats

**Priority:** P2  
**Labels:** `priority: P2`, `area: frontend`  
**Depends on:** 6, 8, 9  
**Blocks:** none

**Why now:** Users need more than one sandbox. History is only useful after backtests exist, and the task list says to keep iterations that have been backtested.

**Scope:**
- Create additional sandboxes and open them for editing.
- List prior revisions, limited to iterations that were backtested.
- Show total program count and algorithm status.
- Post-engagement stats can render as empty until issue 13 exists.

**Done when:**
- A user can create two sandboxes and edit each one.
- A save that was never backtested does not appear in the history list.
- A backtested iteration does, and opening it reaches the issue 10 results.

---

## 12. Discussion schema and API

**Priority:** P3  
**Labels:** `priority: P3`, `area: backend`  
**Depends on:** 3, 5, 6  
**Blocks:** 13

**Why now:** Discussion is its own lane and is not required to run a backtest. It does need a signed-in user, a stock, and an algorithm id so posts can reference either one.

**Scope:**
- Schema for posts, comments, and likes.
- A post references an algorithm or a stock.
- `POST /create_post`
- `POST /comment_post`
- `POST /like_post`

**Done when:**
- A signed-in user can create a post that points at a ticker or a published algorithm.
- Another user can comment and like that post.
- A reference to a private, unshared algorithm is rejected.

---

## 13. Discussion UI

**Priority:** P3  
**Labels:** `priority: P3`, `area: frontend`  
**Depends on:** 12  
**Blocks:** none

**Why now:** The discussion API is usable only after a screen exists for viewing, posting, and commenting. This matches the frontend half of that lane.

**Scope:**
- View discussions.
- Create a post, including a stock or algorithm reference.
- Comment on a post.
- Like a post.

**Done when:**
- A signed-in user can complete those four actions against the issue 12 API.
- A post shows the stock or algorithm it references.

---

## 14. Sandbox assistant and backtest summary

**Priority:** P4  
**Labels:** `priority: P4`, `area: frontend`, `area: ai`  
**Depends on:** 9, 10  
**Blocks:** none

**Why now:** Both AI features sit on top of a working sandbox and a real backtest result. They do not unblock storage, execution, or the hardware path.

**Scope:**
- In the sandbox, let the user prompt an assistant while building a strategy.
- On a backtest result, show a summary and improvement tips adjusted to the user's technical level.

**Done when:**
- The assistant is available from the sandbox and can refer to the current graph.
- A completed backtest shows a summary that mentions that run's metrics.
- Tips differ with the user's technical level.

---

## 15. Placebo deploy action

**Priority:** P4  
**Labels:** `priority: P4`, `area: frontend`  
**Depends on:** 9  
**Blocks:** none

**Why now:** The task list allows deploy to be a placebo. It should not be confused with the FPGA run, which is a separate execution path.

**Scope:**
- From a saved algorithm, offer a deploy action.
- Record that the user deployed it and confirm in the UI. No live trading.

**Done when:**
- Deploy is available for an owned, saved algorithm.
- The UI shows a deployed state and does not claim an order was sent to a broker.

---

## 16. Convert a strategy document to assembly

**Priority:** P5  
**Labels:** `priority: P5`, `area: hardware`  
**Depends on:** 4, 6  
**Blocks:** 17

**Why now:** Hardware work starts once the strategy JSON is stable. It replaces the dummy executor only after assembly is actually runnable.

**Scope:**
- Translate a basic React Flow strategy document into valid assembly.
- Cover the blocks marked as hardware-expressible in issue 4.
- Fail with a clear error on a graph that uses an unsupported block.

**Done when:**
- A fixture strategy document produces assembly.
- An unsupported block does not produce a partial bitstream or a silent skip.

---

## 17. Flash the FPGA, run it, and collect results

**Priority:** P5  
**Labels:** `priority: P5`, `area: hardware`  
**Depends on:** 16  
**Blocks:** 18

**Why now:** This is the hardware lane's API: assembly and backtest code on the FPGA, with a hardware API returning the run. It is useless to the app until issue 18 stores those results as orders and balance.

**Scope:**
- Hardware API that accepts assembly, flashes the FPGA, runs it, and returns raw results.
- Include enough logging to tell a flash failure from a run failure.

**Done when:**
- A known assembly payload can be flashed and run.
- The caller receives the raw results, or a distinct error for flash failure versus run failure.

---

## 18. Run backtests on the FPGA

**Priority:** P5  
**Labels:** `priority: P5`, `area: hardware`, `area: backend`  
**Depends on:** 8, 17  
**Blocks:** none

**Why now:** This is the last step on the critical path. The dummy backtest, its schema, and its read API stay. Only the executor changes.

**Scope:**
- From `/backtest_algorithm`, convert the stored strategy (issue 16), run it through the hardware API (issue 17), and map the raw results into orders and balance.
- Reuse the issue 7 metrics and the issue 8 read routes.

**Done when:**
- A backtest of a supported strategy persists orders, balance, and metrics from the FPGA run.
- `/view_backtest_orders`, `/view_backtest_balance`, and `/view_backtest_metrics` stay unchanged.
- A hardware failure does not write a successful backtest row.
