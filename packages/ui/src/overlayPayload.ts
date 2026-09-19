/**
 * Small runtime guards for reading `OverlayElement.payload` fields safely.
 * Payloads are `Record<string, unknown>` by design (the backend contract
 * keeps them open-ended for plugin-contributed overlay types), so anything
 * pulled out of one needs a runtime check before use.
 */

export function readNumber(payload: Record<string, unknown>, key: string): number | undefined {
  const value = payload[key]
  return typeof value === 'number' && Number.isFinite(value) ? value : undefined
}

export function readString(payload: Record<string, unknown>, key: string): string | undefined {
  const value = payload[key]
  return typeof value === 'string' ? value : undefined
}

/** True if `payload` looks like a fractional (0..1) bounding box: has
 * finite numeric x/y/w/h fields. Used both for the known `detection_box`
 * type and as a generic fallback for unrecognized overlay types that
 * happen to carry the same shape. */
export function readFractionalBox(
  payload: Record<string, unknown>,
): { x: number; y: number; w: number; h: number } | undefined {
  const x = readNumber(payload, 'x')
  const y = readNumber(payload, 'y')
  const w = readNumber(payload, 'w')
  const h = readNumber(payload, 'h')
  if (x === undefined || y === undefined || w === undefined || h === undefined) return undefined
  return { x, y, w, h }
}
