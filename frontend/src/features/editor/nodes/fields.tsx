import { useState } from 'react'
import type { NumberParamDef, ParamValue, SelectParamDef } from '../../../blocks/types.ts'

/** A number input that commits on blur or Enter, clamped and rounded to the param's rules. */
export function NumberField({
  def,
  value,
  onChange,
  className = 'nodrag param-input',
}: {
  def: NumberParamDef
  value: number
  onChange: (value: number) => void
  className?: string
}) {
  const [draft, setDraft] = useState<string | null>(null)

  const commit = (raw: string) => {
    setDraft(null)
    let next = Number(raw)
    if (raw.trim() === '' || Number.isNaN(next)) return
    if (def.integer) next = Math.round(next)
    if (def.min !== undefined) next = Math.max(def.min, next)
    if (def.max !== undefined) next = Math.min(def.max, next)
    if (next !== value) onChange(next)
  }

  return (
    <input
      className={className}
      type="number"
      aria-label={def.label}
      value={draft ?? String(value)}
      step={def.step ?? (def.integer ? 1 : 'any')}
      min={def.min}
      max={def.max}
      onChange={(event) => setDraft(event.target.value)}
      onBlur={(event) => commit(event.target.value)}
      onKeyDown={(event) => event.key === 'Enter' && event.currentTarget.blur()}
    />
  )
}

export function SelectField({
  def,
  value,
  onChange,
  className = 'nodrag param-input',
}: {
  def: SelectParamDef
  value: ParamValue
  onChange: (value: ParamValue) => void
  className?: string
}) {
  return (
    <select
      className={className}
      aria-label={def.label}
      value={String(value)}
      onChange={(event) => {
        const option = def.options.find((o) => String(o.value) === event.target.value)
        if (option) onChange(option.value)
      }}
    >
      {def.options.map((option) => (
        <option key={String(option.value)} value={String(option.value)}>
          {option.label}
        </option>
      ))}
    </select>
  )
}
