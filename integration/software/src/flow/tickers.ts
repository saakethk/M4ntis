// Which stock each hardware slot (BUF0..BUF4) holds.
//
// Get ticker blocks fill the slots in node-id order; the compiler uses the same
// rule (`_bind_tickers`). Strategies saved before Get ticker existed kept their
// symbols on Start as `symbol0`..`symbol4`, and those still apply when a graph
// has no Get ticker blocks.

import { NUM_STOCK_BUFFERS } from '../blocks/hardware.ts'
import type { BlockNode } from '../blocks/types.ts'
import { START_NODE_ID, makeNode } from './graph.ts'

const SLOTS = Array.from({ length: NUM_STOCK_BUFFERS }, (_, i) => i)

function tickerNodes(nodes: BlockNode[]): BlockNode[] {
  return nodes
    .filter((node) => node.type === 'get_ticker')
    .sort((a, b) => (a.id < b.id ? -1 : a.id > b.id ? 1 : 0))
    .slice(0, NUM_STOCK_BUFFERS)
}

function cleanSymbol(value: unknown): string {
  return String(value ?? '').trim().toUpperCase()
}

function clampBuffer(value: unknown): number {
  const index = Number(value ?? 0)
  return Number.isInteger(index) && index >= 0 && index < NUM_STOCK_BUFFERS ? index : 0
}

function withSymbol(node: BlockNode, symbol: string, buffer: number): BlockNode {
  return { ...node, data: { ...node.data, params: { ...node.data.params, symbol, buffer } } }
}

/** The ticker in each slot ('' when empty). */
export function tickerSymbols(nodes: BlockNode[]): string[] {
  const tickers = tickerNodes(nodes).map((node) => cleanSymbol(node.data.params.symbol))
  if (tickers.length > 0) return SLOTS.map((i) => tickers[i] ?? '')
  const start = nodes.find((node) => node.id === START_NODE_ID)?.data.params ?? {}
  return SLOTS.map((i) => cleanSymbol(start[`symbol${i}`]))
}

/**
 * Copy Get ticker symbols onto Start and set each Get ticker's slot, as the compiler will.
 * Used when saving so the stored document says which stock each slot holds.
 */
export function nodesWithBoundTickers(nodes: BlockNode[]): BlockNode[] {
  const tickers = tickerNodes(nodes)
  if (tickers.length === 0) return nodes
  const slotById = new Map(tickers.map((node, i) => [node.id, i]))
  return nodes.map((node) => {
    if (node.id === START_NODE_ID) {
      const params = { ...node.data.params }
      tickers.forEach((ticker, i) => {
        const symbol = cleanSymbol(ticker.data.params.symbol)
        if (symbol) params[`symbol${i}`] = symbol
      })
      return { ...node, data: { ...node.data, params } }
    }
    const slot = slotById.get(node.id)
    if (slot === undefined) return node
    const symbol = cleanSymbol(node.data.params.symbol)
    return withSymbol(node, symbol || String(node.data.params.symbol ?? ''), slot)
  })
}

/**
 * Point a block that picks its own ticker (Price N Ticks Ago) at `symbol`.
 * Reuses the slot that already holds it, adds a Get ticker while a slot is free,
 * and otherwise retargets the block's current slot.
 */
export function assignPriceTicker(nodes: BlockNode[], nodeId: string, symbol: string): BlockNode[] {
  const next = cleanSymbol(symbol)
  const target = nodes.find((node) => node.id === nodeId)
  if (!next || !target || target.id === START_NODE_ID) return nodes
  const replace = (id: string, buffer: number) => (node: BlockNode) => (node.id === id ? withSymbol(node, next, buffer) : node)

  if (target.type === 'get_ticker') return nodes.map(replace(nodeId, clampBuffer(target.data.params.buffer)))

  const tickers = tickerNodes(nodes)
  if (tickers.length === 0) {
    const start = nodes.find((node) => node.id === START_NODE_ID)?.data.params ?? {}
    const buffer =
      SLOTS.find((i) => cleanSymbol(start[`symbol${i}`]) === next) ??
      SLOTS.find((i) => cleanSymbol(start[`symbol${i}`]) === '') ??
      clampBuffer(target.data.params.buffer)
    return nodes.map((node) => {
      if (node.id === START_NODE_ID) {
        return { ...node, data: { ...node.data, params: { ...node.data.params, [`symbol${buffer}`]: next } } }
      }
      return replace(nodeId, buffer)(node)
    })
  }

  const existing = tickers.findIndex((node) => cleanSymbol(node.data.params.symbol) === next)
  if (existing >= 0) return nodes.map(replace(nodeId, existing))
  if (tickers.length < NUM_STOCK_BUFFERS) {
    const buffer = tickers.length
    const created = makeNode('get_ticker', { x: target.position.x - 240, y: target.position.y }, { symbol: next, buffer })
    return [...nodes.map(replace(nodeId, buffer)), created]
  }
  const buffer = clampBuffer(target.data.params.buffer)
  const slotOwner = tickers[buffer]?.id
  return nodes.map((node) => (node.id === nodeId || node.id === slotOwner ? withSymbol(node, next, buffer) : node))
}
