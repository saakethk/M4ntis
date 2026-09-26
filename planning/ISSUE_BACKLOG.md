# Prioritized GitHub issues

Derived from [planning/README.md](./README.md). The repo currently has planning notes and empty `software/`, `hardware/`, and `integration/` folders. No application code, schemas, or GitHub issues exist yet.

Priority follows what must exist before the next layer can be built:

| Priority | Meaning |
| --- | --- |
| P0 | Blocks every user-facing flow. Auth and private algorithm storage. |
| P1 | Core demo: market data, dummy backtest, discussion API, and the screens that use them. |
| P2 | Completes the product described in the plan after the demo path works. |
| P3 | FPGA execution and the optional alpha metric. |

Suggested labels: `enhancement`, plus `priority/p0` through `priority/p3`, and `area/backend`, `area/frontend`, or `area/fpga`.

## Order

| ID | Priority | Title | Depends on |
| --- | --- | --- | --- |
| 1 | P0 | Bootstrap the application database | — |
| 2 | P0 | User schema and authentication API | 1 |
| 3 | P0 | Private algorithm storage API | 1, 2 |
| 4 | P1 | Market data schema and historical bars | 1 |
| 5 | P1 | Backtest result schema | 1, 3 |
| 6 | P1 | Dummy backtest API | 3, 4, 5 |
| 7 | P1 | Discussion API | 2, 3, 4 |
| 8 | P1 | Algorithm home | 3 |
| 9 | P1 | React Flow sandbox | 3, 8 |
| 10 | P1 | Backtest results UI | 6, 9 |
| 11 | P1 | Discussion UI | 7, 8 |
| 12 | P2 | Publish and share algorithms | 3 |
| 13 | P2 | Backtested revision history | 6, 8 |
| 14 | P2 | Algorithm home statistics | 7, 8, 12 |
| 15 | P2 | In-sandbox agent assistance | 9 |
| 16 | P2 | AI backtest summary and tips | 10 |
| 17 | P2 | Placebo deploy | 9 |
| 18 | P3 | Optional alpha metric | 5, 6 |
| 19 | P3 | Compile a strategy graph to FPGA assembly | 9 |
| 20 | P3 | Flash the FPGA and collect a run | 19 |
| 21 | P3 | Run backtests on the FPGA | 6, 20 |

Issues 4 and 2 can proceed in parallel after issue 1. Frontend issues 8 and 11 can start against mocked responses, but they are not done until they call the real endpoints.

---

## 1. Bootstrap the application database

**Priority:** P0  
**Labels:** `enhancement`, `priority/p0`, `area/backend`  
**Depends on:** none

`software/database/` only contains a README. Every schema in the plan (users, algorithms, posts, backtests, tickers, bars) needs one database and one way to create it.

**Acceptance criteria**

- Postgres (or the chosen database) can be started from the repo for local development.
- Schema init lives under `software/database/` and can be reapplied from a clean database.
- README in that folder states how to create, reset, and connect to the database.

## 2. User schema and authentication API

**Priority:** P0  
**Labels:** `enhancement`, `priority/p0`, `area/backend`  
**Depends on:** 1

Plan endpoints: `/create_user`, `/authenticate_user`, `/delete_user`.

**Acceptance criteria**

- A user schema exists and passwords are not stored in plaintext.
- A client can create a user, authenticate, and delete that user.
- Authenticated requests carry a session or token that later endpoints can check.
- Unauthenticated requests to private resources are rejected.

## 3. Private algorithm storage API

**Priority:** P0  
**Labels:** `enhancement`, `priority/p0`, `area/backend`  
**Depends on:** 1, 2

Plan endpoints: `/create_algorithm`, `/update_algorithm`. Strategies are confidential: a signed-in user may access only their own.

**Acceptance criteria**

- Algorithm schema stores the owner, timestamps, status, and the React Flow graph JSON.
- The owner can create and update their algorithms.
- Reading or updating another user's algorithm returns an authorization error.
- Unpublished algorithms are not returned to anyone except the owner.

## 4. Market data schema and historical bars

**Priority:** P1  
**Labels:** `enhancement`, `priority/p1`, `area/backend`  
**Depends on:** 1

The plan calls for a market-data schema (tickers) and historical bars for a subset of relevant stocks, loaded into the database.

**Acceptance criteria**

- Schemas exist for tickers and historical bars.
- A documented subset of stocks is loaded through a repeatable script.
- Bars for a loaded ticker can be queried by symbol and time range.

## 5. Backtest result schema

**Priority:** P1  
**Labels:** `enhancement`, `priority/p1`, `area/backend`  
**Depends on:** 1, 3

Store naive backtest output: orders, balance, and overall performance derived from those two. Metrics from the plan:

- max drawdown
- CAGR
- Sharpe ratio, using a constant risk-free rate assumption
- number of trades, trades won, trades lost
- expected win/loss per trade
- average win amount, average loss amount
- gross P&L
- distribution of trade returns

Alpha is issue 18, not part of this schema's required columns.

**Acceptance criteria**

- One backtest run is tied to an algorithm and the user who ran it.
- Orders, the balance series, and the metrics above can be stored and read back.
- Metric definitions are documented, including which values are derived from orders and balance.

## 6. Dummy backtest API

**Priority:** P1  
**Labels:** `enhancement`, `priority/p1`, `area/backend`  
**Depends on:** 3, 4, 5

Plan endpoints: `/backtest_algorithm`, `/view_backtest_orders`, `/view_backtest_balance`, `/view_backtest_metrics`.

This is the stand-in execution path. FPGA execution replaces the dummy engine in issue 21 without changing these read endpoints.

**Acceptance criteria**

- An owner can run a backtest for one of their algorithms against loaded market data.
- The run persists dummy orders, a balance series, and the metrics from issue 5.
- The three view endpoints return only that owner's run.
- A second run does not destroy the previous run's stored rows.

## 7. Discussion API

**Priority:** P1  
**Labels:** `enhancement`, `priority/p1`, `area/backend`  
**Depends on:** 2, 3, 4

Plan endpoints: `/create_post`, `/comment_post`, `/like_post`. A post references an algorithm or a stock.

**Acceptance criteria**

- Post, comment, and like schemas exist.
- A signed-in user can create a post, comment, and like.
- A post references either an existing ticker or an algorithm the author is allowed to see, not both and not neither.
- Posts can be listed for the discussion page with comment and like counts.

## 8. Algorithm home

**Priority:** P1  
**Labels:** `enhancement`, `priority/p1`, `area/frontend`  
**Depends on:** 3

The home screen is where a user creates more than one sandbox and opens one to edit.

**Acceptance criteria**

- A signed-in user sees only their sandboxes.
- They can create a sandbox and open it for editing.
- An empty account has a clear empty state, not a broken list.

## 9. React Flow sandbox

**Priority:** P1  
**Labels:** `enhancement`, `priority/p1`, `area/frontend`  
**Depends on:** 3, 8

The plan asks to finalize the blocks available on the canvas, then implement the node UI.

**Acceptance criteria**

- The block catalog is written down (node types, inputs, and outputs) before the canvas is considered done.
- The sandbox loads and saves the graph through the algorithm API.
- A user can add, connect, and remove blocks, then reload the sandbox and see the same graph.

## 10. Backtest results UI

**Priority:** P1  
**Labels:** `enhancement`, `priority/p1`, `area/frontend`  
**Depends on:** 6, 9

From the sandbox, a user runs a backtest and inspects orders, balance, max drawdown, and the other stored metrics.

**Acceptance criteria**

- The sandbox can start a backtest for the open algorithm.
- Results show orders, the balance series, and the metrics returned by the API.
- A failed or empty run shows an error or empty state instead of a blank page.

## 11. Discussion UI

**Priority:** P1  
**Labels:** `enhancement`, `priority/p1`, `area/frontend`  
**Depends on:** 7, 8

**Acceptance criteria**

- A user can view posts, create a post, comment, and like.
- The composer requires a reference to a stock or an algorithm and shows that reference on the post.
- The page works when there are no posts yet.

## 12. Publish and share algorithms

**Priority:** P2  
**Labels:** `enhancement`, `priority/p2`, `area/backend`, `area/frontend`  
**Depends on:** 3

Plan endpoints: `/publish_algorithm`, `/share_algorithm`.

**Acceptance criteria**

- Publish makes an algorithm visible without making every private algorithm visible.
- Share grants access to specific users and does not allow those users to publish or delete it.
- The owner can still edit. Someone outside the share list cannot read the graph.
- The UI exposes publish and share from the sandbox or algorithm home.

## 13. Backtested revision history

**Priority:** P2  
**Labels:** `enhancement`, `priority/p2`, `area/backend`, `area/frontend`  
**Depends on:** 6, 8

The plan says to keep iteration history and only save iterations that have been backtested.

**Acceptance criteria**

- A successful backtest stores a revision of the graph used for that run.
- Editing the graph without backtesting does not add a revision.
- The algorithm home or sandbox lists past backtested revisions and can open one.

## 14. Algorithm home statistics

**Priority:** P2  
**Labels:** `enhancement`, `priority/p2`, `area/frontend`  
**Depends on:** 7, 8, 12

The home screen shows total number of programs and overall statistics: post engagement, algorithm statuses, and similar rollups.

**Acceptance criteria**

- Home shows the user's program count.
- Home shows algorithm status counts and a simple engagement summary for their posts.
- Counts match the API after creating a sandbox, publishing, or receiving a like.

## 15. In-sandbox agent assistance

**Priority:** P2  
**Labels:** `enhancement`, `priority/p2`, `area/frontend`  
**Depends on:** 9

The sandbox should let a user prompt an inbuilt agent for help crafting an algorithm.

**Acceptance criteria**

- The sandbox has a prompt UI next to the canvas.
- A prompt returns a visible suggestion the user can accept or ignore.
- The graph is not overwritten unless the user accepts the suggestion.

## 16. AI backtest summary and tips

**Priority:** P2  
**Labels:** `enhancement`, `priority/p2`, `area/frontend`  
**Depends on:** 10

After a backtest, show an AI summary and improvement tips adjusted to the user's technical level.

**Acceptance criteria**

- Results include a short summary of that run's orders and metrics.
- Tips change with a technical-level setting on the user or the results page.
- The summary is tied to the run being viewed, not a generic paragraph.

## 17. Placebo deploy

**Priority:** P2  
**Labels:** `enhancement`, `priority/p2`, `area/frontend`  
**Depends on:** 9

The plan allows deploy to be a placebo.

**Acceptance criteria**

- The sandbox has a deploy action.
- Deploy records a deployed status on that algorithm and confirms it in the UI.
- Deploy does not require FPGA hardware.

## 18. Optional alpha metric

**Priority:** P3  
**Labels:** `enhancement`, `priority/p3`, `area/backend`  
**Depends on:** 5, 6

Alpha is optional and needs a Treasury risk-free rate. Skip this if the core demo is still open.

**Acceptance criteria**

- A risk-free rate source is documented and stored with the run.
- Alpha is computed from that rate and included in backtest metrics.
- Existing runs remain valid when alpha is absent.

## 19. Compile a strategy graph to FPGA assembly

**Priority:** P3  
**Labels:** `enhancement`, `priority/p3`, `area/fpga`  
**Depends on:** 9

Figure out how to convert a basic strategy, output as JSON from React Flow, into valid assembly.

**Acceptance criteria**

- A documented subset of blocks compiles to assembly.
- Unsupported graphs fail with a specific error instead of emitting partial assembly.
- A fixture graph in the repo compiles in a test or script.

## 20. Flash the FPGA and collect a run

**Priority:** P3  
**Labels:** `enhancement`, `priority/p3`, `area/fpga`  
**Depends on:** 19

Figure out how to flash the FPGA with the assembly, run it, and get results back.

**Acceptance criteria**

- A single compiled strategy can be flashed and started.
- The host receives a structured result payload from the run.
- Failure to flash or run is reported to the caller.

## 21. Run backtests on the FPGA

**Priority:** P3  
**Labels:** `enhancement`, `priority/p3`, `area/fpga`, `area/backend`  
**Depends on:** 6, 20

Integrate the FPGA path into the backtest function, still saving orders and balance through the existing schema.

**Acceptance criteria**

- `/backtest_algorithm` can execute through the FPGA path.
- Orders, balance, and metrics are saved the same way as the dummy path.
- If the FPGA path is unavailable, the dummy path still runs.
