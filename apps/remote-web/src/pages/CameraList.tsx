import { useNavigate } from 'react-router-dom'
import { CameraCard } from '@caelum/ui'
import { useCameras } from '../hooks/useCameras.ts'
import { remoteApiClient } from '../services/client.ts'

export function CameraList() {
  const { cameras, error, loading } = useCameras()
  const navigate = useNavigate()

  if (loading) return <p className="text-sm text-slate-500">Loading cameras…</p>
  if (error) {
    return <p className="rounded-md border border-red-900 bg-red-950/60 px-3 py-2 text-sm text-red-300">{error}</p>
  }
  if (!cameras || cameras.cameras.length === 0) {
    return <p className="text-sm text-slate-500">No cameras published yet.</p>
  }

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-center justify-between">
        <h1 className="text-lg font-semibold text-slate-100">Cameras</h1>
        <span className="text-xs text-slate-500">
          Updated {new Date(cameras.updated_at).toLocaleString()}
        </span>
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
