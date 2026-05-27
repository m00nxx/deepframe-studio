import type { EffectChainItem } from "@/types/domain"

export type LivePreview = {
  filter: string
  backdropFilter: string
  label: string
  supportedCount: number
  unsupportedCount: number
}

function numericParameter(effect: EffectChainItem, names: string[], fallback: number) {
  for (const name of names) {
    const value = effect.parameters[name]
    const numberValue = typeof value === "number" ? value : typeof value === "string" ? Number(value) : Number.NaN
    if (Number.isFinite(numberValue)) return numberValue
  }
  return fallback
}

function clamp(value: number, min: number, max: number) {
  return Math.min(Math.max(value, min), max)
}

function formatPixelValue(value: number) {
  return Number.isInteger(value) ? String(value) : value.toFixed(1).replace(/\.0$/, "")
}

function isBlurEffect(effect: EffectChainItem) {
  const text = `${effect.effect_id} ${effect.name} ${effect.category}`.toLowerCase()
  return text.includes("blur")
}

export function buildLivePreview(chain: EffectChainItem[]): LivePreview {
  const filters: string[] = []
  const labels: string[] = []
  let supportedCount = 0
  let unsupportedCount = 0

  for (const effect of chain) {
    if (!effect.enabled) continue

    if (isBlurEffect(effect)) {
      const radius = clamp(numericParameter(effect, ["hradius", "radius", "strength", "amount"], 1), 0, 24)
      const pixelValue = formatPixelValue(radius)
      filters.push(`blur(${pixelValue}px)`)
      labels.push(`Blur ${pixelValue}px`)
      supportedCount += 1
      continue
    }

    unsupportedCount += 1
  }

  const filter = filters.length ? filters.join(" ") : "none"

  return {
    filter,
    backdropFilter: filter,
    label: labels.join(" + "),
    supportedCount,
    unsupportedCount,
  }
}
