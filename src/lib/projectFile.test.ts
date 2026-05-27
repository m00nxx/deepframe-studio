import { describe, expect, it } from "vitest"

import { parseProjectFile, serializeProjectFile } from "./projectFile"
import { emptyProject } from "@/data"

describe("project file helpers", () => {
  it("serializes readable project json", () => {
    const json = serializeProjectFile({ ...emptyProject, media_path: "C:/video.mp4" })

    expect(json).toContain('"media_path": "C:/video.mp4"')
    expect(json.endsWith("\n")).toBe(true)
  })

  it("parses and normalizes missing optional project fields", () => {
    const project = parseProjectFile(JSON.stringify({ media_path: "clip.mp4", in_point: 1 }))

    expect(project.media_path).toBe("clip.mp4")
    expect(project.in_point).toBe(1)
    expect(project.effect_chain).toEqual([])
    expect(project.output_settings.output_path).toBe("output.mp4")
  })

  it("rejects invalid project json", () => {
    expect(() => parseProjectFile("{bad")).toThrow("Invalid project JSON")
  })

  it("rejects non-object project roots", () => {
    expect(() => parseProjectFile("[]")).toThrow("Project file must contain an object")
  })

  it("normalizes null objects and non-array collections", () => {
    const project = parseProjectFile(
      JSON.stringify({
        media_path: null,
        metadata_cache: null,
        segments: "bad",
        effect_chain: null,
        output_settings: null,
      }),
    )

    expect(project.media_path).toBe("")
    expect(project.metadata_cache).toEqual({})
    expect(project.segments).toEqual([])
    expect(project.effect_chain).toEqual([])
    expect(project.output_settings.video_codec).toBe("copy")
  })

  it("normalizes nested metadata, segments and effect chain values", () => {
    const project = parseProjectFile(
      JSON.stringify({
        metadata_cache: {
          format: { duration: "12.5", format_name: 123 },
          streams: "bad",
        },
        segments: [{ id: 7, name: null, start: 1, end: "bad" }, null],
        effect_chain: [
          {
            id: null,
            effect_id: "vs.test",
            name: "Test",
            engine: "bad",
            category: null,
            enabled: "yes",
            parameters: { strength: 1.2, nested: {}, enabled: false },
          },
        ],
      }),
    )

    expect(project.metadata_cache.format?.duration).toBe("12.5")
    expect(project.metadata_cache.format?.format_name).toBeUndefined()
    expect(project.metadata_cache.streams).toBeUndefined()
    expect(project.segments).toEqual([{ id: "segment-1", name: "Segment 1", start: 1, end: 1 }])
    expect(project.effect_chain[0]).toMatchObject({
      id: "effect-1",
      engine: "vapoursynth",
      category: "custom",
      enabled: true,
      parameters: { strength: 1.2, enabled: false },
    })
  })
})
