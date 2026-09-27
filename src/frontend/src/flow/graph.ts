// Graph primitives: creating blocks and wires, and the rules for connecting them.

import { BLOCK_DEFS, defaultParams } from '../blocks/catalog.ts'
import type { BlockEdge, BlockNode, BlockType, ParamValue, PortKind } from '../blocks/types.ts'

export const START_NODE_ID = 'start'

let idCounter = 0

export function newNodeId(type: BlockType): string {
  idCounter += 1
  return `${type}_${Date.now().toString(36)}${idCounter.toString(36)}`
}

export function makeNode(
  type: BlockType,
  position: { x: number; y: number },
  params: Record<string, ParamValue> = {},
  id: string = type === 'start' ? START_NODE_ID : newNodeId(type),
): BlockNode {
  const system = BLOCK_DEFS[type].system === true
  return {
    id,
    type,
    position,
    data: { params: { ...defaultParams(type), ...params } },
    ...(system ? { deletable: false } : {}),
  }
}

export function portKind(handleId: string | null | undefined): PortKind | null {
  const kind = handleId?.split(':')[0]
  return kind === 'exec' || kind === 'data' ? kind : null
}

export function makeEdge(source: string, sourceHandle: string, target: string, targetHandle: string): BlockEdge {
  return hydrateEdge({
    id: `e_${source}.${sourceHandle}__${target}.${targetHandle}`,
    source,
    sourceHandle,
    target,
    targetHandle,
    data: { kind: portKind(sourceHandle) ?? 'data' },
  })
}

/** Visual props derived from the edge kind. They are not saved, so loading re-applies them. */
export function hydrateEdge(edge: BlockEdge): BlockEdge {
  const kind = edge.data?.kind ?? portKind(edge.sourceHandle) ?? 'data'
  return {
    ...edge,
    data: { kind },
    type: kind === 'exec' ? 'smoothstep' : 'default',
    className: `edge-${kind}`,
    markerEnd: undefined,
    markerStart: undefined,
    // Leave the chevron straight down, step across, then enter straight up.
    ...(kind === 'exec' ? { pathOptions: { borderRadius: 8, offset: 28 } } : {}),
  }
}

export interface ConnectionLike {
  source: string | null
  target: string | null
  sourceHandle?: string | null
  targetHandle?: string | null
}

/**
 * Why a connection is not allowed, or null when it is. Exec connects to exec and data to data,
 * and neither may form a cycle: the compiler owns every loop (the tick loop and For bodies).
 */
export function checkConnection(conn: ConnectionLike, edges: BlockEdge[]): string | null {
  if (!conn.source || !conn.target) return 'Incomplete connection'
  if (conn.source === conn.target) return 'A block cannot connect to itself'
  const kind = portKind(conn.sourceHandle)
  if (!kind || kind !== portKind(conn.targetHandle)) return 'Exec ports only connect to exec ports, data to data'
  const others = edges.filter((edge) => !isReplacedBy(edge, conn, kind))
  if (reaches(conn.target, conn.source, others, kind)) {
    return kind === 'exec'
      ? 'Exec loops are added by the compiler; use a For block for in-tick loops'
      : 'Data connections cannot form a cycle'
  }
  return null
}

/** Add a connection. It replaces the wire already on that data input or exec output. */
export function connect(conn: ConnectionLike, edges: BlockEdge[]): BlockEdge[] {
  const kind = portKind(conn.sourceHandle)
  if (!kind || checkConnection(conn, edges)) return edges
  const kept = edges.filter((edge) => !isReplacedBy(edge, conn, kind))
  return [...kept, makeEdge(conn.source!, conn.sourceHandle!, conn.target!, conn.targetHandle!)]
}

/** Exec blocks reachable from Start, in breadth-first order. */
export function reachableExecNodes(nodes: BlockNode[], edges: BlockEdge[]): string[] {
  const execEdges = edges.filter((edge) => edge.data?.kind === 'exec')
  const seen = new Set<string>()
  const queue = nodes.some((node) => node.id === START_NODE_ID) ? [START_NODE_ID] : []
  const order: string[] = []
  while (queue.length) {
    const id = queue.shift()!
    if (seen.has(id)) continue
    seen.add(id)
    order.push(id)
    for (const edge of execEdges) if (edge.source === id) queue.push(edge.target)
  }
  return order
}

function isReplacedBy(edge: BlockEdge, conn: ConnectionLike, kind: PortKind): boolean {
  if (kind === 'data') return edge.target === conn.target && edge.targetHandle === conn.targetHandle
  return edge.source === conn.source && edge.sourceHandle === conn.sourceHandle
}

function reaches(from: string, to: string, edges: BlockEdge[], kind: PortKind): boolean {
  const stack = [from]
  const seen = new Set<string>()
  while (stack.length) {
    const current = stack.pop()!
    if (current === to) return true
    if (seen.has(current)) continue
    seen.add(current)
    for (const edge of edges) if (edge.source === current && edge.data?.kind === kind) stack.push(edge.target)
  }
  return false
}
