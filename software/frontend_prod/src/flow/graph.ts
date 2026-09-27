import { BLOCK_DEFS, defaultParams, historyTicks, isDataBlock, portsOf } from '../blocks/catalog.ts';
import { NUM_STOCK_BUFFERS, NUM_VAR_SLOTS, ticksToDuration } from '../blocks/hardware.ts';
import type {
  BlockEdge,
  BlockNode,
  BlockType,
  ParamValue,
  PortKind,
} from '../blocks/types.ts';

export const START_NODE_ID = 'start';

let idCounter = 0;
export function newNodeId(type: BlockType) {
  idCounter += 1;
  return `${type}_${Date.now().toString(36)}${idCounter.toString(36)}`;
}

export function makeNode(
  type: BlockType,
  position: { x: number; y: number },
  params: Record<string, ParamValue> = {},
  id: string = type === 'start' ? START_NODE_ID : newNodeId(type),
): BlockNode {
  const system = BLOCK_DEFS[type].system === true;
  return {
    id,
    type,
    position,
    data: { params: { ...defaultParams(type), ...params } },
    ...(system ? { draggable: false, deletable: false } : {}),
  };
}

export function portKind(handleId: string | null | undefined): PortKind | null {
  const kind = handleId?.split(':')[0];
  return kind === 'exec' || kind === 'data' ? kind : null;
}

export function makeEdge(
  source: string,
  sourceHandle: string,
  target: string,
  targetHandle: string,
): BlockEdge {
  const kind = portKind(sourceHandle) ?? 'data';
  return hydrateEdge({
    id: `e_${source}.${sourceHandle}__${target}.${targetHandle}`,
    source,
    sourceHandle,
    target,
    targetHandle,
    data: { kind },
  });
}

/** Re-applies visual props that are derived from the edge kind (not persisted in JSON). */
export function hydrateEdge(edge: BlockEdge): BlockEdge {
  const kind = edge.data?.kind ?? portKind(edge.sourceHandle) ?? 'data';
  return {
    ...edge,
    data: { kind },
    type: kind === 'exec' ? 'smoothstep' : 'default',
    className: `edge-${kind}`,
    markerEnd: undefined,
    markerStart: undefined,
    // Leave the chevron straight down, then step across, then enter straight up.
    ...(kind === 'exec' ? { pathOptions: { borderRadius: 8, offset: 28 } } : {}),
  };
}

interface ConnectionLike {
  source: string | null;
  target: string | null;
  sourceHandle?: string | null;
  targetHandle?: string | null;
}

function reaches(from: string, to: string, edges: BlockEdge[], kind: PortKind) {
  const stack = [from];
  const seen = new Set<string>();
  while (stack.length) {
    const cur = stack.pop()!;
    if (cur === to) return true;
    if (seen.has(cur)) continue;
    seen.add(cur);
    for (const e of edges) {
      if (e.source === cur && e.data?.kind === kind) stack.push(e.target);
    }
  }
  return false;
}

/**
 * Exec → exec and data → data only; no cycles of either kind. Exec loop-back is owned by the
 * compiler (tick end and For-body both loop implicitly), so users can never wire one.
 */
export function checkConnection(conn: ConnectionLike, edges: BlockEdge[]): string | null {
  if (!conn.source || !conn.target) return 'Incomplete connection';
  if (conn.source === conn.target) return 'A block cannot connect to itself';
  const sk = portKind(conn.sourceHandle);
  const tk = portKind(conn.targetHandle);
  if (!sk || !tk || sk !== tk) return 'Exec ports only connect to exec ports, data to data';
  const others = edges.filter((e) => !isReplacedBy(e, conn, sk));
  if (reaches(conn.target, conn.source, others, sk)) {
    return sk === 'exec'
      ? 'Exec loops are added by the compiler; use a For block for in-tick loops'
      : 'Data connections cannot form a cycle';
  }
  return null;
}

/** A data input and an exec output each accept exactly one edge; a new connection replaces the old one. */
function isReplacedBy(edge: BlockEdge, conn: ConnectionLike, kind: PortKind) {
  if (kind === 'data') return edge.target === conn.target && edge.targetHandle === conn.targetHandle;
  return edge.source === conn.source && edge.sourceHandle === conn.sourceHandle;
}

export function connect(conn: ConnectionLike, edges: BlockEdge[]): BlockEdge[] {
  const kind = portKind(conn.sourceHandle);
  if (!kind || checkConnection(conn, edges)) return edges;
  const kept = edges.filter((e) => !isReplacedBy(e, conn, kind));
  return [...kept, makeEdge(conn.source!, conn.sourceHandle!, conn.target!, conn.targetHandle!)];
}

export type DiagnosticLevel = 'error' | 'warning' | 'info';

export interface Diagnostic {
  level: DiagnosticLevel;
  message: string;
  nodeId?: string;
}

export function reachableExecNodes(nodes: BlockNode[], edges: BlockEdge[]) {
  const execEdges = edges.filter((e) => e.data?.kind === 'exec');
  const seen = new Set<string>();
  const queue = nodes.some((n) => n.id === START_NODE_ID) ? [START_NODE_ID] : [];
  const order: string[] = [];
  while (queue.length) {
    const id = queue.shift()!;
    if (seen.has(id)) continue;
    seen.add(id);
    order.push(id);
    for (const e of execEdges) if (e.source === id) queue.push(e.target);
  }
  return order;
}

/** Get ticker blocks in node-id order, capped at the hardware buffer count. */
function tickerNodes(nodes: BlockNode[]): BlockNode[] {
  return nodes
    .filter((n) => n.type === 'get_ticker')
    .sort((a, b) => (a.id < b.id ? -1 : a.id > b.id ? 1 : 0))
    .slice(0, NUM_STOCK_BUFFERS);
}

/** Tickers in Get-ticker creation order. Older graphs keep symbols stored on Start. */
export function tickerSymbols(nodes: BlockNode[]): string[] {
  const tickers = tickerNodes(nodes).map((n) => String(n.data.params.symbol ?? '').trim());
  if (tickers.length > 0) {
    return Array.from({ length: NUM_STOCK_BUFFERS }, (_, i) => tickers[i] ?? '');
  }
  const start = nodes.find((n) => n.id === START_NODE_ID)?.data.params ?? {};
  return Array.from({ length: NUM_STOCK_BUFFERS }, (_, i) => String(start[`symbol${i}`] ?? ''));
}

/**
 * Copy Get ticker symbols onto Start (`symbol0`…) and set each ticker's buffer.
 * Same rules as the compiler's `_bind_tickers`. The canvas is left unchanged.
 */
export function nodesWithBoundTickers(nodes: BlockNode[]): BlockNode[] {
  const tickers = tickerNodes(nodes);
  if (tickers.length === 0) return nodes;
  const bufferById = new Map(tickers.map((n, i) => [n.id, i]));
  return nodes.map((n) => {
    if (n.id === START_NODE_ID) {
      const params = { ...n.data.params };
      for (const [i, ticker] of tickers.entries()) {
        const symbol = String(ticker.data.params.symbol ?? '').trim();
        if (symbol) params[`symbol${i}`] = symbol.toUpperCase();
      }
      return { ...n, data: { ...n.data, params } };
    }
    const buffer = bufferById.get(n.id);
    if (buffer === undefined) return n;
    const symbol = String(n.data.params.symbol ?? '').trim();
    return {
      ...n,
      data: {
        ...n.data,
        params: {
          ...n.data.params,
          buffer,
          ...(symbol ? { symbol: symbol.toUpperCase() } : {}),
        },
      },
    };
  });
}

function cleanSymbol(value: unknown): string {
  return String(value ?? '').trim().toUpperCase();
}

function clampBuffer(value: unknown): number {
  const index = Number(value ?? 0);
  if (!Number.isInteger(index) || index < 0 || index >= NUM_STOCK_BUFFERS) return 0;
  return index;
}

function withSymbolBuffer(node: BlockNode, symbol: string, buffer: number): BlockNode {
  return {
    ...node,
    data: { ...node.data, params: { ...node.data.params, symbol, buffer } },
  };
}

/**
 * Point one block at `symbol` and the hardware buffer that holds it.
 * Graphs with no Get ticker blocks store the symbol on Start. Graphs that
 * already have Get ticker blocks reuse one, or add one while a buffer is free.
 */
export function assignPriceTicker(nodes: BlockNode[], nodeId: string, symbol: string): BlockNode[] {
  const next = cleanSymbol(symbol);
  if (!next) return nodes;
  const target = nodes.find((n) => n.id === nodeId);
  if (!target || target.id === START_NODE_ID) return nodes;
  if (target.type === 'get_ticker') {
    return nodes.map((n) => (n.id === nodeId ? withSymbolBuffer(n, next, clampBuffer(n.data.params.buffer)) : n));
  }

  const tickers = tickerNodes(nodes);
  if (tickers.length === 0) {
    const start = nodes.find((n) => n.id === START_NODE_ID)?.data.params ?? {};
    let buffer = Array.from({ length: NUM_STOCK_BUFFERS }, (_, i) => i).find(
      (i) => cleanSymbol(start[`symbol${i}`]) === next,
    );
    if (buffer === undefined) {
      buffer = Array.from({ length: NUM_STOCK_BUFFERS }, (_, i) => i).find(
        (i) => cleanSymbol(start[`symbol${i}`]) === '',
      );
    }
    if (buffer === undefined) buffer = clampBuffer(target.data.params.buffer);
    return nodes.map((n) => {
      if (n.id === START_NODE_ID) {
        return { ...n, data: { ...n.data, params: { ...n.data.params, [`symbol${buffer}`]: next } } };
      }
      if (n.id === nodeId) return withSymbolBuffer(n, next, buffer);
      return n;
    });
  }

  const existing = tickers.findIndex((n) => cleanSymbol(n.data.params.symbol) === next);
  if (existing >= 0) {
    return nodes.map((n) => (n.id === nodeId ? withSymbolBuffer(n, next, existing) : n));
  }
  if (tickers.length < NUM_STOCK_BUFFERS) {
    const buffer = tickers.length;
    const created = makeNode(
      'get_ticker',
      { x: target.position.x - 240, y: target.position.y },
      { symbol: next, buffer },
    );
    return [...nodes.map((n) => (n.id === nodeId ? withSymbolBuffer(n, next, buffer) : n)), created];
  }

  const buffer = clampBuffer(target.data.params.buffer);
  const slotId = tickers[buffer]?.id;
  return nodes.map((n) => {
    if (n.id === nodeId) return withSymbolBuffer(n, next, buffer);
    if (slotId && n.id === slotId) return withSymbolBuffer(n, next, buffer);
    return n;
  });
}

export function analyze(nodes: BlockNode[], edges: BlockEdge[]): Diagnostic[] {
  const out: Diagnostic[] = [];
  const byId = new Map(nodes.map((n) => [n.id, n]));

  if (!byId.has(START_NODE_ID)) out.push({ level: 'error', message: 'Missing Start block' });

  const reachable = new Set(reachableExecNodes(nodes, edges));
  const consumed = new Set(edges.filter((e) => e.data?.kind === 'data').map((e) => e.source));
  const fedInputs = new Set(
    edges.filter((e) => e.data?.kind === 'data').map((e) => `${e.target}|${e.targetHandle}`),
  );

  const setSlots = new Set<string>();
  const getSlots = new Map<string, string>();
  const startParams = byId.get(START_NODE_ID)?.data.params ?? {};
  const unassignedBuffers = new Map<number, string>();
  let forLoops = 0;
  let trades = 0;
  let history = 1;

  for (const n of nodes) {
    const type = n.type as BlockType;
    const def = BLOCK_DEFS[type];
    if (!def) {
      out.push({ level: 'error', message: `Unknown block type "${n.type}"`, nodeId: n.id });
      continue;
    }

    if (def.status === 'blocked') {
      out.push({
        level: 'error',
        message: `${def.label}: not supported by hardware yet. ${def.statusNote ?? ''}`.trim(),
        nodeId: n.id,
      });
    }

    for (const p of portsOf(type, 'data', 'in')) {
      if (!fedInputs.has(`${n.id}|${p.id}`)) {
        out.push({
          level: 'error',
          message: `${def.label}: input "${p.label ?? p.id}" is not connected`,
          nodeId: n.id,
        });
      }
    }

    if (isDataBlock(type)) {
      if (!consumed.has(n.id)) {
        out.push({ level: 'info', message: `${def.label}: output is unused`, nodeId: n.id });
      }
    } else if (!reachable.has(n.id)) {
      out.push({
        level: 'warning',
        message: `${def.label}: not reachable from Start, will never run`,
        nodeId: n.id,
      });
    }

    if (type === 'set_var') setSlots.add(String(n.data.params.slot));
    if (type === 'get_var') getSlots.set(String(n.data.params.slot), n.id);
    if (type === 'for') forLoops += 1;
    if ((type === 'buy' || type === 'sell') && reachable.has(n.id)) trades += 1;
    if (type === 'for' && Number(n.data.params.step) === 0) {
      out.push({ level: 'error', message: 'For (Range): step cannot be 0', nodeId: n.id });
    }
    if (def.history && (reachable.has(n.id) || (isDataBlock(type) && consumed.has(n.id)))) {
      history = Math.max(history, historyTicks(type, n.data.params));
      const buf = Number(n.data.params.buffer ?? 0);
      if (type !== 'get_ticker' && !tickerSymbols(nodes)[buf]) unassignedBuffers.set(buf, n.id);
    }
  }

  const tickerCount = nodes.filter((n) => n.type === 'get_ticker').length;
  if (tickerCount > NUM_STOCK_BUFFERS) {
    out.push({
      level: 'error',
      message: `Only ${NUM_STOCK_BUFFERS} Get ticker blocks fit. Remove ${tickerCount - NUM_STOCK_BUFFERS}.`,
    });
  }

  for (const [, nodeId] of unassignedBuffers) {
    out.push({
      level: 'error',
      message: 'This block needs a Get ticker for that stock',
      nodeId,
    });
  }

  if (history > 1) {
    const span = ticksToDuration(history - 1, String(startParams.resolution));
    out.push({
      level: 'info',
      message: `Needs ${history} ticks of history: the first ${history - 1} ticks (${span}) are warm-up with no trades`,
    });
  }

  for (const [slot, nodeId] of getSlots) {
    if (!setSlots.has(slot)) {
      out.push({
        level: 'warning',
        message: `Get Variable reads ${slot}, which is never set (reads 0)`,
        nodeId,
      });
    }
  }

  // For loops each consume a hidden counter slot.
  const slotsNeeded = new Set([...setSlots, ...getSlots.keys()]).size + forLoops;
  if (slotsNeeded > NUM_VAR_SLOTS) {
    out.push({
      level: 'error',
      message: `Graph needs ${slotsNeeded} variable slots (incl. ${forLoops} For counters), hardware has ${NUM_VAR_SLOTS}`,
    });
  }

  if (byId.has(START_NODE_ID) && trades === 0) {
    out.push({ level: 'warning', message: 'No reachable Buy or Sell block, strategy never trades' });
  }

  const rank: Record<DiagnosticLevel, number> = { error: 0, warning: 1, info: 2 };
  return out.sort((a, b) => rank[a.level] - rank[b.level]);
}
