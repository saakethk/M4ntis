# gt_hacks_fall_26

Mantis: build block-based trading strategies, compile them for the TradeCPU FPGA, backtest, and discuss.

- `integration/`: the web platform (backend and frontend). Start here: [integration/README.md](integration/README.md)
- `software/`: compiler, database loaders, and the earlier prototypes
- `hardware/`: TradeCPU

## How to run

### To run backend server
1. cd src/backend
2. python main.py
3. Ensure FPGA is connected on COM4 with flashed program from hardware

### To run frontend server
1. cd src/frontend
2. npm install
3. npm run dev