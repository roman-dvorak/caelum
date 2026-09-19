import { useNavigate } from 'react-router-dom'
import { CameraCard } from '@caelum/ui'
import { useCameras } from '../hooks/useCameras.ts'
import { remoteApiClient } from '../services/client.ts'

export function CameraList() {
  const { cameras, error, loading } = useCameras()
  const navigate = useNavigate()

  if (loading) return <p className="text-sm text-ink-faint">Loading cameras…</p>
  if (error) {
    return <p className="border border-danger/40 bg-danger/10 px-3 py-2 text-sm text-danger">{error}</p>
  }
  if (!cameras || cameras.cameras.length === 0) {
    return <p className="text-sm text-ink-faint">No cameras published yet.</p>
  }

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-center justify-between">
        <h1 className="text-sm font-semibold tracking-[0.2em] text-ink-dim uppercase">Cameras</h1>
        <span className="text-xs text-ink-faint">Updated {new Date(cameras.updated_at).toLocaleString()}</span>
      </div>
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
