import type { Edge, Node } from '@xyflow/react';

/** Exec ports sequence opcodes (chevrons, top-in / bottom-out). Data ports carry register values (circles, left-in / right-out). */
export type PortKind = 'exec' | 'data';
export type PortDirection = 'in' | 'out';

/** `confirmed` = opcode exists in the current ISA; `blocked` = needs hardware support before it can be compiled. */
export type BlockStatus = 'confirmed' | 'blocked';

export type BlockCategory =
  | 'structure'
  | 'reserved'
  | 'variables'
  | 'math'
  | 'control'
  | 'trade'
  | 'composite';

export type BlockType =
  | 'start'
  | 'current_price'
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
  | 'mean_reversion_bands';

/**
 * Handle ids are `${kind}:${name}` (e.g. `exec:then`, `data:a`) so the port kind can be
 * recovered from any React Flow edge without looking up the block definition.
 */
export type HandleId = `${PortKind}:${string}`;

export interface PortDef {
  id: HandleId;
  kind: PortKind;
  direction: PortDirection;
  label?: string;
}

export type ParamValue = number | string;

interface ParamBase {
  key: string;
  label: string;
}

export interface NumberParamDef extends ParamBase {
  type: 'number';
  default: number;
  min?: number;
  max?: number;
  step?: number;
  integer?: boolean;
  /** Lookback in ticks: the node shows the equivalent time span at the strategy's resolution. */
  ticks?: boolean;
}

export interface SelectParamDef extends ParamBase {
  type: 'select';
  default: ParamValue;
  options: { value: ParamValue; label: string; hint?: string }[];
}

export type ParamDef = NumberParamDef | SelectParamDef;

export interface BlockDef {
  type: BlockType;
  label: string;
  category: BlockCategory;
  description: string;
  ports: PortDef[];
  params: ParamDef[];
  /** Opcode(s) or macro expansion this block lowers to. */
  compilesTo: string;
  status: BlockStatus;
  statusNote?: string;
  /** Program-structure blocks are auto-placed and cannot be added, moved or deleted by the user. */
  system?: boolean;
  /** If-block: the data inputs + operator are rendered as an inline condition panel. */
  condition?: boolean;
  /** Ticks of buffer history the block reads: 1, N, or N+1 (N = its `n` param). */
  history?: '1' | 'n' | 'n+1';
}

export type BlockData = {
  params: Record<string, ParamValue>;
};

export type BlockNode = Node<BlockData, BlockType>;

export type EdgeData = {
  kind: PortKind;
};

export type BlockEdge = Edge<EdgeData>;
