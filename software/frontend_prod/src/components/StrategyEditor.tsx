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
  createStrategy,
  getDummyBacktest,
  getStrategy,
  runDummyBacktest,
  updateStrategy,
  type BacktestMenu,
} from '../api'
import { BLOCK_DEFS, BLOCK_TYPES, isBlockType } from '../blocks/catalog'
import type { BlockEdge, BlockNode as BlockNodeT, BlockType } from '../blocks/types'
import { BlockNode } from '../flow/BlockNode'
import { START_NODE_ID, analyze, checkConnection, connect, makeNode } from '../flow/graph'
import { fromDocument, toDocument, toIR } from '../flow/serialize'
import { TEMPLATES, assistantCrossover, type AssistantProgram } from '../flow/templates'
import { BlockPalette, DRAG_MIME } from './BlockPalette'

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
}

function documentPayload(raw: unknown): unknown {
  if (typeof raw !== 'string') return raw
  return JSON.parse(raw)
}

function StrategyCanvas({ userId, strategyId, unavailable = false, onClose, onCreated }: Props) {
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
  const [backtest, setBacktest] = useState<BacktestMenu | null>(null)
  const [backtestError, setBacktestError] = useState<string | null>(null)
  const [message, setMessage] = useState<string | null>(unavailable ? 'Could not open this strategy.' : null)
  const [messageError, setMessageError] = useState(unavailable)
  const [compiledLog, setCompiledLog] = useState<string | null>(null)
  const canvasRef = useRef<HTMLDivElement>(null)
  const skipFetchId = useRef<number | null>(null)
  const { screenToFlowPosition, getViewport } = useReactFlow()

  useEffect(() => {
    let ignore = false
    getDummyBacktest()
      .then((menu) => {
        if (!ignore) {
          setBacktest(menu)
          setBacktestError(null)
        }
      })
      .catch((error: unknown) => {
        if (!ignore) {
          setBacktestError(error instanceof Error ? error.message : 'Could not load the backtest.')
        }
      })
    return () => {
      ignore = true
    }
  }, [])

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

  function compile() {
    const raw = JSON.stringify(toDocument(name.trim(), nodes, edges, getViewport()))
    const compiled = JSON.stringify(toIR(nodes, edges), null, 2)
    console.info(raw)
    console.info(compiled)
    setCompiledLog(`raw\n${raw}\n\ncompiled\n${compiled}`)
    const errors = analyze(nodes, edges).filter((item) => item.level === 'error')
    if (errors.length === 0) {
      showMessage('Compiled', false)
      return
    }
    const summary = errors.length === 1 ? errors[0].message : `${errors.length} errors. ${errors[0].message}`
    showMessage(summary, true)
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
      setMessage(null)
      setMessageError(false)
      if (existingId == null) {
        // Keep the canvas. The route change would otherwise reload this id.
        skipFetchId.current = savedRow.id
        onCreated?.(savedRow.id)
      }
      return savedRow.id
    } catch (error) {
      setSaved(false)
      showMessage(error instanceof Error ? error.message : 'Could not save', true)
      return null
    } finally {
      setSaving(false)
    }
  }

  async function runBacktest() {
    if (!loaded || running || saving) return
    setRunning(true)
    setBacktest(null)
    try {
      const id = saved && storedId != null ? storedId : await persist()
      if (id == null) return
      const result = await runDummyBacktest(userId, id)
      const ending = result.balances[result.balances.length - 1]
      const starting = result.balances[0]
      const equity = ending?.equity ?? 0
      const returnPct =
        starting && starting.equity !== 0 ? ((equity - starting.equity) / starting.equity) * 100 : 0
      setBacktest({
        dummy: result.dummy,
        equity,
        returnPct,
        orders: result.orders,
        balances: result.balances,
      })
      setBacktestError(null)
      showMessage(`Dummy backtest finished. Ending equity ${equity.toLocaleString('en-US')}.`, false)
    } catch (error) {
      showMessage(error instanceof Error ? error.message : 'Could not run the backtest', true)
    } finally {
      setRunning(false)
    }
  }

  return (
    <div className="strategy-editor">
      <BlockPalette onAdd={addBlock} onApply={applyProgram} />
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
            <button type="button" className="quiet" onClick={compile} disabled={!loaded}>
              Compile
            </button>
            <button type="button" className="quiet" onClick={() => void persist()} disabled={!loaded || saving || running}>
              {saving ? 'Saving…' : saved ? 'Saved' : 'Save'}
            </button>
            <button
              type="button"
              className="run-backtest"
              onClick={() => void runBacktest()}
              disabled={!loaded || saving || running}
            >
              {running ? 'Running…' : 'Run Backtest'}
            </button>
          </div>
        </div>
        {compiledLog ? (
          <pre className="compile-log" aria-label="Strategy JSON">
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
      <BacktestMenu menu={backtest} error={backtestError} />
    </div>
  )
}

function money(value: number) {
  return value.toLocaleString('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 })
}

function BacktestMenu({ menu, error }: { menu: BacktestMenu | null; error: string | null }) {
  return (
    <aside className="backtest-menu" aria-label="Backtest">
      <h2>Backtest</h2>
      {error ? <p className="form-error">{error}</p> : null}
      {menu ? (
        <>
          <p className="backtest-equity">{money(menu.equity)}</p>
          <p className={menu.returnPct >= 0 ? 'backtest-return up' : 'backtest-return down'}>
            {menu.returnPct >= 0 ? '+' : ''}
            {menu.returnPct.toFixed(2)}%
          </p>
          <h3>Orders</h3>
          <ul>
            {menu.orders.map((order, index) => (
              <li key={`${order.symbol}-${order.side}-${index}`}>
                <span className={order.side === 'buy' ? 'up' : 'down'}>{order.side}</span>
                {order.quantity} {order.symbol} at {order.price}
              </li>
            ))}
          </ul>
          <h3>Balance</h3>
          <ul>
            {menu.balances.map((point, index) => (
              <li key={`${point.equity}-${index}`}>
                Equity {money(point.equity)} · Cash {money(point.cash)}
              </li>
            ))}
          </ul>
        </>
      ) : (
        !error && <p className="backtest-wait">Loading backtest…</p>
      )}
    </aside>
  )
}

export function StrategyEditor(props: Props) {
  return (
    <ReactFlowProvider>
      <StrategyCanvas {...props} />
    </ReactFlowProvider>
  )
}
