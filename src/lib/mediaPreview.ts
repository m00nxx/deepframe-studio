export type MediaPreviewOptions = {
  isDesktop: boolean
  allowPreviewFile?: (path: string) => Promise<unknown>
  convertFileSrc: (path: string) => string
  mediaFileUrl?: (path: string) => Promise<string>
}

export async function createMediaPreviewSource(mediaPath: string, options: MediaPreviewOptions) {
  const normalizedPath = mediaPath.trim()
  if (!normalizedPath) return null

  if (options.isDesktop) {
    try {
      await options.allowPreviewFile?.(normalizedPath)
      return options.convertFileSrc(normalizedPath)
    } catch {
      if (!options.mediaFileUrl) return null
    }
  }

  return options.mediaFileUrl ? options.mediaFileUrl(normalizedPath) : null
}
