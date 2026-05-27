import { describe, expect, it } from "vitest"

import { createMediaPreviewSource } from "./mediaPreview"

describe("createMediaPreviewSource", () => {
  it("returns null without media or outside the desktop shell when no backend URL builder exists", async () => {
    const convertFileSrc = (path: string) => `asset://${path}`

    await expect(createMediaPreviewSource("", { isDesktop: true, convertFileSrc })).resolves.toBeNull()
    await expect(createMediaPreviewSource("C:/clip.mp4", { isDesktop: false, convertFileSrc })).resolves.toBeNull()
  })

  it("uses the backend media URL when available", async () => {
    const convertFileSrc = (path: string) => `asset://${path}`

    await expect(
      createMediaPreviewSource("C:/clip.mp4", {
        isDesktop: false,
        convertFileSrc,
        mediaFileUrl: async (path) => `http://127.0.0.1:8765/media/file?path=${encodeURIComponent(path)}`,
      }),
    ).resolves.toBe("http://127.0.0.1:8765/media/file?path=C%3A%2Fclip.mp4")
  })

  it("prefers the desktop asset URL over the backend URL inside the desktop shell", async () => {
    const convertFileSrc = (path: string) => `asset://${path}`

    await expect(
      createMediaPreviewSource("C:/clip.mp4", {
        isDesktop: true,
        allowPreviewFile: async () => undefined,
        convertFileSrc,
        mediaFileUrl: async (path) => `http://127.0.0.1:8765/media/file?path=${encodeURIComponent(path)}`,
      }),
    ).resolves.toBe("asset://C:/clip.mp4")
  })

  it("allows and returns a converted asset URL inside the desktop shell", async () => {
    const convertFileSrc = (path: string) => `asset://${path}`
    const allowed: string[] = []

    await expect(
      createMediaPreviewSource(" C:/clips/source video.mp4 ", {
        isDesktop: true,
        allowPreviewFile: async (path) => allowed.push(path),
        convertFileSrc,
      }),
    ).resolves.toBe(
      "asset://C:/clips/source video.mp4",
    )
    expect(allowed).toEqual(["C:/clips/source video.mp4"])
  })

  it("falls back to null if conversion fails", async () => {
    await expect(
      createMediaPreviewSource("C:/clip.mp4", {
        isDesktop: true,
        convertFileSrc: () => {
          throw new Error("asset protocol unavailable")
        },
      }),
    ).resolves.toBeNull()
  })
})
