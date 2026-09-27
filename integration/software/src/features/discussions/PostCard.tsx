import { useState } from 'react'
import { summarizeDiscussion, type DiscussionPost, type PostSummary } from '../../api/discussions.ts'
import { HeartIcon, ReplyIcon, SparkleIcon } from '../../components/icons.tsx'
import { displayName, handleOf, initials, relativeTime } from '../../lib/format.ts'
import { Composer } from './Composer.tsx'
import { sortPosts } from './threads.ts'

type Props = {
  post: DiscussionPost
  childrenOf: Map<number | null, DiscussionPost[]>
  onReply: (body: string, parentId: number) => Promise<void>
  onLike: (post: DiscussionPost) => Promise<void>
  onOpenStrategy: (id: number) => void
  depth?: number
}

export function PostCard({ post, childrenOf, onReply, onLike, onOpenStrategy, depth = 0 }: Props) {
  const [replying, setReplying] = useState(false)
  const replies = sortPosts(childrenOf.get(post.id) ?? [], 'oldest')

  return (
    <article className={depth === 0 ? 'tweet' : 'tweet tweet-nested'}>
      <span className="tweet-avatar" aria-hidden="true">
        {initials(post.author)}
      </span>
      <div className="tweet-main">
        <header className="tweet-head">
          <strong>{displayName(post.author)}</strong>
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
          <button type="button" className="tweet-strategy" onClick={() => onOpenStrategy(post.strategyId!)}>
            <span>Shared strategy · open in editor</span>
            <strong>{post.strategyName ?? `Strategy ${post.strategyId}`}</strong>
          </button>
        ) : null}
        {depth === 0 ? <ThreadSummary postId={post.id} initial={post.summary} hasContent={replies.length > 0 || post.body.length > 140 || post.strategyId != null} /> : null}
        <div className="tweet-actions">
          <button type="button" className="tweet-action" aria-expanded={replying} onClick={() => setReplying((open) => !open)}>
            <ReplyIcon size={18} />
            <span>{replies.length > 0 ? replies.length : 'Reply'}</span>
          </button>
          <button
            type="button"
            className={post.liked ? 'tweet-action liked' : 'tweet-action'}
            aria-pressed={post.liked}
            aria-label={post.liked ? 'Unlike' : 'Like'}
            onClick={() => void onLike(post)}
          >
            <HeartIcon filled={post.liked} />
            <span>{post.likesCount}</span>
          </button>
        </div>
        {replying ? (
          <Composer
            onSubmit={async (body) => {
              await onReply(body, post.id)
              setReplying(false)
            }}
          />
        ) : null}
        {replies.length > 0 ? (
          <div className="tweet-replies">
            {replies.map((reply) => (
              <PostCard key={reply.id} post={reply} childrenOf={childrenOf} onReply={onReply} onLike={onLike} onOpenStrategy={onOpenStrategy} depth={depth + 1} />
            ))}
          </div>
        ) : null}
      </div>
    </article>
  )
}

/** The Muse-written summary of a thread: shown when cached, generated on request. */
function ThreadSummary({ postId, initial, hasContent }: { postId: number; initial: PostSummary | null; hasContent: boolean }) {
  const [summary, setSummary] = useState<PostSummary | null>(initial)
  const [pending, setPending] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function load(refresh: boolean) {
    setPending(true)
    setError(null)
    try {
      setSummary(await summarizeDiscussion(postId, refresh))
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not summarize this thread.')
    } finally {
      setPending(false)
    }
  }

  if (!summary) {
    if (!hasContent) return null
    return (
      <div className="ai-summary-empty">
        <button type="button" className="text-btn ai-summary-btn" onClick={() => void load(false)} disabled={pending}>
          <SparkleIcon size={14} />
          {pending ? 'Summarizing…' : 'Summarize thread'}
        </button>
        {error ? <p className="form-error">{error}</p> : null}
      </div>
    )
  }
  return (
    <aside className="ai-summary" aria-label="AI summary">
      <p className="ai-summary-label">
        <SparkleIcon size={13} /> AI summary · Meta Muse
      </p>
      <p>{summary.text}</p>
      <div className="ai-summary-foot">
        {summary.stale ? <span>New replies since this summary.</span> : <span />}
        <button type="button" className="text-btn" onClick={() => void load(true)} disabled={pending}>
          {pending ? 'Updating…' : summary.stale ? 'Update' : 'Regenerate'}
        </button>
      </div>
      {error ? <p className="form-error">{error}</p> : null}
    </aside>
  )
}
