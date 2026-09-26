import { useMemo, useState } from 'react';
import { BLOCK_DEFS } from '../blocks/catalog';
import type { BlockEdge, BlockNode, BlockType } from '../blocks/types';
import type { Diagnostic } from '../flow/graph';
import { toDocument, toIR } from '../flow/serialize';

type Tab = 'diagnostics' | 'document' | 'ir' | 'block' | 'catalog';

const TABS: { id: Tab; label: string }[] = [
  { id: 'diagnostics', label: 'Checks' },
  { id: 'document', label: 'Flow JSON' },
  { id: 'ir', label: 'Compiler IR' },
  { id: 'block', label: 'Selected' },
  { id: 'catalog', label: 'Catalog' },
];

function JsonView({ value, filename }: { value: unknown; filename: string }) {
  const text = useMemo(() => JSON.stringify(value, null, 2), [value]);
  const [copied, setCopied] = useState(false);
  return (
    <div className="json-view">
      <div className="json-actions">
        <button
          type="button"
          onClick={async () => {
            await navigator.clipboard.writeText(text);
            setCopied(true);
            setTimeout(() => setCopied(false), 1200);
          }}
        >
          {copied ? 'Copied' : 'Copy'}
        </button>
        <button
          type="button"
          onClick={() => {
            const url = URL.createObjectURL(new Blob([text], { type: 'application/json' }));
            const a = Object.assign(document.createElement('a'), { href: url, download: filename });
            a.click();
            URL.revokeObjectURL(url);
          }}
        >
          Download
        </button>
      </div>
      <pre>{text}</pre>
    </div>
  );
}

export function SidePanel({
  name,
  nodes,
  edges,
  diagnostics,
  onFocusNode,
}: {
  name: string;
  nodes: BlockNode[];
  edges: BlockEdge[];
  diagnostics: Diagnostic[];
  onFocusNode: (id: string) => void;
}) {
  const [tab, setTab] = useState<Tab>('diagnostics');
  const selected = nodes.filter((n) => n.selected);
  const errors = diagnostics.filter((d) => d.level === 'error').length;
  const slug = name.trim().toLowerCase().replace(/[^a-z0-9]+/g, '_') || 'strategy';

  const content = () => {
    switch (tab) {
      case 'diagnostics':
        return diagnostics.length === 0 ? (
          <p className="empty">No issues. Strategy is ready to compile.</p>
        ) : (
          <ul className="diagnostics">
            {diagnostics.map((d, i) => (
              <li
                key={i}
                className={`diag diag-${d.level} ${d.nodeId ? 'clickable' : ''}`}
                onClick={() => d.nodeId && onFocusNode(d.nodeId)}
              >
                <span className="diag-level">{d.level}</span>
                {d.message}
              </li>
            ))}
          </ul>
        );
      case 'document':
        return <JsonView value={toDocument(name, nodes, edges)} filename={`${slug}.strategy.json`} />;
      case 'ir':
        return <JsonView value={toIR(nodes, edges)} filename={`${slug}.ir.json`} />;
      case 'block': {
        if (selected.length === 0) return <p className="empty">Select a block on the canvas.</p>;
        const ids = new Set(selected.map((n) => n.id));
        const doc = toDocument(name, selected, edges.filter((e) => ids.has(e.source) || ids.has(e.target)));
        return (
          <JsonView
            value={{
              nodes: doc.flow.nodes,
              connectedEdges: doc.flow.edges,
              definitions: [...new Set(selected.map((n) => n.type as BlockType))].map((t) => BLOCK_DEFS[t]),
            }}
            filename="selection.json"
          />
        );
      }
      case 'catalog':
        return <JsonView value={BLOCK_DEFS} filename="block_catalog.json" />;
    }
  };

  return (
    <aside className="side-panel">
      <nav className="tabs">
        {TABS.map((t) => (
          <button
            type="button"
            key={t.id}
            className={`tab ${tab === t.id ? 'active' : ''}`}
            onClick={() => setTab(t.id)}
          >
            {t.label}
            {t.id === 'diagnostics' && errors > 0 && <span className="tab-count">{errors}</span>}
          </button>
        ))}
      </nav>
      <div className="tab-body">{content()}</div>
    </aside>
  );
}
