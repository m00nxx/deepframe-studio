import { describe, expect, it } from "vitest"

import type { EffectDescriptor } from "@/types/domain"
import { canAddEffectToChain, isEffectRenderable } from "./effectRenderability"

function effect(overrides: Partial<EffectDescriptor> = {}): EffectDescriptor {
  return {
    effect_id: "vs.test",
    name: "Test",
    engine: "vapoursynth",
    category: "test",
    description: "",
    recommended: false,
    install_status: "installed",
    ...overrides,
  }
}

describe("effect renderability", () => {
  it("treats catalog effects as addable unless explicitly marked non renderable", () => {
    expect(canAddEffectToChain(effect())).toBe(true)
    expect(canAddEffectToChain(effect({ renderable: true }))).toBe(true)
    expect(canAddEffectToChain(effect({ render_status: "renderable" }))).toBe(true)
  })

  it("blocks effects marked with renderable=false or non-renderable render statuses", () => {
    expect(isEffectRenderable(effect({ renderable: false }))).toBe(false)
    expect(canAddEffectToChain(effect({ render_status: "not_renderable" }))).toBe(false)
    expect(canAddEffectToChain(effect({ render_status: "metadata_only" }))).toBe(false)
    expect(canAddEffectToChain(effect({ render_status: "missing_runtime" }))).toBe(false)
  })
})
