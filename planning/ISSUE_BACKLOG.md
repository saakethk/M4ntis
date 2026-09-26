# Prioritized GitHub issues

Derived from [planning/README.md](./README.md). These items are open on GitHub as issues [#3](https://github.com/saakethk/gt_hacks_fall_26/issues/3) through [#23](https://github.com/saakethk/gt_hacks_fall_26/issues/23). The repo still has planning notes and empty `software/`, `hardware/`, and `integration/` folders.

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
| 1 | P0 | [#3 Bootstrap the application database](https://github.com/saakethk/gt_hacks_fall_26/issues/3) | — |
| 2 | P0 | [#4 User schema and authentication API](https://github.com/saakethk/gt_hacks_fall_26/issues/4) | #3 |
| 3 | P0 | [#5 Private algorithm storage API](https://github.com/saakethk/gt_hacks_fall_26/issues/5) | #3, #4 |
| 4 | P1 | [#6 Market data schema and historical bars](https://github.com/saakethk/gt_hacks_fall_26/issues/6) | #3 |
| 5 | P1 | [#7 Backtest result schema](https://github.com/saakethk/gt_hacks_fall_26/issues/7) | #3, #5 |
| 6 | P1 | [#8 Dummy backtest API](https://github.com/saakethk/gt_hacks_fall_26/issues/8) | #5, #6, #7 |
| 7 | P1 | [#9 Discussion API](https://github.com/saakethk/gt_hacks_fall_26/issues/9) | #4, #5, #6 |
| 8 | P1 | [#10 Algorithm home](https://github.com/saakethk/gt_hacks_fall_26/issues/10) | #5 |
| 9 | P1 | [#11 React Flow sandbox](https://github.com/saakethk/gt_hacks_fall_26/issues/11) | #5, #10 |
| 10 | P1 | [#12 Backtest results UI](https://github.com/saakethk/gt_hacks_fall_26/issues/12) | #8, #11 |
| 11 | P1 | [#13 Discussion UI](https://github.com/saakethk/gt_hacks_fall_26/issues/13) | #9, #10 |
| 12 | P2 | [#14 Publish and share algorithms](https://github.com/saakethk/gt_hacks_fall_26/issues/14) | #5 |
| 13 | P2 | [#15 Backtested revision history](https://github.com/saakethk/gt_hacks_fall_26/issues/15) | #8, #10 |
| 14 | P2 | [#16 Algorithm home statistics](https://github.com/saakethk/gt_hacks_fall_26/issues/16) | #9, #10, #14 |
| 15 | P2 | [#17 In-sandbox agent assistance](https://github.com/saakethk/gt_hacks_fall_26/issues/17) | #11 |
| 16 | P2 | [#18 AI backtest summary and tips](https://github.com/saakethk/gt_hacks_fall_26/issues/18) | #12 |
| 17 | P2 | [#19 Placebo deploy](https://github.com/saakethk/gt_hacks_fall_26/issues/19) | #11 |
| 18 | P3 | [#20 Optional alpha metric](https://github.com/saakethk/gt_hacks_fall_26/issues/20) | #7, #8 |
| 19 | P3 | [#21 Compile a strategy graph to FPGA assembly](https://github.com/saakethk/gt_hacks_fall_26/issues/21) | #11 |
| 20 | P3 | [#22 Flash the FPGA and collect a run](https://github.com/saakethk/gt_hacks_fall_26/issues/22) | #21 |
| 21 | P3 | [#23 Run backtests on the FPGA](https://github.com/saakethk/gt_hacks_fall_26/issues/23) | #8, #22 |

[#6](https://github.com/saakethk/gt_hacks_fall_26/issues/6) and [#4](https://github.com/saakethk/gt_hacks_fall_26/issues/4) can proceed in parallel after [#3](https://github.com/saakethk/gt_hacks_fall_26/issues/3). Frontend issues [#10](https://github.com/saakethk/gt_hacks_fall_26/issues/10) and [#13](https://github.com/saakethk/gt_hacks_fall_26/issues/13) can start against mocked responses, but they are not done until they call the real endpoints.

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
**Depends on:** [#3](https://github.com/saakethk/gt_hacks_fall_26/issues/3)

Plan endpoints: `/create_user`, `/authenticate_user`, `/delete_user`.

**Acceptance criteria**

- A user schema exists and passwords are not stored in plaintext.
- A client can create a user, authenticate, and delete that user.
- Authenticated requests carry a session or token that later endpoints can check.
- Unauthenticated requests to private resources are rejected.

## 3. Private algorithm storage API

**Priority:** P0  
**Labels:** `enhancement`, `priority/p0`, `area/backend`  
**Depends on:** [#3](https://github.com/saakethk/gt_hacks_fall_26/issues/3), [#4](https://github.com/saakethk/gt_hacks_fall_26/issues/4)

Plan endpoints: `/create_algorithm`, `/update_algorithm`. Strategies are confidential: a signed-in user may access only their own.

**Acceptance criteria**

- Algorithm schema stores the owner, timestamps, status, and the React Flow graph JSON.
- The owner can create and update their algorithms.
- Reading or updating another user's algorithm returns an authorization error.
- Unpublished algorithms are not returned to anyone except the owner.

## 4. Market data schema and historical bars

**Priority:** P1  
**Labels:** `enhancement`, `priority/p1`, `area/backend`  
**Depends on:** [#3](https://github.com/saakethk/gt_hacks_fall_26/issues/3)

The plan calls for a market-data schema (tickers) and historical bars for a subset of relevant stocks, loaded into the database.

**Acceptance criteria**

- Schemas exist for tickers and historical bars.
- A documented subset of stocks is loaded through a repeatable script.
- Bars for a loaded ticker can be queried by symbol and time range.

## 5. Backtest result schema

**Priority:** P1  
**Labels:** `enhancement`, `priority/p1`, `area/backend`  
**Depends on:** [#3](https://github.com/saakethk/gt_hacks_fall_26/issues/3), [#5](https://github.com/saakethk/gt_hacks_fall_26/issues/5)

Store naive backtest output: orders, balance, and overall performance derived from those two. Metrics from the plan:

- max drawdown
- CAGR
- Sharpe ratio, using a constant risk-free rate assumption
- number of trades, trades won, trades lost
- expected win/loss per trade
- average win amount, average loss amount
- gross P&L
- distribution of trade returns

Alpha is [#20](https://github.com/saakethk/gt_hacks_fall_26/issues/20), not part of this schema's required columns.

**Acceptance criteria**

- One backtest run is tied to an algorithm and the user who ran it.
- Orders, the balance series, and the metrics above can be stored and read back.
- Metric definitions are documented, including which values are derived from orders and balance.

## 6. Dummy backtest API

**Priority:** P1  
**Labels:** `enhancement`, `priority/p1`, `area/backend`  
**Depends on:** [#5](https://github.com/saakethk/gt_hacks_fall_26/issues/5), [#6](https://github.com/saakethk/gt_hacks_fall_26/issues/6), [#7](https://github.com/saakethk/gt_hacks_fall_26/issues/7)

Plan endpoints: `/backtest_algorithm`, `/view_backtest_orders`, `/view_backtest_balance`, `/view_backtest_metrics`.

This is the stand-in execution path. FPGA execution replaces the dummy engine in [#23](https://github.com/saakethk/gt_hacks_fall_26/issues/23) without changing these read endpoints.

**Acceptance criteria**

- An owner can run a backtest for one of their algorithms against loaded market data.
- The run persists dummy orders, a balance series, and the metrics from [#7](https://github.com/saakethk/gt_hacks_fall_26/issues/7).
- The three view endpoints return only that owner's run.
- A second run does not destroy the previous run's stored rows.

## 7. Discussion API

**Priority:** P1  
**Labels:** `enhancement`, `priority/p1`, `area/backend`  
**Depends on:** [#4](https://github.com/saakethk/gt_hacks_fall_26/issues/4), [#5](https://github.com/saakethk/gt_hacks_fall_26/issues/5), [#6](https://github.com/saakethk/gt_hacks_fall_26/issues/6)

Plan endpoints: `/create_post`, `/comment_post`, `/like_post`. A post references an algorithm or a stock.

**Acceptance criteria**

- Post, comment, and like schemas exist.
- A signed-in user can create a post, comment, and like.
- A post references either an existing ticker or an algorithm the author is allowed to see, not both and not neither.
- Posts can be listed for the discussion page with comment and like counts.

## 8. Algorithm home

**Priority:** P1  
**Labels:** `enhancement`, `priority/p1`, `area/frontend`  
**Depends on:** [#5](https://github.com/saakethk/gt_hacks_fall_26/issues/5)

The home screen is where a user creates more than one sandbox and opens one to edit.

**Acceptance criteria**

- A signed-in user sees only their sandboxes.
- They can create a sandbox and open it for editing.
- An empty account has a clear empty state, not a broken list.

## 9. React Flow sandbox

**Priority:** P1  
**Labels:** `enhancement`, `priority/p1`, `area/frontend`  
**Depends on:** [#5](https://github.com/saakethk/gt_hacks_fall_26/issues/5), [#10](https://github.com/saakethk/gt_hacks_fall_26/issues/10)

The plan asks to finalize the blocks available on the canvas, then implement the node UI.

**Acceptance criteria**

- The block catalog is written down (node types, inputs, and outputs) before the canvas is considered done.
- The sandbox loads and saves the graph through the algorithm API.
- A user can add, connect, and remove blocks, then reload the sandbox and see the same graph.

## 10. Backtest results UI

**Priority:** P1  
**Labels:** `enhancement`, `priority/p1`, `area/frontend`  
**Depends on:** [#8](https://github.com/saakethk/gt_hacks_fall_26/issues/8), [#11](https://github.com/saakethk/gt_hacks_fall_26/issues/11)

From the sandbox, a user runs a backtest and inspects orders, balance, max drawdown, and the other stored metrics.

**Acceptance criteria**

- The sandbox can start a backtest for the open algorithm.
- Results show orders, the balance series, and the metrics returned by the API.
- A failed or empty run shows an error or empty state instead of a blank page.

## 11. Discussion UI

**Priority:** P1  
**Labels:** `enhancement`, `priority/p1`, `area/frontend`  
**Depends on:** [#9](https://github.com/saakethk/gt_hacks_fall_26/issues/9), [#10](https://github.com/saakethk/gt_hacks_fall_26/issues/10)

**Acceptance criteria**

- A user can view posts, create a post, comment, and like.
- The composer requires a reference to a stock or an algorithm and shows that reference on the post.
- The page works when there are no posts yet.

## 12. Publish and share algorithms

**Priority:** P2  
**Labels:** `enhancement`, `priority/p2`, `area/backend`, `area/frontend`  
**Depends on:** [#5](https://github.com/saakethk/gt_hacks_fall_26/issues/5)

Plan endpoints: `/publish_algorithm`, `/share_algorithm`.

**Acceptance criteria**

- Publish makes an algorithm visible without making every private algorithm visible.
- Share grants access to specific users and does not allow those users to publish or delete it.
- The owner can still edit. Someone outside the share list cannot read the graph.
- The UI exposes publish and share from the sandbox or algorithm home.

## 13. Backtested revision history

**Priority:** P2  
**Labels:** `enhancement`, `priority/p2`, `area/backend`, `area/frontend`  
**Depends on:** [#8](https://github.com/saakethk/gt_hacks_fall_26/issues/8), [#10](https://github.com/saakethk/gt_hacks_fall_26/issues/10)

The plan says to keep iteration history and only save iterations that have been backtested.

**Acceptance criteria**

- A successful backtest stores a revision of the graph used for that run.
- Editing the graph without backtesting does not add a revision.
- The algorithm home or sandbox lists past backtested revisions and can open one.

## 14. Algorithm home statistics

**Priority:** P2  
**Labels:** `enhancement`, `priority/p2`, `area/frontend`  
**Depends on:** [#9](https://github.com/saakethk/gt_hacks_fall_26/issues/9), [#10](https://github.com/saakethk/gt_hacks_fall_26/issues/10), [#14](https://github.com/saakethk/gt_hacks_fall_26/issues/14)

The home screen shows total number of programs and overall statistics: post engagement, algorithm statuses, and similar rollups.

**Acceptance criteria**

- Home shows the user's program count.
- Home shows algorithm status counts and a simple engagement summary for their posts.
- Counts match the API after creating a sandbox, publishing, or receiving a like.

## 15. In-sandbox agent assistance

**Priority:** P2  
**Labels:** `enhancement`, `priority/p2`, `area/frontend`  
**Depends on:** [#11](https://github.com/saakethk/gt_hacks_fall_26/issues/11)

The sandbox should let a user prompt an inbuilt agent for help crafting an algorithm.

**Acceptance criteria**

- The sandbox has a prompt UI next to the canvas.
- A prompt returns a visible suggestion the user can accept or ignore.
- The graph is not overwritten unless the user accepts the suggestion.

## 16. AI backtest summary and tips

**Priority:** P2  
**Labels:** `enhancement`, `priority/p2`, `area/frontend`  
**Depends on:** [#12](https://github.com/saakethk/gt_hacks_fall_26/issues/12)

After a backtest, show an AI summary and improvement tips adjusted to the user's technical level.

**Acceptance criteria**

- Results include a short summary of that run's orders and metrics.
- Tips change with a technical-level setting on the user or the results page.
- The summary is tied to the run being viewed, not a generic paragraph.

## 17. Placebo deploy

**Priority:** P2  
**Labels:** `enhancement`, `priority/p2`, `area/frontend`  
**Depends on:** [#11](https://github.com/saakethk/gt_hacks_fall_26/issues/11)

The plan allows deploy to be a placebo.

**Acceptance criteria**

- The sandbox has a deploy action.
- Deploy records a deployed status on that algorithm and confirms it in the UI.
- Deploy does not require FPGA hardware.

## 18. Optional alpha metric

**Priority:** P3  
**Labels:** `enhancement`, `priority/p3`, `area/backend`  
**Depends on:** [#7](https://github.com/saakethk/gt_hacks_fall_26/issues/7), [#8](https://github.com/saakethk/gt_hacks_fall_26/issues/8)

Alpha is optional and needs a Treasury risk-free rate. Skip this if the core demo is still open.

**Acceptance criteria**

- A risk-free rate source is documented and stored with the run.
- Alpha is computed from that rate and included in backtest metrics.
- Existing runs remain valid when alpha is absent.

## 19. Compile a strategy graph to FPGA assembly

**Priority:** P3  
**Labels:** `enhancement`, `priority/p3`, `area/fpga`  
**Depends on:** [#11](https://github.com/saakethk/gt_hacks_fall_26/issues/11)

Figure out how to convert a basic strategy, output as JSON from React Flow, into valid assembly.

**Acceptance criteria**

- A documented subset of blocks compiles to assembly.
- Unsupported graphs fail with a specific error instead of emitting partial assembly.
- A fixture graph in the repo compiles in a test or script.

## 20. Flash the FPGA and collect a run

**Priority:** P3  
**Labels:** `enhancement`, `priority/p3`, `area/fpga`  
**Depends on:** [#21](https://github.com/saakethk/gt_hacks_fall_26/issues/21)

Figure out how to flash the FPGA with the assembly, run it, and get results back.

**Acceptance criteria**

- A single compiled strategy can be flashed and started.
- The host receives a structured result payload from the run.
- Failure to flash or run is reported to the caller.

## 21. Run backtests on the FPGA

**Priority:** P3  
**Labels:** `enhancement`, `priority/p3`, `area/fpga`, `area/backend`  
**Depends on:** [#8](https://github.com/saakethk/gt_hacks_fall_26/issues/8), [#22](https://github.com/saakethk/gt_hacks_fall_26/issues/22)

Integrate the FPGA path into the backtest function, still saving orders and balance through the existing schema.

**Acceptance criteria**

- `/backtest_algorithm` can execute through the FPGA path.
- Orders, balance, and metrics are saved the same way as the dummy path.
- If the FPGA path is unavailable, the dummy path still runs.
