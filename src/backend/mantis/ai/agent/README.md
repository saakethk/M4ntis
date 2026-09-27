# Strategy agent harness

Lets any chat model build and edit block strategies through tools, one validated
step at a time, instead of emitting a whole graph in one shot.

## How a request runs

1. `AgentHarness.run(request, canvas, history)` wraps the canvas in a `Workspace`
   and sends the model the system prompt (persona, protocol, tool list, block
   catalog) plus the current canvas and the request.
2. The model answers with one JSON object: either
   `{"tool_calls": [{"name": ..., "args": {...}}]}` or `{"reply": "..."}`.
3. Tool calls run in order against the workspace. Results (or errors) go back to the
   model as the next message, and the loop repeats.
4. The loop ends on a `reply`, on plain text (treated as the reply; a fenced
   `{"graph": ...}` in it is applied, for models that answer in one shot), or after
   `max_steps` model turns.
5. The result is the reply, the final graph if anything changed, and a `Step` per
   tool call, which the editor shows under the reply.

## Pieces

- `workspace.py`: the graph being edited. Every mutation is applied to a copy and
  the whole graph is re-validated with `blocks.canvas.normalize_graph`; invalid
  changes raise `ToolError` and leave the graph untouched, so the canvas is always
  placeable. Ports can be named `then` or `exec:then`.
- `tools.py`: `Tool` (name, description, documented args, `run(context, args)`) and
  `ToolRegistry`. `BLOCK_TOOLS` holds `list_blocks`, `view_canvas`, `add_block`,
  `update_block`, `remove_block`, `connect`, `disconnect`, `replace_canvas`, and
  `check_strategy` (compiles the draft and returns diagnostics).
- `harness.py`: the loop, action parsing, and step reporting.

## Why a JSON protocol instead of native function calling

Each vendor's function-calling API differs. Plain JSON in the message works with every
provider behind `ChatClient` without per-vendor code, and it is easy to test with a
scripted fake model (see `tests/test_agent.py`).

## Extending

Register a tool and the harness lists it in the prompt automatically:

```python
from src.backend.mantis.ai.agent import BLOCK_TOOLS, Tool

def count_blocks(ctx, args):
    return len(ctx.workspace.graph["nodes"])

tools = BLOCK_TOOLS.extended(Tool("count_blocks", "Number of blocks on the canvas.", count_blocks))
harness = AgentHarness(complete, system_prompt(tools), tools=tools)
```

A tool should return JSON-serializable data and raise `ToolError` with a message the
model can act on.
