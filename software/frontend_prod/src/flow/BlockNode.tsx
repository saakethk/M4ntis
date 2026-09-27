import { Handle, Position, useReactFlow, useStore, type NodeProps } from '@xyflow/react';
import { memo, useEffect, useId, useRef, useState } from 'react';
import { BLOCK_DEFS, CATEGORIES, COMPARISON_OPERATORS, portsOf } from '../blocks/catalog';
import { ticksToDuration } from '../blocks/hardware';
import { searchTickers, type TickerHit } from '../api';
import type { BlockDef, BlockNode as BlockNodeT, BlockType, ParamDef, ParamValue, PortDef } from '../blocks/types';
import { START_NODE_ID, assignPriceTicker, tickerSymbols } from './graph';

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
  className,
}: {
  def: Extract<ParamDef, { type: 'number' }>;
  value: number;
  onChange: (v: number) => void;
  className?: string;
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
      className={className ?? 'nodrag param-input'}
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

function SelectControl({
  def,
  value,
  onChange,
  className,
}: {
  def: Extract<ParamDef, { type: 'select' }>;
  value: ParamValue;
  onChange: (v: ParamValue) => void;
  className?: string;
}) {
  return (
    <select
      className={className ?? 'nodrag param-input'}
      aria-label={def.label}
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
      ) : def.type === 'select' ? (
        <SelectControl def={def} value={value} onChange={onChange} />
      ) : (
        <TickerSearch value={String(value)} onChange={(symbol) => onChange(symbol)} />
      )}
    </label>
  );
}

/**
 * Canvas-only chips for blocks that hold or forward a single value.
 * `current_price` forwards one stock buffer, `constant` holds a literal,
 * and `get_var` forwards a variable slot. The document and IR are unchanged.
 */
const VALUE_CHIP_LABEL: Partial<Record<BlockType, string>> = {
  current_price: 'Price',
  constant: 'Constant',
  get_var: 'Var',
};

function StartBlock({
  data,
  selected,
  def,
  setParam,
}: {
  data: BlockNodeT['data'];
  selected?: boolean;
  def: BlockDef;
  setParam: (key: string, value: ParamValue) => void;
}) {
  const balance = def.params.find((p) => p.key === 'startingBalance');
  const resolution = def.params.find((p) => p.key === 'resolution');
  const buffers = def.params.filter((p) => p.key.startsWith('symbol') && p.type === 'select');
  const execOuts = portsOf('start', 'exec', 'out');

  return (
    <div className={['block', 'block-start', selected ? 'selected' : ''].join(' ')}>
      <div className="start-title">{def.label}</div>
      <div className="start-fields">
        {balance?.type === 'number' && (
          <label className="start-field">
            <span>Balance</span>
            <NumberField
              def={balance}
              value={Number(data.params[balance.key] ?? balance.default)}
              onChange={(v) => setParam(balance.key, v)}
            />
          </label>
        )}
        {resolution?.type === 'select' && (
          <label className="start-field">
            <span>Resolution</span>
            <SelectControl
              def={resolution}
              value={data.params[resolution.key] ?? resolution.default}
              onChange={(v) => setParam(resolution.key, v)}
            />
          </label>
        )}
      </div>
      {buffers.length > 0 && (
        <div className="buffer-chips" aria-label="Stock buffers">
          {buffers.map((p) =>
            p.type === 'select' ? (
              <label key={p.key} className="buffer-chip" title={p.label}>
                <span>{p.label}</span>
                <SelectControl
                  def={p}
                  value={data.params[p.key] ?? p.default}
                  onChange={(v) => setParam(p.key, v)}
                  className="nodrag buffer-chip-select"
                />
              </label>
            ) : null,
          )}
        </div>
      )}
      {execOuts.length > 0 && (
        <div className="exec-outs">
          {execOuts.map((p) => (
            <div className="exec-out" key={p.id}>
              <Handle type="source" position={Position.Bottom} id={p.id} className="handle-exec" />
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function ValueChip({
  data,
  selected,
  def,
  setParam,
  withSymbols,
}: {
  data: BlockNodeT['data'];
  selected?: boolean;
  def: BlockDef;
  setParam: (key: string, value: ParamValue) => void;
  withSymbols: (p: ParamDef) => ParamDef;
}) {
  const label = VALUE_CHIP_LABEL[def.type] ?? def.label;
  const dataOuts = portsOf(def.type, 'data', 'out');

  return (
    <div
      className={['block', 'block-slim', `block-${def.type}`, selected ? 'selected' : ''].join(' ')}
      title={def.label}
    >
      <span className="slim-label">{label}</span>
      {def.params.map((raw) => {
        const param = withSymbols(raw);
        const value = data.params[param.key] ?? param.default;
        if (param.type === 'number') {
          return (
            <NumberField
              key={param.key}
              def={param}
              value={Number(value)}
              onChange={(v) => setParam(param.key, v)}
              className="nodrag param-input slim-input"
            />
          );
        }
        if (param.type !== 'select') return null;
        return (
          <SelectControl
            key={param.key}
            def={param}
            value={value}
            onChange={(v) => setParam(param.key, v)}
            className="nodrag param-input slim-input"
          />
        );
      })}
      {dataOuts.map((port) => (
        <Handle key={port.id} type="source" position={Position.Right} id={port.id} className="handle-data" />
      ))}
    </div>
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

function TickerSearch({ value, onChange }: { value: string; onChange: (symbol: string) => void }) {
  const selected = value.trim().toUpperCase();
  const [query, setQuery] = useState('');
  const [open, setOpen] = useState(false);
  const [matches, setMatches] = useState<TickerHit[]>([]);
  const [searchError, setSearchError] = useState<string | null>(null);
  const listId = useId();
  const inputRef = useRef<HTMLInputElement>(null);
  const showList = open && query.trim().length > 0;

  useEffect(() => {
    const q = query.trim();
    if (!q) {
      setMatches([]);
      setSearchError(null);
      return;
    }
    let ignore = false;
    const timer = window.setTimeout(() => {
      searchTickers(q)
        .then((rows) => {
          if (ignore) return;
          setMatches(rows);
          setSearchError(null);
        })
        .catch(() => {
          if (ignore) return;
          setMatches([]);
          setSearchError('Search unavailable');
        });
    }, 180);
    return () => {
      ignore = true;
      window.clearTimeout(timer);
    };
  }, [query]);

  const choose = (symbol: string) => {
    onChange(symbol);
    setQuery('');
    setOpen(false);
    inputRef.current?.blur();
  };

  return (
    <div className={`ticker-search nodrag nopan nowheel${open ? ' open' : ''}`}>
      <span className="ticker-chip">{selected || '—'}</span>
      <input
        ref={inputRef}
        className="nodrag nopan ticker-search-input"
        aria-label="Search ticker"
        role="combobox"
        aria-expanded={showList}
        aria-controls={listId}
        aria-autocomplete="list"
        spellCheck={false}
        autoComplete="off"
        autoCapitalize="characters"
        placeholder="Search"
        value={query}
        onFocus={() => setOpen(true)}
        onBlur={() => {
          setOpen(false);
          setQuery('');
        }}
        onChange={(event) => {
          setQuery(event.target.value.toUpperCase());
          setOpen(true);
        }}
        onKeyDown={(event) => {
          if (event.key === 'Enter') {
            event.preventDefault();
            event.stopPropagation();
            const pick = matches[0];
            if (pick) choose(pick.symbol);
          } else if (event.key === 'Escape') {
            event.preventDefault();
            event.stopPropagation();
            setQuery('');
            setOpen(false);
            inputRef.current?.blur();
          }
        }}
      />
      {showList && (
        <ul className="ticker-matches nodrag nopan nowheel" id={listId} role="listbox">
          {searchError ? (
            <li className="ticker-match-empty">{searchError}</li>
          ) : matches.length === 0 ? (
            <li className="ticker-match-empty">No matches</li>
          ) : (
            matches.map((hit, index) => (
              <li key={hit.symbol}>
                <button
                  type="button"
                  role="option"
                  aria-selected={hit.symbol === selected}
                  className={['nodrag', 'nopan', 'ticker-match', index === 0 ? 'top' : '']
                    .filter(Boolean)
                    .join(' ')}
                  onMouseDown={(event) => {
                    event.preventDefault();
                    choose(hit.symbol);
                  }}
                >
                  <span>{hit.symbol}</span>
                  {hit.name && hit.name !== hit.symbol ? <span className="ticker-match-name">{hit.name}</span> : null}
                </button>
              </li>
            ))
          )}
        </ul>
      )}
    </div>
  );
}

/** Resolution from Start. Tickers come from `tickerSymbols` (Get ticker blocks, then older Start symbols). */
function useStrategyContext() {
  const joined = useStore((s) => {
    const p = s.nodeLookup.get(START_NODE_ID)?.data?.params as Record<string, ParamValue> | undefined;
    const symbols = tickerSymbols(s.nodes as BlockNodeT[]);
    return [p?.resolution ?? '', ...symbols].join('|');
  });
  const [resolution, ...symbols] = joined.split('|');
  return { resolution, symbols };
}

function BlockNodeImpl({ id, type, data, selected }: NodeProps<BlockNodeT>) {
  const def = BLOCK_DEFS[type as BlockType];
  const { updateNodeData, setNodes } = useReactFlow();
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
          <TickerSearch
            value={String(data.params.symbol ?? 'AAPL')}
            onChange={(symbol) => setParam('symbol', symbol)}
          />
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

  if (def.type === 'start') {
    return <StartBlock data={data} selected={selected} def={def} setParam={setParam} />;
  }

  if (def.type in VALUE_CHIP_LABEL) {
    return (
      <ValueChip data={data} selected={selected} def={def} setParam={setParam} withSymbols={withSymbols} />
    );
  }

  const execIn = portsOf(def.type, 'exec', 'in')[0];
  const execOuts = portsOf(def.type, 'exec', 'out');
  const dataIns = portsOf(def.type, 'data', 'in');
  const dataOuts = portsOf(def.type, 'data', 'out');
  const params = (def.condition ? def.params.filter((p) => p.key !== 'operator') : def.params).filter(
    (p) => !(def.type === 'price_n_ticks_ago' && p.key === 'buffer'),
  );
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
      title={def.description || undefined}
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
            if (p.type === 'ticker') {
              const named = String(data.params.symbol ?? '').trim();
              const fromBuffer = String(symbols[Number(data.params.buffer ?? 0)] ?? '').trim();
              return (
                <label className="param" key={p.key}>
                  <span className="param-label">{p.label}</span>
                  <TickerSearch
                    value={named || fromBuffer}
                    onChange={(symbol) => {
                      setNodes((current) => assignPriceTicker(current as BlockNodeT[], id, symbol));
                    }}
                  />
                </label>
              );
            }
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
