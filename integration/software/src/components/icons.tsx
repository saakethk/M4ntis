// Inline SVG icons. All are decorative (aria-hidden); the button around them carries the label.

import type { ReactNode } from 'react'

type IconProps = { size?: number }

function Stroke({ size = 16, children }: IconProps & { children: ReactNode }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden="true" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      {children}
    </svg>
  )
}

export const TrashIcon = (p: IconProps) => (
  <Stroke {...p}>
    <path d="M4 7h16M9 7V5h6v2M18.5 7l-.8 12.2a1.5 1.5 0 0 1-1.5 1.4H7.8a1.5 1.5 0 0 1-1.5-1.4L5.5 7M10 11v6M14 11v6" />
  </Stroke>
)

export const SearchIcon = (p: IconProps) => (
  <Stroke {...p}>
    <circle cx="11" cy="11" r="6.25" />
    <path d="M16 16.5 20 20.5" />
  </Stroke>
)

export const PlusIcon = (p: IconProps) => (
  <Stroke {...p}>
    <path d="M12 5v14M5 12h14" />
  </Stroke>
)

export const DownloadIcon = (p: IconProps) => (
  <Stroke {...p}>
    <path d="M12 4v11M7 10.5l5 5 5-5M5 19.5h14" />
  </Stroke>
)

export const UploadIcon = (p: IconProps) => (
  <Stroke {...p}>
    <path d="M12 20V9M7 13.5l5-5 5 5M5 4.5h14" />
  </Stroke>
)

export const FitIcon = (p: IconProps) => (
  <Stroke {...p}>
    <path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5" />
  </Stroke>
)

export const ReplyIcon = (p: IconProps) => (
  <Stroke {...p}>
    <path d="M7 8.5h7.2A3.8 3.8 0 0 1 18 12.3v.2M7 8.5 10.2 5.4M7 8.5l3.2 3.2M6 18.5h8.2c2.4 0 4.3-1.8 4.3-4.1V12" />
  </Stroke>
)

export const SparkleIcon = (p: IconProps) => (
  <Stroke {...p}>
    <path d="M12 3.5 13.9 9l5.6 2-5.6 2L12 18.5 10.1 13l-5.6-2 5.6-2L12 3.5ZM19 3v3M17.5 4.5h3" />
  </Stroke>
)

export function HeartIcon({ filled, size = 18 }: IconProps & { filled: boolean }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" aria-hidden="true">
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

export function UserIcon({ size = 18 }: IconProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
      <circle cx="12" cy="8" r="3.2" />
      <path d="M5.2 19.2c1.3-3 3.6-4.5 6.8-4.5s5.5 1.5 6.8 4.5" />
    </svg>
  )
}
