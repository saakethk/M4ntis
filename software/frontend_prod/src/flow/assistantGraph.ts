import { isBlockType } from '../blocks/catalog.ts'
import type { BlockEdge, BlockNode, ParamValue } from '../blocks/types.ts'
import { START_NODE_ID, connect, makeNode } from './graph.ts'

export type AssistantNode = {
  id: string
  type: string
  params: Record<string, ParamValue>
}

export type AssistantEdge = {
  source: string
  sourceHandle: string
  target: string
  targetHandle: string
}

export type AssistantGraph = {
  nodes: AssistantNode[]
  edges: AssistantEdge[]
}

const COLUMN = 280
const ROW = 160

/** The canvas as the assistant sees it: ids, block types, params, and ports. */
export function canvasSnapshot(nodes: BlockNode[], edges: BlockEdge[]): AssistantGraph {
  return {
    nodes: nodes.map((node) => ({
      id: node.id,
      type: String(node.type),
      params: { ...node.data.params },
    })),
    edges: edges
      .filter((edge) => edge.sourceHandle && edge.targetHandle)
      .map((edge) => ({
        source: edge.source,
        sourceHandle: edge.sourceHandle ?? '',
        target: edge.target,
        targetHandle: edge.targetHandle ?? '',
      })),
  }
}

export function readAssistantGraph(body: unknown): AssistantGraph | null {
  if (body == null) return null
  if (!body || typeof body !== 'object') throw new Error('Assistant response was not valid.')
  const row = body as { nodes?: unknown; edges?: unknown }
  if (!Array.isArray(row.nodes) || !Array.isArray(row.edges)) {
    throw new Error('Assistant response was not valid.')
  }
  return { nodes: row.nodes.map(readNode), edges: row.edges.map(readEdge) }
}

/** Build editor nodes from an assistant graph. Blocks already on the canvas keep their position. */
export function applyAssistantGraph(
  graph: AssistantGraph,
  previous: BlockNode[] = [],
): { nodes: BlockNode[]; edges: BlockEdge[] } {
  if (!graph.nodes.some((node) => node.type === 'start')) {
    throw new Error('Assistant graph has no Start block.')
  }
  const nodes = graph.nodes.map((node) => {
    if (!isBlockType(node.type)) throw new Error('Assistant graph has an unknown block.')
    const id = node.type === 'start' ? START_NODE_ID : node.id
    return makeNode(node.type, { x: 0, y: 0 }, node.params, id)
  })
  let edges: BlockEdge[] = []
  for (const edge of graph.edges) {
    edges = connect(
      {
        source: edge.source,
        target: edge.target,
        sourceHandle: edge.sourceHandle,
        targetHandle: edge.targetHandle,
      },
      edges,
    )
  }
  const positions = layoutPositions(nodes, edges, previous)
  return {
    nodes: nodes.map((node) => ({ ...node, position: positions.get(node.id) ?? node.position })),
    edges,
  }
}

function readNode(body: unknown): AssistantNode {
  if (!body || typeof body !== 'object') throw new Error('Assistant response was not valid.')
  const row = body as { id?: unknown; type?: unknown; params?: unknown }
  if (typeof row.id !== 'string' || typeof row.type !== 'string') {
    throw new Error('Assistant response was not valid.')
  }
  if (row.params != null && (typeof row.params !== 'object' || Array.isArray(row.params))) {
    throw new Error('Assistant response was not valid.')
  }
  const params: Record<string, ParamValue> = {}
  for (const [key, value] of Object.entries(row.params ?? {})) {
    if (typeof value !== 'string' && typeof value !== 'number') {
      throw new Error('Assistant response was not valid.')
    }
    params[key] = value
  }
  return { id: row.id, type: row.type, params }
}

function readEdge(body: unknown): AssistantEdge {
  if (!body || typeof body !== 'object') throw new Error('Assistant response was not valid.')
  const row = body as {
    source?: unknown
    sourceHandle?: unknown
    target?: unknown
    targetHandle?: unknown
  }
  if (
    typeof row.source !== 'string' ||
    typeof row.sourceHandle !== 'string' ||
    typeof row.target !== 'string' ||
    typeof row.targetHandle !== 'string'
  ) {
    throw new Error('Assistant response was not valid.')
  }
  return {
    source: row.source,
    sourceHandle: row.sourceHandle,
    target: row.target,
    targetHandle: row.targetHandle,
  }
}

function layoutPositions(
  nodes: BlockNode[],
  edges: BlockEdge[],
  previous: BlockNode[],
): Map<string, { x: number; y: number }> {
  const previousAt = new Map(previous.map((node) => [node.id, node.position]))
  const kept = nodes.filter((node) => node.id !== START_NODE_ID && previousAt.has(node.id))
  if (kept.length === 0) return autoLayout(nodes, edges)
  const placed = new Map<string, { x: number; y: number }>()
  for (const node of nodes) {
    const at = previousAt.get(node.id)
    if (at) placed.set(node.id, at)
  }
  const maxX = Math.max(...kept.map((node) => previousAt.get(node.id)?.x ?? 0))
  nodes
    .filter((node) => !placed.has(node.id))
    .forEach((node, index) => placed.set(node.id, { x: maxX + COLUMN, y: index * ROW }))
  return placed
}

function autoLayout(nodes: BlockNode[], edges: BlockEdge[]): Map<string, { x: number; y: number }> {
  const column = new Map<string, number>()
  const depth = new Map<string, number>([[START_NODE_ID, 0]])
  const queue = nodes.some((node) => node.id === START_NODE_ID) ? [START_NODE_ID] : []
  while (queue.length) {
    const id = queue.shift()
    if (!id) break
    const here = depth.get(id) ?? 0
    for (const edge of edges) {
      if (edge.data?.kind !== 'exec' || edge.source !== id || depth.has(edge.target)) continue
      depth.set(edge.target, here + 1)
      queue.push(edge.target)
    }
  }
  for (const [id, value] of depth) column.set(id, value)
  let progressed = true
  while (progressed) {
    progressed = false
    for (const node of nodes) {
      if (column.has(node.id)) continue
      const consumers = edges.filter((edge) => edge.source === node.id && edge.data?.kind === 'data')
      const columns = consumers
        .map((edge) => column.get(edge.target))
        .filter((value): value is number => value != null)
      if (columns.length === 0) continue
      column.set(node.id, Math.min(...columns) - 1)
      progressed = true
    }
  }
  for (const node of nodes) if (!column.has(node.id)) column.set(node.id, -1)
  const min = Math.min(...column.values())
  const rows = new Map<number, number>()
  const positions = new Map<string, { x: number; y: number }>()
  const ordered = [...nodes].sort((a, b) => {
    if (a.id === START_NODE_ID) return -1
    if (b.id === START_NODE_ID) return 1
    return a.id < b.id ? -1 : 1
  })
  for (const node of ordered) {
    const col = (column.get(node.id) ?? 0) - min
    const row = rows.get(col) ?? 0
    rows.set(col, row + 1)
    positions.set(node.id, { x: col * COLUMN, y: row * ROW })
  }
  return positions
}
