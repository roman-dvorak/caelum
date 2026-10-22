import { useNavigate } from 'react-router-dom'
import { CameraCard, Message, PageHeader } from '@caelum/ui'
import { useCameras } from '../hooks/useCameras.ts'
import { remoteApiClient } from '../services/client.ts'

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
          <CameraCard
            key={camera.slug}
            camera={camera}
            thumbnailUrl={camera.latest_thumbnail ? remoteApiClient.resolveUrl(camera.latest_thumbnail) : null}
            onClick={() => navigate(`/camera/${camera.slug}`)}
          />
        ))}
      </div>
    </div>
  )
}
