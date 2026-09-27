import { useEffect, useState, type FormEvent } from 'react'
import {
  createDiscussion,
  likeDiscussion,
  listDiscussions,
  listStrategies,
  type DiscussionPost,
  type StrategySummary,
  type User,
} from '../api'
import { displayName } from '../strategies'

type Props = {
  user: User
  onOpenStrategy: (id: string) => void
}

export function Discussions({ user, onOpenStrategy }: Props) {
  const [posts, setPosts] = useState<DiscussionPost[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [strategies, setStrategies] = useState<StrategySummary[]>([])

  async function reload() {
    const next = await listDiscussions()
    setPosts(next)
  }

  useEffect(() => {
    let ignore = false
    listDiscussions()
      .then((next) => {
        if (!ignore) {
          setPosts(next)
          setError(null)
        }
      })
      .catch((caught: unknown) => {
        if (!ignore) setError(caught instanceof Error ? caught.message : 'Could not load discussions.')
      })
      .finally(() => {
        if (!ignore) setLoading(false)
      })
    return () => {
      ignore = true
    }
  }, [])

  useEffect(() => {
    let ignore = false
    listStrategies()
      .then((rows) => {
        if (!ignore) setStrategies(rows)
      })
      .catch(() => {
        if (!ignore) setStrategies([])
      })
    return () => {
      ignore = true
    }
  }, [])

  async function publish(body: string, strategyId?: number, parentId?: number) {
    const created = await createDiscussion({ body, strategyId, parentId })
    await reload()
    if (created.strategyMadePublic) {
      setNotice('That strategy is now public. Others can view it, and only you can edit it.')
    } else {
      setNotice(null)
    }
  }

  async function toggleLike(post: DiscussionPost) {
    const next = await likeDiscussion(post.id)
    setPosts((current) =>
      current.map((item) =>
        item.id === post.id ? { ...item, likesCount: next.likesCount, liked: next.liked } : item,
      ),
    )
  }

  const children = new Map<number | null, DiscussionPost[]>()
  for (const post of posts) {
    const key = post.parentId
    const list = children.get(key) ?? []
    list.push(post)
    children.set(key, list)
  }
  const timeline = sortPosts(children.get(null) ?? [], 'newest')

  return (
    <section className="discussions">
      <header className="feed-head">
        <h1>Discussions</h1>
        <p>Posts from everyone</p>
      </header>
      {error ? <p className="form-error feed-banner">{error}</p> : null}
      {notice ? <p className="discussion-notice feed-banner">{notice}</p> : null}
      <Composer
        user={user}
        strategies={strategies}
        onSubmit={async (body, strategyId) => {
          await publish(body, strategyId)
        }}
      />
      {loading ? <p className="status-line feed-banner">Loading discussions…</p> : null}
      {!loading && timeline.length === 0 ? (
        <p className="feed-empty">No posts yet. Share a strategy to start the timeline.</p>
      ) : null}
      <div className="feed">
        {timeline.map((post) => (
          <PostCard
            key={post.id}
            post={post}
            childrenOf={children}
            onReply={publish}
            onLike={toggleLike}
            onOpenStrategy={onOpenStrategy}
          />
        ))}
      </div>
    </section>
  )
}

function Composer({
  user,
  onSubmit,
  parent,
  strategies = [],
}: {
  user?: User
  onSubmit: (body: string, strategyId?: number) => Promise<void>
  parent?: boolean
  strategies?: StrategySummary[]
}) {
  const [body, setBody] = useState('')
  const [strategy, setStrategy] = useState('')
  const [pending, setPending] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const chosen = strategies.find((item) => String(item.id) === strategy) ?? null

  async function submit(event: FormEvent) {
    event.preventDefault()
    const text = body.trim() || (chosen ? `Sharing ${chosen.name}.` : '')
    if (!text || pending) return
    const strategyId = chosen?.id
    setPending(true)
    setError(null)
    try {
      await onSubmit(text, strategyId)
      setBody('')
      setStrategy('')
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not post.')
    } finally {
      setPending(false)
    }
  }

  const canPost = body.trim() !== '' || chosen != null

  return (
    <form className={parent ? 'tweet-reply' : 'tweet-composer'} onSubmit={submit}>
      {user ? <Avatar email={user.email} /> : null}
      <div className="tweet-compose-main">
        <textarea
          value={body}
          rows={parent ? 2 : 3}
          placeholder={parent ? 'Post your reply' : "What's happening?"}
          onChange={(event) => setBody(event.target.value)}
        />
        {chosen ? (
          <div className="tweet-draft-strategy">
            <div>
              <span>Strategy</span>
              <strong>{chosen.name}</strong>
              {chosen.visibility === 'private' ? <em>Private until you post</em> : null}
            </div>
            <button type="button" className="tweet-remove" onClick={() => setStrategy('')} aria-label="Remove strategy">
              ×
            </button>
          </div>
        ) : null}
        {chosen?.visibility === 'private' ? (
          <p className="tweet-hint">Sharing a private strategy makes it public. Others can view it. Only you can edit it.</p>
        ) : null}
        {error ? <p className="form-error">{error}</p> : null}
        <div className="tweet-compose-bar">
          {parent ? <span /> : (
            <label className="tweet-attach">
              Share a strategy
              <select value={strategy} onChange={(event) => setStrategy(event.target.value)} disabled={strategies.length === 0}>
                <option value="">{strategies.length === 0 ? 'No saved strategies' : 'None'}</option>
                {strategies.map((item) => (
                  <option key={item.id} value={String(item.id)}>
                    {item.name}
                    {item.visibility === 'private' ? ' · Private' : ' · Public'}
                  </option>
                ))}
              </select>
            </label>
          )}
          <button type="submit" className="tweet-post" disabled={pending || !canPost}>
            {pending ? 'Posting…' : parent ? 'Reply' : 'Post'}
          </button>
        </div>
      </div>
    </form>
  )
}

function PostCard({
  post,
  childrenOf,
  onReply,
  onLike,
  onOpenStrategy,
  depth = 0,
}: {
  post: DiscussionPost
  childrenOf: Map<number | null, DiscussionPost[]>
  onReply: (body: string, strategyId?: number, parentId?: number) => Promise<void>
  onLike: (post: DiscussionPost) => Promise<void>
  onOpenStrategy: (id: string) => void
  depth?: number
}) {
  const [replying, setReplying] = useState(false)
  const replies = sortPosts(childrenOf.get(post.id) ?? [], 'oldest')
  const name = displayName(post.author)
  return (
    <article className={depth === 0 ? 'tweet' : 'tweet tweet-nested'}>
      <Avatar email={post.author} />
      <div className="tweet-main">
        <header className="tweet-head">
          <strong>{name}</strong>
          <span>{handleOf(post.author)}</span>
          {post.createdAt ? (
            <>
              <span aria-hidden="true">·</span>
              <time dateTime={post.createdAt}>{relativeTime(post.createdAt)}</time>
            </>
          ) : null}
        </header>
        <p className="tweet-text">{post.body}</p>
        {post.strategyId != null ? (
          <button type="button" className="tweet-strategy" onClick={() => onOpenStrategy(String(post.strategyId))}>
            <span>Shared strategy</span>
            <strong>{post.strategyName ?? `Strategy ${post.strategyId}`}</strong>
          </button>
        ) : null}
        <div className="tweet-actions">
          <button
            type="button"
            className="tweet-action"
            aria-expanded={replying}
            onClick={() => setReplying((open) => !open)}
          >
            <ReplyIcon />
            <span>{replies.length > 0 ? replies.length : 'Reply'}</span>
          </button>
          <button
            type="button"
            className={post.liked ? 'tweet-action liked' : 'tweet-action'}
            aria-pressed={post.liked}
            onClick={() => void onLike(post)}
          >
            <HeartIcon filled={post.liked} />
            <span>{post.likesCount}</span>
          </button>
        </div>
        {replying ? (
          <Composer
            parent
            onSubmit={async (body) => {
              await onReply(body, undefined, post.id)
              setReplying(false)
            }}
          />
        ) : null}
        {replies.length > 0 ? (
          <div className="tweet-replies">
            {replies.map((reply) => (
              <PostCard
                key={reply.id}
                post={reply}
                childrenOf={childrenOf}
                onReply={onReply}
                onLike={onLike}
                onOpenStrategy={onOpenStrategy}
                depth={depth + 1}
              />
            ))}
          </div>
        ) : null}
      </div>
    </article>
  )
}

function Avatar({ email }: { email: string }) {
  const name = displayName(email)
  const initials = name
    .split(' ')
    .slice(0, 2)
    .map((part) => part.charAt(0).toUpperCase())
    .join('')
  return (
    <span className="tweet-avatar" aria-hidden="true">
      {initials || 'M'}
    </span>
  )
}

function ReplyIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path
        d="M7 8.5h7.2A3.8 3.8 0 0 1 18 12.3v.2M7 8.5 10.2 5.4M7 8.5l3.2 3.2"
        stroke="currentColor"
        strokeWidth="1.7"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <path
        d="M6 18.5h8.2c2.4 0 4.3-1.8 4.3-4.1V12"
        stroke="currentColor"
        strokeWidth="1.7"
        strokeLinecap="round"
      />
    </svg>
  )
}

function HeartIcon({ filled }: { filled: boolean }) {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" aria-hidden="true">
      <path
        d="M12 19.4s-6.4-3.9-8.4-7.3C2.2 10 3 7 5.6 6.2 7.4 5.6 9 6.3 12 9c3-2.7 4.6-3.4 6.4-2.8 2.6.8 3.4 3.8 2 6-2 3.3-8.4 7.2-8.4 7.2Z"
        fill={filled ? 'currentColor' : 'none'}
        stroke="currentColor"
        strokeWidth="1.7"
        strokeLinejoin="round"
      />
    </svg>
  )
}

function handleOf(email: string): string {
  const local = email.split('@')[0]?.trim()
  return `@${local || 'user'}`
}

function relativeTime(iso: string): string {
  const then = Date.parse(iso)
  if (Number.isNaN(then)) return ''
  const seconds = Math.max(0, Math.round((Date.now() - then) / 1000))
  if (seconds < 60) return 'now'
  const minutes = Math.round(seconds / 60)
  if (minutes < 60) return `${minutes}m`
  const hours = Math.round(minutes / 60)
  if (hours < 24) return `${hours}h`
  const days = Math.round(hours / 24)
  if (days < 7) return `${days}d`
  return new Date(then).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
}

function sortPosts(posts: DiscussionPost[], direction: 'newest' | 'oldest'): DiscussionPost[] {
  return [...posts].sort((a, b) => {
    const delta = a.createdAt.localeCompare(b.createdAt) || a.id - b.id
    return direction === 'oldest' ? delta : -delta
  })
}
