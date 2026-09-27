import type { CompileResult } from '../../api/compile.ts'
import { BLOCK_DEFS } from '../../blocks/catalog.ts'
import type { BlockNode } from '../../blocks/types.ts'
import type { Diagnostic } from '../../flow/analyze.ts'

export type CompileCheck = {
  result: CompileResult
  /** The canvas changed after this check ran. */
  stale: boolean
}

type Props = {
  local: Diagnostic[]
  compiled: CompileCheck | null
  checking: boolean
  nodes: BlockNode[]
  disabled: boolean
  onCheck: () => void
  onFocusNode: (id: string) => void
}

const LEVEL_LABEL = { error: 'Error', warning: 'Warning', info: 'Note' } as const

/** Instant browser checks, plus the full compiler check on demand. */
export function ChecksPanel({ local, compiled, checking, nodes, disabled, onCheck, onFocusNode }: Props) {
  const blockName = (id?: string) => {
    const node = id ? nodes.find((n) => n.id === id) : undefined
    return node ? BLOCK_DEFS[node.type as keyof typeof BLOCK_DEFS]?.label ?? node.type : null
  }
  const errors = local.filter((d) => d.level === 'error').length

  return (
    <section className="rail-panel" aria-label="Checks">
      <header className="rail-head">
        <h2>Checks</h2>
        <p>{errors === 0 ? 'No blocking problems found while editing.' : `${errors} problem${errors === 1 ? '' : 's'} to fix before compiling.`}</p>
      </header>
      <DiagnosticList items={local.map((d) => ({ level: d.level, message: d.message, node: d.nodeId }))} blockName={blockName} onFocusNode={onFocusNode} />

      <div className="rail-divider" />
      <header className="rail-head">
        <h3>Compiler</h3>
        <p>
          {compiled == null
            ? 'Compile the strategy for TradeCPU to confirm it fits the hardware.'
            : compiled.result.ok
              ? `Compiles to ${compiled.result.words ?? '?'} of 512 program words.`
              : 'The compiler rejected this strategy.'}
          {compiled?.stale ? ' The canvas has changed since this check.' : ''}
        </p>
      </header>
      {compiled ? (
        <DiagnosticList
          items={compiled.result.diagnostics}
          blockName={blockName}
          onFocusNode={onFocusNode}
          empty="No compiler warnings."
        />
      ) : null}
      <button type="button" className="rail-action" onClick={onCheck} disabled={disabled || checking}>
        {checking ? 'Compiling…' : 'Run compiler check'}
      </button>
    </section>
  )
}

function DiagnosticList({
  items,
  blockName,
  onFocusNode,
  empty,
}: {
  items: { level: Diagnostic['level']; message: string; node?: string }[]
  blockName: (id?: string) => string | null
  onFocusNode: (id: string) => void
  empty?: string
}) {
  if (items.length === 0) return empty ? <p className="rail-empty">{empty}</p> : null
  return (
    <ul className="diagnostics">
      {items.map((item, index) => {
        const name = blockName(item.node)
        const body = (
          <>
            <span className={`diag-level diag-${item.level}`}>{LEVEL_LABEL[item.level]}</span>
            <span className="diag-message">{item.message}</span>
            {name ? <span className="diag-block">{name}</span> : null}
          </>
        )
        return (
          <li key={`${item.level}-${index}-${item.message}`}>
            {item.node && name ? (
              <button type="button" className="diag-row" onClick={() => onFocusNode(item.node!)} title="Show this block">
                {body}
              </button>
            ) : (
              <div className="diag-row">{body}</div>
            )}
          </li>
        )
      })}
    </ul>
  )
}
