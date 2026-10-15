import { useEffect, useRef, useState } from 'react'
import type { PointerEvent as ReactPointerEvent, ReactNode, RefObject } from 'react'
import type {
  LensConfig,
  OverlayAssetInfo,
  OverlayElementDef,
  OverlayElementKind,
  OverlaySettings,
  OverlayTemplate,
  TelescopePositionSettings,
} from '@caelum/api-client'
import { Button, Field, Message, PageHeader, Panel, inputClass } from '@caelum/ui'
import { usePlugins } from '../hooks/usePlugins.ts'
import { localApiClient } from '../services/client.ts'

type Tab = 'elements' | 'telescope' | 'lens'

// Mirrors OverlayWorker.LABEL_PLACEHOLDERS in
// caelum/src/caelum/derivatives/overlay.py — the single fixed set of
// `str.format()` fields a label template may reference.
const LABEL_PLACEHOLDERS = [
  'exposure_us',
  'analogue_gain',
  'sky_state.period',
  'sky_state.sun_altitude_deg',
  'sky_state.sun_azimuth_deg',
  'sky_state.moon_altitude_deg',
  'sky_state.moon_azimuth_deg',
  'sky_state.moon_illumination',
  'focus_score',
  'captured_at',
]

const DEFAULT_TELESCOPE_SETTINGS: TelescopePositionSettings = {
  source: 'simulated',
  center_x: 0.5,
  center_y: 0.5,
  radius: 0.48,
  azimuth_offset_deg: 0,
  mirror: false,
  label: 'Telescope',
}

const DEFAULT_LENS_CONFIG: LensConfig = {
  projection: 'equidistant_fisheye',
  center_x: 0.5,
  center_y: 0.5,
  radius: 0.48,
  azimuth_offset_deg: 0,
  mirror: false,
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value))
}

// `crypto.randomUUID()` only exists in secure contexts (HTTPS or localhost);
// this app is commonly served over plain HTTP on the LAN, where it's
// undefined and throws — fall back to a non-cryptographic id in that case.
function newElementId(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID()
  }
  return `el-${Math.random().toString(36).slice(2)}${Math.random().toString(36).slice(2)}`
}

function newElement(kind: OverlayElementKind): OverlayElementDef {
  const id = newElementId()
  if (kind === 'label') {
    return { id, kind, x: 0.5, y: 0.5, color: '#e5e5e5', opacity: 1, template: 'Exp: {exposure_us}us' }
  }
  return { id, kind, x: 0.35, y: 0.35, w: 0.3, h: 0.2, color: '#000000', opacity: 1 }
}

/**
 * Visual drag/resize editor for the `overlay` plugin's user-defined
 * elements (masks, text labels, inserted images) and the `telescope_position`
 * demo plugin's projection calibration — both are plain plugin `settings`
 * blobs, saved through the same `updatePlugin()` the raw-JSON Plugins page
 * already uses; this page is just a friendlier way to produce that JSON.
 */
const DEFAULT_TEMPLATE_NAME = 'Default'

function defaultTemplates(): OverlayTemplate[] {
  return [{ name: DEFAULT_TEMPLATE_NAME, elements: [] }]
}

// Mirrors `OverlaySettings._migrate_flat_elements` in
// caelum/src/caelum/derivatives/overlay.py — a Pi upgraded in place still
// has its old flat `{elements: [...]}` shape in `GET /api/plugins` until
// the editor saves it in the new shape, so this page needs to recognize
// that shape too rather than silently treating it as empty.
function templatesFromSettings(
  settings: (Partial<OverlaySettings> & { elements?: OverlayElementDef[] }) | undefined,
): { templates: OverlayTemplate[]; active: string } {
  if (settings?.templates && settings.templates.length > 0) {
    return { templates: settings.templates, active: settings.active_template ?? settings.templates[0].name }
  }
  if (settings?.elements) {
    return { templates: [{ name: DEFAULT_TEMPLATE_NAME, elements: settings.elements }], active: DEFAULT_TEMPLATE_NAME }
  }
  return { templates: defaultTemplates(), active: DEFAULT_TEMPLATE_NAME }
}

export function OverlayEditor() {
  const { plugins, error, updatePlugin } = usePlugins()
  const [tab, setTab] = useState<Tab>('elements')
  const [templates, setTemplates] = useState<OverlayTemplate[]>(defaultTemplates())
  const [activeTemplateName, setActiveTemplateName] = useState<string>(DEFAULT_TEMPLATE_NAME)
  const [elements, setElements] = useState<OverlayElementDef[]>([])
  const [telescope, setTelescope] = useState<TelescopePositionSettings>(DEFAULT_TELESCOPE_SETTINGS)
  const [lens, setLens] = useState<LensConfig>(DEFAULT_LENS_CONFIG)
  const [lensSeeded, setLensSeeded] = useState(false)
  const [seeded, setSeeded] = useState(false)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [previewToken, setPreviewToken] = useState(0)
  const [assets, setAssets] = useState<OverlayAssetInfo[]>([])
  const [message, setMessage] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const containerRef = useRef<HTMLDivElement>(null)

  // Seeded once, the first time plugin config actually arrives — after
  // that this page owns the working copy until it's explicitly saved.
  useEffect(() => {
    if (seeded || !plugins) return
    const overlaySettings = plugins.overlay?.settings as
      | (Partial<OverlaySettings> & { elements?: OverlayElementDef[] })
      | undefined
    const { templates: loadedTemplates, active: loadedActive } = templatesFromSettings(overlaySettings)
    setTemplates(loadedTemplates)
    setActiveTemplateName(loadedActive)
    setElements(loadedTemplates.find((t) => t.name === loadedActive)?.elements ?? loadedTemplates[0].elements)
    const telescopeSettings = plugins.telescope_position?.settings as Partial<TelescopePositionSettings> | undefined
    setTelescope({ ...DEFAULT_TELESCOPE_SETTINGS, ...telescopeSettings })
    setSeeded(true)
  }, [plugins, seeded])

  // Writes the in-memory `elements` array back into `templates` under the
  // given name — used before switching/saving so the template list always
  // reflects whatever's currently being edited.
  function withCurrentElements(current: OverlayTemplate[]): OverlayTemplate[] {
    return current.map((t) => (t.name === activeTemplateName ? { ...t, elements } : t))
  }

  function switchTemplate(name: string) {
    if (name === activeTemplateName) return
    const updated = withCurrentElements(templates)
    setTemplates(updated)
    setActiveTemplateName(name)
    setElements(updated.find((t) => t.name === name)?.elements ?? [])
    setSelectedId(null)
  }

  function newTemplate() {
    const name = window.prompt('Template name')?.trim()
    if (!name) return
    if (templates.some((t) => t.name === name)) {
      setMessage(`A template named "${name}" already exists.`)
      return
    }
    setTemplates((current) => [...withCurrentElements(current), { name, elements: [] }])
    setActiveTemplateName(name)
    setElements([])
    setSelectedId(null)
  }

  function duplicateTemplate() {
    let candidate = `${activeTemplateName} copy`
    let n = 2
    while (templates.some((t) => t.name === candidate)) {
      candidate = `${activeTemplateName} copy ${n}`
      n += 1
    }
    const updated = withCurrentElements(templates)
    setTemplates([...updated, { name: candidate, elements: elements.map((e) => ({ ...e })) }])
    setActiveTemplateName(candidate)
    setSelectedId(null)
  }

  function renameTemplate() {
    const name = window.prompt('Rename template', activeTemplateName)?.trim()
    if (!name || name === activeTemplateName) return
    if (templates.some((t) => t.name === name)) {
      setMessage(`A template named "${name}" already exists.`)
      return
    }
    setTemplates((current) => withCurrentElements(current).map((t) => (t.name === activeTemplateName ? { ...t, name } : t)))
    setActiveTemplateName(name)
  }

  function deleteTemplate() {
    if (templates.length <= 1) {
      setMessage('At least one template must remain.')
      return
    }
    const remaining = templates.filter((t) => t.name !== activeTemplateName)
    setTemplates(remaining)
    setActiveTemplateName(remaining[0].name)
    setElements(remaining[0].elements)
    setSelectedId(null)
  }

  useEffect(() => {
    void refreshAssets()
  }, [])

  useEffect(() => {
    if (lensSeeded) return
    let cancelled = false
    localApiClient
      .getConfig()
      .then((cfg) => {
        if (!cancelled) setLens(cfg.camera.lens)
      })
      .catch(() => {
        // The lens tab just keeps its defaults — Settings.tsx surfaces
        // config-load errors already, no need to duplicate that here.
      })
      .finally(() => {
        if (!cancelled) setLensSeeded(true)
      })
    return () => {
      cancelled = true
    }
  }, [lensSeeded])

  async function saveLens() {
    setSaving(true)
    setMessage(null)
    try {
      const updated = await localApiClient.updateConfig({ camera: { lens } })
      setLens(updated.camera.lens)
      setMessage('Saved lens calibration.')
    } catch (err) {
      setMessage(err instanceof Error ? err.message : String(err))
    } finally {
      setSaving(false)
    }
  }

  async function refreshAssets() {
    try {
      setAssets(await localApiClient.listOverlayAssets())
    } catch {
      // The asset picker just stays empty — not worth surfacing as an error
      // on a page whose primary job is placing elements, not managing files.
    }
  }

  const selected = elements.find((e) => e.id === selectedId) ?? null

  function updateElement(id: string, patch: Partial<OverlayElementDef>) {
    setElements((current) => current.map((e) => (e.id === id ? { ...e, ...patch } : e)))
  }

  function addElement(kind: OverlayElementKind) {
    const element = newElement(kind)
    setElements((current) => [...current, element])
    setSelectedId(element.id)
  }

  function removeElement(id: string) {
    setElements((current) => current.filter((e) => e.id !== id))
    if (selectedId === id) setSelectedId(null)
  }

  async function saveTemplates() {
    setSaving(true)
    setMessage(null)
    try {
      const finalTemplates = withCurrentElements(templates)
      await updatePlugin('overlay', { settings: { templates: finalTemplates, active_template: activeTemplateName } })
      setTemplates(finalTemplates)
      setMessage('Saved overlay templates.')
    } catch (err) {
      setMessage(err instanceof Error ? err.message : String(err))
    } finally {
      setSaving(false)
    }
  }

  async function saveTelescope() {
    setSaving(true)
    setMessage(null)
    try {
      await updatePlugin('telescope_position', { settings: { ...telescope } })
      setMessage('Saved telescope calibration.')
    } catch (err) {
      setMessage(err instanceof Error ? err.message : String(err))
    } finally {
      setSaving(false)
    }
  }

  const previewUrl = `${localApiClient.latestFrameUrl()}?t=${previewToken}`

  return (
    <>
      <PageHeader
        title="Overlay editor"
        description="Configure masks, text labels and images drawn over the live view — and the demo telescope-position widget. Changes only take effect once saved."
        actions={<Button onClick={() => setPreviewToken((n) => n + 1)}>Refresh preview</Button>}
      />

      {error ? <Message kind="error">{error}</Message> : null}
      {message ? <Message kind="info">{message}</Message> : null}

      <div className="mb-4 flex gap-2">
        <TabButton active={tab === 'elements'} onClick={() => setTab('elements')}>
          Elements
        </TabButton>
        <TabButton active={tab === 'telescope'} onClick={() => setTab('telescope')}>
          Telescope demo
        </TabButton>
        <TabButton active={tab === 'lens'} onClick={() => setTab('lens')}>
          Lens
        </TabButton>
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[1fr_320px]">
        <div ref={containerRef} className="relative overflow-hidden border border-line bg-void">
          <img src={previewUrl} alt="Latest camera frame" className="block w-full" onClick={() => setSelectedId(null)} />
          {tab === 'elements'
            ? elements.map((element) => (
                <ElementBox
                  key={element.id}
                  def={element}
                  selected={element.id === selectedId}
                  containerRef={containerRef}
                  onSelect={() => setSelectedId(element.id)}
                  onChange={(patch) => updateElement(element.id, patch)}
                />
              ))
            : null}
          {tab === 'telescope' ? (
            <TelescopeOverlay
              settings={telescope}
              containerRef={containerRef}
              onChange={(patch) => setTelescope((current) => ({ ...current, ...patch }))}
            />
          ) : null}
          {tab === 'lens' ? (
            <TelescopeOverlay
              settings={lens}
              containerRef={containerRef}
              onChange={(patch) => setLens((current) => ({ ...current, ...patch }))}
            />
          ) : null}
        </div>

        {tab === 'elements' ? (
          <div className="flex flex-col gap-3">
            <Panel title="Overlay plugin">
              <label className="flex items-center gap-2 text-xs font-medium tracking-wide text-ink-dim uppercase">
                <input
                  type="checkbox"
                  checked={plugins?.overlay?.enabled ?? false}
                  onChange={(e) => void updatePlugin('overlay', { enabled: e.target.checked })}
                  className="accent-amber"
                />
                Enabled
              </label>
              {!plugins?.overlay?.enabled ? (
                <p className="mt-1 text-xs text-ink-faint">
                  Elements below only show on the live view once this is enabled and saved.
                </p>
              ) : null}
            </Panel>

            <Panel title="Template">
              <div className="flex flex-col gap-2">
                <select
                  className={inputClass}
                  value={activeTemplateName}
                  onChange={(e) => switchTemplate(e.target.value)}
                >
                  {templates.map((t) => (
                    <option key={t.name} value={t.name}>
                      {t.name}
                    </option>
                  ))}
                </select>
                <div className="flex flex-wrap gap-2">
                  <Button onClick={newTemplate}>New</Button>
                  <Button onClick={duplicateTemplate}>Duplicate</Button>
                  <Button onClick={renameTemplate}>Rename</Button>
                  <Button variant="danger" onClick={deleteTemplate}>
                    Delete
                  </Button>
                </div>
              </div>
            </Panel>

            <Panel title="Add element">
              <div className="flex flex-wrap gap-2">
                <Button onClick={() => addElement('mask')}>+ Mask</Button>
                <Button onClick={() => addElement('label')}>+ Label</Button>
                <Button onClick={() => addElement('image')}>+ Image</Button>
              </div>
            </Panel>

            <Panel title={`Elements (${elements.length})`} bodyClassName="p-2">
              {elements.length === 0 ? (
                <p className="px-2 py-1 text-sm text-ink-faint">None yet — add one above.</p>
              ) : (
                <ul className="flex flex-col gap-1">
                  {elements.map((element) => (
                    <li key={element.id}>
                      <button
                        type="button"
                        onClick={() => setSelectedId(element.id)}
                        className={[
                          'w-full border px-2 py-1 text-left font-mono text-xs',
                          element.id === selectedId
                            ? 'border-amber-dim bg-amber/10 text-ink'
                            : 'border-transparent text-ink-dim hover:border-line',
                        ].join(' ')}
                      >
                        {element.kind} — {element.id.slice(0, 8)}
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </Panel>

            {selected ? (
              <ElementProperties
                element={selected}
                assets={assets}
                onChange={(patch) => updateElement(selected.id, patch)}
                onDelete={() => removeElement(selected.id)}
                onAssetUploaded={() => void refreshAssets()}
              />
            ) : null}

            <Button variant="primary" onClick={() => void saveTemplates()} disabled={saving}>
              Save template
            </Button>
          </div>
        ) : null}

        {tab === 'telescope' ? (
          <div className="flex flex-col gap-3">
            <Panel title="Telescope demo">
              <div className="flex flex-col gap-3">
                <label className="flex items-center gap-2 text-xs font-medium tracking-wide text-ink-dim uppercase">
                  <input
                    type="checkbox"
                    checked={plugins?.telescope_position?.enabled ?? false}
                    onChange={(e) => void updatePlugin('telescope_position', { enabled: e.target.checked })}
                    className="accent-amber"
                  />
                  Enabled
                </label>
                <p className="text-xs text-ink-faint">
                  Source: simulated demo sweep — stands in for a future INDI mount connection. Drag the
                  center point and its radius handle on the preview to calibrate the projection.
                </p>
                <Field label="Label">
                  <input
                    className={inputClass}
                    value={telescope.label}
                    onChange={(e) => setTelescope((c) => ({ ...c, label: e.target.value }))}
                  />
                </Field>
                <Field label="Azimuth offset (deg)">
                  <input
                    type="number"
                    className={inputClass}
                    value={telescope.azimuth_offset_deg}
                    onChange={(e) => setTelescope((c) => ({ ...c, azimuth_offset_deg: Number(e.target.value) }))}
                  />
                </Field>
                <label className="flex items-center gap-2 text-xs font-medium tracking-wide text-ink-dim uppercase">
                  <input
                    type="checkbox"
                    checked={telescope.mirror}
                    onChange={(e) => setTelescope((c) => ({ ...c, mirror: e.target.checked }))}
                    className="accent-amber"
                  />
                  Mirror (east/west flip)
                </label>
              </div>
            </Panel>
            <Button variant="primary" onClick={() => void saveTelescope()} disabled={saving}>
              Save telescope calibration
            </Button>
          </div>
        ) : null}

        {tab === 'lens' ? (
          <div className="flex flex-col gap-3">
            <Panel title="Lens calibration">
              <div className="flex flex-col gap-3">
                <p className="text-xs text-ink-faint">
                  Describes the camera's own fisheye projection, used to convert a pixel position into an
                  alt/az sky position. Drag the center point and its radius handle on the preview, or enter
                  values directly.
                </p>
                <Field label="Center X">
                  <input
                    type="number"
                    step={0.001}
                    className={inputClass}
                    value={lens.center_x}
                    onChange={(e) => setLens((c) => ({ ...c, center_x: Number(e.target.value) }))}
                  />
                </Field>
                <Field label="Center Y">
                  <input
                    type="number"
                    step={0.001}
                    className={inputClass}
                    value={lens.center_y}
                    onChange={(e) => setLens((c) => ({ ...c, center_y: Number(e.target.value) }))}
                  />
                </Field>
                <Field label="Radius">
                  <input
                    type="number"
                    step={0.001}
                    className={inputClass}
                    value={lens.radius}
                    onChange={(e) => setLens((c) => ({ ...c, radius: Number(e.target.value) }))}
                  />
                </Field>
                <Field label="Azimuth offset (deg)">
                  <input
                    type="number"
                    className={inputClass}
                    value={lens.azimuth_offset_deg}
                    onChange={(e) => setLens((c) => ({ ...c, azimuth_offset_deg: Number(e.target.value) }))}
                  />
                </Field>
                <label className="flex items-center gap-2 text-xs font-medium tracking-wide text-ink-dim uppercase">
                  <input
                    type="checkbox"
                    checked={lens.mirror}
                    onChange={(e) => setLens((c) => ({ ...c, mirror: e.target.checked }))}
                    className="accent-amber"
                  />
                  Mirror (east/west flip)
                </label>
              </div>
            </Panel>
            <Button variant="primary" onClick={() => void saveLens()} disabled={saving}>
              Save lens calibration
            </Button>
            <Panel title="Visual calibration">
              <div className="flex flex-col gap-2">
                <p className="text-xs text-ink-faint">
                  Click known stars in a live frame and their real alt/az to fit these parameters
                  automatically — not built yet, manual entry above is the only option for now.
                </p>
                <Button disabled title="Coming soon">
                  Visual calibration (star-based) — coming soon
                </Button>
              </div>
            </Panel>
          </div>
        ) : null}
      </div>
    </>
  )

  function TabButton({
    active,
    onClick,
    children,
  }: {
    active: boolean
    onClick: () => void
    children: ReactNode
  }) {
    return (
      <button
        type="button"
        onClick={onClick}
        className={[
          'border px-3 py-1.5 text-xs font-semibold tracking-wide uppercase transition',
          active ? 'border-amber bg-amber/10 text-amber' : 'border-line text-ink-dim hover:border-amber-dim',
        ].join(' ')}
      >
        {children}
      </button>
    )
  }
}

function ElementBox({
  def,
  selected,
  containerRef,
  onSelect,
  onChange,
}: {
  def: OverlayElementDef
  selected: boolean
  containerRef: RefObject<HTMLDivElement | null>
  onSelect: () => void
  onChange: (patch: Partial<OverlayElementDef>) => void
}) {
  function startDrag(startEvent: ReactPointerEvent, mode: 'move' | 'resize') {
    startEvent.stopPropagation()
    startEvent.preventDefault()
    onSelect()
    const container = containerRef.current
    if (!container) return
    const rect = container.getBoundingClientRect()
    const start = { x: def.x, y: def.y, w: def.w ?? 0.1, h: def.h ?? 0.1 }
    const startClientX = startEvent.clientX
    const startClientY = startEvent.clientY

    function onMove(moveEvent: PointerEvent) {
      const dx = (moveEvent.clientX - startClientX) / rect.width
      const dy = (moveEvent.clientY - startClientY) / rect.height
      if (mode === 'move') {
        onChange({ x: clamp(start.x + dx, 0, 1), y: clamp(start.y + dy, 0, 1) })
      } else {
        onChange({
          w: clamp(start.w + dx, 0.02, 1 - start.x),
          h: clamp(start.h + dy, 0.02, 1 - start.y),
        })
      }
    }
    function onUp() {
      window.removeEventListener('pointermove', onMove)
      window.removeEventListener('pointerup', onUp)
    }
    window.addEventListener('pointermove', onMove)
    window.addEventListener('pointerup', onUp)
  }

  const borderColor = selected ? 'border-amber' : 'border-cyan/70'

  if (def.kind === 'label') {
    return (
      <div
        onPointerDown={(e) => startDrag(e, 'move')}
        className={['absolute -translate-x-1/2 -translate-y-1/2 cursor-move border px-1.5 py-0.5 font-mono text-[10px] whitespace-nowrap', borderColor].join(' ')}
        style={{ left: `${def.x * 100}%`, top: `${def.y * 100}%`, color: def.color, backgroundColor: 'rgba(0,0,0,0.5)' }}
      >
        {def.template || 'label'}
      </div>
    )
  }

  return (
    <div
      onPointerDown={(e) => startDrag(e, 'move')}
      className={['absolute cursor-move border-2', borderColor].join(' ')}
      style={{
        left: `${def.x * 100}%`,
        top: `${def.y * 100}%`,
        width: `${(def.w ?? 0.1) * 100}%`,
        height: `${(def.h ?? 0.1) * 100}%`,
        backgroundColor: def.kind === 'mask' ? def.color : 'transparent',
        opacity: def.kind === 'mask' ? def.opacity : 1,
      }}
    >
      <div
        onPointerDown={(e) => startDrag(e, 'resize')}
        className="absolute -right-1.5 -bottom-1.5 h-3 w-3 cursor-nwse-resize border border-void bg-amber"
      />
    </div>
  )
}

interface CenterRadiusCalibration {
  center_x: number
  center_y: number
  radius: number
}

function TelescopeOverlay<T extends CenterRadiusCalibration>({
  settings,
  containerRef,
  onChange,
}: {
  settings: T
  containerRef: RefObject<HTMLDivElement | null>
  onChange: (patch: Partial<CenterRadiusCalibration>) => void
}) {
  function startDrag(startEvent: ReactPointerEvent, mode: 'center' | 'radius') {
    startEvent.stopPropagation()
    startEvent.preventDefault()
    const container = containerRef.current
    if (!container) return
    const rect = container.getBoundingClientRect()
    const start = { cx: settings.center_x, cy: settings.center_y, r: settings.radius }
    const startClientX = startEvent.clientX
    const startClientY = startEvent.clientY

    function onMove(moveEvent: PointerEvent) {
      const dx = (moveEvent.clientX - startClientX) / rect.width
      const dy = (moveEvent.clientY - startClientY) / rect.height
      if (mode === 'center') {
        onChange({ center_x: clamp(start.cx + dx, 0, 1), center_y: clamp(start.cy + dy, 0, 1) })
      } else {
        onChange({ radius: clamp(start.r + dx, 0.02, 1) })
      }
    }
    function onUp() {
      window.removeEventListener('pointermove', onMove)
      window.removeEventListener('pointerup', onUp)
    }
    window.addEventListener('pointermove', onMove)
    window.addEventListener('pointerup', onUp)
  }

  return (
    <>
      <div
        className="pointer-events-none absolute rounded-full border-2 border-dashed border-amber/70"
        style={{
          left: `${(settings.center_x - settings.radius) * 100}%`,
          top: `${(settings.center_y - settings.radius) * 100}%`,
          width: `${settings.radius * 2 * 100}%`,
          height: `${settings.radius * 2 * 100}%`,
        }}
      />
      <div
        onPointerDown={(e) => startDrag(e, 'center')}
        className="absolute h-3 w-3 -translate-x-1/2 -translate-y-1/2 cursor-move rounded-full border-2 border-void bg-amber"
        style={{ left: `${settings.center_x * 100}%`, top: `${settings.center_y * 100}%` }}
        title="Zenith center — drag to move"
      />
      <div
        onPointerDown={(e) => startDrag(e, 'radius')}
        className="absolute h-3 w-3 -translate-x-1/2 -translate-y-1/2 cursor-ew-resize rounded-full border-2 border-void bg-cyan"
        style={{ left: `${(settings.center_x + settings.radius) * 100}%`, top: `${settings.center_y * 100}%` }}
        title="Horizon radius — drag to resize"
      />
    </>
  )
}

function ElementProperties({
  element,
  assets,
  onChange,
  onDelete,
  onAssetUploaded,
}: {
  element: OverlayElementDef
  assets: OverlayAssetInfo[]
  onChange: (patch: Partial<OverlayElementDef>) => void
  onDelete: () => void
  onAssetUploaded: () => void
}) {
  const [uploading, setUploading] = useState(false)

  async function handleUpload(file: File) {
    setUploading(true)
    try {
      const uploaded = await localApiClient.uploadOverlayAsset(file)
      onChange({ asset: uploaded.name })
      onAssetUploaded()
    } finally {
      setUploading(false)
    }
  }

  return (
    <Panel title={`Properties: ${element.kind}`}>
      <div className="flex flex-col gap-3">
        {element.kind === 'label' ? (
          <>
            <Field label="Template">
              <textarea
                className={inputClass}
                rows={2}
                value={element.template ?? ''}
                onChange={(e) => onChange({ template: e.target.value })}
              />
            </Field>
            <div className="flex flex-wrap gap-1">
              {LABEL_PLACEHOLDERS.map((p) => (
                <button
                  key={p}
                  type="button"
                  onClick={() => onChange({ template: `${element.template ?? ''}{${p}}` })}
                  className="border border-line px-1.5 py-0.5 font-mono text-[10px] text-ink-faint hover:border-amber-dim hover:text-ink"
                >
                  {`{${p}}`}
                </button>
              ))}
            </div>
            <Field label="Font size (px)">
              <input
                type="number"
                className={inputClass}
                value={element.font_size_px ?? ''}
                placeholder="default"
                onChange={(e) => onChange({ font_size_px: e.target.value ? Number(e.target.value) : null })}
              />
            </Field>
          </>
        ) : null}

        {element.kind === 'image' ? (
          <>
            <Field label="Asset">
              <select
                className={inputClass}
                value={element.asset ?? ''}
                onChange={(e) => onChange({ asset: e.target.value || null })}
              >
                <option value="">— choose —</option>
                {assets.map((a) => (
                  <option key={a.name} value={a.name}>
                    {a.name}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Upload new" hint="PNG/JPEG/WebP/GIF, up to 2 MB">
              <input
                type="file"
                accept="image/png,image/jpeg,image/webp,image/gif"
                disabled={uploading}
                onChange={(e) => {
                  const file = e.target.files?.[0]
                  if (file) void handleUpload(file)
                }}
              />
            </Field>
          </>
        ) : null}

        {element.kind === 'mask' || element.kind === 'label' ? (
          <Field label="Color">
            <input
              type="color"
              value={element.color}
              onChange={(e) => onChange({ color: e.target.value })}
              className="h-8 w-16 border border-line bg-void"
            />
          </Field>
        ) : null}

        {element.kind === 'mask' ? (
          <Field label={`Opacity (${element.opacity.toFixed(2)})`}>
            <input
              type="range"
              min={0}
              max={1}
              step={0.05}
              value={element.opacity}
              onChange={(e) => onChange({ opacity: Number(e.target.value) })}
            />
          </Field>
        ) : null}

        <Button variant="danger" onClick={onDelete}>
          Delete element
        </Button>
      </div>
    </Panel>
  )
}
