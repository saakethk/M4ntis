import { useRef } from 'react'
import { BLOCK_DEFS, BLOCK_TYPES, CATEGORIES } from '../blocks/catalog'
import type { BlockType } from '../blocks/types'

export const DRAG_MIME = 'application/x-m4ntis-block'

const GROUPS = CATEGORIES.map((category) => ({
  ...category,
  blocks: BLOCK_TYPES.map((type) => BLOCK_DEFS[type]).filter(
    (block) => block.category === category.id && !block.system,
  ),
})).filter((group) => group.blocks.length > 0)

export function BlockPalette({ onAdd }: { onAdd: (type: BlockType) => void }) {
  const dragged = useRef(false)

  return (
    <aside className="block-palette" aria-label="Blocks">
      {GROUPS.map((group) => (
        <section key={group.id}>
          <h2>{group.label}</h2>
          <ul>
            {group.blocks.map((block) => (
              <li key={block.type}>
                <div
                  role="button"
                  tabIndex={0}
                  className={block.status === 'blocked' ? 'block-choice blocked' : 'block-choice'}
                  draggable
                  title={block.description}
                  onDragStart={(event) => {
                    dragged.current = true
                    event.dataTransfer.setData(DRAG_MIME, block.type)
                    event.dataTransfer.effectAllowed = 'move'
                  }}
                  onDragEnd={() => {
                    window.setTimeout(() => {
                      dragged.current = false
                    }, 0)
                  }}
                  onClick={() => {
                    if (dragged.current) return
                    onAdd(block.type)
                  }}
                  onKeyDown={(event) => {
                    if (event.key === 'Enter' || event.key === ' ') {
                      event.preventDefault()
                      onAdd(block.type)
                    }
                  }}
                >
                  {block.label}
                </div>
              </li>
            ))}
          </ul>
        </section>
      ))}
    </aside>
  )
}
