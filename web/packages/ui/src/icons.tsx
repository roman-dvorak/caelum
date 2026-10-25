/**
 * The icon set: Phosphor Icons (MIT), as the Caelum design system asks —
 * outlined (`regular`) at 20 px by default, `fill` only for an active or
 * selected state. Re-exported under caelum's own names so a page asks for
 * "the logs icon", and swapping a glyph is a one-line change here.
 *
 * All inherit `currentColor`, so the theme switch needs no icon handling.
 */

import {
  Aperture,
  ArrowClockwise,
  BookOpen,
  Camera,
  CaretLeft,
  CaretRight,
  CheckCircle,
  CircleNotch,
  CloudArrowUp,
  Cpu,
  DownloadSimple,
  Drop,
  Folder,
  Gauge,
  Gear,
  Images,
  Info,
  List,
  MapPin,
  Moon,
  MoonStars,
  Pause,
  Play,
  Power,
  PuzzlePiece,
  Scroll,
  SignOut,
  SlidersHorizontal,
  Stack,
  Sun,
  TerminalWindow,
  Timer,
  Trash,
  Users,
  VideoCamera,
  WarningCircle,
  X,
} from '@phosphor-icons/react'
import type { Icon as PhosphorIcon, IconProps as PhosphorIconProps } from '@phosphor-icons/react'

export type IconProps = PhosphorIconProps

function icon(Glyph: PhosphorIcon) {
  const Wrapped = (props: IconProps) => <Glyph size={20} aria-hidden {...props} />
  Wrapped.displayName = `${Glyph.displayName ?? 'Icon'}Icon`
  return Wrapped
}

// Navigation
export const GaugeIcon = icon(Gauge)
export const LiveIcon = icon(VideoCamera)
export const ImagesIcon = icon(Images)
export const FolderIcon = icon(Folder)
export const SlidersIcon = icon(SlidersHorizontal)
export const PuzzleIcon = icon(PuzzlePiece)
export const TerminalIcon = icon(TerminalWindow)
export const UsersIcon = icon(Users)
export const LogsIcon = icon(Scroll)
export const CpuIcon = icon(Cpu)
export const LayersIcon = icon(Stack)
export const DropletIcon = icon(Drop)
export const SettingsIcon = icon(Gear)
export const CameraIcon = icon(Camera)
export const ProgramIcon = icon(Aperture)
export const BookIcon = icon(BookOpen)

// Sky and data
export const SunIcon = icon(Sun)
export const MoonIcon = icon(Moon)
export const NightIcon = icon(MoonStars)
export const TimerIcon = icon(Timer)
export const LocationIcon = icon(MapPin)
export const UploadIcon = icon(CloudArrowUp)

// Status
export const SuccessIcon = icon(CheckCircle)
export const ErrorIcon = icon(WarningCircle)
export const InfoIcon = icon(Info)
/** Static glyph — use `Spinner` for one that turns. */
export const SpinnerIcon = icon(CircleNotch)

// Controls
export const LogoutIcon = icon(SignOut)
export const MenuIcon = icon(List)
export const CloseIcon = icon(X)
export const ChevronRightIcon = icon(CaretRight)
export const ChevronLeftIcon = icon(CaretLeft)
export const DownloadIcon = icon(DownloadSimple)
export const TrashIcon = icon(Trash)
export const RefreshIcon = icon(ArrowClockwise)
export const PauseIcon = icon(Pause)
export const PlayIcon = icon(Play)
export const PowerIcon = icon(Power)
