// The compact graph format exchanged with the assistant (`POST /llm`):
// blocks are `{id, type, params}` and wires are `{source, sourceHandle, target, targetHandle}`.

import { isBlockType } from '../blocks/catalog.ts'
import type { BlockEdge, BlockNode, ParamValue } from '../blocks/types.ts'
import { START_NODE_ID, connect, makeNode } from './graph.ts'
import { layoutPositions } from './layout.ts'

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

const INVALID = 'Assistant response was not valid.'

/** The canvas as the assistant sees it. Positions and UI state stay in the browser. */
export function canvasSnapshot(nodes: BlockNode[], edges: BlockEdge[]): AssistantGraph {
  return {
    nodes: nodes.map((node) => ({ id: node.id, type: String(node.type), params: { ...node.data.params } })),
    edges: edges
      .filter((edge) => edge.sourceHandle && edge.targetHandle)
      .map((edge) => ({
        source: edge.source,
        sourceHandle: edge.sourceHandle!,
        target: edge.target,
        targetHandle: edge.targetHandle!,
      })),
  }
}

export function readAssistantGraph(body: unknown): AssistantGraph | null {
  if (body == null) return null
  const row = body as { nodes?: unknown; edges?: unknown }
  if (typeof body !== 'object' || !Array.isArray(row.nodes) || !Array.isArray(row.edges)) throw new Error(INVALID)
  return { nodes: row.nodes.map(readNode), edges: row.edges.map(readEdge) }
}

/** Editor nodes and edges for an assistant graph. Blocks already on the canvas keep their position. */
export function applyAssistantGraph(graph: AssistantGraph, previous: BlockNode[] = []): { nodes: BlockNode[]; edges: BlockEdge[] } {
  if (!graph.nodes.some((node) => node.type === 'start')) throw new Error('Assistant graph has no Start block.')
  const nodes = graph.nodes.map((node) => {
    if (!isBlockType(node.type)) throw new Error(`Assistant graph has an unknown block "${node.type}".`)
    return makeNode(node.type, { x: 0, y: 0 }, node.params, node.type === 'start' ? START_NODE_ID : node.id)
  })
  const edges = graph.edges.reduce<BlockEdge[]>((wired, edge) => connect(edge, wired), [])
  const positions = layoutPositions(nodes, edges, previous)
  return { nodes: nodes.map((node) => ({ ...node, position: positions.get(node.id) ?? node.position })), edges }
}

function readNode(body: unknown): AssistantNode {
  const row = body as { id?: unknown; type?: unknown; params?: unknown }
  if (!body || typeof body !== 'object' || typeof row.id !== 'string' || typeof row.type !== 'string') throw new Error(INVALID)
  if (row.params != null && (typeof row.params !== 'object' || Array.isArray(row.params))) throw new Error(INVALID)
  const params: Record<string, ParamValue> = {}
  for (const [key, value] of Object.entries(row.params ?? {})) {
    if (typeof value !== 'string' && typeof value !== 'number') throw new Error(INVALID)
    params[key] = value
  }
  return { id: row.id, type: row.type, params }
}

function readEdge(body: unknown): AssistantEdge {
  const row = body as Partial<Record<keyof AssistantEdge, unknown>>
  if (
    !body ||
    typeof row.source !== 'string' ||
    typeof row.sourceHandle !== 'string' ||
    typeof row.target !== 'string' ||
    typeof row.targetHandle !== 'string'
  ) {
    throw new Error(INVALID)
  }
  return { source: row.source, sourceHandle: row.sourceHandle, target: row.target, targetHandle: row.targetHandle }
}
