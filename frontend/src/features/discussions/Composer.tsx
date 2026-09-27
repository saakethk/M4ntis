import { useState, type FormEvent } from 'react'
import type { StrategySummary } from '../../api/strategies.ts'
import { initials } from '../../lib/format.ts'

type Props = {
  onSubmit: (body: string, strategyId?: number) => Promise<void>
  /** Present for a new post; omitted for a reply (replies cannot attach strategies). */
  strategies?: StrategySummary[]
  authorEmail?: string
}

export function Composer({ onSubmit, strategies, authorEmail }: Props) {
  const isReply = strategies === undefined
  const [body, setBody] = useState('')
  const [strategyId, setStrategyId] = useState('')
  const [pending, setPending] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const chosen = strategies?.find((item) => String(item.id) === strategyId) ?? null
  const canPost = body.trim() !== '' || chosen != null

  async function submit(event: FormEvent) {
    event.preventDefault()
    const text = body.trim() || (chosen ? `Sharing ${chosen.name}.` : '')
    if (!text || pending) return
    setPending(true)
    setError(null)
    try {
      await onSubmit(text, chosen?.id)
      setBody('')
      setStrategyId('')
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not post.')
    } finally {
      setPending(false)
    }
  }

  return (
    <form className={isReply ? 'tweet-reply' : 'tweet-composer'} onSubmit={submit}>
      {authorEmail ? (
        <span className="tweet-avatar" aria-hidden="true">
          {initials(authorEmail)}
        </span>
      ) : null}
      <div className="tweet-compose-main">
        <textarea
          value={body}
          rows={isReply ? 2 : 3}
          maxLength={4000}
          aria-label={isReply ? 'Reply' : 'New post'}
          placeholder={isReply ? 'Post your reply' : 'Share an idea or a strategy…'}
          onChange={(event) => setBody(event.target.value)}
        />
        {chosen?.visibility === 'private' ? (
          <p className="tweet-hint">Posting makes “{chosen.name}” public. Others can view and copy it; only you can edit it.</p>
        ) : null}
        {error ? <p className="form-error">{error}</p> : null}
        <div className="tweet-compose-bar">
          {strategies ? (
            <label className="tweet-attach">
              Attach a strategy
              <select value={strategyId} onChange={(event) => setStrategyId(event.target.value)} disabled={strategies.length === 0}>
                <option value="">{strategies.length === 0 ? 'No saved strategies' : 'None'}</option>
                {strategies.map((item) => (
                  <option key={item.id} value={String(item.id)}>
                    {item.name} · {item.visibility === 'private' ? 'Private' : 'Public'}
                  </option>
                ))}
              </select>
            </label>
          ) : (
            <span />
          )}
          <button type="submit" className="tweet-post" disabled={pending || !canPost}>
            {pending ? 'Posting…' : isReply ? 'Reply' : 'Post'}
          </button>
        </div>
      </div>
    </form>
  )
}
