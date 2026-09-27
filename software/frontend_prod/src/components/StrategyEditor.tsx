import {
  Background,
  BackgroundVariant,
  Controls,
  ReactFlow,
  ReactFlowProvider,
  useEdgesState,
  useNodesState,
  useReactFlow,
  type Connection,
  type Edge,
  type EdgeChange,
  type NodeChange,
  type NodeTypes,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { useCallback, useEffect, useRef, useState, type DragEvent } from 'react'
import {
  compileStrategy,
  createStrategy,
  getStrategy,
  listStrategyVersions,
  revertStrategyVersion,
  runDummyBacktest,
  updateStrategy,
  type CompileResult,
  type StrategyVersion,
} from '../api'
import { BLOCK_DEFS, BLOCK_TYPES, isBlockType } from '../blocks/catalog'
import { RESOLUTIONS } from '../blocks/hardware'
import type { BlockEdge, BlockNode as BlockNodeT, BlockType } from '../blocks/types'
import { BlockNode } from '../flow/BlockNode'
import { START_NODE_ID, checkConnection, connect, makeNode } from '../flow/graph'
import { fromDocument, toDocument, toIR } from '../flow/serialize'
import { TEMPLATES, assistantCrossover, type AssistantProgram } from '../flow/templates'
import { Assistant, BlockPalette, DRAG_MIME } from './BlockPalette'

const nodeTypes: NodeTypes = Object.fromEntries(BLOCK_TYPES.map((type) => [type, BlockNode]))

const blankTemplate = TEMPLATES.find((template) => template.id === 'blank')

function isTypingTarget(target: EventTarget | null) {
  if (!(target instanceof HTMLElement)) return false
  const tag = target.tagName
  return tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || target.isContentEditable
}

function isProtectedNode(node: BlockNodeT) {
  if (node.id === START_NODE_ID || node.type === 'start' || node.deletable === false) return true
  return isBlockType(node.type) && BLOCK_DEFS[node.type].system === true
}

function TrashIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" aria-hidden="true" fill="none">
      <path
        d="M4 7h16M9 7V5h6v2M18.5 7l-.8 12.2a1.5 1.5 0 0 1-1.5 1.4H7.8a1.5 1.5 0 0 1-1.5-1.4L5.5 7M10 11v6M14 11v6"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  )
}

type Props = {
  userId: number
  strategyId: number | null
  unavailable?: boolean
  onClose: () => void
  onCreated?: (id: number) => void
  onOpenBacktest: (id: number) => void
}

function documentPayload(raw: unknown): unknown {
  if (typeof raw !== 'string') return raw
  return JSON.parse(raw)
}

function StrategyCanvas({
  userId,
  strategyId,
  unavailable = false,
  onClose,
  onCreated,
  onOpenBacktest,
}: Props) {
  const blank = blankTemplate?.build() ?? { nodes: [], edges: [] }
  const [name, setName] = useState(strategyId == null && !unavailable ? 'Untitled strategy' : '')
  const [nodes, setNodes, onNodesChange] = useNodesState<BlockNodeT>(blank.nodes)
  const [edges, setEdges, onEdgesChange] = useEdgesState<BlockEdge>(blank.edges)
  const [storedId, setStoredId] = useState<number | null>(strategyId)
  const [loading, setLoading] = useState(strategyId != null && !unavailable)
  const [loaded, setLoaded] = useState(strategyId == null && !unavailable)
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [running, setRunning] = useState(false)
  const [message, setMessage] = useState<string | null>(unavailable ? 'Could not open this strategy.' : null)
  const [messageError, setMessageError] = useState(unavailable)
  const [compiledLog, setCompiledLog] = useState<string | null>(null)
  const [historyOpen, setHistoryOpen] = useState(false)
  const [versions, setVersions] = useState<StrategyVersion[] | null>(null)
  const [historyError, setHistoryError] = useState<string | null>(null)
  const [revertingId, setRevertingId] = useState<number | null>(null)
  const canvasRef = useRef<HTMLDivElement>(null)
  const skipFetchId = useRef<number | null>(null)
  const { screenToFlowPosition, getViewport, fitView } = useReactFlow()

  useEffect(() => {
    if (strategyId == null || unavailable) return
    // The id just came back from the first save of this unsaved editor.
    // Reloading here would replace the canvas the user is still editing.
    if (skipFetchId.current === strategyId) return
    let ignore = false
    getStrategy(strategyId)
      .then((row) => {
        if (ignore) return
        const graph = fromDocument(documentPayload(row.document))
        setName(graph.name || row.name)
        setNodes(graph.nodes)
        setEdges(graph.edges)
        setLoaded(true)
        setMessage(null)
        setMessageError(false)
      })
      .catch((error: unknown) => {
        if (ignore) return
        setLoaded(false)
        setMessageError(true)
        setMessage(error instanceof Error ? error.message : 'Could not open this strategy.')
      })
      .finally(() => {
        if (!ignore) setLoading(false)
      })
    return () => {
      ignore = true
    }
  }, [strategyId, unavailable, setEdges, setNodes])

  const showMessage = useCallback((text: string, isError: boolean) => {
    setMessage(text)
    setMessageError(isError)
  }, [])

  const handleNodesChange = useCallback(
    (changes: NodeChange<BlockNodeT>[]) => {
      onNodesChange(changes)
      if (changes.some((change) => change.type !== 'select' && change.type !== 'dimensions')) {
        setSaved(false)
      }
    },
    [onNodesChange],
  )

  const handleEdgesChange = useCallback(
    (changes: EdgeChange<BlockEdge>[]) => {
      onEdgesChange(changes)
      if (changes.some((change) => change.type !== 'select')) setSaved(false)
    },
    [onEdgesChange],
  )

  const isValidConnection = useCallback(
    (connection: Connection | Edge) => checkConnection(connection, edges) === null,
    [edges],
  )

  const onConnect = useCallback(
    (connection: Connection) => {
      const problem = checkConnection(connection, edges)
      if (problem) {
        showMessage(problem, true)
        return
      }
      setEdges((current) => connect(connection, current))
      setSaved(false)
    },
    [edges, setEdges, showMessage],
  )

  const addBlock = useCallback(
    (type: BlockType, position?: { x: number; y: number }) => {
      if (!loaded || BLOCK_DEFS[type].system) return
      const bounds = canvasRef.current?.getBoundingClientRect()
      const pos =
        position ??
        screenToFlowPosition({
          x: bounds ? bounds.left + bounds.width / 2 : window.innerWidth / 2,
          y: bounds ? bounds.top + bounds.height / 2 : window.innerHeight / 2,
        })
      const node = makeNode(type, pos)
      setNodes((current) => [...current.map((item) => ({ ...item, selected: false })), { ...node, selected: true }])
      setSaved(false)
    },
    [loaded, screenToFlowPosition, setNodes],
  )

  const applyProgram = useCallback(
    (program: AssistantProgram) => {
      if (!loaded) return
      const graph = assistantCrossover(program)
      setNodes(graph.nodes)
      setEdges(graph.edges)
      setSaved(false)
      showMessage('Applied the assistant strategy.', false)
    },
    [loaded, setEdges, setNodes, showMessage],
  )

  const onDrop = useCallback(
    (event: DragEvent) => {
      event.preventDefault()
      const type = event.dataTransfer.getData(DRAG_MIME)
      if (!isBlockType(type) || BLOCK_DEFS[type].system) return
      const point = screenToFlowPosition({ x: event.clientX, y: event.clientY })
      addBlock(type, { x: point.x - 110, y: point.y - 20 })
    },
    [addBlock, screenToFlowPosition],
  )

  const deleteSelected = useCallback(() => {
    const doomed = nodes.filter((node) => node.selected && !isProtectedNode(node))
    if (doomed.length === 0) return
    const ids = new Set(doomed.map((node) => node.id))
    setNodes((current) => current.filter((node) => !ids.has(node.id)))
    setEdges((current) => current.filter((edge) => !ids.has(edge.source) && !ids.has(edge.target)))
    setSaved(false)
  }, [nodes, setEdges, setNodes])

  useEffect(() => {
    if (!loaded) return
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== 'Delete' && event.key !== 'Backspace') return
      if (event.metaKey || event.ctrlKey || event.altKey) return
      if (isTypingTarget(event.target)) return
      event.preventDefault()
      deleteSelected()
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [deleteSelected, loaded])

  const canDelete = nodes.some((node) => node.selected && !isProtectedNode(node))

  async function compileDocument(document: unknown, note: string) {
    try {
      const result = await compileStrategy(document)
      showCompiled(result, note)
    } catch (error) {
      setCompiledLog(null)
      showMessage(error instanceof Error ? error.message : 'Could not compile', true)
    }
  }

  function showCompiled(result: CompileResult, note: string) {
    const lines = result.diagnostics.map((item) =>
      item.node ? `${item.level}: ${item.message} [${item.node}]` : `${item.level}: ${item.message}`,
    )
    if (result.ok) {
      setCompiledLog(lines.length > 0 ? `${lines.join('\n')}\n\n${result.asm}` : result.asm)
      showMessage(note, false)
      return
    }
    setCompiledLog(lines.join('\n') || result.detail || 'Could not compile')
    const errors = result.diagnostics.filter((item) => item.level === 'error')
    const first = errors[0]?.message || result.diagnostics[0]?.message || result.detail || 'Could not compile'
    showMessage(errors.length > 1 ? `${errors.length} errors. ${first}` : first, true)
  }

  function compile() {
    const trimmed = name.trim()
    if (!trimmed) {
      showMessage('Name is required', true)
      return
    }
    void compileDocument(toDocument(trimmed, nodes, edges, getViewport()), 'Compiled')
  }

  async function openHistory() {
    if (storedId == null || saving || revertingId != null) return
    setHistoryOpen(true)
    setHistoryError(null)
    setVersions(null)
    try {
      setVersions(await listStrategyVersions(storedId))
    } catch (error) {
      setHistoryError(error instanceof Error ? error.message : 'Could not load saved versions.')
    }
  }

  async function revert(versionId: number) {
    if (storedId == null || revertingId != null) return
    setRevertingId(versionId)
    setHistoryError(null)
    try {
      const row = await revertStrategyVersion(storedId, versionId)
      const graph = fromDocument(documentPayload(row.document))
      setName(graph.name || row.name)
      setNodes(graph.nodes)
      setEdges(graph.edges)
      setSaved(true)
      setVersions(await listStrategyVersions(storedId))
      await compileDocument(row.document, 'Reverted and compiled')
    } catch (error) {
      setHistoryError(error instanceof Error ? error.message : 'Could not revert this version.')
    } finally {
      setRevertingId(null)
    }
  }

  async function persist(): Promise<number | null> {
    if (!loaded || saving) return null
    const trimmed = name.trim()
    if (!trimmed) {
      setSaved(false)
      showMessage('Name is required', true)
      return null
    }
    setSaving(true)
    try {
      const document = toDocument(trimmed, nodes, edges, getViewport())
      const ir = toIR(nodes, edges)
      const body = { name: trimmed, document, ir, visibility: 'private' as const }
      const existingId = storedId
      const savedRow = existingId == null ? await createStrategy(body) : await updateStrategy(existingId, body)
      setStoredId(savedRow.id)
      setSaved(true)
      if (existingId == null) {
        // Keep the canvas. The route change would otherwise reload this id.
        skipFetchId.current = savedRow.id
        onCreated?.(savedRow.id)
      }
      await compileDocument(document, 'Saved and compiled')
      return savedRow.id
    } catch (error) {
      setSaved(false)
      showMessage(error instanceof Error ? error.message : 'Could not save', true)
      return null
    } finally {
      setSaving(false)
    }
  }

  function recenter() {
    void fitView({ padding: 0.22, duration: 250 })
  }

  async function runBacktest() {
    if (!loaded || running || saving) return
    setRunning(true)
    try {
      const id = saved && storedId != null ? storedId : await persist()
      if (id == null) return
      const result = await runDummyBacktest(userId, id)
      onOpenBacktest(result.id)
    } catch (error) {
      showMessage(error instanceof Error ? error.message : 'Could not run the backtest', true)
    } finally {
      setRunning(false)
    }
  }

  return (
    <div className="strategy-editor">
      <BlockPalette onAdd={addBlock} />
      <section className="editor-stage">
        <div className="canvas-bar">
          <div className="canvas-title">
            <button type="button" className="quiet" onClick={onClose}>
              Home
            </button>
            <input
              className="editor-name"
              value={name}
              aria-label="Strategy name"
              disabled={!loaded}
              onChange={(event) => {
                setName(event.target.value)
                setSaved(false)
              }}
            />
          </div>
          <div className="canvas-actions">
            {message ? (
              <p className={messageError ? 'form-error editor-note' : 'editor-note'} role="status">
                {message}
              </p>
            ) : null}
            <button type="button" className="quiet" onClick={recenter} disabled={!loaded}>
              Recenter
            </button>
            <button
              type="button"
              className="quiet icon-button"
              aria-label="Delete selected block"
              title="Delete selected block"
              onClick={deleteSelected}
              disabled={!loaded || !canDelete}
            >
              <TrashIcon />
            </button>
            <button
              type="button"
              className="quiet"
              onClick={() => void openHistory()}
              disabled={!loaded || storedId == null || saving || running || revertingId != null}
            >
              History
            </button>
            <button type="button" className="quiet" onClick={compile} disabled={!loaded}>
              Compile
            </button>
            <button type="button" className="quiet" onClick={() => void persist()} disabled={!loaded || saving || running}>
              {saving ? 'Saving…' : saved ? 'Saved' : 'Save'}
            </button>
          </div>
        </div>
        {historyOpen ? (
          <section className="version-history" aria-label="Saved versions">
            <div className="version-history-head">
              <h2>Saved versions</h2>
              <button type="button" className="quiet" onClick={() => setHistoryOpen(false)}>
                Close
              </button>
            </div>
            {historyError ? <p className="form-error">{historyError}</p> : null}
            {versions == null && !historyError ? <p className="version-empty">Loading versions…</p> : null}
            {versions != null && versions.length === 0 ? (
              <p className="version-empty">No saved versions yet.</p>
            ) : null}
            {versions != null && versions.length > 0 ? (
              <ul>
                {versions.map((version) => (
                  <li key={version.id} className="version-row">
                    <span className="version-name">{version.name}</span>
                    <time dateTime={version.createdAt}>{formatVersionTime(version.createdAt)}</time>
                    <button
                      type="button"
                      className="quiet"
                      onClick={() => void revert(version.id)}
                      disabled={revertingId != null}
                    >
                      {revertingId === version.id ? 'Reverting…' : 'Revert'}
                    </button>
                  </li>
                ))}
              </ul>
            ) : null}
          </section>
        ) : null}
        {compiledLog ? (
          <pre className="compile-log" aria-label="Compiled program">
            {compiledLog}
          </pre>
        ) : null}
        <div
          ref={canvasRef}
          className="editor-canvas"
          onDragOver={(event) => event.preventDefault()}
          onDrop={onDrop}
        >
          {loaded ? (
            <ReactFlow
              nodes={nodes}
              edges={edges}
              nodeTypes={nodeTypes}
              onNodesChange={handleNodesChange}
              onEdgesChange={handleEdgesChange}
              onConnect={onConnect}
              isValidConnection={isValidConnection}
              fitView
              fitViewOptions={{ padding: 0.22 }}
              minZoom={0.2}
              snapToGrid
              snapGrid={[10, 10]}
              deleteKeyCode={null}
              colorMode="light"
              proOptions={{ hideAttribution: true }}
            >
              <Background variant={BackgroundVariant.Dots} gap={20} size={1} color="#e2e6ec" />
              <Controls showInteractive={false} />
            </ReactFlow>
          ) : (
            <p className={messageError ? 'form-error editor-empty' : 'editor-empty'}>
              {loading ? 'Loading strategy…' : message}
            </p>
          )}
        </div>
      </section>
      <aside className="editor-rail">
        <BacktestPanel
          running={running}
          disabled={!loaded || saving || running}
          onRun={() => void runBacktest()}
        />
        <Assistant onApply={applyProgram} />
      </aside>
    </div>
  )
}

function formatVersionTime(value: string): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })
}

const BACKTEST_PARAMETERS = {
  symbol: 'AAPL',
  timeframe: '1m',
  start: '2024-01-02',
  end: '2024-06-28',
  capital: 100_000,
}

function BacktestPanel({
  running,
  disabled,
  onRun,
}: {
  running: boolean
  disabled: boolean
  onRun: () => void
}) {
  const [symbol, setSymbol] = useState(BACKTEST_PARAMETERS.symbol)
  const [timeframe, setTimeframe] = useState(BACKTEST_PARAMETERS.timeframe)
  const [start, setStart] = useState(BACKTEST_PARAMETERS.start)
  const [end, setEnd] = useState(BACKTEST_PARAMETERS.end)
  const [capital, setCapital] = useState(BACKTEST_PARAMETERS.capital.toLocaleString('en-US'))

  return (
    <section className="backtest-menu" aria-label="Backtest">
      <p className="plan-kicker">Backtest</p>
      <h2>Parameters</h2>
      <div className="backtest-params">
        <label>
          <span>Symbol</span>
          <input
            value={symbol}
            aria-label="Symbol"
            spellCheck={false}
            onChange={(event) => setSymbol(event.target.value.toUpperCase())}
          />
        </label>
        <label>
          <span>Timeframe</span>
          <select aria-label="Timeframe" value={timeframe} onChange={(event) => setTimeframe(event.target.value)}>
            {RESOLUTIONS.map((resolution) => (
              <option key={resolution.value} value={resolution.value}>
                {resolution.value}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span>Start</span>
          <input aria-label="Start" type="date" value={start} onChange={(event) => setStart(event.target.value)} />
        </label>
        <label>
          <span>End</span>
          <input aria-label="End" type="date" value={end} onChange={(event) => setEnd(event.target.value)} />
        </label>
        <label>
          <span>Capital</span>
          <span className="backtest-capital">
            <span aria-hidden="true">$</span>
            <input
              aria-label="Capital"
              inputMode="numeric"
              value={capital}
              onChange={(event) => setCapital(event.target.value.replace(/[^\d]/g, ''))}
              onBlur={() => {
                const amount = Number(capital)
                if (!capital || Number.isNaN(amount)) {
                  setCapital(String(BACKTEST_PARAMETERS.capital))
                  return
                }
                setCapital(amount.toLocaleString('en-US'))
              }}
              onFocus={() => setCapital(capital.replace(/,/g, ''))}
            />
          </span>
        </label>
      </div>
      <button type="button" className="run-backtest" onClick={onRun} disabled={disabled}>
        {running ? 'Running…' : 'Run Backtest'}
      </button>
    </section>
  )
}

export function StrategyEditor(props: Props) {
  return (
    <ReactFlowProvider>
      <StrategyCanvas {...props} />
    </ReactFlowProvider>
  )
}
