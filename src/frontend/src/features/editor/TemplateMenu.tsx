import { useCallback, useRef, useState } from 'react'
import { useDismiss } from '../../components/useDismiss.ts'
import { TEMPLATES, type Template } from '../../flow/templates.ts'

/** A dropdown of starter strategies. Choosing one replaces the canvas. */
export function TemplateMenu({ disabled, onPick }: { disabled: boolean; onPick: (template: Template) => void }) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  const close = useCallback(() => setOpen(false), [])
  useDismiss(ref, open, close)

  return (
    <div className="menu-anchor" ref={ref}>
      <button type="button" className="quiet" aria-haspopup="menu" aria-expanded={open} disabled={disabled} onClick={() => setOpen((v) => !v)}>
        Templates
      </button>
      {open ? (
        <ul className="dropdown" role="menu">
          {TEMPLATES.map((template) => (
            <li key={template.id}>
              <button
                type="button"
                role="menuitem"
                onClick={() => {
                  setOpen(false)
                  onPick(template)
                }}
              >
                <strong>{template.name}</strong>
                <span>{template.description}</span>
              </button>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  )
}
