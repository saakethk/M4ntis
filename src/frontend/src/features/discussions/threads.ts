import type { DiscussionPost } from '../../api/discussions.ts'

/** Posts grouped by parent id (null = top level). */
export function childrenByParent(posts: DiscussionPost[]): Map<number | null, DiscussionPost[]> {
  const children = new Map<number | null, DiscussionPost[]>()
  for (const post of posts) children.set(post.parentId, [...(children.get(post.parentId) ?? []), post])
  return children
}

export function sortPosts(posts: DiscussionPost[], direction: 'newest' | 'oldest'): DiscussionPost[] {
  return [...posts].sort((a, b) => {
    const delta = a.createdAt.localeCompare(b.createdAt) || a.id - b.id
    return direction === 'oldest' ? delta : -delta
  })
}
