import { useEffect, useState, type FormEvent } from 'react'
import {
  createDiscussion,
  likeDiscussion,
  listDiscussions,
  listStrategies,
  type DiscussionPost,
  type StrategySummary,
} from '../api'
import { displayName } from '../strategies'

type Props = {
  onOpenStrategy: (id: string) => void
}

export function Discussions({ onOpenStrategy }: Props) {
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

  return (
    <section className="discussions">
      <header className="page-head">
        <h1>Discussions</h1>
        <p className="subtitle">Post a strategy, reply, and like.</p>
      </header>
      {error ? <p className="form-error">{error}</p> : null}
      {notice ? <p className="discussion-notice">{notice}</p> : null}
      <Composer
        strategies={strategies}
        onSubmit={async (body, strategyId) => {
          await publish(body, strategyId)
        }}
      />
      {loading ? <p className="status-line">Loading discussions…</p> : null}
      {!loading && (children.get(null)?.length ?? 0) === 0 ? (
        <p className="status-line">No posts yet.</p>
      ) : null}
      <div className="discussion-list">
        {(children.get(null) ?? []).map((post) => (
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
  onSubmit,
  parent,
  strategies = [],
}: {
  onSubmit: (body: string, strategyId?: number) => Promise<void>
  parent?: boolean
  strategies?: StrategySummary[]
}) {
  const [body, setBody] = useState('')
  const [strategy, setStrategy] = useState('')
  const [pending, setPending] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function submit(event: FormEvent) {
    event.preventDefault()
    const text = body.trim()
    if (!text || pending) return
    const strategyId = strategy.trim() === '' ? undefined : Number(strategy)
    if (strategyId != null && !Number.isInteger(strategyId)) {
      setError('Strategy id must be a number.')
      return
    }
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

  return (
    <form className={parent ? 'discussion-reply' : 'discussion-composer'} onSubmit={submit}>
      <textarea
        value={body}
        rows={parent ? 2 : 4}
        placeholder={parent ? 'Write a reply…' : 'Start a discussion…'}
        onChange={(event) => setBody(event.target.value)}
      />
      {parent ? null : (
        <label>
          Strategy
          <select value={strategy} onChange={(event) => setStrategy(event.target.value)}>
            <option value="">None</option>
            {strategies.map((item) => (
              <option key={item.id} value={String(item.id)}>
                {item.name}
              </option>
            ))}
          </select>
        </label>
      )}
      {error ? <p className="form-error">{error}</p> : null}
      <button type="submit" className="primary" disabled={pending || body.trim() === ''}>
        {pending ? 'Posting…' : parent ? 'Reply' : 'Post'}
      </button>
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
  const replies = childrenOf.get(post.id) ?? []
  return (
    <article className="discussion-post" style={{ marginLeft: depth === 0 ? 0 : 20 }}>
      <header>
        <strong>{displayName(post.author)}</strong>
        {post.strategyId != null ? (
          <button type="button" className="quiet" onClick={() => onOpenStrategy(String(post.strategyId))}>
            Strategy {post.strategyId}
          </button>
        ) : null}
      </header>
      <p>{post.body}</p>
      <div className="discussion-actions">
        <button type="button" className={post.liked ? 'quiet liked' : 'quiet'} onClick={() => void onLike(post)}>
          {post.liked ? 'Liked' : 'Like'} {post.likesCount}
        </button>
        <button type="button" className="quiet" onClick={() => setReplying((open) => !open)}>
          Reply
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
    </article>
  )
}
