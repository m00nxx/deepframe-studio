import type { EffectDescriptor } from "@/types/domain"

export type EffectTaxonomySource = Pick<EffectDescriptor, "category" | "menu_path">

const LEGACY_CATEGORY_PATHS: Record<string, string[]> = {
  "artifact removal": ["Restoration", "Artifact Removal"],
  blur: ["Misc", "Blur"],
  color: ["Color", "General"],
  custom: ["Custom"],
  deband: ["Restoration", "Deband"],
  degrain: ["Noise", "DeGrain"],
  deinterlace: ["Field", "Deinterlace"],
  denoise: ["Noise", "Denoise"],
  encode: ["Misc", "Encode"],
  "face restore": ["Restoration", "Face Restore"],
  "frame interpolation": ["Frame Rate", "Interpolation"],
  repair: ["Restoration", "Repair"],
  resize: ["Resize", "General"],
  sharpen: ["Restoration", "Sharpen"],
  stabilize: ["Misc", "Stabilize"],
  upscale: ["Resize", "Upscale"],
}

const PRIMARY_LABELS: Record<string, string> = {
  color: "Color",
  crop: "Crop",
  custom: "Custom",
  field: "Field",
  flip: "Flip",
  "frame rate": "Frame Rate",
  line: "Line",
  misc: "Misc",
  new2: "New2",
  new3: "New3",
  noise: "Noise",
  resize: "Resize",
  restoration: "Restoration",
  rotation: "Rotation",
  source: "Source",
}

function normalizedParts(effect: EffectTaxonomySource) {
  const raw = effect.menu_path?.length ? effect.menu_path : LEGACY_CATEGORY_PATHS[effect.category.trim().toLowerCase()] ?? [effect.category]
  return raw.map((part) => part.trim()).filter(Boolean)
}

export function effectTaxonomyPath(effect: EffectTaxonomySource) {
  const path = normalizedParts(effect)
  if (!path.length) return []
  return [PRIMARY_LABELS[path[0].toLowerCase()] ?? path[0], ...path.slice(1)]
}

export function effectTaxonomyId(path: string[]) {
  return path.join(" > ")
}

export function formatTaxonomyLabel(value: string) {
  return value
    .replace(/\bavsynth\b/i, "AviSynth")
    .replace(/\bvapoursynth\b/i, "VapourSynth")
}
