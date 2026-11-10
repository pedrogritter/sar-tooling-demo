import type { ComponentProps } from "react"
import { cn } from "cn"

/**
 * A scrolling region for edge panels. The stage stays fixed while this moves.
 */
function ScrollArea({ className, ...props }: ComponentProps<"div">) {
  return (
    <div
      data-slot="scroll-area"
      className={cn("min-h-0 overflow-y-auto", className)}
      {...props}
    />
  )
}

export { ScrollArea }
