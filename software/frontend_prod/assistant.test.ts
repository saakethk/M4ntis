import assert from 'node:assert/strict'
import { describe, it } from 'node:test'
import {
  ASSISTANT_MODEL_STORAGE_KEY,
  ASSISTANT_MODELS,
  DEFAULT_ASSISTANT_MODEL,
  findAssistantModel,
  modelChoiceId,
  readStoredAssistantModel,
  storeAssistantModel,
  type ModelStorage,
} from './src/assistantModels.ts'
import { applyAssistantGraph, readAssistantGraph } from './src/flow/assistantGraph.ts'
import { makeNode } from './src/flow/graph.ts'

const bands = {
  nodes: [
    { id: 'start', type: 'start', params: { resolution: '15m', startingBalance: 100000 } },
    { id: 't0', type: 'get_ticker', params: { symbol: 'NVDA' } },
    { id: 'bands', type: 'mean_reversion_bands', params: { buffer: 0, n: 20, k: 2 } },
    { id: 'low', type: 'if', params: { operator: '<=' } },
    { id: 'high', type: 'if', params: { operator: '>=' } },
    { id: 'buy', type: 'buy', params: { buffer: 0, quantity: 5 } },
    { id: 'sell', type: 'sell', params: { buffer: 0, quantity: 5 } },
  ],
  edges: [
    { source: 'start', sourceHandle: 'exec:out', target: 'low', targetHandle: 'exec:in' },
    { source: 'bands', sourceHandle: 'data:lower', target: 'low', targetHandle: 'data:a' },
    { source: 't0', sourceHandle: 'data:out', target: 'low', targetHandle: 'data:b' },
    { source: 'low', sourceHandle: 'exec:else', target: 'high', targetHandle: 'exec:in' },
    { source: 'low', sourceHandle: 'exec:then', target: 'buy', targetHandle: 'exec:in' },
    { source: 'bands', sourceHandle: 'data:upper', target: 'high', targetHandle: 'data:a' },
    { source: 't0', sourceHandle: 'data:out', target: 'high', targetHandle: 'data:b' },
    { source: 'high', sourceHandle: 'exec:then', target: 'sell', targetHandle: 'exec:in' },
  ],
}

describe('applyAssistantGraph', () => {
  it('places every returned block and wires its ports', () => {
    const placed = applyAssistantGraph(bands)
    assert.deepEqual(
      placed.nodes.map((node) => node.type).sort(),
      ['buy', 'get_ticker', 'if', 'if', 'mean_reversion_bands', 'sell', 'start'],
    )
    const lower = placed.edges.find((edge) => edge.source === 'bands' && edge.sourceHandle === 'data:lower')
    assert.equal(lower?.target, 'low')
    assert.equal(lower?.targetHandle, 'data:a')
    assert.equal(placed.nodes.find((node) => node.id === 't0')?.data.params.symbol, 'NVDA')
    const start = placed.nodes.find((node) => node.id === 'start')
    const buy = placed.nodes.find((node) => node.id === 'buy')
    assert.ok(start && buy)
    assert.ok(buy.position.x > start.position.x)
  })

  it('keeps blocks that were already on the canvas and lays out only new ones', () => {
    const previous = [
      makeNode('start', { x: 10, y: 20 }),
      makeNode('constant', { x: 40, y: 80 }, { value: 3 }, 'floor'),
    ]
    const placed = applyAssistantGraph(
      {
        nodes: [
          { id: 'start', type: 'start', params: { resolution: '5m' } },
          { id: 'floor', type: 'constant', params: { value: 4 } },
          { id: 'buy', type: 'buy', params: { quantity: 1, buffer: 0 } },
        ],
        edges: [{ source: 'start', sourceHandle: 'exec:out', target: 'buy', targetHandle: 'exec:in' }],
      },
      previous,
    )
    assert.deepEqual(placed.nodes.find((node) => node.id === 'floor')?.position, { x: 40, y: 80 })
    assert.equal(placed.nodes.find((node) => node.id === 'floor')?.data.params.value, 4)
    assert.ok((placed.nodes.find((node) => node.id === 'buy')?.position.x ?? 0) > 40)
  })

  it('rejects a graph with no Start block', () => {
    assert.throws(
      () => applyAssistantGraph({ nodes: [{ id: 'buy', type: 'buy', params: {} }], edges: [] }),
      /Start/,
    )
  })
})

function memoryStorage(initial: Record<string, string> = {}): ModelStorage & { saved: Map<string, string> } {
  const saved = new Map(Object.entries(initial))
  return {
    saved,
    getItem: (key) => saved.get(key) ?? null,
    setItem: (key, value) => {
      saved.set(key, value)
    },
  }
}

describe('assistant models', () => {
  it('defaults to Gemini 2.5 Flash and lists Gemini and Meta', () => {
    assert.equal(DEFAULT_ASSISTANT_MODEL.provider, 'gemini')
    assert.equal(DEFAULT_ASSISTANT_MODEL.model, 'gemini-2.5-flash')
    assert.deepEqual(
      ASSISTANT_MODELS.map((choice) => `${choice.provider}:${choice.model}`),
      [
        'gemini:gemini-2.5-flash',
        'gemini:gemini-2.5-pro',
        'gemini:gemini-3.8-flash',
        'gemini:gemini-3.5-flash-lite',
        'gemini:gemini-3.1-pro-preview',
        'meta:muse-spark-1.3',
        'meta:muse-spark-1.3-contributor',
        'meta:muse-spark-1.2',
        'meta:muse-spark-1.2-contributor',
        'meta:muse-spark-1.1',
      ],
    )
  })

  it('keeps the last choice and falls back when storage is empty or unknown', () => {
    const storage = memoryStorage()
    const muse = ASSISTANT_MODELS.find((choice) => choice.model === 'muse-spark-1.3')
    assert.ok(muse)
    storeAssistantModel(muse, storage)
    assert.equal(storage.saved.get(ASSISTANT_MODEL_STORAGE_KEY), modelChoiceId(muse))
    assert.deepEqual(readStoredAssistantModel(storage), muse)
    assert.equal(readStoredAssistantModel(memoryStorage()).model, 'gemini-2.5-flash')
    assert.equal(readStoredAssistantModel(memoryStorage({ [ASSISTANT_MODEL_STORAGE_KEY]: 'nope' })).model, 'gemini-2.5-flash')
    assert.equal(findAssistantModel('meta:muse-spark-1.1').label, 'Muse Spark 1.1')
    assert.equal(readStoredAssistantModel(null).model, 'gemini-2.5-flash')
    const blocked: ModelStorage = {
      getItem: () => {
        throw new Error('denied')
      },
      setItem: () => {
        throw new Error('denied')
      },
    }
    assert.equal(readStoredAssistantModel(blocked).model, 'gemini-2.5-flash')
    assert.doesNotThrow(() => storeAssistantModel(DEFAULT_ASSISTANT_MODEL, blocked))
  })
})

describe('readAssistantGraph', () => {
  it('reads nodes and edges', () => {
    const graph = readAssistantGraph({ nodes: bands.nodes, edges: bands.edges })
    assert.equal(graph?.nodes.length, 7)
    assert.equal(graph?.edges[0].sourceHandle, 'exec:out')
  })

  it('treats a missing graph as no canvas edit', () => {
    assert.equal(readAssistantGraph(null), null)
  })
})
