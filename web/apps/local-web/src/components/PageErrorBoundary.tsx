import { Component, type ErrorInfo, type ReactNode } from 'react'
import { useLocation } from 'react-router-dom'
import { Message } from '@caelum/ui'

interface State {
  error: Error | null
}

class Boundary extends Component<{ children: ReactNode }, State> {
  state: State = { error: null }

  static getDerivedStateFromError(error: Error): State {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('Page failed to render', error, info.componentStack)
  }

  render() {
    if (this.state.error) {
      return (
        <Message kind="error">
          This page failed to render: {this.state.error.message}. The rest of the interface still works — this is
          usually the web UI and the camera software being out of step after an update.
        </Message>
      )
    }
    return this.props.children
  }
}

/**
 * Without a boundary, one exception while rendering any page unmounts the
 * whole app and leaves a blank screen — sidebar and all. Keyed on the
 * route, so navigating to another page clears the error.
 */
export function PageErrorBoundary({ children }: { children: ReactNode }) {
  const location = useLocation()
  return <Boundary key={location.pathname}>{children}</Boundary>
}
