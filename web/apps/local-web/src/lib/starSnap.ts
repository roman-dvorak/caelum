/**
 * Moves a click on a picture to the middle of the star under it, so marking
 * a star by hand is not limited by how steady the hand is.
 *
 * Works on the pixels of the image element as the browser decoded them: the
 * brightest spot within `radius` of the click that clearly stands out of its
 * surroundings, then the brightness-weighted centre of that spot. Returns the
 * position in frame fractions, or null when nothing stands out (or the
 * pixels cannot be read) — the caller then keeps the click as it was.
 */
export function snapToStar(
  img: HTMLImageElement,
  x: number,
  y: number,
  radius = Math.max(6, Math.round(img.naturalWidth * 0.008)),
): { x: number; y: number } | null {
  const width = img.naturalWidth
  const height = img.naturalHeight
  if (width === 0 || height === 0) return null
  const px = Math.round(x * width)
  const py = Math.round(y * height)
  const half = radius + 6
  const x0 = Math.max(0, px - half)
  const y0 = Math.max(0, py - half)
  const w = Math.min(width, px + half + 1) - x0
  const h = Math.min(height, py + half + 1) - y0
  if (w < 5 || h < 5) return null

  let data: Uint8ClampedArray
  try {
    const canvas = document.createElement('canvas')
    canvas.width = w
    canvas.height = h
    const ctx = canvas.getContext('2d', { willReadFrequently: true })
    if (!ctx) return null
    ctx.drawImage(img, x0, y0, w, h, 0, 0, w, h)
    data = ctx.getImageData(0, 0, w, h).data
  } catch {
    return null // a cross-origin picture cannot be read
  }

  const luma = new Float32Array(w * h)
  for (let i = 0; i < luma.length; i++) luma[i] = (data[4 * i] + data[4 * i + 1] + data[4 * i + 2]) / 3

  // The sky around: median brightness and its scatter.
  const sorted = Float32Array.from(luma).sort()
  const background = sorted[sorted.length >> 1]
  const deviations = Float32Array.from(luma, (v) => Math.abs(v - background)).sort()
  const noise = Math.max(1, 1.4826 * deviations[deviations.length >> 1])

  // Brightest 3x3-averaged pixel within the radius of the click.
  const cx = px - x0
  const cy = py - y0
  let best = -Infinity
  let bx = -1
  let by = -1
  for (let j = 1; j < h - 1; j++) {
    for (let i = 1; i < w - 1; i++) {
      if (Math.hypot(i - cx, j - cy) > radius) continue
      let sum = 0
      for (let dj = -1; dj <= 1; dj++) for (let di = -1; di <= 1; di++) sum += luma[(j + dj) * w + i + di]
      const mean = sum / 9
      if (mean > best) {
        best = mean
        bx = i
        by = j
      }
    }
  }
  if (bx < 0 || best - background < 5 * noise) return null

  let weight = 0
  let sx = 0
  let sy = 0
  for (let j = Math.max(0, by - 3); j <= Math.min(h - 1, by + 3); j++) {
    for (let i = Math.max(0, bx - 3); i <= Math.min(w - 1, bx + 3); i++) {
      if (Math.hypot(i - bx, j - by) > 3.5) continue
      const v = Math.max(0, luma[j * w + i] - background - 2 * noise)
      weight += v
      sx += v * (i + 0.5)
      sy += v * (j + 0.5)
    }
  }
  if (weight <= 0) return null
  return { x: (x0 + sx / weight) / width, y: (y0 + sy / weight) / height }
}
