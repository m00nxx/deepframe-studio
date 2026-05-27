import type { EffectDescriptor } from "@/types/domain"

const RENDERABLE_STATUSES = new Set(["renderable", "ok", "supported"])

function normalizeRenderStatus(status: string) {
  return status.trim().toLowerCase().replace(/[-\s]+/g, "_")
}

export function isEffectRenderable(effect: Pick<EffectDescriptor, "renderable" | "render_status">) {
  if (effect.renderable === false) return false
  if (!effect.render_status) return true

  return RENDERABLE_STATUSES.has(normalizeRenderStatus(effect.render_status))
}

export function canAddEffectToChain(effect: Pick<EffectDescriptor, "renderable" | "render_status">) {
  return isEffectRenderable(effect)
}
