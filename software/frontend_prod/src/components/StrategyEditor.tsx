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
import { createStrategy, getStrategy, updateStrategy } from '../api'
import { BLOCK_DEFS, BLOCK_TYPES, isBlockType } from '../blocks/catalog'
import type { BlockEdge, BlockNode as BlockNodeT, BlockType } from '../blocks/types'
import { BlockNode } from '../flow/BlockNode'
import { START_NODE_ID, analyze, checkConnection, connect, makeNode } from '../flow/graph'
import { fromDocument, toDocument, toIR } from '../flow/serialize'
import { TEMPLATES } from '../flow/templates'
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
  strategyId: number | null
  unavailable?: boolean
  onClose: () => void
}

function documentPayload(raw: unknown): unknown {
  if (typeof raw !== 'string') return raw
  return JSON.parse(raw)
}

function StrategyCanvas({ strategyId, unavailable = false, onClose }: Props) {
  const blank = blankTemplate?.build() ?? { nodes: [], edges: [] }
  const [name, setName] = useState(strategyId == null && !unavailable ? 'Untitled strategy' : '')
  const [nodes, setNodes, onNodesChange] = useNodesState<BlockNodeT>(blank.nodes)
  const [edges, setEdges, onEdgesChange] = useEdgesState<BlockEdge>(blank.edges)
  const [storedId, setStoredId] = useState<number | null>(strategyId)
  const [loading, setLoading] = useState(strategyId != null && !unavailable)
  const [loaded, setLoaded] = useState(strategyId == null && !unavailable)
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [message, setMessage] = useState<string | null>(unavailable ? 'Could not open this strategy.' : null)
  const [messageError, setMessageError] = useState(unavailable)
  const canvasRef = useRef<HTMLDivElement>(null)
  const { screenToFlowPosition, getViewport } = useReactFlow()

  useEffect(() => {
    if (strategyId == null || unavailable) return
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
    const errors = analyze(nodes, edges).filter((item) => item.level === 'error')
    if (errors.length === 0) {
      showMessage('Compiled', false)
      return
    }
    const summary = errors.length === 1 ? errors[0].message : `${errors.length} errors. ${errors[0].message}`
    showMessage(summary, true)
  }

  async function save() {
    if (!loaded || saving) return
    const trimmed = name.trim()
    if (!trimmed) {
      setSaved(false)
      showMessage('Name is required', true)
      return
    }
    setSaving(true)
    try {
      const document = toDocument(trimmed, nodes, edges, getViewport())
      const ir = toIR(nodes, edges)
      const body = { name: trimmed, document, ir, visibility: 'private' as const }
      const savedRow = storedId == null ? await createStrategy(body) : await updateStrategy(storedId, body)
      setStoredId(savedRow.id)
      setSaved(true)
      setMessage(null)
      setMessageError(false)
    } catch (error) {
      setSaved(false)
      showMessage(error instanceof Error ? error.message : 'Could not save', true)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="strategy-editor">
      <BlockPalette onAdd={addBlock} />
      <section className="editor-stage">
        <div className="canvas-bar">
          <div className="canvas-title">
            <button type="button" className="quiet" onClick={onClose}>
              Strategies
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
            <button type="button" className="quiet" onClick={() => void save()} disabled={!loaded || saving}>
              {saving ? 'Saving…' : saved ? 'Saved' : 'Save'}
            </button>
            <button
              type="button"
              className="quiet"
              onClick={() => showMessage('Run is not available yet.', false)}
              disabled={!loaded}
            >
              Run
            </button>
          </div>
        </div>
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
