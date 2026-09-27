import { useCallback, useEffect, useState } from 'react'
import type { User } from '../../api/auth.ts'
import { createDiscussion, likeDiscussion, listDiscussions, type DiscussionPost } from '../../api/discussions.ts'
import { listStrategies, type StrategySummary } from '../../api/strategies.ts'
import { Composer } from './Composer.tsx'
import { PostCard } from './PostCard.tsx'
import { childrenByParent, sortPosts } from './threads.ts'

type Props = {
  user: User
  onOpenStrategy: (id: number) => void
}

export function Discussions({ user, onOpenStrategy }: Props) {
  const [posts, setPosts] = useState<DiscussionPost[] | null>(null)
  const [strategies, setStrategies] = useState<StrategySummary[]>([])
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  const reload = useCallback(async () => {
    try {
      setPosts(await listDiscussions())
      setError(null)
    } catch (caught) {
      setPosts((current) => current ?? [])
      setError(caught instanceof Error ? caught.message : 'Could not load discussions.')
    }
  }, [])

  useEffect(() => {
    void reload()
    listStrategies().then(setStrategies, () => setStrategies([]))
  }, [reload])

  async function publish(body: string, strategyId?: number) {
    const madePublic = await createDiscussion({ body, strategyId })
    setNotice(madePublic ? 'That strategy is now public. Others can view and copy it; only you can edit it.' : null)
    if (madePublic) setStrategies(await listStrategies())
    await reload()
  }

  async function reply(body: string, parentId: number) {
    await createDiscussion({ body, parentId })
    await reload()
  }

  async function toggleLike(post: DiscussionPost) {
    try {
      const next = await likeDiscussion(post.id)
      setPosts((current) => current?.map((item) => (item.id === post.id ? { ...item, ...next } : item)) ?? current)
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not update the like.')
    }
  }

  const children = childrenByParent(posts ?? [])
  const timeline = sortPosts(children.get(null) ?? [], 'newest')

  return (
    <section className="discussions">
      <header className="feed-head">
        <h1>Discussions</h1>
        <p>Share strategies and ideas with everyone on Mantis</p>
      </header>
      {error ? <p className="form-error feed-banner">{error}</p> : null}
      {notice ? <p className="discussion-notice feed-banner">{notice}</p> : null}
      <Composer authorEmail={user.email} strategies={strategies} onSubmit={publish} />
      {posts === null ? <p className="status-line feed-banner">Loading discussions…</p> : null}
      {posts !== null && timeline.length === 0 ? <p className="feed-empty">No posts yet. Share a strategy to start the conversation.</p> : null}
      <div className="feed">
        {timeline.map((post) => (
          <PostCard key={post.id} post={post} childrenOf={children} onReply={reply} onLike={toggleLike} onOpenStrategy={onOpenStrategy} />
        ))}
      </div>
    </section>
  )
}
