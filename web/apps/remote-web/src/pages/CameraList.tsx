import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import type { CameraSummary } from '@caelum/api-client'
import { CameraCard, Message, PageHeader } from '@caelum/ui'
import { useCameras } from '../hooks/useCameras.ts'
import { remoteApiClient } from '../services/client.ts'

/** cameras.json only carries static catalog data, so the newest thumbnail
 * comes from the camera's own manifest. */
function CameraEntry({ camera, onClick }: { camera: CameraSummary; onClick: () => void }) {
  const [thumbnailUrl, setThumbnailUrl] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    remoteApiClient
      .getCameraManifest(camera.slug)
      .then((manifest) => {
        const latest = manifest.dates[manifest.dates.length - 1]?.latest_thumbnail
        if (!cancelled && latest) setThumbnailUrl(remoteApiClient.resolveCameraUrl(camera.slug, latest))
      })
      .catch(() => {})
    return () => {
      cancelled = true
    }
  }, [camera.slug])

  return <CameraCard camera={camera} thumbnailUrl={thumbnailUrl} onClick={onClick} />
}

export function CameraList() {
  const { cameras, error, loading } = useCameras()
  const navigate = useNavigate()

  if (loading) return <p className="text-sm text-ink-muted">Loading cameras…</p>
  if (error) {
    return <Message kind="error">{error}</Message>
  }
  if (!cameras || cameras.cameras.length === 0) {
    return <p className="text-sm text-ink-muted">No cameras published yet.</p>
  }

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Cameras"
        actions={<span className="font-mono text-code-sm text-ink-muted">Updated {new Date(cameras.updated_at).toLocaleString()}</span>}
      />
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {cameras.cameras.map((camera) => (
          <CameraEntry key={camera.slug} camera={camera} onClick={() => navigate(`/camera/${camera.slug}`)} />
        ))}
      </div>
    </div>
  )
}
