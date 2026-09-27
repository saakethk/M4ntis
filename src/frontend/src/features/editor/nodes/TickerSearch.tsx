import { useEffect, useId, useRef, useState } from 'react'
import { searchTickers, type TickerHit } from '../../../api/symbols.ts'

const SEARCH_DELAY_MS = 180

/** Pick a stock by ticker or company name. Enter picks the top match; Escape cancels. */
export function TickerSearch({ value, onChange }: { value: string; onChange: (symbol: string) => void }) {
  const selected = value.trim().toUpperCase()
  const [query, setQuery] = useState('')
  const [open, setOpen] = useState(false)
  const [matches, setMatches] = useState<TickerHit[]>([])
  const [searchError, setSearchError] = useState<string | null>(null)
  const listId = useId()
  const inputRef = useRef<HTMLInputElement>(null)
  const showList = open && query.trim().length > 0

  useEffect(() => {
    const q = query.trim()
    if (!q) {
      setMatches([])
      setSearchError(null)
      return
    }
    let ignore = false
    const timer = window.setTimeout(() => {
      searchTickers(q)
        .then((rows) => {
          if (ignore) return
          setMatches(rows)
          setSearchError(null)
        })
        .catch(() => {
          if (ignore) return
          setMatches([])
          setSearchError('Search unavailable')
        })
    }, SEARCH_DELAY_MS)
    return () => {
      ignore = true
      window.clearTimeout(timer)
    }
  }, [query])

  const close = () => {
    setQuery('')
    setOpen(false)
    inputRef.current?.blur()
  }
  const choose = (symbol: string) => {
    onChange(symbol)
    close()
  }

  return (
    <div className={`ticker-search nodrag nopan nowheel${open ? ' open' : ''}`}>
      <span className="ticker-chip">{selected || '—'}</span>
      <input
        ref={inputRef}
        className="nodrag nopan ticker-search-input"
        aria-label="Search ticker"
        role="combobox"
        aria-expanded={showList}
        aria-controls={listId}
        aria-autocomplete="list"
        spellCheck={false}
        autoComplete="off"
        placeholder="Search"
        value={query}
        onFocus={() => setOpen(true)}
        onBlur={() => {
          setOpen(false)
          setQuery('')
        }}
        onChange={(event) => {
          setQuery(event.target.value.toUpperCase())
          setOpen(true)
        }}
        onKeyDown={(event) => {
          if (event.key !== 'Enter' && event.key !== 'Escape') return
          event.preventDefault()
          event.stopPropagation()
          if (event.key === 'Escape') close()
          else if (matches[0]) choose(matches[0].symbol)
        }}
      />
      {showList ? (
        <ul className="ticker-matches nodrag nopan nowheel" id={listId} role="listbox">
          {searchError || matches.length === 0 ? (
            <li className="ticker-match-empty">{searchError ?? 'No matches'}</li>
          ) : (
            matches.map((hit, index) => (
              <li key={hit.symbol}>
                <button
                  type="button"
                  role="option"
                  aria-selected={hit.symbol === selected}
                  className={index === 0 ? 'nodrag nopan ticker-match top' : 'nodrag nopan ticker-match'}
                  // mousedown fires before the input's blur closes the list.
                  onMouseDown={(event) => {
                    event.preventDefault()
                    choose(hit.symbol)
                  }}
                >
                  <span>{hit.symbol}</span>
                  {hit.name && hit.name !== hit.symbol ? <span className="ticker-match-name">{hit.name}</span> : null}
                </button>
              </li>
            ))
          )}
        </ul>
      ) : null}
    </div>
  )
}
