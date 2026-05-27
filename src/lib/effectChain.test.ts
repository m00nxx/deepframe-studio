import { describe, expect, it } from "vitest"

import type { EffectChainItem } from "@/types/domain"
import { moveChainItem, removeChainItem, toggleChainItem, updateChainParameter } from "./effectChain"

function chain(ids: string[]): EffectChainItem[] {
  return ids.map((id) => ({
    id,
    effect_id: `effect-${id}`,
    name: `Effect ${id}`,
    engine: "vapoursynth",
    category: "denoise",
    enabled: true,
    parameters: {},
  }))
}

describe("effect chain helpers", () => {
  it("removes an effect without mutating the source chain", () => {
    const source = chain(["a", "b", "c"])

    const next = removeChainItem(source, "b")

    expect(next.map((item) => item.id)).toEqual(["a", "c"])
    expect(source.map((item) => item.id)).toEqual(["a", "b", "c"])
  })

  it("toggles a single effect enabled state", () => {
    const source = chain(["a", "b"])

    const next = toggleChainItem(source, "b")

    expect(next.find((item) => item.id === "a")?.enabled).toBe(true)
    expect(next.find((item) => item.id === "b")?.enabled).toBe(false)
  })

  it("moves a dragged effect to the target position", () => {
    const source = chain(["a", "b", "c", "d"])

    const next = moveChainItem(source, "a", "c")

    expect(next.map((item) => item.id)).toEqual(["b", "c", "a", "d"])
  })

  it("updates one parameter without mutating other effects", () => {
    const source = chain(["a", "b"])

    const next = updateChainParameter(source, "b", "strength", 2.4)

    expect(next.find((item) => item.id === "a")?.parameters).toEqual({})
    expect(next.find((item) => item.id === "b")?.parameters).toEqual({ strength: 2.4 })
    expect(source.find((item) => item.id === "b")?.parameters).toEqual({})
  })
})
