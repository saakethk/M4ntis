# Preliminary Tasks

Prioritized GitHub issues for this list: [ISSUE_BACKLOG.md](./ISSUE_BACKLOG.md).

Here is a list of preliminary tasks that need to be done to ensure frontend functionality is done:

## Backend API

### User Management
- /create_user
- /authenticate_user
- /delete_user

### TODO
- Develop schema for users
- Implement basic authentication
- Only allow user to access their strategies when signed in and not others
  - Important to ensure confidential strategies

### Discussion Page
- /create_post
- /comment_post
- /like_post

#### TODO
- Develop schema for posts
  - Needs to be able to reference a algorithm or stock
- Create basic endpoints for posts

### Algorithm Sandbox
- /publish_algorithm
- /create_algorithm
- /update_algorithm
- /share_algorithm

#### TODO
- Develop schema for algorithm storage
- Create basic endpoints for algorithm storage

### Backtest Analysis
- /backtest_algorithm
- /view_backtest_orders
- /view_backtest_balance
- /view_backtest_metrics

#### TODO
- Create sample schema for backtest
- Develop schema for naive backtest metric storage
  - orders
  - balance
  - overall_performance (can be derived from the balance and orders)
    - max_drawdown
    - cagr (compound annual growth rate)
    - alpha (optional - depends on if you have time) (requires risk free rate from treasury)
    - sharpe ratio (we need to assume a constant sharpe ratio)
    - num_trades
    - num_trades_won
    - num_trades_lost
    - expected_win_loss_per_trade
    - avg_win_amount
    - avg_loss_amount
    - gross_p_and_l
    - distribution_of_trade_returns
- Develop schema for market data
  - tickers
- Get historical bars market data for subset of relevant stocks
- Upload data to some sort of database (postgres or otherwise)
- Build dummy backtest function which will produce dummy orders and metrics
- Figure out how to convert a basic strategy outputed as json from react-flow to valid assembly
- Figure out how to flash the FPGA with the assembly, run the code, and get results
- Integrate FPGA part into dummy backtest function with order and balance saving
- Finalize endpoints

## Frontend System Description

### Discussion
- Allow users to create discussions
- Allow users to comment on discussion
- Allow users to like a discussion
- Posts can reference stocks or algorithms

#### TODO
- Create UI for discussion viewing
- Create UI for discussion commenting
- Create UI for discussion posting

### Algorithm Sandbox
- Should allows users to develop an algorithm in a sandbox with a node based UI
- Should allows users to backtest that algorithm
  - Should allow users to inspect the orders, balance, max_drawdown, and other metrics related to this algorithm
  - Should show AI summary of the backtest algorithm and provide tips on improving it based on technical level of user
- Should allow users to deploy that algorithm (Can be placebo)
- Should allow users to prompt a inbuilt agent for assistance with crafting an algorithm

#### TODO
- Finalize the blocks we need available to a user on react flow
- Implement react-flow and UI for frontend
- Add UI for AI collaboration
- Add UI for backtesting
- Add UI for viewing results of backtest
- Add UI for viewing past revisions of a strategy

### Algorithm Home
- Should have ability to create multiple algorithm sandboxes
- Should have ability for users to edit these sandboxes
- Should have ability for users to view history of iterations for the algorithm (only save iterations that have been backtested)
- Should have total number of programs and overall statistics (post engagement, algorithm statuses, ect.)

#### TODO
- Add ability to create a new sandbox
- Add overall statistics

## Presentation

### TODO
- Create a website at m4ntis.tech which explains the project