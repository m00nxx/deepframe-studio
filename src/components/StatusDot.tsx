import { cn } from "@/lib/utils"

type StatusDotProps = {
  state: "ready" | "warning" | "offline"
}

export function StatusDot({ state }: StatusDotProps) {
  return (
    <span
      className={cn(
        "size-2 rounded-full",
        state === "ready" && "bg-emerald-400",
        state === "warning" && "bg-amber-400",
        state === "offline" && "bg-zinc-500",
      )}
    />
  )
}
