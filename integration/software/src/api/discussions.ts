import { id, isRecord, list, num, optionalStr, postJson, record, requestJson, str } from './http.ts'

export type PostSummary = {
  text: string
  model: string
  /** New replies arrived after the summary was written. */
  stale: boolean
}

export type DiscussionPost = {
  id: number
  userId: number
  author: string
  body: string
  strategyId: number | null
  strategyName: string | null
  parentId: number | null
  likesCount: number
  createdAt: string
  liked: boolean
  summary: PostSummary | null
}

const WHAT = 'Discussion'

export async function listDiscussions(): Promise<DiscussionPost[]> {
  return list(await requestJson('/discussions'), WHAT).map(readPost)
}

/** Publish a post. Resolves true when attaching the strategy made it public. */
export async function createDiscussion(post: { body: string; strategyId?: number; parentId?: number }): Promise<boolean> {
  const row = record(
    await postJson('/discussions', {
      body: post.body,
      ...(post.strategyId != null ? { strategy_id: post.strategyId } : {}),
      ...(post.parentId != null ? { parent_id: post.parentId } : {}),
    }),
    WHAT,
  )
  return row.strategy_made_public === true
}

export async function likeDiscussion(postId: number): Promise<{ likesCount: number; liked: boolean }> {
  const row = record(await postJson(`/discussions/${postId}/like`), WHAT)
  return { likesCount: num(row, 'likes_count', WHAT), liked: row.liked === true }
}

/** The AI summary of a post and its replies, written by Meta Muse. */
export async function summarizeDiscussion(postId: number, refresh = false): Promise<PostSummary> {
  const row = record(await postJson(`/discussions/${postId}/summary`, { refresh }), WHAT)
  return { text: str(row, 'summary', WHAT), model: optionalStr(row, 'model'), stale: false }
}

function readPost(body: unknown): DiscussionPost {
  const row = record(body, WHAT)
  const summary = isRecord(row.summary) && typeof row.summary.text === 'string'
    ? { text: row.summary.text, model: optionalStr(row.summary, 'model'), stale: row.summary.stale === true }
    : null
  const strategyName = optionalStr(row, 'strategy_name').trim()
  return {
    id: id(row.id, WHAT),
    userId: id(row.user_id, WHAT),
    author: str(row, 'author', WHAT),
    body: str(row, 'body', WHAT),
    strategyId: row.strategy_id == null ? null : id(row.strategy_id, WHAT),
    strategyName: strategyName || null,
    parentId: row.parent_id == null ? null : id(row.parent_id, WHAT),
    likesCount: typeof row.likes_count === 'number' ? row.likes_count : 0,
    createdAt: optionalStr(row, 'created_at'),
    liked: row.liked === true,
    summary,
  }
}
