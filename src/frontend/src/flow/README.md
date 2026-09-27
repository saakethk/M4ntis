# Flow: graph logic

Pure TypeScript over React Flow nodes and edges. Nothing here renders, so all of it
is unit tested in `tests/`.

| Module | Responsibility |
| --- | --- |
| `graph.ts` | Create blocks and wires; connection rules (exec to exec, data to data, no cycles, one wire per input) |
| `tickers.ts` | Which stock each hardware slot BUF0..BUF4 holds. Get ticker blocks fill slots in id order, as the compiler does |
| `analyze.ts` | Instant checks shown in the Checks tab: unconnected inputs, unreachable blocks, missing tickers, warm-up length, variable slots |
| `serialize.ts` | The saved `m4ntis.strategy/v1` document and the derived `m4ntis.strategy-ir/v1` |
| `programFile.ts` | Download and import programs as `.m4ntis.json` files (the same document) |
| `assistantGraph.ts` | The compact graph exchanged with the assistant, and applying its edits to the canvas |
| `layout.ts` | Positions for blocks that arrive without them |
| `templates.ts` | Starter strategies for the editor's Templates menu |
