import { describe, expect, it } from "vitest"

import { formatCommandForShell } from "./commandFormat"

describe("formatCommandForShell", () => {
  it("quotes paths with spaces without changing argv semantics", () => {
    expect(formatCommandForShell(["ffmpeg", "-i", "/tmp/in video.mp4", "/tmp/out video.mp4"])).toBe(
      'ffmpeg -i "/tmp/in video.mp4" "/tmp/out video.mp4"',
    )
  })

  it("escapes quotes and backslashes", () => {
    expect(formatCommandForShell(["ffmpeg", 'C:\\clips\\a "quote".mp4'])).toBe('ffmpeg "C:\\\\clips\\\\a \\"quote\\".mp4"')
  })
})
