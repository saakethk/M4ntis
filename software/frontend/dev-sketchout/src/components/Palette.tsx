import { useMemo, useState } from 'react';
import { BLOCK_DEFS, BLOCK_TYPES, CATEGORIES } from '../blocks/catalog';
import type { BlockType } from '../blocks/types';

export const DRAG_MIME = 'application/x-m4ntis-block';

export function Palette({ onAdd }: { onAdd: (type: BlockType) => void }) {
  const [query, setQuery] = useState('');

  const groups = useMemo(() => {
    const q = query.trim().toLowerCase();
    return CATEGORIES.map((c) => ({
      ...c,
      blocks: BLOCK_TYPES.map((t) => BLOCK_DEFS[t]).filter(
        (d) =>
          d.category === c.id &&
          !d.system &&
          (!q || d.label.toLowerCase().includes(q) || d.compilesTo.toLowerCase().includes(q)),
      ),
    })).filter((g) => g.blocks.length > 0);
  }, [query]);

  return (
    <aside className="palette">
      <input
        className="palette-search"
        placeholder="Search blocks or opcodes…"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
      />
      {groups.map((g) => (
        <section key={g.id} className="palette-group">
          <h3 className={`palette-heading cat-${g.id}`}>{g.label}</h3>
          {g.blocks.map((d) => (
            <div
              key={d.type}
              className={`palette-item cat-${d.category} ${d.status === 'blocked' ? 'blocked' : ''}`}
              draggable
              onDragStart={(e) => {
                e.dataTransfer.setData(DRAG_MIME, d.type);
                e.dataTransfer.effectAllowed = 'move';
              }}
              onDoubleClick={() => onAdd(d.type)}
              title={`${d.description}\n\nCompiles to: ${d.compilesTo}${d.statusNote ? `\n\n${d.statusNote}` : ''}\n\nDrag onto the canvas or double-click to add.`}
            >
              <span className="palette-swatch" />
              <span className="palette-label">{d.label}</span>
              {d.status === 'blocked' && <span className="badge badge-blocked">HW</span>}
            </div>
          ))}
        </section>
      ))}
      <div className="palette-legend">
        <div>
          <span className="legend-exec" /> Exec: order of execution
        </div>
        <div>
          <span className="legend-data" /> Data: a register value
        </div>
      </div>
    </aside>
  );
}
