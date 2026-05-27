import type { EffectDescriptor } from "@/types/domain"
import { effectTaxonomyPath } from "@/lib/effectTaxonomy"

export type EffectEngineChoice = "auto" | "vapoursynth" | "avisynth"

export type EffectVariantGroup = {
  id: string
  name: string
  category: string
  menu_path?: string[]
  variants: EffectDescriptor[]
}

function groupKey(effect: EffectDescriptor) {
  return `${effectTaxonomyPath(effect).join(" > ").toLowerCase()}::${effect.name.trim().toLowerCase()}`
}

function engineWeight(effect: EffectDescriptor) {
  if (effect.engine === "vapoursynth") return 0
  if (effect.engine === "avisynth") return 1
  return 2
}

export function groupEffectVariants(effects: EffectDescriptor[]) {
  const groups = new Map<string, EffectVariantGroup>()
  for (const effect of effects) {
    const key = groupKey(effect)
    const current = groups.get(key)
    if (current) {
      current.variants.push(effect)
      current.variants.sort((a, b) => engineWeight(a) - engineWeight(b) || a.effect_id.localeCompare(b.effect_id))
    } else {
      groups.set(key, {
        id: key,
        name: effect.name,
        category: effect.category,
        menu_path: effectTaxonomyPath(effect),
        variants: [effect],
      })
    }
  }
  return Array.from(groups.values())
}

export function pickEffectVariant(group: EffectVariantGroup, choice: EffectEngineChoice) {
  if (choice !== "auto") {
    return group.variants.find((variant) => variant.engine === choice) ?? group.variants[0]
  }
  return group.variants.find((variant) => variant.engine === "vapoursynth") ?? group.variants[0]
}
