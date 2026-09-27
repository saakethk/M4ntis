import { BUFFER_DEPTH, NUM_STOCK_BUFFERS, NUM_VAR_SLOTS, RESOLUTIONS } from './hardware';
import { NASDAQ_100 } from './symbols';
import type {
  BlockCategory,
  BlockDef,
  BlockType,
  ParamDef,
  ParamValue,
  PortDef,
} from './types';

const range = (n: number) => Array.from({ length: n }, (_, i) => i);

const EVERY_LABEL: Record<string, string> = {
  '1m': '1 minute',
  '5m': '5 minutes',
  '15m': '15 minutes',
  '30m': '30 minutes',
  '1h': '1 hour',
  '1d': '1 day',
};

const EXEC_IN: PortDef = { id: 'exec:in', kind: 'exec', direction: 'in' };
const EXEC_OUT: PortDef = { id: 'exec:out', kind: 'exec', direction: 'out', label: 'next' };
const DATA_OUT: PortDef = { id: 'data:out', kind: 'data', direction: 'out', label: 'value' };
const dataIn = (name: string, label = name): PortDef => ({
  id: `data:${name}`,
  kind: 'data',
  direction: 'in',
  label,
});
const dataOut = (name: string, label = name): PortDef => ({
  id: `data:${name}`,
  kind: 'data',
  direction: 'out',
  label,
});
const execOut = (name: string, label = name): PortDef => ({
  id: `exec:${name}`,
  kind: 'exec',
  direction: 'out',
  label,
});

const bufferParam: ParamDef = {
  key: 'buffer',
  label: 'Ticker',
  type: 'select',
  default: 0,
  options: range(NUM_STOCK_BUFFERS).map((i) => ({ value: i, label: `BUF${i}` })),
};

/** Symbol chosen by search. Empty until the user picks one, so older graphs keep their buffer. */
const tickerSearchParam: ParamDef = {
  key: 'symbol',
  label: 'Ticker',
  type: 'ticker',
  default: '',
};

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
});

/** GETSTOCKPRICEBEFORE offset 30 wraps back to the current tick, so 29 is the furthest back. */
const offsetParam = (defaultTicks: number): ParamDef => windowParam(defaultTicks, 1, BUFFER_DEPTH - 1);

/** Loop bounds are loaded with LOAD_IMM, which takes a 16-bit signed immediate. */
const IMM16 = { min: -32768, max: 32767, integer: true } as const;

const slotParam: ParamDef = {
  key: 'slot',
  label: 'Slot',
  type: 'select',
  default: 'VAR1',
  options: range(NUM_VAR_SLOTS).map((i) => ({ value: `VAR${i + 1}`, label: `VAR${i + 1}` })),
};

const quantityParam: ParamDef = {
  key: 'quantity',
  label: 'Quantity',
  type: 'number',
  default: 10,
  min: 1,
  max: 32767,
  integer: true,
};

const symbolParam = (buf: number): ParamDef => ({
  key: `symbol${buf}`,
  label: `BUF${buf}`,
  type: 'select',
  default: '',
  options: [{ value: '', label: '—' }, ...NASDAQ_100.map((s) => ({ value: s, label: s }))],
});

export const COMPARISON_OPERATORS = [
  { value: '>', label: '>', hint: 'CMP_GT → JMP_IF Then' },
  { value: '>=', label: '≥', hint: 'CMP_LT → JMP_IF Else' },
  { value: '<', label: '<', hint: 'CMP_LT → JMP_IF Then' },
  { value: '<=', label: '≤', hint: 'CMP_GT → JMP_IF Else' },
  { value: '==', label: '=', hint: 'SUB → JMP_IF Else' },
  { value: '!=', label: '≠', hint: 'SUB → JMP_IF Then' },
] as const;

export type ComparisonOperator = (typeof COMPARISON_OPERATORS)[number]['value'];

const binaryMath = (
  type: BlockType,
  label: string,
  symbol: string,
  opcode: string,
  note?: string,
): BlockDef => ({
  type,
  label,
  category: 'math',
  description: `A ${symbol} B`,
  ports: [dataIn('a', 'A'), dataIn('b', 'B'), DATA_OUT],
  params: [],
  compilesTo: opcode,
  status: 'confirmed',
  statusNote: note,
});

export const BLOCK_DEFS: Record<BlockType, BlockDef> = {
  // 1. Program structure
  start: {
    type: 'start',
    label: 'Start',
    category: 'structure',
    description:
      'Runs once per tick. The compiler adds the tick loop, warm-up and per-tick acknowledgement around the chain.',
    ports: [{ ...EXEC_OUT, label: 'each tick' }],
    params: [
      { key: 'startingBalance', label: 'Starting Balance ($)', type: 'number', default: 100000, min: 0, max: 21000000 },
      {
        key: 'resolution',
        label: 'Every',
        type: 'select',
        default: '5m',
        options: RESOLUTIONS.map((r) => ({ value: r.value, label: EVERY_LABEL[r.value] ?? r.label })),
      },
      ...range(NUM_STOCK_BUFFERS).map(symbolParam),
    ],
    compilesTo: 'SETBALANCE, warm-up, UPDATEALLSTOCKBUFFERS loop',
    status: 'confirmed',
    system: true,
  },

  // 2. Market data
  get_ticker: {
    type: 'get_ticker',
    label: 'Get ticker',
    category: 'reserved',
    description: 'Price of one stock. AAPL is Apple.',
    ports: [dataOut('out', 'price')],
    params: [
      {
        key: 'symbol',
        label: 'Ticker',
        type: 'ticker',
        default: 'AAPL',
      },
      bufferParam,
    ],
    compilesTo: 'GETSTOCKPRICE',
    status: 'confirmed',
    history: '1',
  },
  current_price: {
    type: 'current_price',
    label: 'Current Price',
    category: 'reserved',
    description: 'Price at the current tick.',
    ports: [DATA_OUT],
    params: [bufferParam],
    compilesTo: 'GETSTOCKPRICE',
    status: 'confirmed',
    history: '1',
  },
  sum_n_ticks: {
    type: 'sum_n_ticks',
    label: 'Sum of Last N Ticks',
    category: 'reserved',
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
    category: 'reserved',
    description: 'Price N ticks before the current one.',
    ports: [DATA_OUT],
    // `symbol` is the ticker search. `buffer` stays for the hardware slot; the compiler
    // fills it from `symbol` when the user has picked one.
    params: [tickerSearchParam, bufferParam, offsetParam(10)],
    compilesTo: 'GETSTOCKPRICEBEFORE',
    status: 'confirmed',
    history: 'n+1',
  },
  constant: {
    type: 'constant',
    label: 'Constant',
    category: 'reserved',
    description: 'Literal number. Prices are in dollars, so 150.25 means $150.25.',
    ports: [DATA_OUT],
    params: [{ key: 'value', label: 'Value', type: 'number', default: 0 }],
    compilesTo: 'LOAD_IMM (scaled to fixed point)',
    status: 'confirmed',
  },

  // 3. Variables
  set_var: {
    type: 'set_var',
    label: 'Set Variable',
    category: 'variables',
    description: 'Store a value into a hardware variable slot (16-bit signed).',
    ports: [EXEC_IN, dataIn('value', 'value'), EXEC_OUT],
    params: [slotParam],
    compilesTo: 'ASSIGNVAR',
    status: 'confirmed',
  },
  get_var: {
    type: 'get_var',
    label: 'Get Variable',
    category: 'variables',
    description: 'Read a hardware variable slot.',
    ports: [DATA_OUT],
    params: [slotParam],
    compilesTo: 'GETVAR',
    status: 'confirmed',
  },

  // 4. Math
  add: binaryMath('add', 'Add', '+', 'ADD'),
  subtract: binaryMath('subtract', 'Subtract', '−', 'SUB'),
  multiply: binaryMath('multiply', 'Multiply', '×', 'MUL'),
  divide: binaryMath('divide', 'Divide', '÷', 'MUL ×100 → DIV', 'Numerator is pre-scaled so ratios keep 2 decimals.'),
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
    description: 'log of x in the given base',
    ports: [dataIn('x'), dataIn('base'), DATA_OUT],
    params: [],
    compilesTo: '—',
    status: 'blocked',
    statusNote: 'No opcode and no practical integer expansion on this ISA.',
  },

  // 6. Control flow (5. Comparisons live inside If)
  if: {
    type: 'if',
    label: 'If / Else',
    category: 'control',
    description:
      'Branch on a comparison. Compound logic: nest in Then for AND, chain in Else for OR.',
    ports: [EXEC_IN, dataIn('a', 'A'), dataIn('b', 'B'), execOut('then', 'Then'), execOut('else', 'Else')],
    params: [
      {
        key: 'operator',
        label: 'Operator',
        type: 'select',
        default: '>',
        options: COMPARISON_OPERATORS.map((o) => ({ ...o })),
      },
    ],
    compilesTo: 'CMP_GT | CMP_LT | SUB → JMP_IF',
    status: 'confirmed',
    condition: true,
  },
  for: {
    type: 'for',
    label: 'For (Range)',
    category: 'control',
    description:
      'Runs Body for each i in [start, end) within ONE tick. For sub-calculations, not for walking back through history.',
    ports: [EXEC_IN, dataOut('index', 'i'), execOut('body', 'Body ↻'), execOut('after', 'After')],
    params: [
      { key: 'start', label: 'Start', type: 'number', default: 0, ...IMM16 },
      { key: 'end', label: 'End', type: 'number', default: 10, ...IMM16 },
      { key: 'step', label: 'Step', type: 'number', default: 1, ...IMM16 },
    ],
    compilesTo: 'counter in a spare VAR, CMP_LT/GT bound, ADD step, JMP back',
    status: 'confirmed',
  },

  // 7. Trade actions
  buy: {
    type: 'buy',
    label: 'Buy',
    category: 'trade',
    description: 'Buy shares at the current price.',
    ports: [EXEC_IN, EXEC_OUT],
    params: [bufferParam, quantityParam],
    compilesTo: 'GETSTOCKPRICE → MUL → UPDATEBALANCE (cash −= cost) → EMITDECISION(qty, buf, 1)',
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
    compilesTo: 'GETSTOCKPRICE → MUL → negate → UPDATEBALANCE (cash += proceeds) → EMITDECISION(qty, buf, 0)',
    status: 'confirmed',
    history: '1',
  },

  // 8. Composite macros
  sma: {
    type: 'sma',
    label: 'SMA',
    category: 'composite',
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
    category: 'composite',
    description: 'Fractional change over N ticks: 0.05 = up 5%.',
    ports: [DATA_OUT],
    params: [bufferParam, offsetParam(10)],
    compilesTo: '(price × 100 ÷ price N ticks ago) − 100',
    status: 'confirmed',
    history: 'n+1',
  },
  volatility: {
    type: 'volatility',
    label: 'Volatility',
    category: 'composite',
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
    category: 'composite',
    description: 'SMA ± k × Volatility. Pair with two If blocks: ≤ lower → Buy, ≥ upper → Sell.',
    ports: [dataOut('upper', 'upper'), dataOut('middle', 'middle'), dataOut('lower', 'lower')],
    params: [
      bufferParam,
      windowParam(20, 2),
      { key: 'k', label: 'k (std devs)', type: 'number', default: 2, min: 0, max: 10, step: 0.1 },
    ],
    compilesTo: 'SMA ± k × Volatility',
    status: 'confirmed',
    statusNote: 'Upper and lower each expand Volatility; about 4N + 40 instructions per band used.',
    history: 'n',
  },
};

export const BLOCK_TYPES = Object.keys(BLOCK_DEFS) as BlockType[];

export const CATEGORIES: { id: BlockCategory; label: string }[] = [
  { id: 'structure', label: 'Program' },
  { id: 'reserved', label: 'Market Data' },
  { id: 'variables', label: 'Variables' },
  { id: 'math', label: 'Math' },
  { id: 'control', label: 'Control Flow' },
  { id: 'trade', label: 'Trade Actions' },
  { id: 'composite', label: 'Indicators' },
];

export function defaultParams(type: BlockType): Record<string, ParamValue> {
  return Object.fromEntries(BLOCK_DEFS[type].params.map((p) => [p.key, p.default]));
}

export function isBlockType(value: unknown): value is BlockType {
  return typeof value === 'string' && value in BLOCK_DEFS;
}

export function portsOf(type: BlockType, kind: PortDef['kind'], direction: PortDef['direction']) {
  return BLOCK_DEFS[type].ports.filter((p) => p.kind === kind && p.direction === direction);
}

/** A block is "pure data" if it has no exec ports: it is evaluated on demand wherever its output is consumed. */
export function isDataBlock(type: BlockType) {
  return BLOCK_DEFS[type].ports.every((p) => p.kind === 'data');
}

export function historyTicks(type: BlockType, params: Record<string, ParamValue>): number {
  const h = BLOCK_DEFS[type].history;
  if (!h) return 0;
  if (h === '1') return 1;
  const n = Number(params.n);
  return h === 'n+1' ? n + 1 : n;
}
