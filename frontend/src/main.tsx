import { StrictMode } from "react"
import { createRoot } from "react-dom/client"

import { ThemeProvider } from "@/components/theme-provider"
import { installClientErrorReporting } from "@/lib/client-error"
import App from "@/App"

import "./index.css"

installClientErrorReporting()

const root = document.getElementById("root")

if (!root) {
  throw new Error("Missing #root")
}

createRoot(root).render(
  <StrictMode>
    <ThemeProvider defaultTheme="dark">
      <App />
    </ThemeProvider>
  </StrictMode>
)
