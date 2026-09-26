import {
  Background,
  BackgroundVariant,
  Controls,
  MiniMap,
  ReactFlow,
  ReactFlowProvider,
  useEdgesState,
  useNodesState,
  useReactFlow,
  type Connection,
  type Edge,
  type NodeTypes,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import { useCallback, useEffect, useMemo, useRef, useState, type DragEvent } from 'react';
import './App.css';
import { BLOCK_DEFS, BLOCK_TYPES, isBlockType } from './blocks/catalog';
import type { BlockEdge, BlockNode as BlockNodeT, BlockType } from './blocks/types';
import { DRAG_MIME, Palette } from './components/Palette';
import { SidePanel } from './components/SidePanel';
import { BlockNode } from './flow/BlockNode';
import { analyze, checkConnection, connect, makeNode } from './flow/graph';
import { fromDocument, toDocument } from './flow/serialize';
import { TEMPLATES } from './flow/templates';

const STORAGE_KEY = 'm4ntis.strategy.draft';

const nodeTypes: NodeTypes = Object.fromEntries(BLOCK_TYPES.map((t) => [t, BlockNode]));

function loadInitial() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) return fromDocument(JSON.parse(raw));
  } catch {
    localStorage.removeItem(STORAGE_KEY);
  }
  const t = TEMPLATES.find((x) => x.id === 'sma_crossover')!;
  return { name: t.name, ...t.build() };
}

function Editor() {
  const [initial] = useState(loadInitial);
  const [name, setName] = useState(initial.name);
  const [nodes, setNodes, onNodesChange] = useNodesState<BlockNodeT>(initial.nodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState<BlockEdge>(initial.edges);
  const [notice, setNotice] = useState<string | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const { screenToFlowPosition, setCenter, fitView, getViewport } = useReactFlow();

  const diagnostics = useMemo(() => analyze(nodes, edges), [nodes, edges]);

  useEffect(() => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(toDocument(name, nodes, edges)));
  }, [name, nodes, edges]);

  useEffect(() => {
    if (!notice) return;
    const t = setTimeout(() => setNotice(null), 3500);
    return () => clearTimeout(t);
  }, [notice]);

  const isValidConnection = useCallback(
    (c: Connection | Edge) => checkConnection(c, edges) === null,
    [edges],
  );

  const onConnect = useCallback(
    (c: Connection) => {
      const problem = checkConnection(c, edges);
      if (problem) return setNotice(problem);
      setEdges((es) => connect(c, es));
    },
    [edges, setEdges],
  );

  const addBlock = useCallback(
    (type: BlockType, position?: { x: number; y: number }) => {
      const pos =
        position ??
        screenToFlowPosition({ x: window.innerWidth / 2, y: window.innerHeight / 2 });
      const node = makeNode(type, pos);
      setNodes((ns) => [...ns.map((n) => ({ ...n, selected: false })), { ...node, selected: true }]);
    },
    [screenToFlowPosition, setNodes],
  );

  const onDrop = useCallback(
    (e: DragEvent) => {
      e.preventDefault();
      const type = e.dataTransfer.getData(DRAG_MIME);
      if (!isBlockType(type) || BLOCK_DEFS[type].system) return;
      const p = screenToFlowPosition({ x: e.clientX, y: e.clientY });
      addBlock(type, { x: p.x - 110, y: p.y - 20 });
    },
    [addBlock, screenToFlowPosition],
  );

  const focusNode = useCallback(
    (id: string) => {
      const n = nodes.find((x) => x.id === id);
      if (!n) return;
      setNodes((ns) => ns.map((x) => ({ ...x, selected: x.id === id })));
      const w = n.measured?.width ?? 220;
      const h = n.measured?.height ?? 120;
      setCenter(n.position.x + w / 2, n.position.y + h / 2, { zoom: 1.1, duration: 400 });
    },
    [nodes, setNodes, setCenter],
  );

  const replaceGraph = (next: { name: string; nodes: BlockNodeT[]; edges: BlockEdge[] }) => {
    setName(next.name);
    setNodes(next.nodes);
    setEdges(next.edges);
    requestAnimationFrame(() => fitView({ padding: 0.2, duration: 300 }));
  };

  const loadTemplate = (id: string) => {
    const t = TEMPLATES.find((x) => x.id === id);
    if (!t) return;
    if (nodes.length > 1 && !confirm(`Replace the current graph with "${t.name}"?`)) return;
    replaceGraph({ name: t.name, ...t.build() });
  };

  const importFile = async (file: File) => {
    try {
      replaceGraph(fromDocument(JSON.parse(await file.text())));
      setNotice(`Imported ${file.name}`);
    } catch (err) {
      setNotice(`Import failed: ${(err as Error).message}`);
    }
  };

  const exportFile = () => {
    const doc = toDocument(name, nodes, edges, getViewport());
    const url = URL.createObjectURL(
      new Blob([JSON.stringify(doc, null, 2)], { type: 'application/json' }),
    );
    const slug = name.trim().toLowerCase().replace(/[^a-z0-9]+/g, '_') || 'strategy';
    Object.assign(document.createElement('a'), { href: url, download: `${slug}.strategy.json` }).click();
    URL.revokeObjectURL(url);
  };

  const errorCount = diagnostics.filter((d) => d.level === 'error').length;

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <span className="brand-mark">◆</span> M4ntis <span className="brand-sub">Strategy Sandbox</span>
        </div>
        <input
          className="strategy-name"
          value={name}
          onChange={(e) => setName(e.target.value)}
          aria-label="Strategy name"
        />
        <div className="topbar-actions">
          <select value="" onChange={(e) => loadTemplate(e.target.value)} aria-label="Load template">
            <option value="" disabled>
              Load template…
            </option>
            {TEMPLATES.map((t) => (
              <option key={t.id} value={t.id} title={t.description}>
                {t.name}
              </option>
            ))}
          </select>
          <button type="button" onClick={() => fileInput.current?.click()}>
            Import
          </button>
          <button type="button" onClick={exportFile}>
            Export JSON
          </button>
          <span className={`status-pill ${errorCount ? 'bad' : 'good'}`}>
            {errorCount ? `${errorCount} error${errorCount > 1 ? 's' : ''}` : 'Compilable'}
          </span>
          <input
            ref={fileInput}
            type="file"
            accept="application/json,.json"
            hidden
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (f) importFile(f);
              e.target.value = '';
            }}
          />
        </div>
      </header>

      <div className="workspace">
        <Palette onAdd={addBlock} />
        <main className="canvas" onDragOver={(e) => e.preventDefault()} onDrop={onDrop}>
          <ReactFlow
            nodes={nodes}
            edges={edges}
            nodeTypes={nodeTypes}
            onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange}
            onConnect={onConnect}
            isValidConnection={isValidConnection}
            fitView
            fitViewOptions={{ padding: 0.2 }}
            minZoom={0.2}
            snapToGrid
            snapGrid={[10, 10]}
            deleteKeyCode={['Backspace', 'Delete']}
            colorMode="dark"
            proOptions={{ hideAttribution: true }}
          >
            <Background variant={BackgroundVariant.Dots} gap={20} size={1} />
            <Controls />
            <MiniMap pannable zoomable className="minimap" />
          </ReactFlow>
          {notice && <div className="notice">{notice}</div>}
        </main>
        <SidePanel
          name={name}
          nodes={nodes}
          edges={edges}
          diagnostics={diagnostics}
          onFocusNode={focusNode}
        />
      </div>
    </div>
  );
}

export default function App() {
  return (
    <ReactFlowProvider>
      <Editor />
    </ReactFlowProvider>
  );
}
