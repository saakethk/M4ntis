// Starter strategies offered by the editor's Templates menu.

import type { BlockEdge, BlockNode } from '../blocks/types.ts'
import { START_NODE_ID, makeEdge, makeNode } from './graph.ts'

export interface Template {
  id: string
  name: string
  description: string
  build: () => { nodes: BlockNode[]; edges: BlockEdge[] }
}

const start = (resolution = '5m') => makeNode('start', { x: 0, y: -200 }, { startingBalance: 100000, resolution }, START_NODE_ID)

export const BLANK_TEMPLATE: Template = {
  id: 'blank',
  name: 'Blank',
  description: 'Just the Start block.',
  build: () => ({ nodes: [start()], edges: [] }),
}

export const TEMPLATES: Template[] = [
  BLANK_TEMPLATE,
  {
    id: 'sma_crossover',
    name: 'SMA Crossover',
    description: 'Buy when the 10-tick SMA is above the 30-tick SMA, otherwise sell.',
    build: () => ({
      nodes: [
        start(),
        makeNode('get_ticker', { x: -420, y: -20 }, { symbol: 'AAPL' }, 't0'),
        makeNode('sma', { x: -420, y: 120 }, { buffer: 0, n: 10 }, 'sma_fast'),
        makeNode('sma', { x: -420, y: 300 }, { buffer: 0, n: 30 }, 'sma_slow'),
        makeNode('if', { x: 0, y: 170 }, { operator: '>' }, 'if_cross'),
        makeNode('buy', { x: -160, y: 440 }, { buffer: 0, quantity: 10 }, 'buy'),
        makeNode('sell', { x: 160, y: 440 }, { buffer: 0, quantity: 10 }, 'sell'),
      ],
      edges: [
        makeEdge(START_NODE_ID, 'exec:out', 'if_cross', 'exec:in'),
        makeEdge('sma_fast', 'data:out', 'if_cross', 'data:a'),
        makeEdge('sma_slow', 'data:out', 'if_cross', 'data:b'),
        makeEdge('if_cross', 'exec:then', 'buy', 'exec:in'),
        makeEdge('if_cross', 'exec:else', 'sell', 'exec:in'),
      ],
    }),
  },
  {
    id: 'trend_confirmation',
    name: 'Trend + Confirmation',
    description: 'Buy if fast SMA > slow SMA and price > fast SMA (nested AND). Sell on the mirror condition.',
    build: () => ({
      nodes: [
        start(),
        makeNode('sma', { x: -340, y: 140 }, { buffer: 0, n: 12 }, 'sma_fast'),
        makeNode('set_var', { x: 0, y: 150 }, { slot: 'VAR1' }, 'set_fast'),
        makeNode('sma', { x: -340, y: 330 }, { buffer: 0, n: 26 }, 'sma_slow'),
        makeNode('set_var', { x: 0, y: 340 }, { slot: 'VAR2' }, 'set_slow'),
        makeNode('get_var', { x: -340, y: 520 }, { slot: 'VAR1' }, 'get_fast'),
        makeNode('get_var', { x: -340, y: 660 }, { slot: 'VAR2' }, 'get_slow'),
        makeNode('if', { x: 0, y: 540 }, { operator: '>' }, 'if_trend'),
        makeNode('get_ticker', { x: -560, y: 900 }, { symbol: 'AAPL', buffer: 0 }, 't0'),
        makeNode('if', { x: -200, y: 900 }, { operator: '>' }, 'if_confirm_up'),
        makeNode('if', { x: 240, y: 900 }, { operator: '<' }, 'if_confirm_down'),
        makeNode('buy', { x: -200, y: 1180 }, { buffer: 0, quantity: 10 }, 'buy'),
        makeNode('sell', { x: 240, y: 1180 }, { buffer: 0, quantity: 10 }, 'sell'),
      ],
      edges: [
        makeEdge(START_NODE_ID, 'exec:out', 'set_fast', 'exec:in'),
        makeEdge('sma_fast', 'data:out', 'set_fast', 'data:value'),
        makeEdge('set_fast', 'exec:out', 'set_slow', 'exec:in'),
        makeEdge('sma_slow', 'data:out', 'set_slow', 'data:value'),
        makeEdge('set_slow', 'exec:out', 'if_trend', 'exec:in'),
        makeEdge('get_fast', 'data:out', 'if_trend', 'data:a'),
        makeEdge('get_slow', 'data:out', 'if_trend', 'data:b'),
        makeEdge('if_trend', 'exec:then', 'if_confirm_up', 'exec:in'),
        makeEdge('if_trend', 'exec:else', 'if_confirm_down', 'exec:in'),
        makeEdge('t0', 'data:out', 'if_confirm_up', 'data:a'),
        makeEdge('get_fast', 'data:out', 'if_confirm_up', 'data:b'),
        makeEdge('t0', 'data:out', 'if_confirm_down', 'data:a'),
        makeEdge('get_slow', 'data:out', 'if_confirm_down', 'data:b'),
        makeEdge('if_confirm_up', 'exec:then', 'buy', 'exec:in'),
        makeEdge('if_confirm_down', 'exec:then', 'sell', 'exec:in'),
      ],
    }),
  },
  {
    id: 'mean_reversion',
    name: 'Mean Reversion Bands',
    description: 'Buy at or below the lower band, sell at or above the upper band (chained Else = OR).',
    build: () => ({
      nodes: [
        start(),
        makeNode('get_ticker', { x: -460, y: 120 }, { symbol: 'AAPL', buffer: 0 }, 't0'),
        makeNode('mean_reversion_bands', { x: -460, y: 270 }, { buffer: 0, n: 20, k: 2 }, 'bands'),
        makeNode('if', { x: 0, y: 170 }, { operator: '<=' }, 'if_lower'),
        makeNode('buy', { x: -160, y: 460 }, { buffer: 0, quantity: 10 }, 'buy'),
        makeNode('if', { x: 160, y: 460 }, { operator: '>=' }, 'if_upper'),
        makeNode('sell', { x: 160, y: 760 }, { buffer: 0, quantity: 10 }, 'sell'),
      ],
      edges: [
        makeEdge(START_NODE_ID, 'exec:out', 'if_lower', 'exec:in'),
        makeEdge('t0', 'data:out', 'if_lower', 'data:a'),
        makeEdge('bands', 'data:lower', 'if_lower', 'data:b'),
        makeEdge('if_lower', 'exec:then', 'buy', 'exec:in'),
        makeEdge('if_lower', 'exec:else', 'if_upper', 'exec:in'),
        makeEdge('t0', 'data:out', 'if_upper', 'data:a'),
        makeEdge('bands', 'data:upper', 'if_upper', 'data:b'),
        makeEdge('if_upper', 'exec:then', 'sell', 'exec:in'),
      ],
    }),
  },
  {
    id: 'z_score_reversion',
    name: 'Z-Score Reversion',
    description: 'Buy when price is 2 standard deviations below its 20-tick average, sell when 2 above.',
    build: () => ({
      nodes: [
        start('15m'),
        makeNode('get_ticker', { x: -620, y: 0 }, { symbol: 'AAPL', buffer: 0 }, 't0'),
        makeNode('z_score', { x: -460, y: 140 }, { buffer: 0, n: 20 }, 'z'),
        makeNode('constant', { x: -460, y: 300 }, { value: -2 }, 'low'),
        makeNode('constant', { x: -460, y: 560 }, { value: 2 }, 'high'),
        makeNode('if', { x: 0, y: 170 }, { operator: '<=' }, 'if_cheap'),
        makeNode('buy', { x: -160, y: 460 }, { buffer: 0, quantity: 10 }, 'buy'),
        makeNode('if', { x: 160, y: 460 }, { operator: '>=' }, 'if_rich'),
        makeNode('sell', { x: 160, y: 760 }, { buffer: 0, quantity: 10 }, 'sell'),
      ],
      edges: [
        makeEdge(START_NODE_ID, 'exec:out', 'if_cheap', 'exec:in'),
        makeEdge('z', 'data:out', 'if_cheap', 'data:a'),
        makeEdge('low', 'data:out', 'if_cheap', 'data:b'),
        makeEdge('if_cheap', 'exec:then', 'buy', 'exec:in'),
        makeEdge('if_cheap', 'exec:else', 'if_rich', 'exec:in'),
        makeEdge('z', 'data:out', 'if_rich', 'data:a'),
        makeEdge('high', 'data:out', 'if_rich', 'data:b'),
        makeEdge('if_rich', 'exec:then', 'sell', 'exec:in'),
      ],
    }),
  },
]
