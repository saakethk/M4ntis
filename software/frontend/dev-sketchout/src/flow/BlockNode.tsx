import { Handle, Position, useReactFlow, type NodeProps } from '@xyflow/react';
import { memo, useState } from 'react';
import { BLOCK_DEFS, COMPARISON_OPERATORS, portsOf } from '../blocks/catalog';
import type { BlockNode as BlockNodeT, BlockType, ParamDef, ParamValue, PortDef } from '../blocks/types';

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
}: {
  def: ParamDef;
  value: ParamValue;
  onChange: (v: ParamValue) => void;
}) {
  return (
    <label className="param">
      <span className="param-label">{def.label}</span>
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

function BlockNodeImpl({ id, type, data, selected }: NodeProps<BlockNodeT>) {
  const def = BLOCK_DEFS[type as BlockType];
  const { updateNodeData } = useReactFlow();
  if (!def) return <div className="block block-unknown">Unknown block: {type}</div>;

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
        <span className="block-title">{def.label}</span>
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
          {params.map((p) => (
            <ParamField
              key={p.key}
              def={p}
              value={data.params[p.key] ?? p.default}
              onChange={(v) => setParam(p.key, v)}
            />
          ))}
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
