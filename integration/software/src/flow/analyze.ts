// Instant checks run in the browser as the user edits. The compiler (POST /compile)
// is the final word; these catch the common mistakes without a round trip.

import { BLOCK_DEFS, historyTicks, isDataBlock, portsOf } from '../blocks/catalog.ts'
import { NUM_STOCK_BUFFERS, NUM_VAR_SLOTS, ticksToDuration } from '../blocks/hardware.ts'
import type { BlockEdge, BlockNode, BlockType } from '../blocks/types.ts'
import { START_NODE_ID, reachableExecNodes } from './graph.ts'
import { tickerSymbols } from './tickers.ts'

export type DiagnosticLevel = 'error' | 'warning' | 'info'

export interface Diagnostic {
  level: DiagnosticLevel
  message: string
  nodeId?: string
}

const RANK: Record<DiagnosticLevel, number> = { error: 0, warning: 1, info: 2 }

export function analyze(nodes: BlockNode[], edges: BlockEdge[]): Diagnostic[] {
  const out: Diagnostic[] = []
  const start = nodes.find((node) => node.id === START_NODE_ID)
  if (!start) out.push({ level: 'error', message: 'Missing Start block' })

  const reachable = new Set(reachableExecNodes(nodes, edges))
  const dataEdges = edges.filter((edge) => edge.data?.kind === 'data')
  const consumed = new Set(dataEdges.map((edge) => edge.source))
  const fedInputs = new Set(dataEdges.map((edge) => `${edge.target}|${edge.targetHandle}`))
  const symbols = tickerSymbols(nodes)
  const setSlots = new Set<string>()
  const getSlots = new Map<string, string>()
  const missingTicker = new Map<number, string>()
  let forLoops = 0
  let trades = 0
  let history = 1

  for (const node of nodes) {
    const type = node.type as BlockType
    const def = BLOCK_DEFS[type]
    if (!def) {
      out.push({ level: 'error', message: `Unknown block type "${node.type}"`, nodeId: node.id })
      continue
    }
    const runs = isDataBlock(type) ? consumed.has(node.id) : reachable.has(node.id)
    if (def.status === 'blocked') {
      out.push({ level: 'error', message: `${def.label} is not supported by the hardware. ${def.statusNote ?? ''}`.trim(), nodeId: node.id })
    }
    for (const port of portsOf(type, 'data', 'in')) {
      if (!fedInputs.has(`${node.id}|${port.id}`)) {
        out.push({ level: 'error', message: `${def.label}: input "${port.label ?? port.id}" is not connected`, nodeId: node.id })
      }
    }
    if (!runs) {
      out.push(
        isDataBlock(type)
          ? { level: 'info', message: `${def.label}: output is unused`, nodeId: node.id }
          : { level: 'warning', message: `${def.label}: not reachable from Start, so it never runs`, nodeId: node.id },
      )
    }
    if (type === 'set_var') setSlots.add(String(node.data.params.slot))
    if (type === 'get_var') getSlots.set(String(node.data.params.slot), node.id)
    if (type === 'for') forLoops += 1
    if ((type === 'buy' || type === 'sell') && runs) trades += 1
    if (type === 'for' && Number(node.data.params.step) === 0) {
      out.push({ level: 'error', message: 'For (Range): step cannot be 0', nodeId: node.id })
    }
    if (def.history && runs) {
      history = Math.max(history, historyTicks(type, node.data.params))
      const buffer = Number(node.data.params.buffer ?? 0)
      const ownSymbol = type === 'price_n_ticks_ago' && String(node.data.params.symbol ?? '').trim()
      if (type !== 'get_ticker' && !ownSymbol && !symbols[buffer]) missingTicker.set(buffer, node.id)
    }
  }

  const tickerCount = nodes.filter((node) => node.type === 'get_ticker').length
  if (tickerCount > NUM_STOCK_BUFFERS) {
    out.push({ level: 'error', message: `Only ${NUM_STOCK_BUFFERS} Get ticker blocks fit. Remove ${tickerCount - NUM_STOCK_BUFFERS}.` })
  }
  for (const [buffer, nodeId] of missingTicker) {
    out.push({ level: 'error', message: `Slot BUF${buffer} has no stock. Add a Get ticker block.`, nodeId })
  }
  if (history > 1 && start) {
    const span = ticksToDuration(history - 1, String(start.data.params.resolution))
    out.push({ level: 'info', message: `Needs ${history} ticks of history: the first ${history - 1} (${span}) are warm-up with no trades` })
  }
  for (const [slot, nodeId] of getSlots) {
    if (!setSlots.has(slot)) out.push({ level: 'warning', message: `Get Variable reads ${slot}, which is never set (reads 0)`, nodeId })
  }
  const slotsNeeded = new Set([...setSlots, ...getSlots.keys()]).size + forLoops
  if (slotsNeeded > NUM_VAR_SLOTS) {
    out.push({ level: 'error', message: `Needs ${slotsNeeded} variable slots (${forLoops} for For loops); the hardware has ${NUM_VAR_SLOTS}` })
  }
  if (start && trades === 0) out.push({ level: 'warning', message: 'No reachable Buy or Sell block, so the strategy never trades' })

  return out.sort((a, b) => RANK[a.level] - RANK[b.level])
}
