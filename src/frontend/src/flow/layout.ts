// Automatic block placement for graphs that arrive without positions (from the assistant).

import type { BlockEdge, BlockNode } from '../blocks/types.ts'
import { START_NODE_ID } from './graph.ts'

type Point = { x: number; y: number }

const COLUMN = 280
const ROW = 160

/**
 * Positions for every node. Blocks that were already on the canvas keep their place
 * and new ones line up in a column to the right; a fresh graph is laid out in columns
 * by exec depth from Start, with data blocks one column left of their first consumer.
 */
export function layoutPositions(nodes: BlockNode[], edges: BlockEdge[], previous: BlockNode[] = []): Map<string, Point> {
  const previousAt = new Map(previous.map((node) => [node.id, node.position]))
  const kept = nodes.filter((node) => node.id !== START_NODE_ID && previousAt.has(node.id))
  if (kept.length === 0) return autoLayout(nodes, edges)
  const placed = new Map<string, Point>()
  for (const node of nodes) {
    const at = previousAt.get(node.id)
    if (at) placed.set(node.id, at)
  }
  const right = Math.max(...kept.map((node) => previousAt.get(node.id)?.x ?? 0)) + COLUMN
  nodes.filter((node) => !placed.has(node.id)).forEach((node, index) => placed.set(node.id, { x: right, y: index * ROW }))
  return placed
}

function autoLayout(nodes: BlockNode[], edges: BlockEdge[]): Map<string, Point> {
  const column = new Map<string, number>([[START_NODE_ID, 0]])
  const queue = nodes.some((node) => node.id === START_NODE_ID) ? [START_NODE_ID] : []
  while (queue.length) {
    const id = queue.shift()!
    for (const edge of edges) {
      if (edge.data?.kind !== 'exec' || edge.source !== id || column.has(edge.target)) continue
      column.set(edge.target, (column.get(id) ?? 0) + 1)
      queue.push(edge.target)
    }
  }
  let progressed = true
  while (progressed) {
    progressed = false
    for (const node of nodes) {
      if (column.has(node.id)) continue
      const consumers = edges
        .filter((edge) => edge.source === node.id && edge.data?.kind === 'data')
        .map((edge) => column.get(edge.target))
        .filter((value): value is number => value != null)
      if (consumers.length === 0) continue
      column.set(node.id, Math.min(...consumers) - 1)
      progressed = true
    }
  }
  for (const node of nodes) if (!column.has(node.id)) column.set(node.id, -1)

  const leftmost = Math.min(...column.values())
  const rows = new Map<number, number>()
  const positions = new Map<string, Point>()
  const ordered = [...nodes].sort((a, b) => (a.id === START_NODE_ID ? -1 : b.id === START_NODE_ID ? 1 : a.id < b.id ? -1 : 1))
  for (const node of ordered) {
    const col = (column.get(node.id) ?? 0) - leftmost
    const row = rows.get(col) ?? 0
    rows.set(col, row + 1)
    positions.set(node.id, { x: col * COLUMN, y: row * ROW })
  }
  return positions
}
