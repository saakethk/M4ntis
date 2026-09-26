# Backend Server
This is the code to expose the backend code like the FPGA interface and such to the frontend website.

## Endpoints
- /symbols?q=[query]&limit=[limit]
  - query: user can search either a symbol or stock
  - limit: the max number of results to return
  - result: output a list of the relevant results

## To Run
1. cd software/backend
2. python main.py