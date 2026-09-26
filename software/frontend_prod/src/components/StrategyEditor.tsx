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
import { analyze, checkConnection, connect, makeNode } from '../flow/graph'
import { fromDocument, toDocument, toIR } from '../flow/serialize'
import { TEMPLATES } from '../flow/templates'
import { BlockPalette, DRAG_MIME } from './BlockPalette'

const nodeTypes: NodeTypes = Object.fromEntries(BLOCK_TYPES.map((type) => [type, BlockNode]))

const blankTemplate = TEMPLATES.find((template) => template.id === 'blank')

type Props = {
  strategyId: number | null
  unavailable?: boolean
  onClose: () => void
  onCreated?: (id: number) => void
}

function documentPayload(raw: unknown): unknown {
  if (typeof raw !== 'string') return raw
  return JSON.parse(raw)
}

function StrategyCanvas({ strategyId, unavailable = false, onClose, onCreated }: Props) {
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
  const skipFetchId = useRef<number | null>(null)
  const { screenToFlowPosition, getViewport } = useReactFlow()

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
      const existingId = storedId
      const savedRow = existingId == null ? await createStrategy(body) : await updateStrategy(existingId, body)
      setStoredId(savedRow.id)
      setSaved(true)
      setMessage(null)
      setMessageError(false)
      if (existingId == null) {
        skipFetchId.current = savedRow.id
        onCreated?.(savedRow.id)
      }
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
              deleteKeyCode={['Backspace', 'Delete']}
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
