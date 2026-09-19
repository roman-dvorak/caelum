import { useEffect, useState } from 'react'
import type { ReactNode } from 'react'
import type { AppConfig, DeepPartial, LocationConfig, RetentionConfig, SkyPeriod, StoragePolicyConfig, UploadConfig } from '@caelum/api-client'
import { SKY_PERIODS } from '@caelum/api-client'
import { localApiClient } from '../services/client.ts'

export function Settings() {
  const [config, setConfig] = useState<AppConfig | null>(null)
  const [initialConfig, setInitialConfig] = useState<AppConfig | null>(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [message, setMessage] = useState<string | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    localApiClient
      .getConfig()
      .then((cfg) => {
        if (cancelled) return
        setConfig(cfg)
        setInitialConfig(cfg)
      })
      .catch((err) => {
        if (!cancelled) setLoadError(err instanceof Error ? err.message : String(err))
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [])

  function updateLocation<K extends keyof LocationConfig>(key: K, value: LocationConfig[K]) {
    setConfig((prev) => (prev ? { ...prev, location: { ...prev.location, [key]: value } } : prev))
  }

  function updateStoragePolicy<K extends keyof StoragePolicyConfig>(key: K, value: StoragePolicyConfig[K]) {
    setConfig((prev) => (prev ? { ...prev, storage_policy: { ...prev.storage_policy, [key]: value } } : prev))
  }

  function updateRetention<K extends keyof RetentionConfig>(key: K, value: RetentionConfig[K]) {
    setConfig((prev) => (prev ? { ...prev, retention: { ...prev.retention, [key]: value } } : prev))
  }

  function updateUpload<K extends keyof UploadConfig>(key: K, value: UploadConfig[K]) {
    setConfig((prev) => (prev ? { ...prev, upload: { ...prev.upload, [key]: value } } : prev))
  }

  function toggleRawPeriod(period: SkyPeriod, checked: boolean) {
    setConfig((prev) => {
      if (!prev) return prev
      const next = checked
        ? [...prev.storage_policy.raw_periods, period]
        : prev.storage_policy.raw_periods.filter((p) => p !== period)
      return { ...prev, storage_policy: { ...prev.storage_policy, raw_periods: dedupeInOrder(next) } }
    })
  }

  async function save() {
    if (!config || !initialConfig) return
    setSaving(true)
    setMessage(null)
    try {
      const patch = buildPatch(initialConfig, config)
      if (Object.keys(patch).length === 0) {
        setMessage('Nothing changed.')
        return
      }
      const updated = await localApiClient.updateConfig(patch)
      setConfig(updated)
      setInitialConfig(updated)
      setMessage('Settings saved.')
    } catch (err) {
      setMessage(err instanceof Error ? err.message : String(err))
    } finally {
      setSaving(false)
    }
  }

  if (loading) return <p className="text-sm text-slate-500">Loading configuration…</p>
  if (loadError) {
    return (
      <p className="rounded-md border border-red-900 bg-red-950/60 px-3 py-2 text-sm text-red-300">{loadError}</p>
    )
  }
  if (!config) return null

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-center justify-between">
        <h1 className="text-lg font-semibold text-slate-100">Settings</h1>
        <button
          type="button"
          onClick={() => void save()}
          disabled={saving}
          className="rounded-md bg-sky-600 px-4 py-2 text-sm font-medium text-white transition hover:bg-sky-500 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {saving ? 'Saving…' : 'Save changes'}
        </button>
      </div>
      {message ? <p className="text-sm text-slate-400">{message}</p> : null}

      <Section title="Location">
        <Field label="Latitude">
          <NumberInput value={config.location.lat} onChange={(v) => updateLocation('lat', v)} step={0.0001} />
        </Field>
        <Field label="Longitude">
          <NumberInput value={config.location.lon} onChange={(v) => updateLocation('lon', v)} step={0.0001} />
        </Field>
        <Field label="Elevation (m)">
          <NumberInput value={config.location.elevation_m} onChange={(v) => updateLocation('elevation_m', v)} />
        </Field>
        <Field label="Timezone">
          <TextInput value={config.location.timezone} onChange={(v) => updateLocation('timezone', v)} />
        </Field>
      </Section>

      <Section title="Storage policy">
        <Field label="Thumbnail max dimension (px)">
          <NumberInput
            value={config.storage_policy.thumbnail_max_dim}
            onChange={(v) => updateStoragePolicy('thumbnail_max_dim', v)}
          />
        </Field>
        <Field label="JPEG quality">
          <NumberInput
            value={config.storage_policy.jpeg_quality}
            onChange={(v) => updateStoragePolicy('jpeg_quality', v)}
            min={1}
            max={100}
          />
        </Field>
        <Field label="Night capture interval (s)">
          <NumberInput
            value={config.storage_policy.night_capture_interval_s}
            onChange={(v) => updateStoragePolicy('night_capture_interval_s', v)}
          />
        </Field>
        <Field label="Day capture interval (s)">
          <NumberInput
            value={config.storage_policy.day_capture_interval_s}
            onChange={(v) => updateStoragePolicy('day_capture_interval_s', v)}
          />
        </Field>
        <Field label="Realtime stream FPS">
          <NumberInput
            value={config.storage_policy.realtime_stream_fps}
            onChange={(v) => updateStoragePolicy('realtime_stream_fps', v)}
            step={0.1}
          />
        </Field>
        <Field label="Save raw frames during">
          <div className="flex flex-wrap gap-3">
            {SKY_PERIODS.map((period) => (
              <label key={period} className="flex items-center gap-1.5 text-sm text-slate-300">
                <input
                  type="checkbox"
                  checked={config.storage_policy.raw_periods.includes(period)}
                  onChange={(e) => toggleRawPeriod(period, e.target.checked)}
                  className="accent-sky-500"
                />
                {period.replace(/_/g, ' ')}
              </label>
            ))}
          </div>
        </Field>
      </Section>

      <Section title="Retention">
        <Field label="Max age (days)">
          <NumberInput value={config.retention.max_age_days} onChange={(v) => updateRetention('max_age_days', v)} />
        </Field>
        <Field label="Min free space (MB)">
          <NumberInput
            value={config.retention.min_free_space_mb}
            onChange={(v) => updateRetention('min_free_space_mb', v)}
          />
        </Field>
        <Field label="Sweep interval (s)">
          <NumberInput
            value={config.retention.sweep_interval_s}
            onChange={(v) => updateRetention('sweep_interval_s', v)}
          />
        </Field>
      </Section>

      <Section title="Upload">
        <Field label="Enabled">
          <input
            type="checkbox"
            checked={config.upload.enabled}
            onChange={(e) => updateUpload('enabled', e.target.checked)}
            className="accent-sky-500"
          />
        </Field>
        <Field label="Remote host">
          <TextInput value={config.upload.remote_host} onChange={(v) => updateUpload('remote_host', v)} />
        </Field>
        <Field label="Remote user">
          <TextInput value={config.upload.remote_user} onChange={(v) => updateUpload('remote_user', v)} />
        </Field>
        <Field label="Remote base path">
          <TextInput value={config.upload.remote_base_path} onChange={(v) => updateUpload('remote_base_path', v)} />
        </Field>
        <Field label="SSH key path">
          <TextInput value={config.upload.ssh_key_path} onChange={(v) => updateUpload('ssh_key_path', v)} />
        </Field>
        <Field label="Camera slug">
          <TextInput value={config.upload.camera_slug} onChange={(v) => updateUpload('camera_slug', v)} />
        </Field>
        <Field label="Camera name">
          <TextInput value={config.upload.camera_name} onChange={(v) => updateUpload('camera_name', v)} />
        </Field>
        <Field label="Thumbnail interval (s)">
          <NumberInput
            value={config.upload.thumbnail_interval_s}
            onChange={(v) => updateUpload('thumbnail_interval_s', v)}
          />
        </Field>
        <Field label="Reconcile interval (s)">
          <NumberInput
            value={config.upload.reconcile_interval_s}
            onChange={(v) => updateUpload('reconcile_interval_s', v)}
          />
        </Field>
      </Section>
    </div>
  )
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="flex flex-col gap-4 rounded-lg border border-slate-800 bg-slate-900/60 p-4">
      <h2 className="font-medium text-slate-100">{title}</h2>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">{children}</div>
    </section>
  )
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="flex flex-col gap-1 text-sm text-slate-300">
      {label}
      {children}
    </label>
  )
}

function NumberInput({
  value,
  onChange,
  step,
  min,
  max,
}: {
  value: number
  onChange: (value: number) => void
  step?: number
  min?: number
  max?: number
}) {
  return (
    <input
      type="number"
      value={value}
      step={step}
      min={min}
      max={max}
      onChange={(e) => {
        const parsed = Number(e.target.value)
        if (!Number.isNaN(parsed)) onChange(parsed)
      }}
      className="rounded-md border border-slate-700 bg-slate-950 px-3 py-1.5 text-slate-100 focus:border-sky-500 focus:outline-none"
    />
  )
}

function TextInput({ value, onChange }: { value: string; onChange: (value: string) => void }) {
  return (
    <input
      type="text"
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className="rounded-md border border-slate-700 bg-slate-950 px-3 py-1.5 text-slate-100 focus:border-sky-500 focus:outline-none"
    />
  )
}

function dedupeInOrder<T>(values: T[]): T[] {
  return [...new Set(values)]
}

/** Shallow-per-section diff: for each top-level section this page can edit,
 * compares leaf fields and includes only the ones that changed. Good enough
 * for AppConfig's flat-ish sub-objects without pulling in a deep-diff
 * dependency for four known shapes. */
function buildPatch(before: AppConfig, after: AppConfig): DeepPartial<AppConfig> {
  const patch: DeepPartial<AppConfig> = {}

  const location = diffSection(before.location, after.location)
  if (location) patch.location = location

  const storagePolicy = diffSection(before.storage_policy, after.storage_policy, (key, a, b) =>
    key === 'raw_periods' ? JSON.stringify(a) === JSON.stringify(b) : a === b,
  )
  if (storagePolicy) patch.storage_policy = storagePolicy

  const retention = diffSection(before.retention, after.retention)
  if (retention) patch.retention = retention

  const upload = diffSection(before.upload, after.upload)
  if (upload) patch.upload = upload

  return patch
}

function diffSection<T extends object>(
  before: T,
  after: T,
  isEqual: (key: string, a: unknown, b: unknown) => boolean = (_key, a, b) => a === b,
): Partial<T> | undefined {
  const changed: Partial<T> = {}
  let hasChanges = false
  for (const key of Object.keys(after) as (keyof T)[]) {
    if (!isEqual(key as string, before[key], after[key])) {
      changed[key] = after[key]
      hasChanges = true
    }
  }
  return hasChanges ? changed : undefined
}
