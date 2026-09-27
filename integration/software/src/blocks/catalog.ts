// Every block the editor knows: ports, parameters, and how it compiles.
// Mirrors integration/backend/mantis/blocks/catalog.py (used by the assistant)
// and software/compiler/tradecpu/blocks.py (used by the compiler).

import { BUFFER_DEPTH, NUM_STOCK_BUFFERS, NUM_VAR_SLOTS, RESOLUTIONS } from './hardware.ts'
import type { BlockCategory, BlockDef, BlockType, ParamDef, ParamValue, PortDef } from './types.ts'

const range = (n: number) => Array.from({ length: n }, (_, i) => i)

const EXEC_IN: PortDef = { id: 'exec:in', kind: 'exec', direction: 'in' }
const EXEC_OUT: PortDef = { id: 'exec:out', kind: 'exec', direction: 'out', label: 'next' }
const DATA_OUT: PortDef = { id: 'data:out', kind: 'data', direction: 'out', label: 'value' }
const dataIn = (name: string, label = name): PortDef => ({ id: `data:${name}`, kind: 'data', direction: 'in', label })
const dataOut = (name: string, label = name): PortDef => ({ id: `data:${name}`, kind: 'data', direction: 'out', label })
const execOut = (name: string, label = name): PortDef => ({ id: `exec:${name}`, kind: 'exec', direction: 'out', label })

/** Which stock slot a block reads. The editor labels each option with that slot's ticker. */
const bufferParam: ParamDef = {
  key: 'buffer',
  label: 'Ticker',
  type: 'select',
  default: 0,
  options: range(NUM_STOCK_BUFFERS).map((i) => ({ value: i, label: `BUF${i}` })),
}

/** GETSUMPRICEBEFORE sums the N most recent entries, so N can be the full buffer depth. */
const windowParam = (defaultTicks: number, min = 1, max = BUFFER_DEPTH): ParamDef => ({
  key: 'n',
  label: 'N (ticks)',
  type: 'number',
  default: defaultTicks,
  min,
  max,
  integer: true,
  ticks: true,
})

/** GETSTOCKPRICEBEFORE offset 30 wraps back to the current tick, so 29 is the furthest back. */
const offsetParam = (defaultTicks: number): ParamDef => windowParam(defaultTicks, 1, BUFFER_DEPTH - 1)

/** Loop bounds are loaded with LOAD_IMM, a 16-bit signed immediate. */
const IMM16 = { min: -32768, max: 32767, integer: true } as const

const slotParam: ParamDef = {
  key: 'slot',
  label: 'Slot',
  type: 'select',
  default: 'VAR1',
  options: range(NUM_VAR_SLOTS).map((i) => ({ value: `VAR${i + 1}`, label: `VAR${i + 1}` })),
}

const quantityParam: ParamDef = { key: 'quantity', label: 'Quantity', type: 'number', default: 10, min: 1, max: 32767, integer: true }

/** Older strategies stored slot tickers on Start. Get ticker blocks replaced them. */
const legacySymbolParam = (buffer: number): ParamDef => ({
  key: `symbol${buffer}`,
  label: `BUF${buffer}`,
  type: 'ticker',
  default: '',
  hidden: true,
})

export const COMPARISON_OPERATORS = [
  { value: '>', label: '>' },
  { value: '>=', label: '≥' },
  { value: '<', label: '<' },
  { value: '<=', label: '≤' },
  { value: '==', label: '=' },
  { value: '!=', label: '≠' },
] as const

const binaryMath = (type: BlockType, label: string, symbol: string, opcode: string, note?: string): BlockDef => ({
  type,
  label,
  category: 'math',
  description: `A ${symbol} B`,
  ports: [dataIn('a', 'A'), dataIn('b', 'B'), DATA_OUT],
  params: [],
  compilesTo: opcode,
  status: 'confirmed',
  statusNote: note,
})

export const BLOCK_DEFS: Record<BlockType, BlockDef> = {
  start: {
    type: 'start',
    label: 'Start',
    category: 'structure',
    description: 'Runs once per tick. The compiler adds the tick loop, warm-up and per-tick acknowledgement.',
    ports: [{ ...EXEC_OUT, label: 'each tick' }],
    params: [
      { key: 'startingBalance', label: 'Balance ($)', type: 'number', default: 100000, min: 0, max: 21000000 },
      {
        key: 'resolution',
        label: 'Every',
        type: 'select',
        default: '5m',
        options: RESOLUTIONS.map((r) => ({ value: r.value, label: r.label })),
      },
      ...range(NUM_STOCK_BUFFERS).map(legacySymbolParam),
    ],
    compilesTo: 'SETBALANCE, warm-up, UPDATEALLSTOCKBUFFERS loop',
    status: 'confirmed',
    system: true,
  },

  get_ticker: {
    type: 'get_ticker',
    label: 'Get ticker',
    category: 'market',
    description: 'Current price of one stock. Each Get ticker fills the next stock slot (BUF0 to BUF4).',
    ports: [dataOut('out', 'price')],
    params: [{ key: 'symbol', label: 'Ticker', type: 'ticker', default: 'AAPL' }, { ...bufferParam, hidden: true }],
    compilesTo: 'GETSTOCKPRICE',
    status: 'confirmed',
    history: '1',
  },
  sum_n_ticks: {
    type: 'sum_n_ticks',
    label: 'Sum of Last N Ticks',
    category: 'market',
    description: 'Sum of the N most recent prices, including the current tick.',
    ports: [DATA_OUT],
    params: [bufferParam, windowParam(20)],
    compilesTo: 'GETSUMPRICEBEFORE',
    status: 'confirmed',
    history: 'n',
  },
  price_n_ticks_ago: {
    type: 'price_n_ticks_ago',
    label: 'Price N Ticks Ago',
    category: 'market',
    description: 'Price N ticks before the current one.',
    ports: [DATA_OUT],
    // Picking a ticker sets `buffer` to the slot that holds it (see flow/tickers.ts).
    params: [{ key: 'symbol', label: 'Ticker', type: 'ticker', default: '' }, { ...bufferParam, hidden: true }, offsetParam(10)],
    compilesTo: 'GETSTOCKPRICEBEFORE',
    status: 'confirmed',
    history: 'n+1',
  },
  constant: {
    type: 'constant',
    label: 'Constant',
    category: 'market',
    description: 'A literal number. Prices are in dollars, so 150.25 means $150.25.',
    ports: [DATA_OUT],
    params: [{ key: 'value', label: 'Value', type: 'number', default: 0 }],
    compilesTo: 'LOAD_IMM (scaled to fixed point)',
    status: 'confirmed',
  },

  set_var: {
    type: 'set_var',
    label: 'Set Variable',
    category: 'variables',
    description: 'Store a value in a variable slot. Values persist from tick to tick.',
    ports: [EXEC_IN, dataIn('value', 'value'), EXEC_OUT],
    params: [slotParam],
    compilesTo: 'ASSIGNVAR',
    status: 'confirmed',
  },
  get_var: {
    type: 'get_var',
    label: 'Get Variable',
    category: 'variables',
    description: 'Read a variable slot.',
    ports: [DATA_OUT],
    params: [slotParam],
    compilesTo: 'GETVAR',
    status: 'confirmed',
  },

  add: binaryMath('add', 'Add', '+', 'ADD'),
  subtract: binaryMath('subtract', 'Subtract', '−', 'SUB'),
  multiply: binaryMath('multiply', 'Multiply', '×', 'MUL'),
  divide: binaryMath('divide', 'Divide', '÷', 'MUL ×100 → DIV', 'The numerator is pre-scaled so ratios keep 2 decimals.'),
  power: {
    type: 'power',
    label: 'Power',
    category: 'math',
    description: 'base ^ exponent (whole-number exponent).',
    ports: [dataIn('base'), DATA_OUT],
    params: [{ key: 'exponent', label: 'Exponent', type: 'number', default: 2, min: 0, max: 8, integer: true }],
    compilesTo: 'repeated MUL',
    status: 'confirmed',
  },
  sqrt: {
    type: 'sqrt',
    label: 'Square Root',
    category: 'math',
    description: '√x, to 2 decimal places.',
    ports: [dataIn('x'), DATA_OUT],
    params: [],
    compilesTo: 'integer Newton loop (DIV, CMP_LT, JMP_IF)',
    status: 'confirmed',
  },
  log: {
    type: 'log',
    label: 'Log',
    category: 'math',
    description: 'Logarithm of x in the given base.',
    ports: [dataIn('x'), dataIn('base'), DATA_OUT],
    params: [],
    compilesTo: '—',
    status: 'blocked',
    statusNote: 'No opcode and no practical integer expansion on this ISA.',
  },

  if: {
    type: 'if',
    label: 'If / Else',
    category: 'control',
    description: 'Branch on a comparison. For AND nest a second If in Then; for OR chain it in Else.',
    ports: [EXEC_IN, dataIn('a', 'A'), dataIn('b', 'B'), execOut('then', 'Then'), execOut('else', 'Else')],
    params: [
      { key: 'operator', label: 'Operator', type: 'select', default: '>', options: COMPARISON_OPERATORS.map((o) => ({ ...o })) },
    ],
    compilesTo: 'CMP_GT | CMP_LT | SUB → JMP_IF',
    status: 'confirmed',
  },
  for: {
    type: 'for',
    label: 'For (Range)',
    category: 'control',
    description: 'Runs Body for each i in [start, end) within one tick. Not for walking back through history.',
    ports: [EXEC_IN, dataOut('index', 'i'), execOut('body', 'Body ↻'), execOut('after', 'After')],
    params: [
      { key: 'start', label: 'Start', type: 'number', default: 0, ...IMM16 },
      { key: 'end', label: 'End', type: 'number', default: 10, ...IMM16 },
      { key: 'step', label: 'Step', type: 'number', default: 1, ...IMM16 },
    ],
    compilesTo: 'counter in a spare VAR, CMP_LT/GT bound, ADD step, JMP back',
    status: 'confirmed',
  },

  buy: {
    type: 'buy',
    label: 'Buy',
    category: 'trade',
    description: 'Buy shares at the current price.',
    ports: [EXEC_IN, EXEC_OUT],
    params: [bufferParam, quantityParam],
    compilesTo: 'GETSTOCKPRICE → MUL → UPDATEBALANCE → EMITDECISION(qty, buf, 1)',
    status: 'confirmed',
    history: '1',
  },
  sell: {
    type: 'sell',
    label: 'Sell',
    category: 'trade',
    description: 'Sell shares at the current price.',
    ports: [EXEC_IN, EXEC_OUT],
    params: [bufferParam, quantityParam],
    compilesTo: 'GETSTOCKPRICE → MUL → negate → UPDATEBALANCE → EMITDECISION(qty, buf, 0)',
    status: 'confirmed',
    history: '1',
  },

  sma: {
    type: 'sma',
    label: 'SMA',
    category: 'indicator',
    description: 'Simple moving average over the last N ticks.',
    ports: [DATA_OUT],
    params: [bufferParam, windowParam(20)],
    compilesTo: 'GETSUMPRICEBEFORE ÷ N',
    status: 'confirmed',
    history: 'n',
  },
  momentum: {
    type: 'momentum',
    label: 'Momentum',
    category: 'indicator',
    description: 'Fractional change over N ticks: 0.05 means up 5%.',
    ports: [DATA_OUT],
    params: [bufferParam, offsetParam(10)],
    compilesTo: '(price × 100 ÷ price N ticks ago) − 100',
    status: 'confirmed',
    history: 'n+1',
  },
  volatility: {
    type: 'volatility',
    label: 'Volatility',
    category: 'indicator',
    description: 'Sample standard deviation of price over the last N ticks, in dollars.',
    ports: [DATA_OUT],
    params: [bufferParam, windowParam(20, 2)],
    compilesTo: 'unrolled Σ(price − mean)² ÷ (N − 1), integer sqrt',
    status: 'confirmed',
    statusNote: 'About 4N + 30 instructions per use; cache it in a variable if several blocks need it.',
    history: 'n',
  },
  mean_reversion_bands: {
    type: 'mean_reversion_bands',
    label: 'Mean Reversion Bands',
    category: 'indicator',
    description: 'SMA ± k × Volatility. Pair with two If blocks: ≤ lower → Buy, ≥ upper → Sell.',
    ports: [dataOut('upper', 'upper'), dataOut('middle', 'middle'), dataOut('lower', 'lower')],
    params: [bufferParam, windowParam(20, 2), { key: 'k', label: 'k (std devs)', type: 'number', default: 2, min: 0, max: 10, step: 0.1 }],
    compilesTo: 'SMA ± k × Volatility',
    status: 'confirmed',
    statusNote: 'Upper and lower each expand Volatility; about 4N + 40 instructions per band used.',
    history: 'n',
  },
  z_score: {
    type: 'z_score',
    label: 'Z-Score',
    category: 'indicator',
    description: 'How many standard deviations the price is from its N-tick SMA. Below −2 is unusually cheap, above 2 unusually rich.',
    ports: [dataOut('out', 'z')],
    params: [bufferParam, windowParam(20, 2)],
    compilesTo: '(price − SMA) ÷ Volatility (expanded by the backend before compiling)',
    status: 'confirmed',
    statusNote: 'About 4N + 40 instructions. Reads 0 while prices are flat.',
    history: 'n',
  },
}

export const BLOCK_TYPES = Object.keys(BLOCK_DEFS) as BlockType[]

export const CATEGORIES: { id: BlockCategory; label: string }[] = [
  { id: 'structure', label: 'Program' },
  { id: 'market', label: 'Market Data' },
  { id: 'indicator', label: 'Indicators' },
  { id: 'control', label: 'Control Flow' },
  { id: 'trade', label: 'Trade Actions' },
  { id: 'math', label: 'Math' },
  { id: 'variables', label: 'Variables' },
]

/** Blocks a user can add: not placed automatically, and able to compile. */
export const PALETTE_BLOCKS: BlockDef[] = BLOCK_TYPES.map((type) => BLOCK_DEFS[type]).filter(
  (block) => !block.system && block.status !== 'blocked',
)

export function defaultParams(type: BlockType): Record<string, ParamValue> {
  return Object.fromEntries(BLOCK_DEFS[type].params.map((p) => [p.key, p.default]))
}

export function isBlockType(value: unknown): value is BlockType {
  return typeof value === 'string' && value in BLOCK_DEFS
}

export function portsOf(type: BlockType, kind: PortDef['kind'], direction: PortDef['direction']): PortDef[] {
  return BLOCK_DEFS[type].ports.filter((p) => p.kind === kind && p.direction === direction)
}

/** A data block has no exec ports; it is evaluated wherever its output is used. */
export function isDataBlock(type: BlockType): boolean {
  return BLOCK_DEFS[type].ports.every((p) => p.kind === 'data')
}

export function historyTicks(type: BlockType, params: Record<string, ParamValue>): number {
  const history = BLOCK_DEFS[type].history
  if (!history) return 0
  if (history === '1') return 1
  const n = Number(params.n)
  return history === 'n+1' ? n + 1 : n
}
