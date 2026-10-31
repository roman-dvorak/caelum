import { createContext } from 'react'

/**
 * How many times finer than its box the sky is drawn. A zoomable picture scales
 * its content with CSS; a host that does so provides the zoom here (up to a sane
 * limit) so lines and rings are redrawn crisp instead of being stretched.
 */
export const SkyDetailContext = createContext(1)
