# M4ntis Strategy Sandbox (frontend)

A React Flow block language for building trading strategies that compile to the FPGA ISA.
Built with React + TypeScript + Vite and [`@xyflow/react`](https://reactflow.dev) v12.

```bash
npm install
npm run dev               # http://localhost:5173
npm run build
npm run export:examples   # regenerate examples/*.json from the templates + catalog
```

## Layout

| Path | What it is |
| --- | --- |
| `src/blocks/catalog.ts` | **Single source of truth** for every block: ports, params, opcode, hardware status |
| `src/blocks/hardware.ts` | Hardware limits (buffer count, variable slots, max lookback) |
| `src/flow/BlockNode.tsx` | One generic React Flow node that renders any block from its definition |
| `src/flow/graph.ts` | Node/edge factories, connection rules, graph diagnostics |
| `src/flow/serialize.ts` | Strategy document (save/load) and compiler IR |
| `src/flow/templates.ts` | Preset strategies |
| `examples/` | Generated JSON: block catalog, and each template as document + IR |

## Language rules

- **Exec ports** (white triangles, top-in / bottom-out) set instruction order. An exec output has
  exactly one successor; an exec input may have many (branches can re-converge).
- **Data ports** (blue circles, left-in / right-out) carry a register value. A data input has exactly
  one source; a data output can fan out. Dropping a new wire onto an occupied port replaces it.
- Exec never connects to data. Neither kind may form a cycle. The per-tick loop-back
  (`UPDATEALLSTOCKBUFFERS` + `JMP LOOP`) is appended by the compiler wherever the exec chain
  dead-ends, and a For body loops back implicitly.
- Comparisons are not values. They only exist inside the If block's condition panel. AND = nest an If
  in Then, OR = chain an If in Else.
- `Start` is auto-placed and can't be moved or deleted.
- Blocks with no confirmed opcode (`Price N Days Ago`, `Power`, `Root`, `Log`, `Momentum`,
  `Volatility`, `Mean Reversion Bands`) can be placed but show **NEEDS HW** and raise a compile error.

The **Checks** tab lists live diagnostics: blocked blocks, unconnected inputs, blocks unreachable from
Start, variables read but never set, slot overflow (For loops use a hidden counter slot), and
strategies that never trade. Click a diagnostic to jump to its block.

## JSON formats

The side panel shows all of these live, with copy and download.

### 1. Strategy document (`m4ntis.strategy/v1`)

What gets saved and what the backend should store. It's React Flow's `nodes`/`edges` with UI state
stripped out. The node `type` is the block type, and `data.params` holds the block's settings.
Handle ids are `"<kind>:<port>"`, so the port kind can be read straight off an edge.

```json
{
  "schema": "m4ntis.strategy/v1",
  "name": "SMA Crossover",
  "savedAt": "2026-01-01T00:00:00.000Z",
  "flow": {
    "nodes": [
      { "id": "start", "type": "start", "position": { "x": 0, "y": 0 },
        "data": { "params": { "startingBalance": 100000 } } },
      { "id": "sma_fast", "type": "sma", "position": { "x": -420, "y": 120 },
        "data": { "params": { "buffer": 0, "n": 10 } } },
      { "id": "if_cross", "type": "if", "position": { "x": 0, "y": 170 },
        "data": { "params": { "operator": ">" } } },
      { "id": "buy", "type": "buy", "position": { "x": -160, "y": 440 },
        "data": { "params": { "buffer": 0, "quantity": 10 } } }
    ],
    "edges": [
      { "id": "e_start.exec:out__if_cross.exec:in",
        "source": "start", "sourceHandle": "exec:out",
        "target": "if_cross", "targetHandle": "exec:in", "data": { "kind": "exec" } },
      { "id": "e_sma_fast.data:out__if_cross.data:a",
        "source": "sma_fast", "sourceHandle": "data:out",
        "target": "if_cross", "targetHandle": "data:a", "data": { "kind": "data" } },
      { "id": "e_if_cross.exec:then__buy.exec:in",
        "source": "if_cross", "sourceHandle": "exec:then",
        "target": "buy", "targetHandle": "exec:in", "data": { "kind": "exec" } }
    ]
  }
}
```

(Trimmed. See `examples/sma_crossover.strategy.json` for the full file.)

### 2. Compiler IR (`m4ntis.strategy-ir/v1`)

A resolved view meant for the assembly generator. Exec blocks come first in BFS order from Start,
then data blocks in dependency order. `inputs` gives the node/port that feeds each data input.
`next` gives the successor of each exec output, where `null` is a dead end that the compiler turns
into a tick end (or a For loop-back).

```json
{
  "schema": "m4ntis.strategy-ir/v1",
  "entry": "start",
  "nodes": [
    { "id": "if_cross", "type": "if", "params": { "operator": ">" },
      "inputs": { "a": { "node": "sma_fast", "port": "out" },
                  "b": { "node": "sma_slow", "port": "out" } },
      "next": { "then": "buy", "else": "sell" },
      "compilesTo": "GT | LT | SUB → BR / JMP", "status": "confirmed" },
    { "id": "buy", "type": "buy", "params": { "buffer": 0, "quantity": 10 },
      "inputs": {}, "next": { "out": null }, "...": "..." }
  ],
  "unreachable": [],
  "variableSlots": [],
  "blockedBlocks": []
}
```

### 3. Block catalog

`examples/block_catalog.json` (also in the **Catalog** tab) is `BLOCK_DEFS` serialized: every block's
ports, params with defaults and ranges, opcode mapping, and status.

### Block reference (ports and params)

| Type | Exec in | Exec out | Data in | Data out | Params |
| --- | --- | --- | --- | --- | --- |
| `start` | | `out` | | | `startingBalance` |
| `current_price` | | | | `out` | `buffer` |
| `sum_last_n` | | | | `out` | `buffer`, `n` |
| `price_n_days_ago` ⚠ | | | | `out` | `buffer`, `n` |
| `constant` | | | | `out` | `value` |
| `set_var` | `in` | `out` | `value` | | `slot` |
| `get_var` | | | | `out` | `slot` |
| `add` `subtract` `multiply` `divide` | | | `a`, `b` | `out` | |
| `power` ⚠ | | | `base`, `exp` | `out` | |
| `root` ⚠ / `log` ⚠ | | | `x`, `base` | `out` | |
| `if` | `in` | `then`, `else` | `a`, `b` | | `operator` (`>` `>=` `<` `<=` `==` `!=`) |
| `for` | `in` | `body`, `after` | | `index` | `start`, `end`, `step` |
| `buy` / `sell` | `in` | `out` | | | `buffer`, `quantity` |
| `sma` | | | | `out` | `buffer`, `n` |
| `momentum` ⚠ / `volatility` ⚠ | | | | `out` | `buffer`, `n` |
| `mean_reversion_bands` ⚠ | | | | `upper`, `middle`, `lower` | `buffer`, `n`, `k` |

⚠ = no confirmed hardware opcode yet.
