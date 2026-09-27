import { Handle, Position, useReactFlow, useStore, type NodeProps } from '@xyflow/react'
import { memo, type ReactNode } from 'react'
import { BLOCK_DEFS, CATEGORIES, COMPARISON_OPERATORS, portsOf } from '../../../blocks/catalog.ts'
import { ticksToDuration } from '../../../blocks/hardware.ts'
import type { BlockCategory, BlockDef, BlockNode as BlockNodeT, BlockType, ParamDef, ParamValue, PortDef } from '../../../blocks/types.ts'
import { START_NODE_ID } from '../../../flow/graph.ts'
import { assignPriceTicker, tickerSymbols } from '../../../flow/tickers.ts'
import { NumberField, SelectField } from './fields.tsx'
import { TickerSearch } from './TickerSearch.tsx'

const CATEGORY_LABELS = Object.fromEntries(CATEGORIES.map((c) => [c.id, c.label])) as Record<BlockCategory, string>

const GLYPHS: Record<BlockCategory, string> = {
  structure: 'M4 2.5h8v11H4z M6.5 6h3 M6.5 8.5h3 M6.5 11h2',
  market: 'M2 12 5.2 7.2 8 9.4 14 3.5',
  variables: 'M3 3.5h10v9H3z M3 6.5h10',
  math: 'M8 3v10 M3 8h10',
  control: 'M2.5 3h4.2v3.4H2.5z M9.3 9.6h4.2V13H9.3z M4.6 6.4v2.1h4.7',
  trade: 'M8 2.8 13.2 13H2.8z',
  indicator: 'M1.5 8h2.4l1.5-3.4 2.4 6.8L9.4 8H14.5',
}

/** Blocks drawn as a compact pill: one value and one output. */
const CHIP_LABEL: Partial<Record<BlockType, string>> = { constant: 'Constant', get_var: 'Var' }

type SetParam = (key: string, value: ParamValue) => void

/** Start's resolution and the ticker in each slot, re-rendering only when they change. */
function useStrategyContext(): { resolution: string; symbols: string[] } {
  const joined = useStore((state) => {
    const params = state.nodeLookup.get(START_NODE_ID)?.data?.params as Record<string, ParamValue> | undefined
    return [params?.resolution ?? '', ...tickerSymbols(state.nodes as BlockNodeT[])].join('|')
  })
  const [resolution, ...symbols] = joined.split('|')
  return { resolution, symbols }
}

function visibleParams(def: BlockDef): ParamDef[] {
  return def.params.filter((p) => !p.hidden && !(def.type === 'if' && p.key === 'operator'))
}

function BlockHeader({ def }: { def: BlockDef }) {
  return (
    <div className="block-header">
      <span className="block-glyph" aria-hidden="true">
        <svg width="15" height="15" viewBox="0 0 16 16" fill="none">
          <path d={GLYPHS[def.category]} stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </span>
      <div className="block-heading">
        <span className="block-type">{CATEGORY_LABELS[def.category]}</span>
        <span className="block-title">{def.label}</span>
      </div>
      {def.status === 'blocked' ? (
        <span className="badge badge-blocked" title={def.statusNote}>
          needs HW
        </span>
      ) : null}
    </div>
  )
}

function Frame({ def, selected, className = '', children }: { def: BlockDef; selected?: boolean; className?: string; children: ReactNode }) {
  const classes = ['block', `cat-${def.category}`, `block-${def.type}`, className, selected ? 'selected' : '', def.status === 'blocked' ? 'blocked' : '']
  const tooltip = [def.description, def.statusNote, `Compiles to ${def.compilesTo}`].filter(Boolean).join('\n')
  return (
    <div className={classes.filter(Boolean).join(' ')} title={tooltip}>
      {children}
    </div>
  )
}

function ExecOuts({ ports }: { ports: PortDef[] }) {
  if (ports.length === 0) return null
  return (
    <div className={ports.length > 1 ? 'exec-outs multi' : 'exec-outs'}>
      {ports.map((port) => (
        <div className={`exec-out exec-out-${port.id.split(':')[1]}`} key={port.id}>
          {ports.length > 1 ? <span className="exec-label">{port.label}</span> : null}
          <Handle type="source" position={Position.Bottom} id={port.id} className="handle-exec" />
        </div>
      ))}
    </div>
  )
}

function ExecIn({ type }: { type: BlockType }) {
  const port = portsOf(type, 'exec', 'in')[0]
  return port ? <Handle type="target" position={Position.Top} id={port.id} className="handle-exec" /> : null
}

function DataPort({ port }: { port: PortDef }) {
  const isIn = port.direction === 'in'
  return (
    <div className={isIn ? 'port port-in' : 'port port-out'}>
      {isIn ? <Handle type="target" position={Position.Left} id={port.id} className="handle-data" /> : null}
      <span>{port.label}</span>
      {isIn ? null : <Handle type="source" position={Position.Right} id={port.id} className="handle-data" />}
    </div>
  )
}

function StartNode({ def, params, selected, setParam }: { def: BlockDef; params: Record<string, ParamValue>; selected?: boolean; setParam: SetParam }) {
  const balance = def.params.find((p) => p.key === 'startingBalance')
  const resolution = def.params.find((p) => p.key === 'resolution')
  return (
    <Frame def={def} selected={selected}>
      <BlockHeader def={def} />
      <div className="block-params">
        {resolution?.type === 'select' ? (
          <label className="param">
            <span className="param-label">Every</span>
            <SelectField def={resolution} value={params.resolution ?? resolution.default} onChange={(v) => setParam('resolution', v)} />
          </label>
        ) : null}
        {balance?.type === 'number' ? (
          <label className="param">
            <span className="param-label">Starting balance ($)</span>
            <NumberField def={balance} value={Number(params.startingBalance ?? balance.default)} onChange={(v) => setParam('startingBalance', v)} />
          </label>
        ) : null}
      </div>
      <ExecOuts ports={portsOf('start', 'exec', 'out')} />
    </Frame>
  )
}

function ChipNode({ def, params, selected, setParam }: { def: BlockDef; params: Record<string, ParamValue>; selected?: boolean; setParam: SetParam }) {
  const param = def.params[0]
  return (
    <div className={['block', 'block-slim', `block-${def.type}`, selected ? 'selected' : ''].filter(Boolean).join(' ')} title={def.description}>
      <span className="slim-label">{CHIP_LABEL[def.type]}</span>
      {param?.type === 'number' ? (
        <NumberField def={param} value={Number(params[param.key] ?? param.default)} onChange={(v) => setParam(param.key, v)} className="nodrag param-input slim-input" />
      ) : null}
      {param?.type === 'select' ? (
        <SelectField def={param} value={params[param.key] ?? param.default} onChange={(v) => setParam(param.key, v)} className="nodrag param-input slim-input" />
      ) : null}
      <Handle type="source" position={Position.Right} id="data:out" className="handle-data" />
    </div>
  )
}

function BlockNodeImpl({ id, type, data, selected }: NodeProps<BlockNodeT>) {
  const def = BLOCK_DEFS[type as BlockType]
  const { updateNodeData, setNodes } = useReactFlow()
  const { resolution, symbols } = useStrategyContext()
  if (!def) return <div className="block block-unknown">Unknown block: {type}</div>

  const params = data.params
  const setParam: SetParam = (key, value) => updateNodeData(id, { params: { ...params, [key]: value } })

  if (def.type === 'start') return <StartNode def={def} params={params} selected={selected} setParam={setParam} />
  if (def.type in CHIP_LABEL) return <ChipNode def={def} params={params} selected={selected} setParam={setParam} />

  const dataIns = portsOf(def.type, 'data', 'in')
  const dataOuts = portsOf(def.type, 'data', 'out')
  const isCondition = def.type === 'if'
  const rows = Math.max(isCondition ? 0 : dataIns.length, dataOuts.length)

  const field = (param: ParamDef) => {
    if (param.type === 'ticker') {
      // Get ticker holds its own symbol; Price N Ticks Ago binds to whichever slot has it.
      const current = String(params.symbol ?? '').trim() || String(symbols[Number(params.buffer ?? 0)] ?? '')
      const pick =
        def.type === 'get_ticker'
          ? (symbol: string) => setParam('symbol', symbol)
          : (symbol: string) => setNodes((nodes) => assignPriceTicker(nodes as BlockNodeT[], id, symbol))
      return <TickerSearch value={current} onChange={pick} />
    }
    const value = params[param.key] ?? param.default
    if (param.type === 'number') return <NumberField def={param} value={Number(value)} onChange={(v) => setParam(param.key, v)} />
    const labelled =
      param.key === 'buffer'
        ? { ...param, options: param.options.map((o) => ({ ...o, label: symbols[Number(o.value)] || `${o.label} (no ticker)` })) }
        : param
    return <SelectField def={labelled} value={value} onChange={(v) => setParam(param.key, v)} />
  }

  return (
    <Frame def={def} selected={selected} className={def.type === 'get_ticker' ? 'block-ticker' : ''}>
      <ExecIn type={def.type} />
      <BlockHeader def={def} />
      {isCondition ? (
        <div className="condition">
          <div className="condition-title">Condition</div>
          <DataPort port={dataIns[0]} />
          <div className="condition-op" role="radiogroup" aria-label="Operator">
            {COMPARISON_OPERATORS.map((o) => (
              <button
                key={o.value}
                type="button"
                role="radio"
                aria-checked={o.value === params.operator}
                className={o.value === params.operator ? 'nodrag op-btn active' : 'nodrag op-btn'}
                onClick={() => setParam('operator', o.value)}
              >
                {o.label}
              </button>
            ))}
          </div>
          <DataPort port={dataIns[1]} />
        </div>
      ) : null}
      {visibleParams(def).length > 0 ? (
        <div className="block-params">
          {visibleParams(def).map((param) => (
            <label className="param" key={param.key}>
              <span className="param-label">
                {param.label}
                {param.type === 'number' && param.ticks ? <span className="param-hint">{ticksToDuration(Number(params[param.key]), resolution)}</span> : null}
              </span>
              {field(param)}
            </label>
          ))}
        </div>
      ) : null}
      {rows > 0 ? (
        <div className="block-ports">
          {Array.from({ length: rows }, (_, i) => (
            <div className="port-row" key={i}>
              {!isCondition && dataIns[i] ? <DataPort port={dataIns[i]} /> : <span />}
              {dataOuts[i] ? <DataPort port={dataOuts[i]} /> : <span />}
            </div>
          ))}
        </div>
      ) : null}
      <ExecOuts ports={portsOf(def.type, 'exec', 'out')} />
    </Frame>
  )
}

export const BlockNode = memo(BlockNodeImpl)
