import { Handle, Position, useReactFlow, useStore, type NodeProps } from '@xyflow/react';
import { memo, useState } from 'react';
import { BLOCK_DEFS, CATEGORIES, COMPARISON_OPERATORS, portsOf } from '../blocks/catalog';
import { NUM_STOCK_BUFFERS, ticksToDuration } from '../blocks/hardware';
import { NASDAQ_100 } from '../blocks/symbols';
import type { BlockDef, BlockNode as BlockNodeT, BlockType, ParamDef, ParamValue, PortDef } from '../blocks/types';
import { START_NODE_ID } from './graph';

const CATEGORY_LABELS: Record<string, string> = Object.fromEntries(
  CATEGORIES.map((category) => [category.id, category.label]),
);

const GLYPHS: Record<string, string> = {
  structure: 'M4 2.5h8v11H4z M6.5 6h3 M6.5 8.5h3 M6.5 11h2',
  reserved: 'M2 12 5.2 7.2 8 9.4 14 3.5',
  variables: 'M3 3.5h10v9H3z M3 6.5h10',
  math: 'M8 3v10 M3 8h10',
  control: 'M2.5 3h4.2v3.4H2.5z M9.3 9.6h4.2V13H9.3z M4.6 6.4v2.1h4.7',
  trade: 'M8 2.8 13.2 13H2.8z',
  composite: 'M1.5 8h2.4l1.5-3.4 2.4 6.8L9.4 8H14.5',
};

function NumberField({
  def,
  value,
  onChange,
}: {
  def: Extract<ParamDef, { type: 'number' }>;
  value: number;
  onChange: (v: number) => void;
}) {
  const [draft, setDraft] = useState<string | null>(null);

  const commit = (raw: string) => {
    setDraft(null);
    let v = Number(raw);
    if (raw.trim() === '' || Number.isNaN(v)) return;
    if (def.integer) v = Math.round(v);
    if (def.min !== undefined) v = Math.max(def.min, v);
    if (def.max !== undefined) v = Math.min(def.max, v);
    if (v !== value) onChange(v);
  };

  return (
    <input
      className="nodrag param-input"
      type="number"
      value={draft ?? String(value)}
      step={def.step ?? (def.integer ? 1 : 'any')}
      min={def.min}
      max={def.max}
      onChange={(e) => setDraft(e.target.value)}
      onBlur={(e) => commit(e.target.value)}
      onKeyDown={(e) => e.key === 'Enter' && (e.target as HTMLInputElement).blur()}
    />
  );
}

function ParamField({
  def,
  value,
  onChange,
  hint,
}: {
  def: ParamDef;
  value: ParamValue;
  onChange: (v: ParamValue) => void;
  hint?: string;
}) {
  return (
    <label className="param">
      <span className="param-label">
        {def.label}
        {hint && <span className="param-hint">{hint}</span>}
      </span>
      {def.type === 'number' ? (
        <NumberField def={def} value={Number(value)} onChange={onChange} />
      ) : (
        <select
          className="nodrag param-input"
          value={String(value)}
          onChange={(e) => {
            const opt = def.options.find((o) => String(o.value) === e.target.value);
            if (opt) onChange(opt.value);
          }}
        >
          {def.options.map((o) => (
            <option key={String(o.value)} value={String(o.value)}>
              {o.label}
            </option>
          ))}
        </select>
      )}
    </label>
  );
}

function DataIn({ port }: { port: PortDef }) {
  return (
    <div className="port port-in">
      <Handle type="target" position={Position.Left} id={port.id} className="handle-data" />
      <span>{port.label}</span>
    </div>
  );
}

function DataOut({ port }: { port: PortDef }) {
  return (
    <div className="port port-out">
      <span>{port.label}</span>
      <Handle type="source" position={Position.Right} id={port.id} className="handle-data" />
    </div>
  );
}

function ConditionPanel({
  operator,
  onOperator,
  ports,
}: {
  operator: string;
  onOperator: (v: string) => void;
  ports: PortDef[];
}) {
  const [a, b] = ports;
  const hint = COMPARISON_OPERATORS.find((o) => o.value === operator)?.hint;
  return (
    <div className="condition">
      <div className="condition-title">Condition</div>
      <DataIn port={a} />
      <div className="condition-op">
        {COMPARISON_OPERATORS.map((o) => (
          <button
            key={o.value}
            type="button"
            className={`nodrag op-btn ${o.value === operator ? 'active' : ''}`}
            onClick={() => onOperator(o.value)}
            title={o.hint}
          >
            {o.label}
          </button>
        ))}
      </div>
      <DataIn port={b} />
      {hint && <div className="condition-hint">compiles to {hint}</div>}
    </div>
  );
}

function assignedSymbols(def: BlockDef, params: Record<string, ParamValue>): string[] {
  return def.params
    .filter((param) => param.key.startsWith('symbol'))
    .map((param) => String(params[param.key] ?? param.default).trim())
    .filter((symbol) => symbol.length > 0);
}

function bufferSymbol(def: BlockDef, params: Record<string, ParamValue>, symbols: string[]): string | null {
  if (!def.params.some((param) => param.key === 'buffer')) return null;
  const index = Number(params.buffer ?? 0);
  const symbol = String(symbols[index] ?? '').trim();
  return symbol || null;
}

/** Symbols this node holds or forwards. Buffer indexes resolve through the Start block's tickers. */
function nodeSymbols(def: BlockDef, params: Record<string, ParamValue>, symbols: string[]): string[] {
  const named = assignedSymbols(def, params);
  if (named.length > 0) return named;
  const fromBuffer = bufferSymbol(def, params, symbols);
  return fromBuffer ? [fromBuffer] : [];
}

/**
 * A pass-through / symbol source: every parameter is a buffer or ticker, so the node
 * only holds or forwards a symbol. `current_price` is that block in the catalog.
 */
function isSymbolSource(def: BlockDef): boolean {
  if (def.type === 'start' || def.params.length === 0) return false;
  return def.params.every((param) => param.key === 'buffer' || param.key.startsWith('symbol'));
}

function SymbolText({ symbols }: { symbols: string[] }) {
  if (symbols.length === 0) return <span className="symbol-text">—</span>;
  return (
    <span className="symbol-text">
      {symbols.map((symbol, index) => (
        <span key={`${symbol}-${index}`}>{symbol}</span>
      ))}
    </span>
  );
}

function FlowHandles({ type }: { type: BlockType }) {
  const execIn = portsOf(type, 'exec', 'in')[0];
  const execOuts = portsOf(type, 'exec', 'out');
  const dataIns = portsOf(type, 'data', 'in');
  const dataOuts = portsOf(type, 'data', 'out');
  const place = (index: number, count: number) =>
    count > 1 ? { top: `${((index + 1) / (count + 1)) * 100}%` } : undefined;

  return (
    <>
      {execIn && <Handle type="target" position={Position.Top} id={execIn.id} className="handle-exec" />}
      {dataIns.map((port, index) => (
        <Handle
          key={port.id}
          type="target"
          position={Position.Left}
          id={port.id}
          className="handle-data"
          style={place(index, dataIns.length)}
        />
      ))}
      {dataOuts.map((port, index) => (
        <Handle
          key={port.id}
          type="source"
          position={Position.Right}
          id={port.id}
          className="handle-data"
          style={place(index, dataOuts.length)}
        />
      ))}
      {execOuts.length > 0 && (
        <div className={`exec-outs ${execOuts.length > 1 ? 'multi' : ''}`}>
          {execOuts.map((port) => (
            <div className={`exec-out exec-out-${port.id.split(':')[1]}`} key={port.id}>
              <Handle type="source" position={Position.Bottom} id={port.id} className="handle-exec" />
            </div>
          ))}
        </div>
      )}
    </>
  );
}

/** Resolution from Start. Tickers come from Get ticker blocks, then from symbols saved on older Start blocks. */
function useStrategyContext() {
  const joined = useStore((s) => {
    const p = s.nodeLookup.get(START_NODE_ID)?.data?.params as Record<string, ParamValue> | undefined;
    const tickers = s.nodes
      .filter((node) => node.type === 'get_ticker')
      .sort((a, b) => (a.id < b.id ? -1 : a.id > b.id ? 1 : 0))
      .slice(0, NUM_STOCK_BUFFERS)
      .map((node) => String((node.data?.params as Record<string, ParamValue> | undefined)?.symbol ?? ''));
    const symbols =
      tickers.length > 0
        ? Array.from({ length: NUM_STOCK_BUFFERS }, (_, i) => tickers[i] ?? '')
        : Array.from({ length: NUM_STOCK_BUFFERS }, (_, i) => p?.[`symbol${i}`] ?? '');
    return [p?.resolution ?? '', ...symbols].join('|');
  });
  const [resolution, ...symbols] = joined.split('|');
  return { resolution, symbols };
}

function BlockNodeImpl({ id, type, data, selected }: NodeProps<BlockNodeT>) {
  const def = BLOCK_DEFS[type as BlockType];
  const { updateNodeData } = useReactFlow();
  const { resolution, symbols } = useStrategyContext();
  if (!def) return <div className="block block-unknown">Unknown block: {type}</div>;

  if (def.type === 'start') {
    const resolutionParam = def.params.find((param) => param.key === 'resolution');
    const resolutionOptions = resolutionParam?.type === 'select' ? resolutionParam.options : [];
    const setParam = (key: string, value: ParamValue) =>
      updateNodeData(id, { params: { ...data.params, [key]: value } });
    return (
      <div className={['block', 'block-start', selected ? 'selected' : ''].join(' ')}>
        <div className="block-header">
          <span className="block-glyph" aria-hidden="true">
            <svg width="15" height="15" viewBox="0 0 16 16" fill="none">
              <path
                d={GLYPHS[def.category] ?? GLYPHS.structure}
                stroke="currentColor"
                strokeWidth="1.6"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
          </span>
          <div className="block-heading">
            <span className="block-type">{CATEGORY_LABELS[def.category] ?? def.category}</span>
            <span className="block-title">{def.label}</span>
          </div>
        </div>
        <label className="start-every">
          <span>Every</span>
          <select
            className="nodrag param-input"
            value={String(data.params.resolution ?? '5m')}
            onChange={(event) => setParam('resolution', event.target.value)}
          >
            {resolutionOptions.map((option) => (
              <option key={String(option.value)} value={String(option.value)}>
                {option.label}
              </option>
            ))}
          </select>
        </label>
        <FlowHandles type={def.type} />
      </div>
    );
  }

  if (def.type === 'get_ticker') {
    const setParam = (key: string, value: ParamValue) =>
      updateNodeData(id, { params: { ...data.params, [key]: value } });
    return (
      <div className={['block', 'block-ticker', selected ? 'selected' : ''].join(' ')}>
        <div className="block-header">
          <span className="block-glyph" aria-hidden="true">
            <svg width="15" height="15" viewBox="0 0 16 16" fill="none">
              <path
                d={GLYPHS.reserved}
                stroke="currentColor"
                strokeWidth="1.6"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
          </span>
          <div className="block-heading">
            <span className="block-title">{def.label}</span>
          </div>
        </div>
        <div className="ticker-row">
          <select
            className="nodrag ticker-chip"
            aria-label="Ticker"
            value={String(data.params.symbol ?? 'AAPL')}
            onChange={(event) => setParam('symbol', event.target.value)}
          >
            {NASDAQ_100.map((symbol) => (
              <option key={symbol} value={symbol}>
                {symbol}
              </option>
            ))}
          </select>
        </div>
        <FlowHandles type={def.type} />
      </div>
    );
  }

  if (isSymbolSource(def)) {
    return (
      <div className={['block', 'block-symbol', `block-${def.type}`, selected ? 'selected' : ''].join(' ')}>
        <SymbolText symbols={nodeSymbols(def, data.params, symbols)} />
        <FlowHandles type={def.type} />
      </div>
    );
  }

  const withSymbols = (p: ParamDef): ParamDef =>
    p.key === 'buffer' && p.type === 'select'
      ? {
          ...p,
          options: p.options.map((o) => ({
            ...o,
            label: symbols[Number(o.value)] ? String(symbols[Number(o.value)]) : 'No ticker',
          })),
        }
      : p;

  const setParam = (key: string, value: ParamValue) =>
    updateNodeData(id, { params: { ...data.params, [key]: value } });

  const execIn = portsOf(def.type, 'exec', 'in')[0];
  const execOuts = portsOf(def.type, 'exec', 'out');
  const dataIns = portsOf(def.type, 'data', 'in');
  const dataOuts = portsOf(def.type, 'data', 'out');
  const params = def.condition ? def.params.filter((p) => p.key !== 'operator') : def.params;
  const rows = Math.max(def.condition ? 0 : dataIns.length, dataOuts.length);

  return (
    <div
      className={[
        'block',
        `cat-${def.category}`,
        `block-${def.type}`,
        selected ? 'selected' : '',
        def.status === 'blocked' ? 'blocked' : '',
      ].join(' ')}
    >
      {execIn && (
        <Handle type="target" position={Position.Top} id={execIn.id} className="handle-exec" />
      )}

      <div className="block-header">
        <span className="block-glyph" aria-hidden="true">
          <svg width="15" height="15" viewBox="0 0 16 16" fill="none">
            <path
              d={GLYPHS[def.category] ?? GLYPHS.structure}
              stroke="currentColor"
              strokeWidth="1.6"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
        </span>
        <div className="block-heading">
          <span className="block-type">{CATEGORY_LABELS[def.category] ?? def.category}</span>
          <span className="block-title">{def.label}</span>
        </div>
        {def.status === 'blocked' && (
          <span className="badge badge-blocked" title={def.statusNote}>
            needs HW
          </span>
        )}
      </div>

      {def.description ? (
        <p className="block-summary" title={def.description}>
          {def.description}
        </p>
      ) : null}

      {def.condition && (
        <ConditionPanel
          operator={String(data.params.operator)}
          onOperator={(v) => setParam('operator', v)}
          ports={dataIns}
        />
      )}

      {params.length > 0 && (
        <div className="block-params">
          {params.map((p) => {
            const value = data.params[p.key] ?? p.default;
            const hint = p.type === 'number' && p.ticks ? ticksToDuration(Number(value), resolution) : undefined;
            return (
              <ParamField
                key={p.key}
                def={withSymbols(p)}
                value={value}
                hint={hint}
                onChange={(v) => setParam(p.key, v)}
              />
            );
          })}
        </div>
      )}

      {rows > 0 && (
        <div className="block-ports">
          {Array.from({ length: rows }, (_, i) => (
            <div className="port-row" key={i}>
              {!def.condition && dataIns[i] ? <DataIn port={dataIns[i]} /> : <span />}
              {dataOuts[i] ? <DataOut port={dataOuts[i]} /> : <span />}
            </div>
          ))}
        </div>
      )}

      <div className="block-footer" title={def.statusNote}>
        <code>{def.compilesTo}</code>
      </div>

      {execOuts.length > 0 && (
        <div className={`exec-outs ${execOuts.length > 1 ? 'multi' : ''}`}>
          {execOuts.map((p) => (
            <div className={`exec-out exec-out-${p.id.split(':')[1]}`} key={p.id}>
              {execOuts.length > 1 && <span className="exec-label">{p.label}</span>}
              <Handle type="source" position={Position.Bottom} id={p.id} className="handle-exec" />
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export const BlockNode = memo(BlockNodeImpl);
