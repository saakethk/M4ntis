import type { Edge, Node } from '@xyflow/react'

/** Exec ports order execution (chevrons, top in / bottom out). Data ports carry values (circles, left in / right out). */
export type PortKind = 'exec' | 'data'
export type PortDirection = 'in' | 'out'

/** `confirmed`: the compiler lowers it. `blocked`: needs hardware support, so it never compiles. */
export type BlockStatus = 'confirmed' | 'blocked'

export type BlockCategory = 'structure' | 'market' | 'variables' | 'math' | 'control' | 'trade' | 'indicator'

export type BlockType =
  | 'start'
  | 'get_ticker'
  | 'sum_n_ticks'
  | 'price_n_ticks_ago'
  | 'constant'
  | 'set_var'
  | 'get_var'
  | 'add'
  | 'subtract'
  | 'multiply'
  | 'divide'
  | 'power'
  | 'sqrt'
  | 'log'
  | 'if'
  | 'for'
  | 'buy'
  | 'sell'
  | 'sma'
  | 'momentum'
  | 'volatility'
  | 'mean_reversion_bands'
  | 'z_score'

/** `${kind}:${name}`, e.g. `exec:then` or `data:a`, so an edge's kind is readable from its handle. */
export type HandleId = `${PortKind}:${string}`

export interface PortDef {
  id: HandleId
  kind: PortKind
  direction: PortDirection
  label?: string
}

export type ParamValue = number | string

interface ParamBase {
  key: string
  label: string
  /** Stored in documents but not shown on the block (legacy fields kept for older strategies). */
  hidden?: boolean
}

export interface NumberParamDef extends ParamBase {
  type: 'number'
  default: number
  min?: number
  max?: number
  step?: number
  integer?: boolean
  /** A lookback in ticks: the block shows the equivalent time at the strategy's resolution. */
  ticks?: boolean
}

export interface SelectParamDef extends ParamBase {
  type: 'select'
  default: ParamValue
  options: { value: ParamValue; label: string }[]
}

/** A stock symbol chosen with ticker search. */
export interface TickerParamDef extends ParamBase {
  type: 'ticker'
  default: string
}

export type ParamDef = NumberParamDef | SelectParamDef | TickerParamDef

export interface BlockDef {
  type: BlockType
  label: string
  category: BlockCategory
  description: string
  ports: PortDef[]
  params: ParamDef[]
  /** What the compiler lowers this block to (shown in the block's tooltip). */
  compilesTo: string
  status: BlockStatus
  statusNote?: string
  /** Placed automatically; cannot be added from the palette or deleted. */
  system?: boolean
  /** Ticks of history the block reads: 1, N, or N+1 (N is its `n` param). */
  history?: '1' | 'n' | 'n+1'
}

export type BlockData = {
  params: Record<string, ParamValue>
}

export type BlockNode = Node<BlockData, BlockType>

export type EdgeData = {
  kind: PortKind
}

export type BlockEdge = Edge<EdgeData>
