import { useCallback, useState } from 'react'

/** Which toggleable overlay layers the viewer has switched off, remembered
 * in this browser under `storageKey`. */
export function useHiddenLayers(storageKey: string): [ReadonlySet<string>, (layer: string, visible: boolean) => void] {
  const [hidden, setHidden] = useState<ReadonlySet<string>>(() => {
    try {
      return new Set<string>(JSON.parse(localStorage.getItem(storageKey) ?? '[]'))
    } catch {
      return new Set<string>()
    }
  })
  const setVisible = useCallback(
    (layer: string, visible: boolean) => {
      setHidden((previous) => {
        const next = new Set(previous)
        if (visible) next.delete(layer)
        else next.add(layer)
        try {
          localStorage.setItem(storageKey, JSON.stringify([...next]))
        } catch {
          /* storage unavailable — the choice just isn't remembered */
        }
        return next
      })
    },
    [storageKey],
  )
  return [hidden, setVisible]
}
