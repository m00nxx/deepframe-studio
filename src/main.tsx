import React, { Component, type ErrorInfo, type ReactNode } from "react"
import ReactDOM from "react-dom/client"

import { App } from "@/App"
import "@/styles.css"

type BootErrorBoundaryState = {
  error: Error | null
}

class BootErrorBoundary extends Component<{ children: ReactNode }, BootErrorBoundaryState> {
  state: BootErrorBoundaryState = { error: null }

  static getDerivedStateFromError(error: Error): BootErrorBoundaryState {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("DeepFrame render failed", error, info)
  }

  render() {
    if (this.state.error) {
      return (
        <main className="grid h-full place-items-center bg-background p-6 text-foreground">
          <div className="max-w-3xl rounded-md border border-red-500/30 bg-red-500/10 p-4">
            <h1 className="text-sm font-semibold text-red-100">DeepFrame Studio failed to render.</h1>
            <pre className="mt-3 whitespace-pre-wrap text-xs text-red-200">{this.state.error.stack ?? this.state.error.message}</pre>
          </div>
        </main>
      )
    }

    return this.props.children
  }
}

const root = document.getElementById("root")
if (!root) {
  throw new Error("DeepFrame root element is missing")
}

ReactDOM.createRoot(root).render(
  <React.StrictMode>
    <BootErrorBoundary>
      <App />
    </BootErrorBoundary>
  </React.StrictMode>,
)
