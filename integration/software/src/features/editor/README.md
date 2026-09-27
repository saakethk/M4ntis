# Editor

`StrategyEditor.tsx` owns the canvas state (nodes, edges, name, saved and dirty
flags, last compiler result) and composes the pieces around it:

- **Toolbar**: back to Strategies, name, save state, Templates, import and download
  JSON, fit view, delete selected, History, and Save (or **Save a copy** when viewing
  someone else's public strategy, which opens read-only).
- `BlockPalette.tsx`: searchable blocks by category. Click adds at the canvas
  center; drag drops at the cursor. Blocks the hardware can't run are hidden.
- `nodes/`: how each block renders. `BlockNode.tsx` picks a variant (Start, value
  chip, or the general block with header, parameters, If condition, and ports);
  `fields.tsx` and `TickerSearch.tsx` are its inputs.
- **Right rail tabs**:
  - Assistant (`features/assistant`): chat with the agent, see its tool steps, apply its canvas.
  - `ChecksPanel.tsx`: live browser checks plus an on-demand compiler check; clicking
    an item selects and centers the block. Blocks with errors get a red marker.
  - `BacktestPanel.tsx`: what a run will use (from Start and Get ticker blocks), optional start/end dates from
    `GET /backtests/range` (snaps to days with data), whether the TradeCPU FPGA is connected (`GET /backtests/fpga`,
    with Refresh), and **Run on FPGA**, disabled without a board.
- `HistoryPanel.tsx`: saved versions with Restore.
- `TemplateMenu.tsx`: the starter strategies from `flow/templates.ts`.

Saving writes the document and IR, then runs the compiler check automatically.
The Delete and Backspace keys remove selected blocks and wires; Start can't be deleted.
