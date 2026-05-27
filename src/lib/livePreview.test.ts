import { describe, expect, it } from "vitest"

import type { EffectChainItem } from "@/types/domain"
import { buildLivePreview } from "./livePreview"

function effect(overrides: Partial<EffectChainItem>): EffectChainItem {
  return {
    id: "effect-1",
    effect_id: "vs.std.box_blur",
    name: "Box Blur",
    engine: "vapoursynth",
    category: "blur",
    enabled: true,
    parameters: {},
    ...overrides,
  }
}

describe("live preview mapper", () => {
  it("maps enabled blur effects to a visible CSS preview", () => {
    const preview = buildLivePreview([effect({ parameters: { hradius: 4 } })])

    expect(preview.filter).toBe("blur(4px)")
    expect(preview.backdropFilter).toBe("blur(4px)")
    expect(preview.label).toBe("Blur 4px")
    expect(preview.supportedCount).toBe(1)
  })

  it("ignores disabled effects", () => {
    const preview = buildLivePreview([effect({ enabled: false, parameters: { hradius: 4 } })])

    expect(preview.filter).toBe("none")
    expect(preview.supportedCount).toBe(0)
    expect(preview.unsupportedCount).toBe(0)
  })

  it("reports enabled effects without a live preview mapping", () => {
    const preview = buildLivePreview([
      effect({
        effect_id: "vs.knlmeanscl",
        name: "KNLMeansCL Denoise",
        category: "denoise",
      }),
    ])

    expect(preview.filter).toBe("none")
    expect(preview.supportedCount).toBe(0)
    expect(preview.unsupportedCount).toBe(1)
  })
})
