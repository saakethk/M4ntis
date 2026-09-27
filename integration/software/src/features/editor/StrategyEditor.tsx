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
import { useCallback, useEffect, useMemo, useRef, useState, type DragEvent } from 'react'
import { runBacktest } from '../../api/backtests.ts'
import { compileStrategy } from '../../api/compile.ts'
import { createStrategy, getStrategy, revertStrategyVersion, updateStrategy } from '../../api/strategies.ts'
import { BLOCK_DEFS, BLOCK_TYPES, isBlockType } from '../../blocks/catalog.ts'
import type { BlockEdge, BlockNode as BlockNodeT, BlockType } from '../../blocks/types.ts'
import { DownloadIcon, FitIcon, TrashIcon, UploadIcon } from '../../components/icons.tsx'
import { analyze } from '../../flow/analyze.ts'
import { applyAssistantGraph, canvasSnapshot, type AssistantGraph } from '../../flow/assistantGraph.ts'
import { START_NODE_ID, checkConnection, connect, makeNode } from '../../flow/graph.ts'
import { parseProgramFile, programFileName, programFileText } from '../../flow/programFile.ts'
import { fromDocument, toDocument, toIR, type LoadedStrategy } from '../../flow/serialize.ts'
import { BLANK_TEMPLATE, type Template } from '../../flow/templates.ts'
import { downloadText, pickTextFile } from '../../lib/files.ts'
import { useResolvedTheme } from '../../lib/theme.ts'
import { AssistantPanel } from '../assistant/AssistantPanel.tsx'
import { BacktestPanel } from './BacktestPanel.tsx'
import { BlockPalette, DRAG_MIME } from './BlockPalette.tsx'
import { ChecksPanel, type CompileCheck } from './ChecksPanel.tsx'
import { HistoryPanel } from './HistoryPanel.tsx'
import { BlockNode } from './nodes/BlockNode.tsx'
import { TemplateMenu } from './TemplateMenu.tsx'

const nodeTypes: NodeTypes = Object.fromEntries(BLOCK_TYPES.map((type) => [type, BlockNode]))
const FIT = { padding: 0.22, duration: 250 }

type RailTab = 'assistant' | 'checks' | 'backtest'
type Note = { text: string; error: boolean }

type Props = {
  userId: number
  /** A saved strategy to open, or null for a new one. */
  strategyId: number | null
  /** A program imported from a JSON file, used for a new strategy. */
  initialProgram?: LoadedStrategy | null
  unavailable?: boolean
  onClose: () => void
  /** A new strategy (or a copy) was saved for the first time. */
  onCreated: (id: number) => void
  onOpenBacktest: (id: number) => void
}

function isTypingTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false
  return ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName) || target.isContentEditable
}

function isProtected(node: BlockNodeT): boolean {
  return node.id === START_NODE_ID || node.deletable === false || (isBlockType(node.type) && BLOCK_DEFS[node.type].system === true)
}

function StrategyCanvas({ userId, strategyId, initialProgram, unavailable = false, onClose, onCreated, onOpenBacktest }: Props) {
  const opening = strategyId != null && !unavailable
  const start = initialProgram ?? { name: 'Untitled strategy', ...BLANK_TEMPLATE.build() }
  const [name, setName] = useState(opening || unavailable ? '' : start.name)
  const [nodes, setNodes, onNodesChange] = useNodesState<BlockNodeT>(start.nodes)
  const [edges, setEdges, onEdgesChange] = useEdgesState<BlockEdge>(start.edges)
  const [storedId, setStoredId] = useState<number | null>(strategyId)
  const [owned, setOwned] = useState(true)
  const [loaded, setLoaded] = useState(!opening && !unavailable)
  const [dirty, setDirty] = useState(initialProgram != null)
  const [saving, setSaving] = useState(false)
  const [running, setRunning] = useState(false)
  const [checking, setChecking] = useState(false)
  const [compiled, setCompiled] = useState<CompileCheck | null>(null)
  const [note, setNote] = useState<Note | null>(unavailable ? { text: 'Could not open this strategy.', error: true } : null)
  const [historyOpen, setHistoryOpen] = useState(false)
  const [tab, setTab] = useState<RailTab>('assistant')
  const canvasRef = useRef<HTMLDivElement>(null)
  const colorMode = useResolvedTheme()
  const justCreated = useRef<number | null>(null)
  const { screenToFlowPosition, getViewport, fitView, getNodes } = useReactFlow()

  const show = useCallback((text: string, error = false) => setNote({ text, error }), [])
  const touch = useCallback(() => {
    setDirty(true)
    setCompiled((current) => (current ? { ...current, stale: true } : current))
  }, [])

  const replaceCanvas = useCallback(
    (program: { nodes: BlockNodeT[]; edges: BlockEdge[] }) => {
      setNodes(program.nodes)
      setEdges(program.edges)
      requestAnimationFrame(() => void fitView(FIT))
    },
    [fitView, setEdges, setNodes],
  )

  useEffect(() => {
    if (strategyId == null || unavailable || justCreated.current === strategyId) return
    let ignore = false
    getStrategy(strategyId)
      .then((row) => {
        if (ignore) return
        const program = fromDocument(row.document)
        setName(program.name || row.name)
        replaceCanvas(program)
        setOwned(row.owned)
        setLoaded(true)
        setDirty(false)
        setNote(row.owned ? null : { text: 'View only. Save a copy to make changes your own.', error: false })
      })
      .catch((error: unknown) => {
        if (ignore) return
        setLoaded(false)
        show(error instanceof Error ? error.message : 'Could not open this strategy.', true)
      })
    return () => {
      ignore = true
    }
  }, [strategyId, unavailable, replaceCanvas, show])

  const local = useMemo(() => analyze(nodes, edges), [nodes, edges])

  const errorIds = useMemo(() => {
    const ids = new Set(local.filter((d) => d.level === 'error' && d.nodeId).map((d) => d.nodeId!))
    if (compiled && !compiled.stale) for (const d of compiled.result.diagnostics) if (d.level === 'error' && d.node) ids.add(d.node)
    return ids
  }, [local, compiled])

  const shownNodes = useMemo(
    () => nodes.map((node) => (errorIds.has(node.id) ? { ...node, className: 'node-error' } : node.className ? { ...node, className: undefined } : node)),
    [nodes, errorIds],
  )

  const handleNodesChange = useCallback(
    (changes: NodeChange<BlockNodeT>[]) => {
      onNodesChange(changes)
      if (changes.some((c) => c.type !== 'select' && c.type !== 'dimensions')) touch()
    },
    [onNodesChange, touch],
  )

  const handleEdgesChange = useCallback(
    (changes: EdgeChange<BlockEdge>[]) => {
      onEdgesChange(changes)
      if (changes.some((c) => c.type !== 'select')) touch()
    },
    [onEdgesChange, touch],
  )

  const isValidConnection = useCallback((conn: Connection | Edge) => checkConnection(conn, edges) === null, [edges])

  const onConnect = useCallback(
    (conn: Connection) => {
      const problem = checkConnection(conn, edges)
      if (problem) return show(problem, true)
      setEdges((current) => connect(conn, current))
      touch()
    },
    [edges, setEdges, show, touch],
  )

  const addBlock = useCallback(
    (type: BlockType, position?: { x: number; y: number }) => {
      if (!loaded || BLOCK_DEFS[type].system) return
      const bounds = canvasRef.current?.getBoundingClientRect()
      const at =
        position ??
        screenToFlowPosition({
          x: bounds ? bounds.left + bounds.width / 2 : window.innerWidth / 2,
          y: bounds ? bounds.top + bounds.height / 2 : window.innerHeight / 2,
        })
      setNodes((current) => [...current.map((n) => ({ ...n, selected: false })), { ...makeNode(type, at), selected: true }])
      touch()
    },
    [loaded, screenToFlowPosition, setNodes, touch],
  )

  const onDrop = useCallback(
    (event: DragEvent) => {
      event.preventDefault()
      const type = event.dataTransfer.getData(DRAG_MIME)
      if (!isBlockType(type)) return
      const point = screenToFlowPosition({ x: event.clientX, y: event.clientY })
      addBlock(type, { x: point.x - 110, y: point.y - 20 })
    },
    [addBlock, screenToFlowPosition],
  )

  const deleteSelected = useCallback(() => {
    const doomed = new Set(nodes.filter((n) => n.selected && !isProtected(n)).map((n) => n.id))
    const selectedEdges = edges.some((e) => e.selected)
    if (doomed.size === 0 && !selectedEdges) return
    setNodes((current) => current.filter((n) => !doomed.has(n.id)))
    setEdges((current) => current.filter((e) => !e.selected && !doomed.has(e.source) && !doomed.has(e.target)))
    touch()
  }, [edges, nodes, setEdges, setNodes, touch])

  useEffect(() => {
    if (!loaded || !owned) return
    const onKeyDown = (event: KeyboardEvent) => {
      if ((event.key !== 'Delete' && event.key !== 'Backspace') || event.metaKey || event.ctrlKey || event.altKey) return
      if (isTypingTarget(event.target)) return
      event.preventDefault()
      deleteSelected()
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [deleteSelected, loaded, owned])

  const currentDocument = () => toDocument(name.trim() || 'Untitled strategy', nodes, edges, getViewport())

  async function check(doc: unknown = currentDocument()) {
    setChecking(true)
    try {
      const result = await compileStrategy(doc)
      setCompiled({ result, stale: false })
      return result
    } catch (error) {
      show(error instanceof Error ? error.message : 'Could not compile.', true)
      return null
    } finally {
      setChecking(false)
    }
  }

  /** Save (or, for someone else's strategy, save a copy). Resolves with the saved id. */
  async function persist(): Promise<number | null> {
    if (!loaded || saving) return null
    const trimmed = name.trim()
    if (!trimmed) {
      show('Name is required', true)
      return null
    }
    setSaving(true)
    try {
      const doc = toDocument(trimmed, nodes, edges, getViewport())
      const body = { name: trimmed, document: doc, ir: toIR(nodes, edges) }
      const creating = storedId == null || !owned
      const row = creating ? await createStrategy(body) : await updateStrategy(storedId, body)
      setStoredId(row.id)
      setOwned(true)
      setDirty(false)
      if (creating) {
        justCreated.current = row.id
        onCreated(row.id)
      }
      const result = await check(doc)
      const errors = result?.diagnostics.filter((d) => d.level === 'error').length ?? 0
      show(errors > 0 ? `Saved. ${errors} compiler error${errors === 1 ? '' : 's'}, see Checks.` : creating && !owned ? 'Saved your copy.' : 'Saved.', errors > 0)
      if (errors > 0) setTab('checks')
      return row.id
    } catch (error) {
      show(error instanceof Error ? error.message : 'Could not save.', true)
      return null
    } finally {
      setSaving(false)
    }
  }

  async function runCheck() {
    const result = await check()
    if (!result) return
    setTab('checks')
    show(result.ok ? 'Compiles for TradeCPU.' : 'The compiler found problems. See Checks.', !result.ok)
  }

  async function startBacktest() {
    if (!loaded || running || saving) return
    setRunning(true)
    try {
      const saved = !dirty && storedId != null ? storedId : await persist()
      if (saved != null) onOpenBacktest(await runBacktest(userId, saved))
    } catch (error) {
      show(error instanceof Error ? error.message : 'Could not run the backtest.', true)
    } finally {
      setRunning(false)
    }
  }

  async function revert(versionId: number) {
    if (storedId == null) return
    const row = await revertStrategyVersion(storedId, versionId)
    const program = fromDocument(row.document)
    setName(program.name || row.name)
    replaceCanvas(program)
    setDirty(false)
    show('Restored that version.')
    await check(row.document)
  }

  function confirmReplace(): boolean {
    return !dirty || window.confirm('Replace the canvas? Unsaved changes will be lost.')
  }

  function loadTemplate(template: Template) {
    if (!confirmReplace()) return
    replaceCanvas(template.build())
    touch()
    show(`Loaded the ${template.name} template.`)
  }

  async function importProgram() {
    try {
      const file = await pickTextFile()
      if (!file || !confirmReplace()) return
      const program = parseProgramFile(file.text)
      setName(program.name)
      replaceCanvas(program)
      touch()
      show(`Imported ${file.name}. Save to keep it.`)
    } catch (error) {
      show(error instanceof Error ? error.message : 'Could not read that file.', true)
    }
  }

  function exportProgram() {
    const fileName = programFileName(name)
    downloadText(fileName, programFileText(name.trim() || 'Untitled strategy', nodes, edges, getViewport()))
    show(`Downloaded ${fileName}.`)
  }

  function applyAssistant(graph: AssistantGraph) {
    try {
      replaceCanvas(applyAssistantGraph(graph, nodes))
      touch()
      show('Applied the assistant’s blocks.')
    } catch (error) {
      show(error instanceof Error ? error.message : 'Could not apply those blocks.', true)
    }
  }

  function focusNode(id: string) {
    setNodes((current) => current.map((n) => ({ ...n, selected: n.id === id })))
    const target = getNodes().find((n) => n.id === id)
    if (target) void fitView({ nodes: [target], duration: 250, maxZoom: 1.2 })
  }

  const editable = loaded && owned
  const busy = saving || running
  const canDelete = nodes.some((n) => n.selected && !isProtected(n)) || edges.some((e) => e.selected)
  const status = !loaded ? null : !owned ? 'View only' : storedId == null ? 'Not saved yet' : dirty ? 'Unsaved changes' : 'Saved'

  return (
    <div className="strategy-editor">
      <BlockPalette onAdd={addBlock} disabled={!editable} />
      <section className="editor-stage">
        <div className="canvas-bar">
          <div className="canvas-title">
            <button type="button" className="quiet" onClick={onClose}>
              ← Strategies
            </button>
            <input
              className="editor-name"
              value={name}
              aria-label="Strategy name"
              disabled={!loaded}
              onChange={(event) => {
                setName(event.target.value)
                touch()
              }}
            />
            {status ? <span className={`save-state${dirty || storedId == null ? ' pending' : ''}`}>{status}</span> : null}
          </div>
          <div className="canvas-actions">
            <div className="action-group">
              <TemplateMenu disabled={!editable} onPick={loadTemplate} />
              <button type="button" className="quiet icon-button" title="Import JSON program" aria-label="Import JSON program" onClick={() => void importProgram()} disabled={!editable}>
                <UploadIcon />
              </button>
              <button type="button" className="quiet icon-button" title="Download as JSON" aria-label="Download as JSON" onClick={exportProgram} disabled={!loaded}>
                <DownloadIcon />
              </button>
            </div>
            <div className="action-group">
              <button type="button" className="quiet icon-button" title="Fit blocks in view" aria-label="Fit blocks in view" onClick={() => void fitView(FIT)} disabled={!loaded}>
                <FitIcon />
              </button>
              <button type="button" className="quiet icon-button danger" title="Delete selected" aria-label="Delete selected" onClick={deleteSelected} disabled={!editable || !canDelete}>
                <TrashIcon />
              </button>
            </div>
            <div className="action-group">
              <button type="button" className="quiet" onClick={() => setHistoryOpen((open) => !open)} disabled={!editable || storedId == null || busy} aria-pressed={historyOpen}>
                History
              </button>
              <button type="button" className="primary" onClick={() => void persist()} disabled={!loaded || busy || (owned && !dirty && storedId != null)}>
                {saving ? 'Saving…' : owned ? 'Save' : 'Save a copy'}
              </button>
            </div>
          </div>
        </div>
        {note ? (
          <p className={note.error ? 'editor-note error' : 'editor-note'} role="status">
            {note.text}
            <button type="button" className="note-dismiss" aria-label="Dismiss" onClick={() => setNote(null)}>
              ×
            </button>
          </p>
        ) : null}
        {historyOpen && storedId != null ? <HistoryPanel strategyId={storedId} onRevert={revert} onClose={() => setHistoryOpen(false)} /> : null}
        <div ref={canvasRef} className="editor-canvas" onDragOver={(event) => event.preventDefault()} onDrop={onDrop}>
          {loaded ? (
            <ReactFlow
              nodes={shownNodes}
              edges={edges}
              nodeTypes={nodeTypes}
              onNodesChange={handleNodesChange}
              onEdgesChange={handleEdgesChange}
              onConnect={onConnect}
              isValidConnection={isValidConnection}
              nodesDraggable={owned}
              nodesConnectable={owned}
              fitView
              fitViewOptions={{ padding: FIT.padding }}
              minZoom={0.2}
              snapToGrid
              snapGrid={[10, 10]}
              deleteKeyCode={null}
              colorMode={colorMode}
              proOptions={{ hideAttribution: true }}
            >
              <Background variant={BackgroundVariant.Dots} gap={20} size={1} color="#e2e6ec" />
              <Controls showInteractive={false} showFitView={false} />
            </ReactFlow>
          ) : (
            <p className={note?.error ? 'form-error editor-empty' : 'editor-empty'}>{note?.error ? note.text : 'Loading strategy…'}</p>
          )}
        </div>
      </section>
      <aside className="editor-rail">
        <div className="rail-tabs" role="tablist" aria-label="Editor panels">
          {(['assistant', 'checks', 'backtest'] as const).map((item) => {
            const errors = item === 'checks' ? errorIds.size : 0
            return (
              <button key={item} type="button" role="tab" aria-selected={tab === item} onClick={() => setTab(item)}>
                {item === 'assistant' ? 'Assistant' : item === 'checks' ? 'Checks' : 'Backtest'}
                {errors > 0 ? <span className="tab-count">{errors}</span> : null}
              </button>
            )
          })}
        </div>
        <div className="rail-body" hidden={tab !== 'assistant'}>
          <AssistantPanel canvas={canvasSnapshot(nodes, edges)} canEdit={editable} onApply={applyAssistant} />
        </div>
        {tab === 'checks' ? (
          <ChecksPanel local={local} compiled={compiled} checking={checking} nodes={nodes} disabled={!loaded} onCheck={() => void runCheck()} onFocusNode={focusNode} />
        ) : null}
        {tab === 'backtest' ? (
          <BacktestPanel nodes={nodes} running={running} disabled={!loaded || busy} canRun={owned} onRun={() => void startBacktest()} />
        ) : null}
      </aside>
    </div>
  )
}

export function StrategyEditor(props: Props) {
  return (
    <ReactFlowProvider>
      <StrategyCanvas {...props} />
    </ReactFlowProvider>
  )
}
