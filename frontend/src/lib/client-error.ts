const REPORT_PATH = "/client-error"

/**
 * Forward browser failures to the Python server, which logs them.
 * The listener is installed once, at startup, outside React render.
 */
export function installClientErrorReporting(): void {
  window.addEventListener("error", (event) => {
    report(event.message, event.filename)
  })

  window.addEventListener("unhandledrejection", (event) => {
    report(reasonMessage(event.reason), "unhandledrejection")
  })
}

function report(message: unknown, source: unknown): void {
  const body = JSON.stringify({
    message: String(message ?? ""),
    source: String(source ?? ""),
  })

  void fetch(REPORT_PATH, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body,
  }).catch(() => undefined)
}

function reasonMessage(reason: unknown): unknown {
  if (reason && typeof reason === "object" && "message" in reason) {
    return reason.message
  }

  return reason
}
