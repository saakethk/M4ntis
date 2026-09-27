import { useRef, useState } from 'react'
import { CATEGORIES, PALETTE_BLOCKS } from '../../blocks/catalog.ts'
import type { BlockType } from '../../blocks/types.ts'
import { SearchIcon } from '../../components/icons.tsx'

export const DRAG_MIME = 'application/x-m4ntis-block'

/** Blocks grouped by category. Click (or Enter) adds at the canvas center; drag drops at the cursor. */
export function BlockPalette({ onAdd, disabled }: { onAdd: (type: BlockType) => void; disabled: boolean }) {
  const [query, setQuery] = useState('')
  const dragged = useRef(false)
  const needle = query.trim().toLowerCase()
  const groups = CATEGORIES.map((category) => ({
    ...category,
    blocks: PALETTE_BLOCKS.filter(
      (block) =>
        block.category === category.id &&
        (!needle || block.label.toLowerCase().includes(needle) || block.description.toLowerCase().includes(needle)),
    ),
  })).filter((group) => group.blocks.length > 0)

  return (
    <aside className="block-palette" aria-label="Blocks">
      <label className="palette-search">
        <SearchIcon size={14} />
        <input type="search" placeholder="Find a block" aria-label="Find a block" value={query} onChange={(e) => setQuery(e.target.value)} />
      </label>
      <div className="palette-blocks">
        {groups.length === 0 ? <p className="palette-empty">No blocks match.</p> : null}
        {groups.map((group) => (
          <section key={group.id}>
            <h2>{group.label}</h2>
            <ul>
              {group.blocks.map((block) => (
                <li key={block.type}>
                  <button
                    type="button"
                    className="block-choice"
                    draggable={!disabled}
                    disabled={disabled}
                    title={block.description}
                    onDragStart={(event) => {
                      dragged.current = true
                      event.dataTransfer.setData(DRAG_MIME, block.type)
                      event.dataTransfer.effectAllowed = 'move'
                    }}
                    onDragEnd={() => window.setTimeout(() => (dragged.current = false), 0)}
                    onClick={() => !dragged.current && onAdd(block.type)}
                  >
                    <span className="block-choice-label">{block.label}</span>
                    <span className="block-choice-desc">{block.description}</span>
                  </button>
                </li>
              ))}
            </ul>
          </section>
        ))}
      </div>
    </aside>
  )
}
