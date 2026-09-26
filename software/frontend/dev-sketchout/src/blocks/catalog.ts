import { MAX_LOOKBACK_DAYS, NUM_STOCK_BUFFERS, NUM_VAR_SLOTS } from './hardware';
import type {
  BlockCategory,
  BlockDef,
  BlockType,
  ParamDef,
  ParamValue,
  PortDef,
} from './types';

const range = (n: number) => Array.from({ length: n }, (_, i) => i);

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
  label: 'Buffer',
  type: 'select',
  default: 0,
  options: range(NUM_STOCK_BUFFERS).map((i) => ({ value: i, label: `BUF${i}` })),
};

const daysParam = (defaultDays: number, key = 'n', label = 'N (days)'): ParamDef => ({
  key,
  label,
  type: 'number',
  default: defaultDays,
  min: 1,
  max: MAX_LOOKBACK_DAYS,
  integer: true,
});

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
  integer: true,
};

export const COMPARISON_OPERATORS = [
  { value: '>', label: '>', hint: 'GT → BR' },
  { value: '>=', label: '≥', hint: 'LT → BR, Then/Else swapped' },
  { value: '<', label: '<', hint: 'LT → BR' },
  { value: '<=', label: '≤', hint: 'GT → BR, Then/Else swapped' },
  { value: '==', label: '=', hint: 'SUB → BR≠0, Then/Else swapped' },
  { value: '!=', label: '≠', hint: 'SUB → BR≠0' },
] as const;

export type ComparisonOperator = (typeof COMPARISON_OPERATORS)[number]['value'];

const binaryMath = (
  type: BlockType,
  label: string,
  symbol: string,
  opcode: string,
): BlockDef => ({
  type,
  label,
  category: 'math',
  description: `A ${symbol} B`,
  ports: [dataIn('a', 'A'), dataIn('b', 'B'), DATA_OUT],
  params: [],
  compilesTo: opcode,
  status: 'confirmed',
  statusNote:
    'Every operand must resolve to a register: Constants feeding this block are routed through LOAD_IMM.',
});

export const BLOCK_DEFS: Record<BlockType, BlockDef> = {
  // 1. Program structure
  start: {
    type: 'start',
    label: 'Start',
    category: 'structure',
    description:
      'Entry point, runs once. Wherever the exec chain dead-ends, the compiler appends UPDATEALLSTOCKBUFFERS + JMP LOOP.',
    ports: [{ ...EXEC_OUT, label: 'each tick' }],
    params: [
      { key: 'startingBalance', label: 'Starting Balance', type: 'number', default: 100000, min: 0 },
    ],
    compilesTo: 'SETBALANCE (once)',
    status: 'confirmed',
    system: true,
  },

  // 2. Reserved variables
  current_price: {
    type: 'current_price',
    label: 'Current Price',
    category: 'reserved',
    description: 'Latest price of the stock in the selected buffer.',
    ports: [DATA_OUT],
    params: [bufferParam],
    compilesTo: 'GETSTOCKPRICE',
    status: 'confirmed',
  },
  sum_last_n: {
    type: 'sum_last_n',
    label: 'Sum of Last N Days',
    category: 'reserved',
    description: 'Sum of the last N daily prices in the buffer.',
    ports: [DATA_OUT],
    params: [bufferParam, daysParam(20)],
    compilesTo: 'GETSUMPRICEBEFORE',
    status: 'confirmed',
  },
  price_n_days_ago: {
    type: 'price_n_days_ago',
    label: 'Price N Days Ago',
    category: 'reserved',
    description: 'Price of the stock N days before the current tick.',
    ports: [DATA_OUT],
    params: [bufferParam, daysParam(10)],
    compilesTo: '—',
    status: 'blocked',
    statusNote: 'No confirmed opcode. Required by Momentum.',
  },
  constant: {
    type: 'constant',
    label: 'Constant',
    category: 'reserved',
    description: 'Literal number.',
    ports: [DATA_OUT],
    params: [{ key: 'value', label: 'Value', type: 'number', default: 0 }],
    compilesTo: 'LOAD_IMM (deduped / cached)',
    status: 'confirmed',
  },

  // 3. Variables
  set_var: {
    type: 'set_var',
    label: 'Set Variable',
    category: 'variables',
    description: 'Store a value into a hardware variable slot.',
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
  divide: binaryMath('divide', 'Divide', '÷', 'DIV'),
  power: {
    type: 'power',
    label: 'Power',
    category: 'math',
    description: 'base ^ exponent',
    ports: [dataIn('base'), dataIn('exp', 'exponent'), DATA_OUT],
    params: [],
    compilesTo: '—',
    status: 'blocked',
    statusNote: 'No opcode seen. Flag for hardware team.',
  },
  root: {
    type: 'root',
    label: 'Root',
    category: 'math',
    description: 'base-th root of x',
    ports: [dataIn('x'), dataIn('base'), DATA_OUT],
    params: [],
    compilesTo: '—',
    status: 'blocked',
    statusNote: 'No opcode seen. Volatility needs this for sqrt.',
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
    statusNote: 'No opcode seen.',
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
    compilesTo: 'GT | LT | SUB → BR / JMP',
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
      { key: 'start', label: 'Start', type: 'number', default: 0, integer: true },
      { key: 'end', label: 'End', type: 'number', default: 10, integer: true },
      { key: 'step', label: 'Step', type: 'number', default: 1, integer: true },
    ],
    compilesTo: 'ASSIGNVAR counter, GT/LT bound, ADD/SUB step, JMP back',
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
    compilesTo: 'GETSTOCKPRICE → MUL → UPDATEBALANCE(+) → EMITDECISION(qty, buf, 1)',
    status: 'confirmed',
  },
  sell: {
    type: 'sell',
    label: 'Sell',
    category: 'trade',
    description: 'Sell shares at the current price.',
    ports: [EXEC_IN, EXEC_OUT],
    params: [bufferParam, quantityParam],
    compilesTo: 'GETSTOCKPRICE → MUL → SUB from R0 → UPDATEBALANCE(−) → EMITDECISION(qty, buf, 0)',
    status: 'confirmed',
  },

  // 8. Composite macros
  sma: {
    type: 'sma',
    label: 'SMA',
    category: 'composite',
    description: 'Simple moving average over N days.',
    ports: [DATA_OUT],
    params: [bufferParam, daysParam(20)],
    compilesTo: 'Sum of Last N Days ÷ N',
    status: 'confirmed',
  },
  momentum: {
    type: 'momentum',
    label: 'Momentum',
    category: 'composite',
    description: 'Fractional price change over N days.',
    ports: [DATA_OUT],
    params: [bufferParam, daysParam(10)],
    compilesTo: '(Current Price ÷ Price N Days Ago) − 1',
    status: 'blocked',
    statusNote: 'Blocked on "Price N Days Ago".',
  },
  volatility: {
    type: 'volatility',
    label: 'Volatility',
    category: 'composite',
    description: 'Sample standard deviation of price over N days.',
    ports: [DATA_OUT],
    params: [bufferParam, daysParam(20)],
    compilesTo: 'sqrt(Σ(price − mean)² / (N − 1))',
    status: 'blocked',
    statusNote:
      'Blocked on a per-day price source (or sum-of-squares sibling to GETSUMPRICEBEFORE) and a sqrt/root opcode.',
  },
  mean_reversion_bands: {
    type: 'mean_reversion_bands',
    label: 'Mean Reversion Bands',
    category: 'composite',
    description: 'SMA ± k × Volatility. Pair with two If blocks: ≤ lower → Buy, ≥ upper → Sell.',
    ports: [dataOut('upper', 'upper'), dataOut('middle', 'middle'), dataOut('lower', 'lower')],
    params: [
      bufferParam,
      daysParam(20),
      { key: 'k', label: 'k (std devs)', type: 'number', default: 2, min: 0, step: 0.1 },
    ],
    compilesTo: 'SMA ± k × Volatility',
    status: 'blocked',
    statusNote: "Inherits Volatility's blockers.",
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
