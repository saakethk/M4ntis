# Blocks

Everything the backend knows about strategy blocks.

- `catalog.py`: every block type with its ports, parameter ranges, and a
  description. It mirrors the editor's `src/blocks/catalog.ts` (a frontend test
  checks the two list the same types) and feeds the assistant's prompt.
- `canvas.py`: `normalize_graph()` validates a compact graph (`{nodes: [{id, type,
  params}], edges: [...]}`): known types, params in range with defaults filled,
  ports that exist, exec-to-exec and data-to-data only, one wire per exec output
  and data input, no cycles, at most five Get ticker blocks.
- `document.py`: builds a minimal `m4ntis.strategy/v1` document from a canvas graph.
- `macros.py`: composite blocks the compiler doesn't know. `expand_document()`
  replaces each one with a subgraph of compiler blocks, named `<block id>::<part>`
  so diagnostics can be traced back.

## Macro blocks

**Z-Score** = (price − SMA<sub>N</sub>) ÷ Volatility<sub>N</sub>, built from
`current_price`, `sma`, `subtract`, `volatility`, and `divide`. The hardware returns 0
for division by zero, so flat prices read 0.

Adding a macro:

1. Write a function in `macros.py` that returns an `Expansion` (parts, internal
   wires, and which part produces each output) and register it in `MACROS`.
2. Add the block to `catalog.py` with `macro=True`.
3. Add it to the editor catalog (`integration/software/src/blocks/catalog.ts`).
