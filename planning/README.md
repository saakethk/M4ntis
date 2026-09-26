# Preliminary Tasks
Here is a list of preliminary tasks that need to be done to ensure frontend functionality is done:

## Backend API

### User Management
- /create_user
- /authenticate_user
- /delete_user

### Discussion Page
- /create_post
- /comment_post
- /like_post

### Algorithm Sandbox
- /publish_algorithm
- /create_algorithm
- /update_algorithm
- /share_algorithm

### Backtest Analysis
- /backtest_algorithm
- /view_backtest_orders
- /view_backtest_balance
- /view_backtest_metrics

## Frontend System Description

### Discussion
- Allow users to create discussions
- Allow users to comment on discussion
- Allow users to like a discussion
- Posts can reference stocks or algorithms

### Algorithm Sandbox
- Should allows users to develop an algorithm in a sandbox with a node based UI
- Should allows users to backtest that algorithm
  - Should allow users to inspect the orders, balance, max_drawdown, and other metrics related to this algorithm
  - Should show AI summary of the backtest algorithm and provide tips on improving it based on technical level of user
- Should allow users to deploy that algorithm (Can be placebo)
- Should allow users to prompt a inbuilt agent for assistance with crafting an algorithm

### Algorithm Home
- Should have ability to create multiple algorithm sandboxes
- Should have ability for users to edit these sandboxes
- Should have ability for users to view history of iterations for the algorithm (only save iterations that have been backtested)
- Should have total number of programs and overall statistics (post engagement, algorithm statuses, ect.)


1. Create the program to retrieve stock data for 5 years for NASDAQ 100 stocks and store in MongoDB
2. Come up with series of blocks that can be used on frontend to create strategies
3. Write basic algorithm on frontend using the blocks created in #2
4. Write a function that converts the block code to assembly (translation logic - basic)
5. Create unit tests for #4 to ensure robust implementation for translation logic
6. Test preliminary program compiling on FPGA
7. Create OP Codes for FPGA
8. Run a sample program on FPGA and get results
9. Make the main endpoint for taking in JSON algorithm, parsing it, running the aseembly on FPGA, getting results
