import { useRef, useState, type FormEvent } from 'react'
import { askAssistant } from '../api'
import { BLOCK_DEFS, BLOCK_TYPES, CATEGORIES } from '../blocks/catalog'
import type { BlockType } from '../blocks/types'

export const DRAG_MIME = 'application/x-m4ntis-block'

const GROUPS = CATEGORIES.map((category) => ({
  ...category,
  blocks: BLOCK_TYPES.map((type) => BLOCK_DEFS[type]).filter(
    (block) => block.category === category.id && !block.system,
  ),
})).filter((group) => group.blocks.length > 0)

function Assistant() {
  const [prompt, setPrompt] = useState('')
  const [reply, setReply] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [pending, setPending] = useState(false)

  async function onSubmit(event: FormEvent) {
    event.preventDefault()
    const text = prompt.trim()
    if (!text || pending) return
    setPending(true)
    setError(null)
    try {
      const body = await askAssistant(text)
      setReply(body.reply)
    } catch (caught) {
      setReply(null)
      setError(caught instanceof Error ? caught.message : 'Could not reach the server.')
    } finally {
      setPending(false)
    }
  }

  return (
    <form className="assistant" onSubmit={onSubmit}>
      <h2>AI Assistant</h2>
      <p>Ask for help with your strategy</p>
      <textarea
        value={prompt}
        placeholder="Describe a strategy..."
        rows={3}
        onChange={(event) => setPrompt(event.target.value)}
      />
      <button type="submit" disabled={pending || prompt.trim() === ''}>
        {pending ? 'Asking…' : 'Ask'}
      </button>
      {reply && <p className="assistant-reply">{reply}</p>}
      {error && <p className="assistant-error">{error}</p>}
    </form>
  )
}

export function BlockPalette({ onAdd }: { onAdd: (type: BlockType) => void }) {
  const dragged = useRef(false)

  return (
    <aside className="block-palette" aria-label="Blocks">
      <div className="palette-blocks">
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
      </div>
      <Assistant />
    </aside>
  )
}
