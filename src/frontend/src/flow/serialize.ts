// Saved formats.
//
// `m4ntis.strategy/v1` is the document: the canvas as the user arranged it. It is
// what the backend stores, what the compiler reads, and what "Export JSON" writes.
// `m4ntis.strategy-ir/v1` is a derived, execution-ordered view stored alongside it.

import { BLOCK_DEFS, isBlockType, isDataBlock, portsOf } from '../blocks/catalog.ts'
import type { BlockEdge, BlockNode, BlockStatus, BlockType, ParamValue, PortKind } from '../blocks/types.ts'
import { START_NODE_ID, hydrateEdge, makeNode, portKind, reachableExecNodes } from './graph.ts'
import { nodesWithBoundTickers } from './tickers.ts'

export const DOCUMENT_SCHEMA = 'm4ntis.strategy/v1'
export const IR_SCHEMA = 'm4ntis.strategy-ir/v1'

export type Viewport = { x: number; y: number; zoom: number }

export interface SerializedNode {
  id: string
  type: BlockType
  position: { x: number; y: number }
  data: { params: Record<string, ParamValue> }
}

export interface SerializedEdge {
  id: string
  source: string
  sourceHandle: string
  target: string
  targetHandle: string
  data: { kind: PortKind }
}

export interface StrategyDocument {
  schema: typeof DOCUMENT_SCHEMA
  name: string
  savedAt: string
  flow: { nodes: SerializedNode[]; edges: SerializedEdge[]; viewport?: Viewport }
}

export type LoadedStrategy = { name: string; nodes: BlockNode[]; edges: BlockEdge[] }

export function toDocument(name: string, nodes: BlockNode[], edges: BlockEdge[], viewport?: Viewport): StrategyDocument {
  return {
    schema: DOCUMENT_SCHEMA,
    name,
    savedAt: new Date().toISOString(),
    flow: {
      nodes: nodesWithBoundTickers(nodes).map((node) => ({
        id: node.id,
        type: node.type as BlockType,
        position: { x: Math.round(node.position.x), y: Math.round(node.position.y) },
        data: { params: { ...node.data.params } },
      })),
      edges: edges.map((edge) => ({
        id: edge.id,
        source: edge.source,
        sourceHandle: edge.sourceHandle ?? '',
        target: edge.target,
        targetHandle: edge.targetHandle ?? '',
        data: { kind: edge.data?.kind ?? portKind(edge.sourceHandle) ?? 'data' },
      })),
      ...(viewport ? { viewport } : {}),
    },
  }
}

/** Read a document into editor nodes and edges. Throws a readable message for anything else. */
export function fromDocument(raw: unknown): LoadedStrategy {
  const doc = raw as Partial<StrategyDocument> | null
  if (!doc || typeof doc !== 'object' || doc.schema !== DOCUMENT_SCHEMA || !doc.flow || typeof doc.flow !== 'object') {
    throw new Error(`Not a ${DOCUMENT_SCHEMA} strategy file.`)
  }
  if (!Array.isArray(doc.flow.nodes) || (doc.flow.edges != null && !Array.isArray(doc.flow.edges))) {
    throw new Error('The strategy file has no blocks.')
  }
  const nodes = doc.flow.nodes.map((node) => {
    if (!node || typeof node !== 'object' || typeof node.id !== 'string') throw new Error('A block in the file has no id.')
    const stored = String(node.type)
    // `current_price` was renamed to `get_ticker`.
    const type = stored === 'current_price' ? 'get_ticker' : stored
    if (!isBlockType(type)) throw new Error(`Unknown block type "${stored}".`)
    const params = { ...(node.data?.params ?? {}) }
    if (stored === 'current_price' && String(params.symbol ?? '').trim() === '') params.symbol = 'AAPL'
    const position = node.position && Number.isFinite(node.position.x) && Number.isFinite(node.position.y) ? node.position : { x: 0, y: 0 }
    return makeNode(type, position, params, node.id)
  })
  if (!nodes.some((node) => node.id === START_NODE_ID)) nodes.unshift(makeNode('start', { x: 0, y: 0 }))
  const ids = new Set(nodes.map((node) => node.id))
  const edges = (doc.flow.edges ?? [])
    .filter((edge) => edge && ids.has(edge.source) && ids.has(edge.target))
    .map((edge) => hydrateEdge(edge as BlockEdge))
  return { name: typeof doc.name === 'string' && doc.name.trim() ? doc.name : 'Untitled strategy', nodes, edges }
}

export interface IrPortRef {
  node: string
  port: string
}

export interface IrNode {
  id: string
  type: BlockType
  params: Record<string, ParamValue>
  /** Data inputs: which node and port produce each value. */
  inputs: Record<string, IrPortRef | null>
  /** Exec successors. `null` ends the tick (or loops back to the For head inside a body). */
  next: Record<string, string | null>
  compilesTo: string
  status: BlockStatus
}

export interface StrategyIR {
  schema: typeof IR_SCHEMA
  entry: string
  /** Exec blocks in breadth-first order from Start, then data blocks in dependency order. */
  nodes: IrNode[]
  unreachable: string[]
  variableSlots: string[]
  blockedBlocks: string[]
}

const portName = (handleId: string) => handleId.split(':').slice(1).join(':')

export function toIR(rawNodes: BlockNode[], edges: BlockEdge[]): StrategyIR {
  const nodes = nodesWithBoundTickers(rawNodes)
  const byId = new Map(nodes.map((node) => [node.id, node]))
  const execOrder = reachableExecNodes(nodes, edges)
  const reachable = new Set(execOrder)
  const dataSources = new Map<string, BlockEdge>()
  const execTargets = new Map<string, string>()
  for (const edge of edges) {
    if (edge.data?.kind === 'data') dataSources.set(`${edge.target}|${edge.targetHandle}`, edge)
    else execTargets.set(`${edge.source}|${edge.sourceHandle}`, edge.target)
  }

  const dataOrder: string[] = []
  const visited = new Set<string>()
  const visitData = (id: string) => {
    if (visited.has(id)) return
    visited.add(id)
    const node = byId.get(id)
    if (!node) return
    for (const port of portsOf(node.type as BlockType, 'data', 'in')) {
      const source = dataSources.get(`${id}|${port.id}`)
      if (source) visitData(source.source)
    }
    if (isDataBlock(node.type as BlockType)) dataOrder.push(id)
  }
  execOrder.forEach(visitData)
  nodes.forEach((node) => visitData(node.id))

  const ordered = [...execOrder, ...dataOrder]
  const rest = nodes.map((node) => node.id).filter((id) => !ordered.includes(id))
  const irNodes = [...ordered, ...rest].map((id): IrNode => {
    const node = byId.get(id)!
    const type = node.type as BlockType
    const inputs: IrNode['inputs'] = {}
    for (const port of portsOf(type, 'data', 'in')) {
      const source = dataSources.get(`${id}|${port.id}`)
      inputs[portName(port.id)] = source ? { node: source.source, port: portName(source.sourceHandle ?? '') } : null
    }
    const next: IrNode['next'] = {}
    for (const port of portsOf(type, 'exec', 'out')) next[portName(port.id)] = execTargets.get(`${id}|${port.id}`) ?? null
    return { id, type, params: { ...node.data.params }, inputs, next, compilesTo: BLOCK_DEFS[type].compilesTo, status: BLOCK_DEFS[type].status }
  })

  const slots = new Set(
    nodes.filter((node) => node.type === 'set_var' || node.type === 'get_var').map((node) => String(node.data.params.slot)),
  )
  return {
    schema: IR_SCHEMA,
    entry: START_NODE_ID,
    nodes: irNodes,
    unreachable: nodes.filter((node) => !isDataBlock(node.type as BlockType) && !reachable.has(node.id)).map((node) => node.id),
    variableSlots: [...slots].sort(),
    blockedBlocks: nodes.filter((node) => BLOCK_DEFS[node.type as BlockType]?.status === 'blocked').map((node) => node.id),
  }
}
