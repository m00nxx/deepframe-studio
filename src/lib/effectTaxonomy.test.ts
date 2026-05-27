import { describe, expect, it } from "vitest"

import { effectTaxonomyPath } from "@/lib/effectTaxonomy"

describe("effect taxonomy", () => {
  it("maps legacy singleton categories into the StaxRip-style tree", () => {
    expect(effectTaxonomyPath({ category: "upscale" })).toEqual(["Resize", "Upscale"])
    expect(effectTaxonomyPath({ category: "stabilize" })).toEqual(["Misc", "Stabilize"])
    expect(effectTaxonomyPath({ category: "sharpen" })).toEqual(["Restoration", "Sharpen"])
    expect(effectTaxonomyPath({ category: "deinterlace" })).toEqual(["Field", "Deinterlace"])
  })

  it("normalizes primary category casing without changing deeper menu levels", () => {
    expect(effectTaxonomyPath({ category: "resize", menu_path: ["resize", "advanced"] })).toEqual(["Resize", "advanced"])
    expect(effectTaxonomyPath({ category: "new3", menu_path: ["new3", "repair", "dfmderainbow"] })).toEqual([
      "New3",
      "repair",
      "dfmderainbow",
    ])
  })
})
