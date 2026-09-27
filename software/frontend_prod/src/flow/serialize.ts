import { BLOCK_DEFS, isBlockType, isDataBlock, portsOf } from '../blocks/catalog.ts';
import type {
  BlockEdge,
  BlockNode,
  BlockType,
  ParamValue,
  PortKind,
} from '../blocks/types.ts';
import { START_NODE_ID, hydrateEdge, makeNode, nodesWithBoundTickers, portKind, reachableExecNodes } from './graph.ts';

export const DOCUMENT_SCHEMA = 'm4ntis.strategy/v1';
export const IR_SCHEMA = 'm4ntis.strategy-ir/v1';

/** One React Flow node as persisted. Everything else (selection, measured size, …) is UI state. */
export interface SerializedNode {
  id: string;
  type: BlockType;
  position: { x: number; y: number };
  data: { params: Record<string, ParamValue> };
}

export interface SerializedEdge {
  id: string;
  source: string;
  sourceHandle: string;
  target: string;
  targetHandle: string;
  data: { kind: PortKind };
}

export interface StrategyDocument {
  schema: typeof DOCUMENT_SCHEMA;
  name: string;
  savedAt: string;
  flow: {
    nodes: SerializedNode[];
    edges: SerializedEdge[];
    viewport?: { x: number; y: number; zoom: number };
  };
}

export function toDocument(
  name: string,
  nodes: BlockNode[],
  edges: BlockEdge[],
  viewport?: { x: number; y: number; zoom: number },
): StrategyDocument {
  const bound = nodesWithBoundTickers(nodes);
  return {
    schema: DOCUMENT_SCHEMA,
    name,
    savedAt: new Date().toISOString(),
    flow: {
      nodes: bound.map((n) => ({
        id: n.id,
        type: n.type as BlockType,
        position: { x: Math.round(n.position.x), y: Math.round(n.position.y) },
        data: { params: { ...n.data.params } },
      })),
      edges: edges.map((e) => ({
        id: e.id,
        source: e.source,
        sourceHandle: e.sourceHandle ?? '',
        target: e.target,
        targetHandle: e.targetHandle ?? '',
        data: { kind: e.data?.kind ?? portKind(e.sourceHandle) ?? 'data' },
      })),
      ...(viewport ? { viewport } : {}),
    },
  };
}

export function fromDocument(raw: unknown): { name: string; nodes: BlockNode[]; edges: BlockEdge[] } {
  const doc = raw as Partial<StrategyDocument>;
  if (doc?.schema !== DOCUMENT_SCHEMA || !doc.flow) {
    throw new Error(`Not a ${DOCUMENT_SCHEMA} document`);
  }
  const nodes = (doc.flow.nodes ?? []).map((n) => {
    const stored = String(n.type);
    const type = stored === 'current_price' ? 'get_ticker' : n.type;
    if (!isBlockType(type)) throw new Error(`Unknown block type "${stored}"`);
    const params = { ...(n.data?.params ?? {}) };
    if (stored === 'current_price' && String(params.symbol ?? '').trim() === '') {
      params.symbol = 'AAPL';
    }
    return makeNode(type, n.position, params, n.id);
  });
  if (!nodes.some((n) => n.id === START_NODE_ID)) {
    nodes.unshift(makeNode('start', { x: 0, y: 0 }));
  }
  const ids = new Set(nodes.map((n) => n.id));
  const edges = (doc.flow.edges ?? [])
    .filter((e) => ids.has(e.source) && ids.has(e.target))
    .map((e) => hydrateEdge(e as BlockEdge));
  return { name: doc.name ?? 'Untitled strategy', nodes, edges };
}

const portName = (handleId: string) => handleId.split(':').slice(1).join(':');

export interface IrPortRef {
  node: string;
  port: string;
}

export interface IrNode {
  id: string;
  type: BlockType;
  params: Record<string, ParamValue>;
  /** Data inputs: which node/port produces the register value. */
  inputs: Record<string, IrPortRef | null>;
  /**
   * Exec successors. `null` = dead end: the compiler appends UPDATEALLSTOCKBUFFERS + JMP LOOP
   * (or, inside a For body, jumps back to the loop head).
   */
  next: Record<string, string | null>;
  compilesTo: string;
  status: 'confirmed' | 'blocked';
}

export interface StrategyIR {
  schema: typeof IR_SCHEMA;
  entry: string;
  /** Exec blocks in BFS order from Start, followed by data blocks in dependency order. */
  nodes: IrNode[];
  unreachable: string[];
  variableSlots: string[];
  blockedBlocks: string[];
}

export function toIR(nodes: BlockNode[], edges: BlockEdge[]): StrategyIR {
  nodes = nodesWithBoundTickers(nodes);
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const execOrder = reachableExecNodes(nodes, edges);
  const reachable = new Set(execOrder);

  const dataSources = new Map<string, BlockEdge>();
  const execTargets = new Map<string, string>();
  for (const e of edges) {
    if (e.data?.kind === 'data') dataSources.set(`${e.target}|${e.targetHandle}`, e);
    else execTargets.set(`${e.source}|${e.sourceHandle}`, e.target);
  }

  const dataOrder: string[] = [];
  const visited = new Set<string>();
  const visitData = (id: string) => {
    if (visited.has(id)) return;
    visited.add(id);
    const n = byId.get(id);
    if (!n) return;
    for (const p of portsOf(n.type as BlockType, 'data', 'in')) {
      const src = dataSources.get(`${id}|${p.id}`);
      if (src) visitData(src.source);
    }
    if (isDataBlock(n.type as BlockType)) dataOrder.push(id);
  };
  for (const id of execOrder) visitData(id);
  for (const n of nodes) visitData(n.id);

  const order = [...execOrder, ...dataOrder];
  const rest = nodes.filter((n) => !order.includes(n.id)).map((n) => n.id);

  const irNodes = [...order, ...rest].map((id): IrNode => {
    const n = byId.get(id)!;
    const type = n.type as BlockType;
    const def = BLOCK_DEFS[type];
    const inputs: IrNode['inputs'] = {};
    for (const p of portsOf(type, 'data', 'in')) {
      const src = dataSources.get(`${id}|${p.id}`);
      inputs[portName(p.id)] = src
        ? { node: src.source, port: portName(src.sourceHandle ?? '') }
        : null;
    }
    const next: IrNode['next'] = {};
    for (const p of portsOf(type, 'exec', 'out')) {
      next[portName(p.id)] = execTargets.get(`${id}|${p.id}`) ?? null;
    }
    return {
      id,
      type,
      params: { ...n.data.params },
      inputs,
      next,
      compilesTo: def.compilesTo,
      status: def.status,
    };
  });

  const slots = new Set<string>();
  for (const n of nodes) {
    if (n.type === 'set_var' || n.type === 'get_var') slots.add(String(n.data.params.slot));
  }

  return {
    schema: IR_SCHEMA,
    entry: START_NODE_ID,
    nodes: irNodes,
    unreachable: nodes
      .filter((n) => !isDataBlock(n.type as BlockType) && !reachable.has(n.id))
      .map((n) => n.id),
    variableSlots: [...slots].sort(),
    blockedBlocks: nodes.filter((n) => BLOCK_DEFS[n.type as BlockType]?.status === 'blocked').map((n) => n.id),
  };
}
