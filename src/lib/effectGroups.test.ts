import { describe, expect, it } from "vitest"

import { groupEffectVariants, pickEffectVariant } from "@/lib/effectGroups"
import type { EffectDescriptor } from "@/types/domain"

function effect(overrides: Partial<EffectDescriptor>): EffectDescriptor {
  return {
    effect_id: overrides.effect_id ?? `effect.${overrides.engine ?? "vapoursynth"}.${overrides.name ?? "test"}`,
    name: overrides.name ?? "Crop",
    engine: overrides.engine ?? "vapoursynth",
    category: overrides.category ?? "Crop",
    description: "",
    recommended: false,
    install_status: "installed",
    menu_path: overrides.menu_path ?? ["Crop"],
    ...overrides,
  }
}

describe("effect grouping", () => {
  it("groups AviSynth and VapourSynth variants with the same menu path and name", () => {
    const groups = groupEffectVariants([
      effect({ effect_id: "avs.crop", engine: "avisynth", name: "Crop", menu_path: ["Crop"] }),
      effect({ effect_id: "vs.crop", engine: "vapoursynth", name: "Crop", menu_path: ["Crop"] }),
      effect({ effect_id: "avs.tweak", engine: "avisynth", name: "Tweak", menu_path: ["Color", "ColorYUV"] }),
    ])

    expect(groups).toHaveLength(2)
    expect(groups[0].name).toBe("Crop")
    expect(groups[0].variants.map((variant) => variant.engine)).toEqual(["vapoursynth", "avisynth"])
  })

  it("uses VapourSynth for auto when available", () => {
    const group = groupEffectVariants([
      effect({ effect_id: "avs.crop", engine: "avisynth", name: "Crop" }),
      effect({ effect_id: "vs.crop", engine: "vapoursynth", name: "Crop" }),
    ])[0]

    expect(pickEffectVariant(group, "auto")?.effect_id).toBe("vs.crop")
    expect(pickEffectVariant(group, "avisynth")?.effect_id).toBe("avs.crop")
  })
})
