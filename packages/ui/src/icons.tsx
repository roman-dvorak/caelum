/**
 * Hand-rolled stroke icons rather than an icon package.
 *
 * The set is small and fixed (one per nav entry plus a handful of controls),
 * they all share one geometry — 24-unit grid, 1.5 stroke, round caps — so
 * they sit together consistently, and they inherit `currentColor` so the
 * theme switch needs no icon-specific handling. A dependency would be more
 * bytes than the whole file for a worse fit.
 */

import type { SVGProps } from 'react'

export type IconProps = SVGProps<SVGSVGElement> & { size?: number }

function Icon({ size = 18, children, ...props }: IconProps) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      {...props}
    >
      {children}
    </svg>
  )
}

export const GaugeIcon = (props: IconProps) => (
  <Icon {...props}>
    <path d="M12 14l4-4" />
    <path d="M3.5 17a9 9 0 1117 0" />
    <circle cx="12" cy="14" r="1.2" />
  </Icon>
)

export const LiveIcon = (props: IconProps) => (
  <Icon {...props}>
    <circle cx="12" cy="12" r="3" />
    <path d="M7.8 7.8a6 6 0 000 8.4M16.2 16.2a6 6 0 000-8.4" />
    <path d="M4.9 4.9a10 10 0 000 14.2M19.1 19.1a10 10 0 000-14.2" />
  </Icon>
)

export const ImagesIcon = (props: IconProps) => (
  <Icon {...props}>
    <rect x="3" y="6" width="14" height="12" rx="1.5" />
    <path d="M20 8v9a1.5 1.5 0 01-1.5 1.5H7" />
    <circle cx="7.5" cy="10" r="1.2" />
    <path d="M3.5 15.5l3.5-3 4 3.5" />
  </Icon>
)

export const FolderIcon = (props: IconProps) => (
  <Icon {...props}>
    <path d="M3 7a1.5 1.5 0 011.5-1.5h4L10.5 8h9A1.5 1.5 0 0121 9.5v8A1.5 1.5 0 0119.5 19h-15A1.5 1.5 0 013 17.5z" />
  </Icon>
)

export const SlidersIcon = (props: IconProps) => (
  <Icon {...props}>
    <path d="M5 4v6M5 14v6M12 4v3M12 11v9M19 4v9M19 17v3" />
    <circle cx="5" cy="12" r="2" />
    <circle cx="12" cy="9" r="2" />
    <circle cx="19" cy="15" r="2" />
  </Icon>
)

export const PuzzleIcon = (props: IconProps) => (
  <Icon {...props}>
    <path d="M10 4h4v2.2a1.8 1.8 0 103.6 0V4H20v4h-2.2a1.8 1.8 0 100 3.6H20V20h-4.4v-2.2a1.8 1.8 0 10-3.6 0V20H4v-4.4h2.2a1.8 1.8 0 100-3.6H4V8h6z" />
  </Icon>
)

export const TerminalIcon = (props: IconProps) => (
  <Icon {...props}>
    <rect x="3" y="4" width="18" height="16" rx="1.5" />
    <path d="M7 9l3 3-3 3M13 15h4" />
  </Icon>
)

export const UsersIcon = (props: IconProps) => (
  <Icon {...props}>
    <circle cx="9" cy="8" r="3" />
    <path d="M3.5 19a5.5 5.5 0 0111 0" />
    <path d="M16 5.5a3 3 0 010 5.5M17 14.5a5.5 5.5 0 013.5 4.5" />
  </Icon>
)

export const BookIcon = (props: IconProps) => (
  <Icon {...props}>
    <path d="M4 5.5A1.5 1.5 0 015.5 4H11v15H5.5A1.5 1.5 0 014 17.5z" />
    <path d="M20 5.5A1.5 1.5 0 0018.5 4H13v15h5.5a1.5 1.5 0 001.5-1.5z" />
  </Icon>
)

export const SunIcon = (props: IconProps) => (
  <Icon {...props}>
    <circle cx="12" cy="12" r="4" />
    <path d="M12 2.5v2M12 19.5v2M2.5 12h2M19.5 12h2M5.2 5.2l1.4 1.4M17.4 17.4l1.4 1.4M18.8 5.2l-1.4 1.4M6.6 17.4l-1.4 1.4" />
  </Icon>
)

export const MoonIcon = (props: IconProps) => (
  <Icon {...props}>
    <path d="M20 14.5A8.5 8.5 0 019.5 4a8.5 8.5 0 1010.5 10.5z" />
  </Icon>
)

export const LogoutIcon = (props: IconProps) => (
  <Icon {...props}>
    <path d="M14 4h4.5A1.5 1.5 0 0120 5.5v13a1.5 1.5 0 01-1.5 1.5H14" />
    <path d="M10 8l-4 4 4 4M6 12h9" />
  </Icon>
)

export const MenuIcon = (props: IconProps) => (
  <Icon {...props}>
    <path d="M4 7h16M4 12h16M4 17h16" />
  </Icon>
)

export const CloseIcon = (props: IconProps) => (
  <Icon {...props}>
    <path d="M6 6l12 12M18 6L6 18" />
  </Icon>
)

export const ChevronRightIcon = (props: IconProps) => (
  <Icon {...props}>
    <path d="M9 5l7 7-7 7" />
  </Icon>
)

export const DownloadIcon = (props: IconProps) => (
  <Icon {...props}>
    <path d="M12 3v11M8 10.5l4 4 4-4" />
    <path d="M4 18v1.5A1.5 1.5 0 005.5 21h13a1.5 1.5 0 001.5-1.5V18" />
  </Icon>
)

export const TrashIcon = (props: IconProps) => (
  <Icon {...props}>
    <path d="M4 6.5h16M9.5 6.5V4.5h5v2" />
    <path d="M6.5 6.5l.8 12A1.5 1.5 0 008.8 20h6.4a1.5 1.5 0 001.5-1.4l.8-12" />
    <path d="M10.5 10v6M13.5 10v6" />
  </Icon>
)

export const RefreshIcon = (props: IconProps) => (
  <Icon {...props}>
    <path d="M20 11a8 8 0 10-1.9 6.4" />
    <path d="M20 20v-5h-5" />
  </Icon>
)

export const CameraIcon = (props: IconProps) => (
  <Icon {...props}>
    <path d="M3 8.5A1.5 1.5 0 014.5 7h2.2l1.3-2h7l1.3 2h2.2A1.5 1.5 0 0120 8.5v9A1.5 1.5 0 0118.5 19h-14A1.5 1.5 0 013 17.5z" />
    <circle cx="11.5" cy="12.5" r="3.5" />
  </Icon>
)
