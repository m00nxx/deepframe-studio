import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type DragEvent,
  type PointerEvent as ReactPointerEvent,
} from "react"
import { convertFileSrc, invoke, isTauri } from "@tauri-apps/api/core"
import {
  Activity,
  AlertCircle,
  Braces,
  Check,
  Copy,
  Eye,
  FileVideo,
  FolderOpen,
  GripVertical,
  ListFilter,
  Pause,
  Play,
  Plus,
  Save,
  Scissors,
  Search,
  Settings,
  SquareSplitHorizontal,
  Wand2,
  X,
} from "lucide-react"

import { StatusDot } from "@/components/StatusDot"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogDescription, DialogTitle, DialogTrigger } from "@/components/ui/dialog"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { emptyProject, fallbackEffects } from "@/data"
import { formatCommandForShell } from "@/lib/commandFormat"
import { moveChainItem, removeChainItem, toggleChainItem, updateChainParameter } from "@/lib/effectChain"
import { canAddEffectToChain, isEffectRenderable } from "@/lib/effectRenderability"
import { buildLivePreview } from "@/lib/livePreview"
import { createMediaPreviewSource } from "@/lib/mediaPreview"
import { parseProjectFile, serializeProjectFile } from "@/lib/projectFile"
import { cn, compactMiddle, formatSeconds } from "@/lib/utils"
import { groupEffectVariants, pickEffectVariant, type EffectEngineChoice } from "@/lib/effectGroups"
import { api } from "@/services/api"
import { pickExportPath, pickProjectPathForOpen, pickProjectPathForSave, pickVideoPath } from "@/services/dialogs"
import { readProjectFile, writeProjectFile } from "@/services/projectStorage"
import type {
  EffectChainItem,
  EffectDescriptor,
  EffectParameter,
  ExportJobStatus,
  FrameCacheResult,
  MediaMetadata,
  ProjectState,
  ToolStatus,
} from "@/types/domain"

type BackendState = "ready" | "warning" | "offline"
type CompareMode = "original" | "processed" | "split"
type EffectQuickFilter = "usable" | "all" | "recommended" | "installed" | "missing" | "vapoursynth" | "avisynth"
type FrameCacheView = FrameCacheResult & { urls: string[] }
type UiPrefs = {
  selectedCategory: string
  selectedSubcategory: string
  quickFilter: EffectQuickFilter
}

type EffectTaxonomyNode = {
  id: string
  label: string
  count: number
}

const UI_PREFS_KEY = "deepframe.ui.v2"
const AUTO_PARAMETER_VALUE = "__deepframe_auto__"
const COMPARE_MODES: Array<{ id: CompareMode; label: string }> = [
  { id: "original", label: "Original" },
  { id: "processed", label: "Processed" },
  { id: "split", label: "Split" },
]
const EFFECT_QUICK_FILTERS = ["usable", "all", "recommended", "installed", "missing", "vapoursynth", "avisynth"] as const
const TERMINAL_EXPORT_STATES = new Set(["completed", "failed", "canceled"])

function isEffectQuickFilter(value: unknown): value is EffectQuickFilter {
  return typeof value === "string" && EFFECT_QUICK_FILTERS.includes(value as EffectQuickFilter)
}

function loadUiPrefs(): Partial<UiPrefs> {
  try {
    const parsed = JSON.parse(window.localStorage.getItem(UI_PREFS_KEY) ?? "{}") as Record<string, unknown>
    return {
      quickFilter: isEffectQuickFilter(parsed.quickFilter) ? parsed.quickFilter : undefined,
      selectedCategory: typeof parsed.selectedCategory === "string" ? parsed.selectedCategory : undefined,
      selectedSubcategory: typeof parsed.selectedSubcategory === "string" ? parsed.selectedSubcategory : undefined,
    }
  } catch {
    return {}
  }
}

function isEditableTarget(target: EventTarget | null) {
  if (!(target instanceof HTMLElement)) return false
  const tagName = target.tagName.toLowerCase()
  return tagName === "input" || tagName === "textarea" || tagName === "select" || target.isContentEditable
}

function metadataDuration(metadata: MediaMetadata) {
  const raw = metadata.format?.duration
  const value = raw ? Number.parseFloat(raw) : 0
  return Number.isFinite(value) ? value : 0
}

function metadataSummary(metadata: MediaMetadata) {
  const video = metadata.streams?.find((stream) => stream.codec_type === "video")
  const audio = metadata.streams?.find((stream) => stream.codec_type === "audio")
  return {
    duration: metadataDuration(metadata),
    format: metadata.format?.format_name ?? "unknown",
    video: video ? `${video.codec_name ?? "video"} ${video.width ?? "?"}x${video.height ?? "?"}` : "no video",
    audio: audio?.codec_name ?? "no audio",
  }
}

function fillTemplate(template: string | undefined, values: Record<string, string | number | boolean> = {}) {
  const rendered = Object.entries(values).reduce(
    (result, [key, value]) => result.replaceAll(`{${key}}`, String(value)),
    template ?? "",
  )
  return removeAutoArguments(rendered)
}

function removeAutoArguments(script: string) {
  const auto = AUTO_PARAMETER_VALUE.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")
  const valuePattern = `(?:r?['"])?${auto}(?:['"])?`
  return script
    .replace(new RegExp(`,\\s*[A-Za-z_][A-Za-z0-9_]*\\s*=\\s*${valuePattern}`, "g"), "")
    .replace(new RegExp(`\\(\\s*[A-Za-z_][A-Za-z0-9_]*\\s*=\\s*${valuePattern}\\s*,\\s*`, "g"), "(")
    .replace(new RegExp(`\\(\\s*[A-Za-z_][A-Za-z0-9_]*\\s*=\\s*${valuePattern}\\s*\\)`, "g"), "()")
}

function effectTaxonomyPath(effect: Pick<EffectDescriptor, "category" | "menu_path">) {
  const path = effect.menu_path?.length ? effect.menu_path : [effect.category]
  return path.map((part) => part.trim()).filter(Boolean)
}

function effectTaxonomyId(path: string[]) {
  return path.join(" > ")
}

function formatTaxonomyLabel(value: string) {
  return value
    .replace(/\bavsynth\b/i, "AviSynth")
    .replace(/\bvapoursynth\b/i, "VapourSynth")
}

function compactScriptForDisplay(script: string) {
  const lines = script.split(/\r?\n/)
  const compacted: string[] = []
  let hiddenLoads = 0
  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index]
    if (line.startsWith("def _deepframe_load_plugin")) {
      while (index + 1 < lines.length && !lines[index + 1].startsWith("_deepframe_load_plugin(")) index += 1
      continue
    }
    if (line.startsWith("_deepframe_load_plugin(")) {
      hiddenLoads += 1
      continue
    }
    if (line.trim() === "try {" && lines[index + 1]?.includes("LoadPlugin(")) {
      hiddenLoads += 1
      index += 3
      continue
    }
    compacted.push(line)
  }
  const output = compacted.join("\n").trim()
  return hiddenLoads ? `# DeepFrame autoloaded ${hiddenLoads} bundled plugin candidates.\n${output}\n` : script
}

function effectMatchesQuickFilter(effect: EffectDescriptor, quickFilter: EffectQuickFilter) {
  return (
    (quickFilter === "usable" && canAddEffectToChain(effect)) ||
    quickFilter === "all" ||
    (quickFilter === "recommended" && effect.recommended && isEffectRenderable(effect)) ||
    (quickFilter === "installed" && effect.install_status === "installed" && isEffectRenderable(effect)) ||
    (quickFilter === "missing" && !isEffectRenderable(effect)) ||
    ((quickFilter === "vapoursynth" || quickFilter === "avisynth") &&
      effect.engine === quickFilter &&
      isEffectRenderable(effect))
  )
}

function effectMatchesSearch(effect: EffectDescriptor, needle: string) {
  if (!needle) return true
  return [
    effect.name,
    effect.engine,
    effect.category,
    effect.install_status,
    effect.install_policy,
    effect.render_status,
    effect.license_status,
    effect.description,
    effect.cpu_gpu_notes,
    effect.license_notes,
    effect.source_url,
    effect.origin,
    ...(effect.menu_path ?? []),
    ...(effect.required_plugins ?? []),
  ]
    .join(" ")
    .toLowerCase()
    .includes(needle)
}

function parameterStep(parameter: EffectParameter) {
  if (parameter.step) return parameter.step
  return parameter.type === "int" ? 1 : 0.1
}

function parameterValue(
  item: EffectChainItem,
  descriptor: EffectDescriptor | undefined,
  parameter: EffectParameter,
) {
  return item.parameters[parameter.name] ?? descriptor?.defaults?.[parameter.name] ?? parameter.default ?? ""
}

function isAutoParameterValue(value: unknown) {
  return value === AUTO_PARAMETER_VALUE
}

function parameterSuggestedValue(parameter: EffectParameter) {
  if (parameter.suggested !== undefined) return parameter.suggested
  if (parameter.type === "bool") return false
  if (parameter.type === "string") return ""
  if (typeof parameter.min === "number" && typeof parameter.max === "number") {
    const midpoint = (parameter.min + parameter.max) / 2
    return parameter.type === "int" ? Math.trunc(midpoint) : midpoint
  }
  return parameter.type === "int" ? 0 : 0
}

function coerceParameterValue(parameter: EffectParameter, value: string | boolean) {
  if (value === AUTO_PARAMETER_VALUE) return AUTO_PARAMETER_VALUE
  if (parameter.type === "bool") return Boolean(value)
  if (parameter.type === "int" || parameter.type === "float") {
    const numberValue = Number(value)
    if (!Number.isFinite(numberValue)) return parameter.default ?? 0
    return parameter.type === "int" ? Math.trunc(numberValue) : numberValue
  }
  return String(value)
}

function clamp(value: number, min: number, max: number) {
  return Math.min(Math.max(value, min), max)
}

function frameCacheUrlAt(cache: FrameCacheView, absoluteTime: number, cacheStart: number) {
  if (!cache.urls.length) return null
  const relativeTime = Math.max(0, absoluteTime - cacheStart)
  const index = clamp(Math.floor(relativeTime * cache.fps), 0, cache.urls.length - 1)
  return cache.urls[index]
}

export function App() {
  const initialUiPrefs = useMemo(loadUiPrefs, [])
  const scriptRequestId = useRef(0)
  const frameRequestId = useRef(0)
  const frameFetchInFlight = useRef(false)
  const framePlaybackRaf = useRef<number | null>(null)
  const splitSweepRaf = useRef<number | null>(null)
  const previewTimeRef = useRef(0)
  const originalVideoRef = useRef<HTMLVideoElement>(null)
  const processedVideoRef = useRef<HTMLVideoElement>(null)
  const [project, setProject] = useState<ProjectState>(emptyProject)
  const [effects, setEffects] = useState<EffectDescriptor[]>(fallbackEffects)
  const [query, setQuery] = useState("")
  const [backendState, setBackendState] = useState<BackendState>("offline")
  const [tools, setTools] = useState<ToolStatus[]>([])
  const [logs, setLogs] = useState<string[]>([])
  const [lastError, setLastError] = useState("")
  const [projectPath, setProjectPath] = useState("")
  const [script, setScript] = useState("# Load media and add effects to preview generated scripts.")
  const [scriptValidation, setScriptValidation] = useState("")
  const [isValidatingScript, setIsValidatingScript] = useState(false)
  const [commandPreview, setCommandPreview] = useState<string[]>([])
  const [previewSource, setPreviewSource] = useState<string | null>(null)
  const [renderedPreviewSource, setRenderedPreviewSource] = useState<string | null>(null)
  const [renderedPreviewPath, setRenderedPreviewPath] = useState("")
  const [renderedPreviewStart, setRenderedPreviewStart] = useState(0)
  const [browserPreviewSource, setBrowserPreviewSource] = useState(false)
  const [isRenderingPreview, setIsRenderingPreview] = useState(false)
  const [isGeneratingBrowserPreview, setIsGeneratingBrowserPreview] = useState(false)
  const [thumbnailSource, setThumbnailSource] = useState<string | null>(null)
  const [originalFrameSource, setOriginalFrameSource] = useState<string | null>(null)
  const [processedFrameSource, setProcessedFrameSource] = useState<string | null>(null)
  const [sourceFrameCache, setSourceFrameCache] = useState<FrameCacheView | null>(null)
  const [processedFrameCache, setProcessedFrameCache] = useState<FrameCacheView | null>(null)
  const [previewPlaybackFailed, setPreviewPlaybackFailed] = useState(false)
  const [isPreviewPlaying, setIsPreviewPlaying] = useState(false)
  const [previewTime, setPreviewTime] = useState(0)
  const [previewDuration, setPreviewDuration] = useState(0)
  const [activeExportJob, setActiveExportJob] = useState<ExportJobStatus | null>(null)
  const [isStartingExport, setIsStartingExport] = useState(false)
  const [draggedEffectId, setDraggedEffectId] = useState<string | null>(null)
  const [dropTargetEffectId, setDropTargetEffectId] = useState<string | null>(null)
  const [selectedChainItemId, setSelectedChainItemId] = useState<string | null>(null)
  const [selectedCategory, setSelectedCategory] = useState(initialUiPrefs.selectedCategory ?? "all")
  const [selectedSubcategory, setSelectedSubcategory] = useState(initialUiPrefs.selectedSubcategory ?? "all")
  const [quickFilter, setQuickFilter] = useState<EffectQuickFilter>(initialUiPrefs.quickFilter ?? "usable")
  const [effectEngineChoices, setEffectEngineChoices] = useState<Record<string, EffectEngineChoice>>({})
  const [compareMode, setCompareMode] = useState<CompareMode>("original")
  const [splitPosition, setSplitPosition] = useState(50)
  const [isSplitSweepActive, setIsSplitSweepActive] = useState(false)
  const [rightPanelWidth, setRightPanelWidth] = useState(720)
  const [bottomPanelHeight, setBottomPanelHeight] = useState(136)

  const summary = useMemo(() => metadataSummary(project.metadata_cache), [project.metadata_cache])
  const hasMedia = Boolean(project.media_path)
  const forceFramePlayback = isTauri()
  const hasEnabledEffects = project.effect_chain.some((effect) => effect.enabled)
  const isExportBusy =
    isStartingExport || Boolean(activeExportJob && !TERMINAL_EXPORT_STATES.has(activeExportJob.state))
  const effectById = useMemo(() => new Map(effects.map((effect) => [effect.effect_id, effect])), [effects])
  const effectGroups = useMemo(() => groupEffectVariants(effects), [effects])
  const primaryTaxonomyNodes = useMemo<EffectTaxonomyNode[]>(() => {
    const counts = new Map<string, { label: string; count: number }>()
    for (const group of effectGroups) {
      const path = effectTaxonomyPath(group)
      const label = path[0] ?? group.category
      const current = counts.get(label)
      counts.set(label, { label, count: (current?.count ?? 0) + 1 })
    }
    return [
      { id: "all", label: "All", count: effectGroups.length },
      ...Array.from(counts.entries())
        .map(([id, value]) => ({ id, ...value }))
        .sort((a, b) => a.id.localeCompare(b.id)),
    ]
  }, [effectGroups])
  const subcategoryNodes = useMemo<EffectTaxonomyNode[]>(() => {
    if (selectedCategory === "all") return [{ id: "all", label: "All", count: effectGroups.length }]
    const counts = new Map<string, { label: string; count: number }>()
    let total = 0
    for (const group of effectGroups) {
      const path = effectTaxonomyPath(group)
      if (path[0] !== selectedCategory) continue
      total += 1
      const hasSubcategory = Boolean(path[1])
      const label = path[1] ?? "General"
      const id = hasSubcategory ? effectTaxonomyId([selectedCategory, label]) : effectTaxonomyId([selectedCategory])
      const current = counts.get(id)
      counts.set(id, { label, count: (current?.count ?? 0) + 1 })
    }
    return [
      { id: "all", label: "All", count: total },
      ...Array.from(counts.entries())
        .map(([id, value]) => ({ id, ...value }))
        .sort((a, b) => a.label.localeCompare(b.label)),
    ]
  }, [effectGroups, selectedCategory])
  const visibleEffectGroups = useMemo(() => {
    const needle = query.trim().toLowerCase()
    return effectGroups.filter((group) => {
      const groupPath = effectTaxonomyPath(group)
      const groupTaxonomyId = effectTaxonomyId(groupPath)
      const matchesCategory = selectedCategory === "all" || groupPath[0] === selectedCategory
      const matchesSubcategory =
        selectedSubcategory === "all" ||
        groupTaxonomyId === selectedSubcategory ||
        groupTaxonomyId.startsWith(`${selectedSubcategory} > `)
      if (!matchesCategory || !matchesSubcategory) return false

      return group.variants.some((effect) => {
        return effectMatchesSearch(effect, needle) && effectMatchesQuickFilter(effect, quickFilter)
      })
    })
  }, [effectGroups, query, quickFilter, selectedCategory, selectedSubcategory])
  const selectedChainItem =
    project.effect_chain.find((effect) => effect.id === selectedChainItemId) ?? project.effect_chain[0] ?? null
  const selectedEffectDescriptor = selectedChainItem ? effectById.get(selectedChainItem.effect_id) : undefined
  const selectedParameters = useMemo<EffectParameter[]>(() => {
    if (!selectedChainItem) return []
    if (selectedEffectDescriptor?.parameters?.length) return selectedEffectDescriptor.parameters
    return Object.entries(selectedEffectDescriptor?.defaults ?? selectedChainItem.parameters)
      .filter(([name]) => name !== "script_template")
      .map(([name, value]) => ({
        name,
        type: typeof value === "number" ? "float" : typeof value === "boolean" ? "bool" : "string",
        default: value,
        label: name,
        description: "Custom registry parameter.",
      }))
  }, [selectedChainItem, selectedEffectDescriptor])
  const projectSnapshot = useMemo(() => serializeProjectFile(project), [project])
  const [savedProjectSnapshot, setSavedProjectSnapshot] = useState(() => serializeProjectFile(emptyProject))
  const isDirty = projectSnapshot !== savedProjectSnapshot
  const formattedCommandPreview = useMemo(() => formatCommandForShell(commandPreview), [commandPreview])
  const isProcessedPreview = compareMode === "processed"
  const isSplitPreview = compareMode === "split"
  const effectivePreviewDuration = summary.duration || project.out_point || previewDuration || 0
  const canPlayPreview = Boolean(
    hasMedia &&
      effectivePreviewDuration > 0 &&
      !isGeneratingBrowserPreview &&
      (!forceFramePlayback || sourceFrameCache),
  )
  const previewRangeStart = project.in_point || 0
  const sourceVideoStart = browserPreviewSource ? project.in_point || 0 : 0
  const previewRangeEnd = renderedPreviewSource
    ? Math.min(project.out_point || effectivePreviewDuration, renderedPreviewStart + previewDuration)
    : browserPreviewSource
    ? Math.min(project.out_point || effectivePreviewDuration, project.in_point + previewDuration)
    : project.out_point || effectivePreviewDuration
  const previewRangeMax = Math.max(previewRangeStart, previewRangeEnd || previewRangeStart)
  const originalPreviewFrame = originalFrameSource ?? thumbnailSource
  const processedPreviewFrame = renderedPreviewPath ? processedFrameSource ?? originalPreviewFrame : originalPreviewFrame
  const sourceFrameCacheUrl = sourceFrameCache ? frameCacheUrlAt(sourceFrameCache, previewTime, sourceFrameCache.start_seconds) : null
  const processedFrameCacheUrl = processedFrameCache ? frameCacheUrlAt(processedFrameCache, previewTime, renderedPreviewStart) : null
  const displayedOriginalFrame = sourceFrameCacheUrl ?? originalPreviewFrame
  const displayedProcessedFrame = processedFrameCacheUrl ?? (renderedPreviewPath ? processedPreviewFrame : displayedOriginalFrame)
  const livePreview = useMemo(() => buildLivePreview(project.effect_chain), [project.effect_chain])
  const hasLivePreview = livePreview.supportedCount > 0
  const livePreviewLabel = livePreview.label || "Script preview"
  const hasComparablePreview = Boolean(renderedPreviewSource) || hasLivePreview
  const canSweepSplit = Boolean(renderedPreviewSource) || (compareMode === "split" && hasLivePreview)
  const processedPreviewLabel = renderedPreviewSource ? "Rendered preview" : hasLivePreview ? livePreviewLabel : "Processed preview"
  const processedPreviewStyle: CSSProperties | undefined =
    isProcessedPreview && !renderedPreviewSource && hasLivePreview ? { filter: livePreview.filter } : undefined
  const splitPreviewStyle: CSSProperties | undefined =
    isSplitPreview && !renderedPreviewSource && hasLivePreview
      ? {
          backdropFilter: livePreview.backdropFilter,
          WebkitBackdropFilter: livePreview.backdropFilter,
        }
      : undefined
  const splitClipPath = `inset(0 0 0 ${splitPosition}%)`

  useEffect(() => {
    window.localStorage.setItem(
      UI_PREFS_KEY,
      JSON.stringify({
        selectedCategory,
        selectedSubcategory,
        quickFilter,
      } satisfies UiPrefs),
    )
  }, [quickFilter, selectedCategory, selectedSubcategory])

  useEffect(() => {
    if (!primaryTaxonomyNodes.some((node) => node.id === selectedCategory)) {
      setSelectedCategory("all")
    }
  }, [primaryTaxonomyNodes, selectedCategory])

  useEffect(() => {
    setSelectedSubcategory("all")
  }, [selectedCategory])

  useEffect(() => {
    if (!subcategoryNodes.some((node) => node.id === selectedSubcategory)) {
      setSelectedSubcategory("all")
    }
  }, [subcategoryNodes, selectedSubcategory])

  useEffect(() => {
    let active = true
    setPreviewPlaybackFailed(false)
    setIsPreviewPlaying(false)
    setPreviewTime(0)
    setPreviewDuration(0)
    setRenderedPreviewSource(null)
    setRenderedPreviewPath("")
    setRenderedPreviewStart(0)
    setIsSplitSweepActive(false)
    setBrowserPreviewSource(false)
    setSourceFrameCache(null)
    setProcessedFrameCache(null)
    async function updatePreviewSource() {
      const source = await createMediaPreviewSource(project.media_path, {
        isDesktop: isTauri(),
        allowPreviewFile: (path) => invoke("allow_preview_file", { path }),
        convertFileSrc,
        mediaFileUrl: api.mediaFileUrl,
      })
      if (active) setPreviewSource(source)
    }
    void updatePreviewSource()
    return () => {
      active = false
    }
  }, [project.media_path])

  useEffect(() => {
    let active = true
    setSourceFrameCache(null)
    if (!forceFramePlayback || !project.media_path) {
      return () => {
        active = false
      }
    }

    async function updateSourceFrameCache() {
      try {
        const start = project.in_point || 0
        const duration = Math.min(60, Math.max(1, (project.out_point || summary.duration || start + 30) - start))
        const cache = await api.frameCache(project.media_path, start, duration, 15, 1280)
        const urls = await Promise.all(cache.frames.map((frame) => api.frameCacheFileUrl(cache.cache_id, frame.filename)))
        if (active) {
          setSourceFrameCache({ ...cache, urls })
        }
      } catch (error) {
        if (active) appendLog("media.frame_cache.failed", { error: error instanceof Error ? error.message : String(error) })
      }
    }

    void updateSourceFrameCache()
    return () => {
      active = false
    }
  }, [forceFramePlayback, project.media_path, project.in_point, project.out_point, summary.duration])

  useEffect(() => {
    let active = true
    setThumbnailSource(null)
    if (!project.media_path) return () => {
      active = false
    }
    async function updateThumbnailSource() {
      try {
        const thumbnail = await api.thumbnail(project.media_path, Math.max(project.in_point, 0))
        if (active) setThumbnailSource(thumbnail.data_url)
      } catch (error) {
        if (active) appendLog("media.thumbnail.failed", { error: error instanceof Error ? error.message : String(error) })
      }
    }
    void updateThumbnailSource()
    return () => {
      active = false
    }
  }, [project.media_path, project.in_point])

  useEffect(() => {
    previewTimeRef.current = previewTime
  }, [previewTime])

  useEffect(() => {
    if (!isSplitSweepActive) return
    if (!hasComparablePreview) {
      setIsSplitSweepActive(false)
      return
    }

    setCompareMode("split")
    const startedAt = performance.now()
    const cycleMs = 2600

    const tick = (now: number) => {
      const phase = ((now - startedAt) % cycleMs) / cycleMs
      const sweep = phase <= 0.5 ? phase * 2 : (1 - phase) * 2
      setSplitPosition(sweep * 100)
      splitSweepRaf.current = window.requestAnimationFrame(tick)
    }

    splitSweepRaf.current = window.requestAnimationFrame(tick)
    return () => {
      if (splitSweepRaf.current !== null) {
        window.cancelAnimationFrame(splitSweepRaf.current)
        splitSweepRaf.current = null
      }
    }
  }, [hasComparablePreview, isSplitSweepActive])

  useEffect(() => {
    if (compareMode !== "split" && isSplitSweepActive) {
      setIsSplitSweepActive(false)
    }
  }, [compareMode, isSplitSweepActive])

  useEffect(() => {
    if (!isPreviewPlaying || (previewSource && !forceFramePlayback)) return
    const startedAt = performance.now()
    const baseTime = previewTimeRef.current

    const tick = (now: number) => {
      const next = baseTime + (now - startedAt) / 1000
      const end = previewRangeMax || effectivePreviewDuration
      if (end > previewRangeStart && next >= end) {
        setIsPreviewPlaying(false)
        setPreviewTime(end)
        return
      }
      setPreviewTime(next)
      framePlaybackRaf.current = window.requestAnimationFrame(tick)
    }

    framePlaybackRaf.current = window.requestAnimationFrame(tick)
    return () => {
      if (framePlaybackRaf.current !== null) {
        window.cancelAnimationFrame(framePlaybackRaf.current)
        framePlaybackRaf.current = null
      }
    }
  }, [effectivePreviewDuration, forceFramePlayback, isPreviewPlaying, previewRangeMax, previewRangeStart, previewSource])

  useEffect(() => {
    syncPreviewVideos(previewTime || project.in_point || 0)
  }, [compareMode, previewSource, renderedPreviewSource])

  useEffect(() => {
    if (!hasMedia || previewSource || isPreviewPlaying) return
    if (frameFetchInFlight.current) return
    const requestId = ++frameRequestId.current
    frameFetchInFlight.current = true
    const originalTime = previewTime
    async function updateFrames() {
      try {
        const [original, processed] = await Promise.all([
          api.thumbnail(project.media_path, Math.max(originalTime, 0)),
          renderedPreviewPath
            ? api.thumbnail(renderedPreviewPath, clamp(previewTime - renderedPreviewStart, 0, previewDuration || previewTime))
            : Promise.resolve(null),
        ])
        if (requestId !== frameRequestId.current) return
        setOriginalFrameSource(original.data_url)
        setProcessedFrameSource(processed?.data_url ?? null)
      } catch (error) {
        if (requestId === frameRequestId.current) {
          appendLog("media.frame.failed", { error: error instanceof Error ? error.message : String(error) })
        }
      } finally {
        frameFetchInFlight.current = false
      }
    }
    void updateFrames()
  }, [hasMedia, isPreviewPlaying, previewDuration, previewSource, project.media_path, previewTime, renderedPreviewPath, renderedPreviewStart])

  function syncPreviewVideos(time: number) {
    const original = originalVideoRef.current
    const processed = processedVideoRef.current
    const originalTime = time - sourceVideoStart
    if (original && Number.isFinite(originalTime) && Math.abs(original.currentTime - originalTime) > 0.08) {
      original.currentTime = clamp(originalTime, 0, browserPreviewSource ? previewDuration || original.duration || originalTime : effectivePreviewDuration || originalTime)
    }
    if (processed && Number.isFinite(time)) {
      const processedTime = clamp(time - renderedPreviewStart, 0, previewDuration || processed.duration || 0)
      if (Math.abs(processed.currentTime - processedTime) > 0.08) {
        processed.currentTime = processedTime
      }
    }
  }

  async function togglePreviewPlayback() {
    if (!canPlayPreview) return
    setPreviewPlaybackFailed(false)
    if (forceFramePlayback) {
      setIsPreviewPlaying((current) => !current)
      return
    }
    if (isPreviewPlaying) {
      originalVideoRef.current?.pause()
      processedVideoRef.current?.pause()
      setIsPreviewPlaying(false)
      return
    }
    syncPreviewVideos(previewTime)
    try {
      await originalVideoRef.current?.play()
      if (processedVideoRef.current) {
        await processedVideoRef.current.play()
      }
      setIsPreviewPlaying(true)
    } catch (error) {
      appendLog("media.preview.play_failed", { error: error instanceof Error ? error.message : String(error) })
      setIsPreviewPlaying(true)
    }
  }

  function seekPreview(value: number) {
    const nextValue = clamp(value, previewRangeStart, previewRangeMax || value)
    syncPreviewVideos(nextValue)
    setPreviewTime(nextValue)
  }

  function handleOriginalVideoTimeUpdate(video: HTMLVideoElement) {
    const current = sourceVideoStart + video.currentTime
    if (current >= previewRangeMax && previewRangeMax > previewRangeStart) {
      video.pause()
      processedVideoRef.current?.pause()
      setIsPreviewPlaying(false)
      setPreviewTime(previewRangeMax)
      return
    }
    setPreviewTime(current)
    const processed = processedVideoRef.current
    if (processed && !processed.paused && Math.abs(processed.currentTime - (current - renderedPreviewStart)) > 0.2) {
      processed.currentTime = clamp(current - renderedPreviewStart, 0, previewDuration || processed.duration || 0)
    }
  }

  function startSplitResize(event: ReactPointerEvent<HTMLDivElement>) {
    event.preventDefault()
    setIsSplitSweepActive(false)
    const rect = event.currentTarget.parentElement?.getBoundingClientRect()
    if (!rect) return
    const update = (clientX: number) => {
      setSplitPosition(clamp(((clientX - rect.left) / rect.width) * 100, 0, 100))
    }
    update(event.clientX)
    const previousCursor = document.body.style.cursor
    const previousUserSelect = document.body.style.userSelect
    document.body.style.cursor = "ew-resize"
    document.body.style.userSelect = "none"
    const handleMove = (moveEvent: PointerEvent) => update(moveEvent.clientX)
    const handleUp = () => {
      document.body.style.cursor = previousCursor
      document.body.style.userSelect = previousUserSelect
      window.removeEventListener("pointermove", handleMove)
      window.removeEventListener("pointerup", handleUp)
    }
    window.addEventListener("pointermove", handleMove)
    window.addEventListener("pointerup", handleUp, { once: true })
  }

  async function handlePreviewVideoError(video: HTMLVideoElement) {
    setIsPreviewPlaying(false)
    const mediaError = video.error
    appendLog("media.preview.video.failed", {
      path: project.media_path,
      code: mediaError?.code,
      message: mediaError?.message,
      network_state: video.networkState,
      ready_state: video.readyState,
      source: video.currentSrc,
    })

    if (!hasMedia || renderedPreviewSource || browserPreviewSource || isGeneratingBrowserPreview) {
      setPreviewPlaybackFailed(true)
      return
    }

    setIsGeneratingBrowserPreview(true)
    try {
      const proxyStart = project.in_point || 0
      const duration = Math.min(30, Math.max(1, (project.out_point || summary.duration || 30) - proxyStart))
      const generated = await api.browserPreview(project.media_path, proxyStart, duration)
      setPreviewSource(await api.previewFileUrl(generated.path))
      setBrowserPreviewSource(true)
      setPreviewPlaybackFailed(false)
      setPreviewTime(proxyStart)
      setPreviewDuration(generated.duration_seconds)
      appendLog("media.browser_preview.ready", { path: generated.path, command: generated.command })
    } catch (error) {
      setPreviewPlaybackFailed(true)
      reportError("media.browser_preview.failed", error)
    } finally {
      setIsGeneratingBrowserPreview(false)
    }
  }

  function appendLog(event: string, payload: Record<string, unknown> = {}) {
    const line = JSON.stringify({ time: new Date().toISOString(), event, ...payload })
    setLogs((current) => [line, ...current].slice(0, 80))
  }

  function reportError(event: string, error: unknown, payload: Record<string, unknown> = {}) {
    const message = error instanceof Error ? error.message : String(error)
    setLastError(message)
    appendLog(event, { ...payload, error: message })
  }

  async function validateScriptChain() {
    setIsValidatingScript(true)
    try {
      const result = await api.validateChain(project.media_path, project.effect_chain)
      setScript(
        `# VapourSynth\n${compactScriptForDisplay(result.scripts.vapoursynth)}\n# AviSynth+\n${compactScriptForDisplay(result.scripts.avisynth)}`,
      )
      const vapoursynth = result.validations.vapoursynth
      const avisynth = result.validations.avisynth
      const enabledEngines = new Set(project.effect_chain.filter((effect) => effect.enabled).map((effect) => effect.engine))
      const validationLabel = (engine: "vapoursynth" | "avisynth", validation: typeof vapoursynth, missingTool: string) => {
        if (enabledEngines.size && !enabledEngines.has(engine)) return "skipped"
        return validation.available ? (validation.ok ? "valid" : "failed") : missingTool
      }
      const summaryText = [
        `VapourSynth: ${validationLabel("vapoursynth", vapoursynth, "vspipe missing")}`,
        `AviSynth+: ${validationLabel("avisynth", avisynth, "avs2yuv missing")}`,
      ].join(" · ")
      setScriptValidation(summaryText)
      appendLog("script.validate", {
        vapoursynth: vapoursynth.ok,
        avisynth: avisynth.ok,
        vapoursynth_available: vapoursynth.available,
        avisynth_available: avisynth.available,
      })
    } catch (error) {
      reportError("script.validate.failed", error)
    } finally {
      setIsValidatingScript(false)
    }
  }

  async function previewEffectChain() {
    if (!hasMedia) {
      setLastError("Import media before preview.")
      return
    }
    if (!project.effect_chain.length) {
      setLastError("Add at least one effect before rendering a processed preview.")
      return
    }

    setIsRenderingPreview(true)
    setIsSplitSweepActive(false)
    try {
      const enabledEngines = new Set(project.effect_chain.filter((effect) => effect.enabled).map((effect) => effect.engine))
      const renderEngine = enabledEngines.size === 1 && enabledEngines.has("avisynth") ? "avisynth" : "vapoursynth"
      const currentTime = clamp(previewTime || project.in_point || 0, project.in_point || 0, project.out_point || summary.duration || previewTime || 0)
      const duration = Math.min(5, Math.max(0.5, (project.out_point || summary.duration || currentTime + 5) - currentTime))
      const rendered = await api.renderPreview(
        project,
        duration,
        renderEngine,
        currentTime,
      )
      if (isTauri()) {
        await invoke("allow_preview_file", { path: rendered.path })
        setRenderedPreviewSource(convertFileSrc(rendered.path))
      } else {
        setRenderedPreviewSource(await api.previewFileUrl(rendered.path))
      }
      if (forceFramePlayback) {
        const cache = await api.frameCache(rendered.path, 0, rendered.duration_seconds, 15, 1280)
        const urls = await Promise.all(cache.frames.map((frame) => api.frameCacheFileUrl(cache.cache_id, frame.filename)))
        setProcessedFrameCache({ ...cache, urls })
      }
      setRenderedPreviewPath(rendered.path)
      setRenderedPreviewStart(currentTime)
      setPreviewDuration(rendered.duration_seconds)
      setPreviewTime(currentTime)
      setPreviewPlaybackFailed(false)
      setBrowserPreviewSource(false)
      setSplitPosition(50)
      setCompareMode("split")
      setScriptValidation(`Rendered ${rendered.engine} preview`)
      appendLog("preview.render.done", { path: rendered.path, command: rendered.command })
      return
    } catch (error) {
      reportError("preview.render.failed", error)
    } finally {
      setIsRenderingPreview(false)
    }

    if (hasLivePreview) {
      setSplitPosition(50)
      setCompareMode("split")
      appendLog("preview.chain.css", {
        live_supported: livePreview.supportedCount,
        script_only: livePreview.unsupportedCount,
        filter: livePreview.filter,
      })
    } else {
      setCompareMode("original")
      setScriptValidation("Render failed. This chain has no lightweight visual preview.")
    }
  }

  useEffect(() => {
    let active = true
    async function boot() {
      let health: Awaited<ReturnType<typeof api.health>> | null = null
      try {
        for (let attempt = 0; attempt < 30; attempt += 1) {
          try {
            health = await api.health()
            break
          } catch (error) {
            if (attempt === 29) throw error
            await new Promise((resolve) => window.setTimeout(resolve, 350))
          }
        }
        if (!active) return
        setBackendState(health?.ok ? "ready" : "warning")
        appendLog("backend.ready", { version: health?.version })
      } catch (error) {
        if (!active) return
        setBackendState("offline")
        reportError("backend.offline", error)
      }
      try {
        const [detectedTools, loadedEffects] = await Promise.all([api.detectTools(), api.effects()])
        if (!active) return
        setTools(detectedTools)
        setEffects(loadedEffects.length ? loadedEffects : fallbackEffects)
      } catch (error) {
        if (!active) return
        reportError("backend.catalog.failed", error)
      }
    }
    void boot()
    return () => {
      active = false
    }
  }, [])

  useEffect(() => {
    const requestId = scriptRequestId.current + 1
    scriptRequestId.current = requestId
    const timer = window.setTimeout(() => {
      async function updateScript() {
        try {
          const generated = await api.chainScript(project.media_path, project.effect_chain)
          if (scriptRequestId.current !== requestId) return
          setScript(
            `# VapourSynth\n${compactScriptForDisplay(generated.vapoursynth)}\n# AviSynth+\n${compactScriptForDisplay(generated.avisynth)}`,
          )
          setScriptValidation("")
        } catch {
          if (scriptRequestId.current !== requestId) return
          const lines = project.effect_chain
            .filter((effect) => effect.enabled)
            .map((effect, index) => {
              const descriptor = effectById.get(effect.effect_id)
              const parameters = { ...(descriptor?.defaults ?? {}), ...effect.parameters }
              const template = descriptor?.script_template ?? String(effect.parameters.script_template ?? "")
              return `# ${index + 1}. ${effect.name}\n${fillTemplate(template, parameters)}`
            })
          setScript(lines.length ? lines.join("\n\n") : "# Add effects to generate script preview.")
          setScriptValidation("")
        }
      }
      void updateScript()
    }, 150)
    return () => window.clearTimeout(timer)
  }, [effectById, project.effect_chain, project.media_path])

  async function importVideo() {
    const path = await pickVideoPath()
    if (!path) return
    appendLog("media.import.start", { path })
    try {
      const metadata = await api.probeMedia(path)
      const duration = metadataDuration(metadata)
      setProject((current) => ({
        ...current,
        media_path: path,
        metadata_cache: metadata,
        in_point: 0,
        out_point: duration,
      }))
      appendLog("media.import.done", { duration })
    } catch (error) {
      reportError("media.import.failed", error)
    }
  }

  function addEffect(effect: EffectDescriptor) {
    if (!canAddEffectToChain(effect)) {
      const status = effect.render_status ?? "not renderable"
      setLastError(`${effect.name} is not usable yet (${status}).`)
      appendLog("effect.add.blocked", { effect: effect.effect_id, status })
      return
    }
    setRenderedPreviewSource(null)
    setRenderedPreviewPath("")
    setProcessedFrameCache(null)
    setIsSplitSweepActive(false)
    const id = crypto.randomUUID()
    const parameters = { ...(effect.defaults ?? {}) }
    const item: EffectChainItem = {
      id,
      effect_id: effect.effect_id,
      name: effect.name,
      engine: effect.engine,
      category: effect.category,
      enabled: true,
      parameters,
    }
    setProject((current) => ({ ...current, effect_chain: [...current.effect_chain, item] }))
    setSelectedChainItemId(id)
  }

  function toggleEffect(effectId: string) {
    setRenderedPreviewSource(null)
    setRenderedPreviewPath("")
    setProcessedFrameCache(null)
    setIsSplitSweepActive(false)
    setProject((current) => ({ ...current, effect_chain: toggleChainItem(current.effect_chain, effectId) }))
  }

  function removeEffect(effectId: string) {
    setRenderedPreviewSource(null)
    setRenderedPreviewPath("")
    setProcessedFrameCache(null)
    setIsSplitSweepActive(false)
    if (selectedChainItemId === effectId) {
      const index = project.effect_chain.findIndex((effect) => effect.id === effectId)
      const next = removeChainItem(project.effect_chain, effectId)
      setSelectedChainItemId(next[Math.min(index, next.length - 1)]?.id ?? null)
    }
    setProject((current) => ({ ...current, effect_chain: removeChainItem(current.effect_chain, effectId) }))
  }

  function updateEffectParameter(itemId: string, parameter: EffectParameter, value: string | boolean) {
    setRenderedPreviewSource(null)
    setRenderedPreviewPath("")
    setProcessedFrameCache(null)
    setIsSplitSweepActive(false)
    setProject((current) => ({
      ...current,
      effect_chain: updateChainParameter(current.effect_chain, itemId, parameter.name, coerceParameterValue(parameter, value)),
    }))
  }

  function startChainDrag(event: DragEvent<HTMLElement>, effectId: string) {
    setDraggedEffectId(effectId)
    setDropTargetEffectId(effectId)
    event.dataTransfer.effectAllowed = "move"
    event.dataTransfer.setData("application/x-deepframe-effect", effectId)
    event.dataTransfer.setData("text/plain", effectId)
  }

  function dragOverChainItem(event: DragEvent<HTMLDivElement>, targetEffectId: string) {
    const sourceEffectId = draggedEffectId ?? event.dataTransfer.getData("application/x-deepframe-effect")
    if (!sourceEffectId || sourceEffectId === targetEffectId) return
    event.preventDefault()
    event.dataTransfer.dropEffect = "move"
    setDropTargetEffectId(targetEffectId)
  }

  function dropChainItem(event: DragEvent<HTMLDivElement>, targetEffectId: string) {
    event.preventDefault()
    const sourceEffectId = event.dataTransfer.getData("application/x-deepframe-effect") || draggedEffectId
    if (sourceEffectId && sourceEffectId !== targetEffectId) {
      setRenderedPreviewSource(null)
      setRenderedPreviewPath("")
      setProcessedFrameCache(null)
      setIsSplitSweepActive(false)
      setProject((current) => ({ ...current, effect_chain: moveChainItem(current.effect_chain, sourceEffectId, targetEffectId) }))
    }
    setDraggedEffectId(null)
    setDropTargetEffectId(null)
  }

  function endChainDrag() {
    setDraggedEffectId(null)
    setDropTargetEffectId(null)
  }

  function startRightPanelResize(event: ReactPointerEvent<HTMLDivElement>) {
    event.preventDefault()
    const startX = event.clientX
    const startWidth = rightPanelWidth
    const previousCursor = document.body.style.cursor
    const previousUserSelect = document.body.style.userSelect
    document.body.style.cursor = "ew-resize"
    document.body.style.userSelect = "none"
    const handleMove = (moveEvent: PointerEvent) => {
      setRightPanelWidth(clamp(startWidth - (moveEvent.clientX - startX), 520, 920))
    }
    const handleUp = () => {
      document.body.style.cursor = previousCursor
      document.body.style.userSelect = previousUserSelect
      window.removeEventListener("pointermove", handleMove)
      window.removeEventListener("pointerup", handleUp)
    }
    window.addEventListener("pointermove", handleMove)
    window.addEventListener("pointerup", handleUp, { once: true })
  }

  function startBottomPanelResize(event: ReactPointerEvent<HTMLDivElement>) {
    event.preventDefault()
    const startY = event.clientY
    const startHeight = bottomPanelHeight
    const previousCursor = document.body.style.cursor
    const previousUserSelect = document.body.style.userSelect
    document.body.style.cursor = "ns-resize"
    document.body.style.userSelect = "none"
    const handleMove = (moveEvent: PointerEvent) => {
      setBottomPanelHeight(clamp(startHeight - (moveEvent.clientY - startY), 128, 260))
    }
    const handleUp = () => {
      document.body.style.cursor = previousCursor
      document.body.style.userSelect = previousUserSelect
      window.removeEventListener("pointermove", handleMove)
      window.removeEventListener("pointerup", handleUp)
    }
    window.addEventListener("pointermove", handleMove)
    window.addEventListener("pointerup", handleUp, { once: true })
  }

  function updateRange(key: "in_point" | "out_point", value: number) {
    setRenderedPreviewSource(null)
    setRenderedPreviewPath("")
    setProcessedFrameCache(null)
    setIsSplitSweepActive(false)
    setProject((current) => {
      const duration = metadataDuration(current.metadata_cache) || current.out_point || value
      const nextValue = clamp(Number.isFinite(value) ? value : 0, 0, Math.max(duration, 0))
      if (key === "in_point") {
        return { ...current, in_point: Math.min(nextValue, current.out_point || nextValue) }
      }
      return { ...current, out_point: Math.max(nextValue, current.in_point) }
    })
  }

  function addSegment() {
    if (project.out_point <= project.in_point) return
    setProject((current) => ({
      ...current,
      segments: [
        ...current.segments,
        {
          id: crypto.randomUUID(),
          name: `Segment ${current.segments.length + 1}`,
          start: current.in_point,
          end: current.out_point,
        },
      ],
    }))
  }

  async function startExportJob() {
    if (!hasMedia || isExportBusy) return
    if (hasEnabledEffects) {
      setLastError("Final effect export is not implemented yet. Use Preview to render a short processed range, or disable the chain to export the original trim.")
      return
    }
    const outputPath = await pickExportPath()
    if (!outputPath) {
      appendLog("export.job.cancelled")
      return
    }
    const exportProject: ProjectState = {
      ...project,
      output_settings: {
        ...project.output_settings,
        output_path: outputPath,
      },
    }
    setProject(exportProject)
    setIsStartingExport(true)
    try {
      const job = await api.startExport(exportProject)
      setActiveExportJob(job)
      setCommandPreview(job.command)
      appendLog("export.job.started", { job_id: job.job_id, command: job.command })
    } catch (error) {
      reportError("export.job.failed_to_start", error)
    } finally {
      setIsStartingExport(false)
    }
  }

  async function cancelExportJob() {
    if (!activeExportJob || TERMINAL_EXPORT_STATES.has(activeExportJob.state)) return
    try {
      const job = await api.cancelExport(activeExportJob.job_id)
      setActiveExportJob(job)
      appendLog("export.job.cancelled", { job_id: job.job_id, state: job.state })
    } catch (error) {
      reportError("export.job.cancel_failed", error, { job_id: activeExportJob.job_id })
    }
  }

  async function saveProject(saveAs = false) {
    const path = !saveAs && projectPath ? projectPath : await pickProjectPathForSave()
    if (!path) {
      appendLog("project.save.cancelled")
      return
    }
    try {
      await writeProjectFile(path, projectSnapshot)
      setProjectPath(path)
      setSavedProjectSnapshot(projectSnapshot)
      appendLog("project.save.done", { path })
    } catch (error) {
      reportError("project.save.failed", error, { path })
    }
  }

  async function openProject() {
    if (isDirty && !window.confirm("Open another project and discard unsaved changes?")) {
      appendLog("project.open.cancelled", { reason: "dirty" })
      return
    }
    const path = await pickProjectPathForOpen()
    if (!path) {
      appendLog("project.open.cancelled")
      return
    }
    try {
      const contents = await readProjectFile(path)
      const loadedProject = parseProjectFile(contents)
      const loadedSnapshot = serializeProjectFile(loadedProject)
      setProject(loadedProject)
      setProjectPath(path)
      setSavedProjectSnapshot(loadedSnapshot)
      setSelectedChainItemId(loadedProject.effect_chain[0]?.id ?? null)
      appendLog("project.open.done", { path })
    } catch (error) {
      reportError("project.open.failed", error, { path })
    }
  }

  useEffect(() => {
    if (!activeExportJob || TERMINAL_EXPORT_STATES.has(activeExportJob.state)) return

    let active = true
    let failureCount = 0
    const interval = window.setInterval(async () => {
      try {
        const job = await api.exportJob(activeExportJob.job_id)
        if (!active) return
        failureCount = 0
        setActiveExportJob(job)
        setCommandPreview(job.command)
        if (TERMINAL_EXPORT_STATES.has(job.state)) {
          appendLog("export.job.finished", { job_id: job.job_id, state: job.state, error: job.error })
        }
      } catch (error) {
        if (!active) return
        failureCount += 1
        reportError("export.job.poll_failed", error, { job_id: activeExportJob.job_id })
        if (failureCount >= 3) {
          setActiveExportJob((current) =>
            current?.job_id === activeExportJob.job_id
              ? {
                  ...current,
                  state: "failed",
                  error: "Lost connection to export job status.",
                }
              : current,
          )
          window.clearInterval(interval)
        }
      }
    }, 750)

    return () => {
      active = false
      window.clearInterval(interval)
    }
  }, [activeExportJob?.job_id, activeExportJob?.state])

  useEffect(() => {
    function handleKeyDown(event: KeyboardEvent) {
      const isModifier = event.ctrlKey || event.metaKey
      if (!isModifier || event.repeat) return
      const key = event.key.toLowerCase()

      if (key === "s") {
        event.preventDefault()
        void saveProject(event.shiftKey)
        return
      }

      if (isEditableTarget(event.target)) return

      if (key === "i") {
        event.preventDefault()
        void importVideo()
        return
      }
      if (key === "o") {
        event.preventDefault()
        void openProject()
        return
      }
      if (key === "e" && hasMedia) {
        event.preventDefault()
        void startExportJob()
      }
    }

    window.addEventListener("keydown", handleKeyDown)
    return () => window.removeEventListener("keydown", handleKeyDown)
  })

  const exportPercent = Math.round(Math.max(0, Math.min(activeExportJob?.percent ?? 0, 1)) * 100)
  const activeExportIsTerminal = Boolean(activeExportJob && TERMINAL_EXPORT_STATES.has(activeExportJob.state))

  return (
    <main className="grid h-full grid-rows-[34px_minmax(0,1fr)] overflow-hidden bg-background text-foreground">
      <header className="flex items-center justify-between border-b border-border/70 bg-background/95 px-2">
        <div className="flex items-center gap-2">
          <div className="flex size-6 items-center justify-center rounded bg-primary text-primary-foreground">
            <Wand2 data-icon="inline-start" />
          </div>
          <div>
            <div className="text-[12px] font-semibold leading-none">DeepFrame Studio</div>
            <div className="mt-0.5 flex items-center gap-1.5 text-[9px] text-muted-foreground">
              <StatusDot state={backendState} />
              <span>{backendState === "ready" ? "Engine ready" : backendState === "warning" ? "Engine warning" : "Engine offline"}</span>
            </div>
          </div>
        </div>
        {lastError && (
          <div
            className="mx-3 flex min-w-0 max-w-[42vw] items-center gap-2 rounded-md border border-red-500/30 bg-red-500/10 px-2 py-1 text-[11px] text-red-100"
            role="alert"
            aria-live="polite"
            title={lastError}
          >
            <AlertCircle className="size-3.5 shrink-0 text-red-300" />
            <span className="truncate">{lastError}</span>
            <button
              className="rounded px-1 text-red-200 hover:bg-red-400/20 hover:text-white"
              onClick={() => setLastError("")}
              type="button"
              aria-label="Dismiss error"
            >
              <X className="size-3" />
            </button>
          </div>
        )}
        <div className="flex items-center gap-1">
          <Button onClick={importVideo} size="sm" variant="secondary">
            <FolderOpen data-icon="inline-start" />
            Import
          </Button>
          <Button onClick={openProject} size="sm" variant="quiet">
            Open
          </Button>
          <Button
            disabled={!hasMedia || isExportBusy}
            onClick={startExportJob}
            size="sm"
            title={hasEnabledEffects ? "Disable the chain for original trim export, or use Preview for processed range render." : "Export selected range"}
          >
            <Scissors data-icon="inline-start" />
            {isStartingExport ? "Starting" : isExportBusy ? "Exporting" : "Export"}
          </Button>
          <Button onClick={() => void saveProject()} size="icon" variant="quiet" aria-label={projectPath ? `Save ${projectPath}` : "Save project"}>
            <Save />
          </Button>
          <Button onClick={() => void saveProject(true)} size="sm" variant="quiet" title="Ctrl+Shift+S">
            Save as
          </Button>
          <Dialog>
            <DialogTrigger asChild>
              <Button size="icon" variant="quiet" aria-label="Settings">
                <Settings />
              </Button>
            </DialogTrigger>
            <DialogContent>
              <DialogTitle className="text-base font-semibold">External tools</DialogTitle>
              <DialogDescription className="mt-1 text-sm text-muted-foreground">
                Configure paths later. The MVP detects binaries from PATH.
              </DialogDescription>
              <div className="mt-4 grid gap-2">
                {tools.length ? (
                  tools.map((tool) => (
                    <div key={tool.name} className="flex items-center justify-between rounded-md border border-border bg-muted/40 px-3 py-2">
                      <div>
                        <div className="text-sm font-medium">{tool.name}</div>
                        <div className="max-w-[480px] truncate text-xs text-muted-foreground">{tool.path}</div>
                      </div>
                      <Badge tone={tool.detected ? "good" : "warn"}>{tool.detected ? "detected" : "missing"}</Badge>
                    </div>
                  ))
                ) : (
                  <div className="rounded-md border border-border bg-muted/40 px-3 py-2 text-sm text-muted-foreground">
                    Backend not connected.
                  </div>
                )}
              </div>
            </DialogContent>
          </Dialog>
        </div>
      </header>

      <section
        className="grid min-h-0 overflow-hidden"
        style={{ gridTemplateColumns: `minmax(0,1fr) 8px ${rightPanelWidth}px` }}
      >
        <div
          className="grid min-h-0 min-w-0 overflow-hidden"
          style={{
            gridTemplateRows: activeExportJob
              ? `minmax(220px,1fr) 104px 4px ${bottomPanelHeight}px`
              : "minmax(220px,1fr) 104px",
          }}
        >
          <div className="relative min-h-0 overflow-hidden border-b border-border/70 bg-[#07090d]">
            <div className="absolute left-2 top-2 z-10 flex items-center gap-0.5 rounded border border-border/80 bg-background/80 p-0.5 backdrop-blur">
              {COMPARE_MODES.map((mode) => (
                <Button
                  key={mode.id}
                  onClick={() => setCompareMode(mode.id)}
                  size="sm"
                  variant={compareMode === mode.id ? "secondary" : "quiet"}
                >
                  {mode.id === "split" && <SquareSplitHorizontal data-icon="inline-start" />}
                  {mode.label}
                </Button>
              ))}
            </div>
            {hasMedia && (previewSource || thumbnailSource) ? (
              <>
                <div className="relative h-full w-full overflow-hidden bg-[#05070a]">
                  {previewSource && !forceFramePlayback ? (
                    <video
                      ref={originalVideoRef}
                      className={cn(
                        "absolute inset-0 h-full w-full bg-[#05070a] object-contain",
                        isProcessedPreview && (renderedPreviewSource || hasLivePreview) && "opacity-0",
                      )}
                      muted
                      onError={(event) => void handlePreviewVideoError(event.currentTarget)}
                      onLoadedMetadata={(event) => syncPreviewVideos(previewTime || project.in_point || 0)}
                      onPause={() => setIsPreviewPlaying(false)}
                      onPlay={() => setIsPreviewPlaying(true)}
                      onTimeUpdate={(event) => handleOriginalVideoTimeUpdate(event.currentTarget)}
                      playsInline
                      preload="auto"
                      src={previewSource}
                    />
                  ) : displayedOriginalFrame ? (
                    <img
                      alt="Original preview frame"
                      className={cn("absolute inset-0 h-full w-full bg-[#05070a] object-contain", isProcessedPreview && "opacity-0")}
                      src={displayedOriginalFrame}
                    />
                  ) : (
                    <div className="absolute inset-0 flex items-center justify-center text-xs text-muted-foreground">Loading frame...</div>
                  )}
                  {(isProcessedPreview || isSplitPreview) && renderedPreviewSource && !forceFramePlayback && (
                    <video
                      ref={processedVideoRef}
                      className="absolute inset-0 h-full w-full bg-[#05070a] object-contain"
                      muted
                      playsInline
                      preload="auto"
                      src={renderedPreviewSource}
                      style={{ clipPath: isSplitPreview ? splitClipPath : undefined }}
                    />
                  )}
                  {(isProcessedPreview || isSplitPreview) && !renderedPreviewSource && previewSource && !forceFramePlayback && hasLivePreview && (
                    <video
                      ref={processedVideoRef}
                      aria-hidden="true"
                      className="pointer-events-none absolute inset-0 h-full w-full bg-[#05070a] object-contain"
                      muted
                      playsInline
                      preload="auto"
                      src={previewSource}
                      style={{
                        ...(processedPreviewStyle ?? splitPreviewStyle ?? {}),
                        clipPath: isSplitPreview ? splitClipPath : undefined,
                      }}
                    />
                  )}
                  {(isProcessedPreview || isSplitPreview) && (forceFramePlayback || !previewSource) && displayedProcessedFrame && (
                    <img
                      alt="Processed preview frame"
                      className="absolute inset-0 h-full w-full bg-[#05070a] object-contain"
                      src={displayedProcessedFrame}
                      style={{
                        ...(processedPreviewStyle ?? splitPreviewStyle ?? {}),
                        clipPath: isSplitPreview ? splitClipPath : undefined,
                      }}
                    />
                  )}
                  {isSplitPreview && (
                    <div
                      className="group absolute inset-y-0 z-20 w-5 -translate-x-1/2 cursor-ew-resize touch-none"
                      onPointerDown={startSplitResize}
                      style={{ cursor: "ew-resize", left: `${splitPosition}%` }}
                      title="Drag split"
                    >
                      <div className="mx-auto h-full w-px bg-primary transition-all group-hover:w-1 group-hover:bg-primary" style={{ cursor: "ew-resize" }} />
                    </div>
                  )}
                  {isSplitPreview && (
                    <>
                      <div className="pointer-events-none absolute bottom-12 left-3 rounded bg-background/85 px-2 py-1 text-[10px] font-medium text-muted-foreground">
                        Original
                      </div>
                      <div className="pointer-events-none absolute bottom-12 right-3 rounded bg-background/85 px-2 py-1 text-[10px] font-medium text-primary">
                        {processedPreviewLabel}
                      </div>
                    </>
                  )}
                  {isProcessedPreview && (
                    <div className="pointer-events-none absolute bottom-12 right-3 rounded bg-background/85 px-2 py-1 text-[10px] font-medium text-primary">
                      {processedPreviewLabel}
                    </div>
                  )}
                  <div className="absolute bottom-2 left-2 right-2 z-10 flex items-center gap-2 rounded border border-border/80 bg-background/88 px-2 py-1.5 backdrop-blur">
                    <Button
                      disabled={!canPlayPreview}
                      onClick={() => void togglePreviewPlayback()}
                      size="icon"
                      title={canPlayPreview ? (isPreviewPlaying ? "Pause" : "Play") : "Video playback unavailable"}
                      variant="secondary"
                    >
                      {isPreviewPlaying ? <Pause /> : <Play />}
                    </Button>
                    <span className="w-16 shrink-0 text-[11px] tabular-nums text-muted-foreground">{formatSeconds(previewTime)}</span>
                    <input
                      className="min-w-0 flex-1 accent-primary"
                      disabled={!canPlayPreview || effectivePreviewDuration <= 0}
                      max={previewRangeMax || 0}
                      min={previewRangeStart}
                      onChange={(event) => seekPreview(Number(event.target.value))}
                      step={0.01}
                      type="range"
                      value={clamp(previewTime, previewRangeStart, previewRangeMax || previewTime)}
                    />
                    <span className="w-16 shrink-0 text-right text-[11px] tabular-nums text-muted-foreground">
                      {formatSeconds(effectivePreviewDuration)}
                    </span>
                  </div>
                </div>
                <div className="pointer-events-none absolute left-2 top-11 max-w-[72%] rounded border border-border/80 bg-background/80 px-2 py-1 backdrop-blur">
                  <div className="truncate text-xs font-medium text-zinc-200" title={project.media_path}>
                    {compactMiddle(project.media_path.split(/[\\/]/).pop() ?? project.media_path, 72)}
                  </div>
                  <div className="mt-1 flex flex-wrap gap-1 text-[10px] text-muted-foreground">
                    <Badge tone="info">{formatSeconds(summary.duration)}</Badge>
                    <Badge>{summary.video}</Badge>
                    <Badge>{summary.audio}</Badge>
                    <Badge tone={compareMode === "original" ? "neutral" : "info"}>
                      {renderedPreviewSource
                        ? "rendered preview"
                        : compareMode !== "original" && hasLivePreview
                        ? livePreviewLabel
                        : COMPARE_MODES.find((mode) => mode.id === compareMode)?.label}
                    </Badge>
	                    {isRenderingPreview && <Badge tone="info">rendering</Badge>}
	                    {isGeneratingBrowserPreview && <Badge tone="info">proxying</Badge>}
	                    {browserPreviewSource && <Badge tone="info">browser proxy</Badge>}
	                    {previewPlaybackFailed && <Badge tone="warn">thumbnail preview</Badge>}
                  </div>
                </div>
              </>
            ) : (
              <div className="flex h-full flex-col items-center justify-center px-12 text-center">
                <FileVideo className="mb-5 size-12 text-muted-foreground/45" />
                <h1 className="max-w-full truncate text-2xl font-semibold tracking-tight text-zinc-200" title={project.media_path}>
                  {hasMedia ? compactMiddle(project.media_path.split(/[\\/]/).pop() ?? project.media_path, 68) : "Import a source clip"}
                </h1>
                <div className="mt-3 flex flex-wrap items-center justify-center gap-2 text-xs text-muted-foreground">
                  <Badge tone={hasMedia ? "info" : "neutral"}>{formatSeconds(summary.duration)}</Badge>
                  <Badge>{summary.video}</Badge>
                  <Badge>{summary.audio}</Badge>
                  <Badge>{summary.format.split(",")[0]}</Badge>
                </div>
              </div>
            )}
          </div>

          <div className="grid min-h-0 grid-rows-[24px_8px_minmax(0,1fr)] gap-1.5 overflow-hidden bg-muted/20 px-3 py-1.5">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2 text-xs font-medium text-muted-foreground">
                <Activity className="size-3.5" />
                Timeline
              </div>
              <Button disabled={!hasMedia} onClick={addSegment} size="sm" variant="outline">
                Add segment
              </Button>
            </div>
            <div className="h-1.5 self-center rounded-full bg-background">
              <div className="h-full rounded-full bg-primary/80" style={{ width: hasMedia ? "100%" : "0%" }} />
            </div>
            <div className="grid min-h-0 grid-cols-[1fr_1fr_minmax(180px,260px)] gap-2">
              <label className="grid gap-1 text-[11px] text-muted-foreground">
                In
                <input
                  className="h-7 min-w-0 rounded border border-input bg-background px-2 text-sm text-foreground outline-none focus:ring-2 focus:ring-ring"
                  min={0}
                  onChange={(event) => updateRange("in_point", Number(event.target.value))}
                  step={0.001}
                  type="number"
                  value={project.in_point}
                />
              </label>
              <label className="grid gap-1 text-[11px] text-muted-foreground">
                Out
                <input
                  className="h-7 min-w-0 rounded border border-input bg-background px-2 text-sm text-foreground outline-none focus:ring-2 focus:ring-ring"
                  min={0}
                  onChange={(event) => updateRange("out_point", Number(event.target.value))}
                  step={0.001}
                  type="number"
                  value={project.out_point}
                />
              </label>
              <div className="flex min-w-0 items-end gap-2 overflow-hidden">
                {project.segments.slice(-2).map((segment) => (
                  <div key={segment.id} className="min-w-0 rounded border border-border/70 bg-background px-2 py-1">
                    <div className="truncate text-xs font-medium">{segment.name}</div>
                    <div className="text-[10px] text-muted-foreground">
                      {formatSeconds(segment.start)} - {formatSeconds(segment.end)}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>

          {activeExportJob && (
            <>
              <div
                className="cursor-row-resize bg-border/60 hover:bg-primary/50"
                onPointerDown={startBottomPanelResize}
                style={{ cursor: "ns-resize" }}
                title="Resize export monitor"
              />

              <div className="min-h-0 bg-muted/15 p-1.5">
                <div className="min-h-0 rounded border border-border/70 bg-background/60 p-2">
              <div className="mb-2 flex items-center justify-between gap-2">
                <div className="flex items-center gap-2 text-xs font-medium text-muted-foreground">
                  <Play className="size-3.5" />
                  Export progress
                </div>
                <div className="flex items-center gap-2">
                  <Button
                    disabled={!commandPreview.length}
                    onClick={() => void navigator.clipboard.writeText(formattedCommandPreview)}
                    size="sm"
                    variant="outline"
                  >
                    <Copy data-icon="inline-start" />
                    Copy FFmpeg command
                  </Button>
                  <Badge tone={activeExportJob.state === "completed" ? "good" : activeExportJob.state === "failed" ? "warn" : "info"}>
                    {activeExportJob.state}
                  </Badge>
                </div>
              </div>
                <div className="grid h-full min-h-[58px] content-between rounded border border-border/70 bg-background p-2">
                  <div className="flex items-center justify-between gap-3 text-xs">
                    <div className="min-w-0">
                      <div className="truncate font-medium">{compactMiddle(project.output_settings.output_path, 58)}</div>
                      <div className="mt-0.5 text-[10px] text-muted-foreground">
                        {formatSeconds(activeExportJob.progress.out_time_seconds ?? 0)}
                        {activeExportJob.duration_seconds ? ` / ${formatSeconds(activeExportJob.duration_seconds)}` : ""}
                        {activeExportJob.progress.speed ? ` · ${activeExportJob.progress.speed}` : ""}
                      </div>
                    </div>
                    <Button
                      disabled={activeExportIsTerminal || activeExportJob.state === "cancel_requested"}
                      onClick={cancelExportJob}
                      size="sm"
                      variant="outline"
                    >
                      Cancel
                    </Button>
                  </div>
                  <div>
                    <div className="mb-1 flex items-center justify-between text-[10px] text-muted-foreground">
                      <span>{exportPercent}%</span>
                      <span>{activeExportJob.error ? compactMiddle(activeExportJob.error, 56) : activeExportJob.job_id.slice(0, 8)}</span>
                    </div>
                    <div className="h-2 rounded-full bg-muted">
                      <div className="h-full rounded-full bg-primary transition-[width]" style={{ width: `${exportPercent}%` }} />
                    </div>
                  </div>
                </div>
                </div>
              </div>
            </>
          )}
        </div>

        <div
          className="group relative cursor-ew-resize touch-none bg-transparent"
          onPointerDown={startRightPanelResize}
          style={{ cursor: "ew-resize" }}
          title="Resize effects panel"
        >
          <div className="absolute inset-y-0 left-1/2 w-px -translate-x-1/2 bg-border/80 transition-all group-hover:w-1 group-hover:bg-primary" style={{ cursor: "ew-resize" }} />
        </div>

        <aside className="min-h-0 overflow-hidden bg-muted/15">
          <Tabs defaultValue="effects" className="flex h-full flex-col">
            <div className="flex items-center justify-between border-b border-border/70 p-1.5">
              <TabsList>
                <TabsTrigger value="effects">Effects</TabsTrigger>
                <TabsTrigger value="media">Media</TabsTrigger>
                <TabsTrigger value="logs">Logs</TabsTrigger>
              </TabsList>
            </div>

            <TabsContent value="effects" className="min-h-0 flex-1 overflow-hidden p-1">
              <div className="grid h-full min-h-0 grid-rows-[minmax(220px,1.35fr)_minmax(116px,0.7fr)_minmax(150px,0.9fr)] gap-1.5">
                <section className="flex min-h-0 flex-col overflow-hidden rounded-md border border-border bg-background">
                  <div className="flex items-center justify-between gap-2 border-b border-border/70 px-2 py-1.5">
                    <div className="text-xs font-semibold text-foreground">Effect Library</div>
                    <div className="text-[10px] tabular-nums text-muted-foreground">{visibleEffectGroups.length} / {effectGroups.length}</div>
                  </div>
                  <div className="grid gap-1.5 border-b border-border/70 p-1.5">
                    <div className="relative">
                      <Search className="absolute left-2 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground" />
                      <input
                        className="h-7 w-full rounded-md border border-input bg-background pl-7 pr-2 text-xs outline-none focus:ring-2 focus:ring-ring"
                        onChange={(event) => setQuery(event.target.value)}
                        placeholder="Search effects"
                        value={query}
                      />
                    </div>
                    <div className="flex flex-wrap gap-1">
                      {EFFECT_QUICK_FILTERS.map((filter) => (
                        <button
                          key={filter}
                          className={cn(
                            "h-6 rounded border border-border px-2 text-[10px] capitalize text-muted-foreground hover:bg-accent hover:text-foreground",
                            quickFilter === filter && "border-primary/60 bg-primary/10 text-foreground",
                          )}
                          onClick={() => setQuickFilter(filter)}
                          type="button"
                        >
                          {filter}
                        </button>
                      ))}
                    </div>
                  </div>
                  <div className="grid min-h-0 flex-1 grid-cols-[minmax(118px,0.8fr)_minmax(118px,0.8fr)_minmax(210px,1.6fr)] gap-1.5 p-1.5">
                    <div className="min-h-0 overflow-auto rounded-md border border-border/70 bg-muted/10 p-1">
                      {primaryTaxonomyNodes.map((node) => (
                        <button
                          key={node.id}
                          className={cn(
                            "flex h-6 w-full items-center justify-between gap-1.5 rounded px-2 text-left text-[10px] text-muted-foreground hover:bg-accent hover:text-foreground",
                            selectedCategory === node.id && "bg-secondary text-secondary-foreground",
                          )}
                          onClick={() => setSelectedCategory(node.id)}
                          type="button"
                        >
                          <span className="truncate">{formatTaxonomyLabel(node.label)}</span>
                          <span className="tabular-nums">{node.count}</span>
                        </button>
                      ))}
                    </div>
                    <div className="min-h-0 overflow-auto rounded-md border border-border/70 bg-muted/10 p-1">
                      {subcategoryNodes.map((node) => (
                        <button
                          key={node.id}
                          className={cn(
                            "flex h-6 w-full items-center justify-between gap-1.5 rounded px-2 text-left text-[10px] text-muted-foreground hover:bg-accent hover:text-foreground",
                            selectedSubcategory === node.id && "bg-secondary text-secondary-foreground",
                          )}
                          onClick={() => setSelectedSubcategory(node.id)}
                          type="button"
                        >
                          <span className="truncate">{formatTaxonomyLabel(node.label)}</span>
                          <span className="tabular-nums">{node.count}</span>
                        </button>
                      ))}
                    </div>
                    <div className="grid min-h-0 content-start gap-0.5 overflow-auto">
                      {visibleEffectGroups.length ? (
                        visibleEffectGroups.map((group) => {
                          const visibleVariants = group.variants.filter(
                            (variant) =>
                              effectMatchesSearch(variant, query.trim().toLowerCase()) &&
                              effectMatchesQuickFilter(variant, quickFilter),
                          )
                          const choice =
                            quickFilter === "vapoursynth" || quickFilter === "avisynth"
                              ? quickFilter
                              : effectEngineChoices[group.id] ?? "auto"
                          const effect = pickEffectVariant({ ...group, variants: visibleVariants }, choice)
                          if (!effect) return null
                          const engines = group.variants.map((variant) => variant.engine)
                          const hasEngineChoice = group.variants.length > 1
                          const canAddEffect = canAddEffectToChain(effect)
                          return (
                          <div
                            className={cn(
                              "group grid min-h-10 grid-cols-[minmax(0,1fr)_68px_24px] items-center gap-1 rounded border border-transparent px-2 py-1 hover:border-border hover:bg-accent/45",
                              !canAddEffect && "opacity-60",
                            )}
                            key={group.id}
                            onDoubleClick={() => {
                              if (canAddEffect) addEffect(effect)
                            }}
                            title={canAddEffect ? "Double click to add" : "Plugin is listed but not usable yet"}
                          >
                            <div className="min-w-0">
                              <div className="flex min-w-0 items-center">
                                <span className="truncate text-[12px] font-medium">{effect.name}</span>
                              </div>
                              <div className="mt-0.5 flex min-w-0 items-center gap-1.5 text-[10px] text-muted-foreground">
                                <span>{hasEngineChoice ? engines.map((engine) => (engine === "vapoursynth" ? "VS" : "AVS")).join("/") : effect.engine}</span>
                                {effect.recommended && <span className="text-primary">rec</span>}
                                <span
                                  className={cn(
                                    isEffectRenderable(effect) ? "text-emerald-300" : "text-muted-foreground",
                                  )}
                                >
                                  {isEffectRenderable(effect) ? effect.install_status : "not usable"}
                                </span>
                                <span className="truncate">
                                  {effectTaxonomyPath(effect).concat(effect.name).map(formatTaxonomyLabel).join(" > ")}
                                </span>
                              </div>
                            </div>
                            {hasEngineChoice ? (
                              <select
                                className="deepframe-select h-6 min-w-0 rounded border border-input px-1 text-[10px] outline-none focus:ring-2 focus:ring-ring"
                                onChange={(event) =>
                                  setEffectEngineChoices((current) => ({
                                    ...current,
                                    [group.id]: event.target.value as EffectEngineChoice,
                                  }))
                                }
                                onClick={(event) => event.stopPropagation()}
                                onDoubleClick={(event) => event.stopPropagation()}
                                title="Choose script engine"
                                value={effectEngineChoices[group.id] ?? "auto"}
                              >
                                <option value="auto">Auto</option>
                                {engines.includes("vapoursynth") && <option value="vapoursynth">VS</option>}
                                {engines.includes("avisynth") && <option value="avisynth">AVS</option>}
                              </select>
                            ) : (
                              <span className="truncate text-right text-[10px] text-muted-foreground">{effect.engine === "vapoursynth" ? "VS" : "AVS"}</span>
                            )}
                            <button
                              className="flex size-6 items-center justify-center rounded border border-border bg-secondary text-secondary-foreground opacity-90 hover:border-primary hover:text-primary disabled:cursor-not-allowed disabled:opacity-35"
                              disabled={!canAddEffect}
                              onClick={(event) => {
                                event.stopPropagation()
                                addEffect(effect)
                              }}
                              onDoubleClick={(event) => event.stopPropagation()}
                              type="button"
                              aria-label={`Add ${effect.name}`}
                              title={canAddEffect ? "Add to chain" : "Not usable yet"}
                            >
                              <Plus className="size-3.5" />
                            </button>
                          </div>
                          )
                        })
                      ) : (
                        <div className="m-2 rounded-md border border-dashed border-border p-4 text-center text-xs text-muted-foreground">
                          No effects match the current filters.
                        </div>
                      )}
                    </div>
                  </div>
                </section>

                <section className="flex min-h-0 flex-col overflow-hidden rounded-md border border-border bg-background">
                  <div className="flex items-center justify-between gap-2 border-b border-border/70 px-2 py-1.5">
                    <div className="flex min-w-0 items-center gap-2 text-xs font-semibold">
                      <ListFilter className="size-3.5 text-muted-foreground" />
                      <span>Active Chain</span>
                      <span className="text-[10px] tabular-nums text-muted-foreground">{project.effect_chain.length}</span>
                    </div>
                    <div className="flex items-center gap-1.5">
                      {canSweepSplit && (
                        <Button
                          className="h-7 px-2.5 font-semibold"
                          onClick={() => {
                            setCompareMode("split")
                            setIsSplitSweepActive((current) => !current)
                          }}
                          size="sm"
                          title="Move the split line continuously"
                          variant={isSplitSweepActive ? "secondary" : "quiet"}
                        >
                          <SquareSplitHorizontal data-icon="inline-start" />
                          {isSplitSweepActive ? "Stop sweep" : "Sweep split"}
                        </Button>
                      )}
                      <Button
                        className="h-7 px-2.5 font-semibold"
                        disabled={!hasMedia || !project.effect_chain.length || isRenderingPreview}
                        onClick={() => void previewEffectChain()}
                        size="sm"
                        title={hasMedia ? "Render a short processed preview" : "Import media before preview"}
                        variant="default"
                      >
                        <Eye data-icon="inline-start" />
                        {isRenderingPreview ? "Rendering" : "Render preview"}
                      </Button>
                    </div>
                  </div>
                  <div className="grid min-h-0 content-start overflow-auto">
                    {project.effect_chain.length ? (
                      project.effect_chain.map((effect) => (
                        <div
                          key={effect.id}
                          className={cn(
                            "group grid h-7 cursor-grab select-none grid-cols-[18px_22px_minmax(48px,66px)_minmax(0,1fr)_24px] items-center gap-1 border-b border-border/70 px-1 text-xs last:border-b-0 hover:bg-accent/45 active:cursor-grabbing",
                            selectedChainItem?.id === effect.id && "bg-primary/10",
                            draggedEffectId === effect.id && "bg-primary/15",
                            dropTargetEffectId === effect.id &&
                              draggedEffectId !== effect.id &&
                              "bg-primary/10 outline outline-1 outline-primary/60",
                          )}
                          draggable
                          onClick={() => setSelectedChainItemId(effect.id)}
                          onDragEnd={endChainDrag}
                          onDragOver={(event) => dragOverChainItem(event, effect.id)}
                          onDragStart={(event) => startChainDrag(event, effect.id)}
                          onDrop={(event) => dropChainItem(event, effect.id)}
                        >
                          <div className="flex size-4 shrink-0 items-center justify-center text-muted-foreground">
                            <GripVertical className="size-3" />
                          </div>
                          <button
                            className="flex size-4 items-center justify-center border border-input bg-muted/30 text-foreground hover:border-primary"
                            onClick={(event) => {
                              event.stopPropagation()
                              toggleEffect(effect.id)
                            }}
                            aria-label={effect.enabled ? `Disable ${effect.name}` : `Enable ${effect.name}`}
                            title={effect.enabled ? "Disable effect" : "Enable effect"}
                            type="button"
                          >
                            {effect.enabled && <Check className="size-3" />}
                          </button>
                          <div className="truncate text-[10px] text-muted-foreground">{effect.category}</div>
                          <div className="truncate font-medium">{effect.name}</div>
                          <button
                            className="flex size-5 items-center justify-center rounded text-muted-foreground hover:bg-accent hover:text-foreground"
                            onClick={(event) => {
                              event.stopPropagation()
                              removeEffect(effect.id)
                            }}
                            aria-label={`Remove ${effect.name}`}
                            title="Remove effect"
                            type="button"
                          >
                            <X className="size-3.5" />
                          </button>
                        </div>
                      ))
                    ) : (
                      <div className="m-2 rounded-md border border-dashed border-border p-3 text-center text-xs text-muted-foreground">
                        Add effects with the plus button or double click.
                      </div>
                    )}
                  </div>
                </section>

                <section className="flex min-h-0 flex-col overflow-hidden rounded-md border border-border bg-background">
                  <div className="flex items-center justify-between gap-2 border-b border-border/70 px-2 py-1.5">
                    <div className="text-xs font-semibold">Inspector</div>
                    <div className="min-w-0 truncate text-[11px] text-muted-foreground">
                      {selectedChainItem ? selectedChainItem.name : "No effect selected"}
                    </div>
                  </div>
                  <div className="grid content-start gap-1 overflow-auto p-1.5">
                    {selectedChainItem && selectedParameters.length ? (
                      selectedParameters.map((parameter) => {
                        const value = parameterValue(selectedChainItem, selectedEffectDescriptor, parameter)
                        const inputId = `${selectedChainItem.id}-${parameter.name}`
                        const isNumber = parameter.type === "int" || parameter.type === "float"
                        const hasSlider =
                          isNumber && typeof parameter.min === "number" && typeof parameter.max === "number"
                        const hasAuto = Boolean(parameter.auto)
                        const autoSelected = hasAuto && isAutoParameterValue(value)
                        const editableValue = autoSelected ? parameterSuggestedValue(parameter) : value
                        const numericValue = Number(value)
                        const editableNumericValue = Number(editableValue)

                        return (
                          <div key={parameter.name} className="grid gap-0.5 rounded border border-border/70 bg-muted/20 px-2 py-1">
                            <div className="grid grid-cols-[72px_minmax(0,1fr)] items-center gap-2">
                              <label className="truncate text-[10px] font-medium" htmlFor={inputId}>
                                {parameter.label || parameter.name}
                              </label>
                              <div className="min-w-0">
                                {parameter.type === "enum" ? (
                                  <div className={cn("grid items-center gap-1", hasAuto && "grid-cols-[46px_minmax(0,1fr)]")}>
                                    {hasAuto && (
                                      <button
                                        className={cn(
                                          "h-5 rounded border px-1 text-[10px]",
                                          autoSelected ? "border-primary bg-primary/20 text-primary" : "border-border text-muted-foreground",
                                        )}
                                        onClick={() =>
                                          updateEffectParameter(
                                            selectedChainItem.id,
                                            parameter,
                                            autoSelected ? String(parameterSuggestedValue(parameter)) : AUTO_PARAMETER_VALUE,
                                          )
                                        }
                                        type="button"
                                      >
                                        Auto
                                      </button>
                                    )}
                                    <select
                                      className="deepframe-select h-5 w-full rounded border border-input px-1.5 text-[10px] outline-none focus:ring-1 focus:ring-ring disabled:opacity-50"
                                      disabled={autoSelected}
                                      id={inputId}
                                      onChange={(event) => updateEffectParameter(selectedChainItem.id, parameter, event.target.value)}
                                      value={String(editableValue)}
                                    >
                                      {(parameter.options?.length ? parameter.options : [String(editableValue)]).map((option) => (
                                        <option key={option} value={option}>
                                          {option}
                                        </option>
                                      ))}
                                    </select>
                                  </div>
                                ) : parameter.type === "bool" ? (
                                  <div className="flex items-center gap-2">
                                    {hasAuto && (
                                      <button
                                        className={cn(
                                          "h-5 rounded border px-1 text-[10px]",
                                          autoSelected ? "border-primary bg-primary/20 text-primary" : "border-border text-muted-foreground",
                                        )}
                                        onClick={() =>
                                          updateEffectParameter(
                                            selectedChainItem.id,
                                            parameter,
                                            autoSelected ? Boolean(parameterSuggestedValue(parameter)) : AUTO_PARAMETER_VALUE,
                                          )
                                        }
                                        type="button"
                                      >
                                        Auto
                                      </button>
                                    )}
                                    <input
                                      checked={!autoSelected && Boolean(editableValue)}
                                      className="size-3.5 accent-primary disabled:opacity-50"
                                      disabled={autoSelected}
                                      id={inputId}
                                      onChange={(event) => updateEffectParameter(selectedChainItem.id, parameter, event.target.checked)}
                                      type="checkbox"
                                    />
                                  </div>
                                ) : isNumber ? (
                                  <div
                                    className={cn(
                                      "grid items-center gap-1",
                                      hasAuto && hasSlider
                                        ? "grid-cols-[46px_minmax(0,1fr)_52px]"
                                        : hasAuto
                                          ? "grid-cols-[46px_minmax(0,1fr)]"
                                          : hasSlider && "grid-cols-[minmax(0,1fr)_52px]",
                                    )}
                                  >
                                    {hasAuto && (
                                      <button
                                        className={cn(
                                          "h-5 rounded border px-1 text-[10px]",
                                          autoSelected ? "border-primary bg-primary/20 text-primary" : "border-border text-muted-foreground",
                                        )}
                                        onClick={() =>
                                          updateEffectParameter(
                                            selectedChainItem.id,
                                            parameter,
                                            autoSelected ? String(parameterSuggestedValue(parameter)) : AUTO_PARAMETER_VALUE,
                                          )
                                        }
                                        type="button"
                                      >
                                        Auto
                                      </button>
                                    )}
                                    {hasSlider && (
                                      <input
                                        className="parameter-range min-w-0 disabled:opacity-50"
                                        disabled={autoSelected}
                                        id={inputId}
                                        max={parameter.max}
                                        min={parameter.min}
                                        onChange={(event) => updateEffectParameter(selectedChainItem.id, parameter, event.target.value)}
                                        step={parameterStep(parameter)}
                                        type="range"
                                        value={Number.isFinite(editableNumericValue) ? editableNumericValue : Number(parameterSuggestedValue(parameter))}
                                      />
                                    )}
                                    <input
                                      className="parameter-number h-5 min-w-0 rounded border border-input bg-background px-1.5 text-[10px] outline-none focus:ring-1 focus:ring-ring disabled:opacity-50"
                                      disabled={autoSelected}
                                      id={hasSlider ? undefined : inputId}
                                      max={parameter.max}
                                      min={parameter.min}
                                      onChange={(event) => updateEffectParameter(selectedChainItem.id, parameter, event.target.value)}
                                      step={parameterStep(parameter)}
                                      type="number"
                                      value={autoSelected ? "" : String(editableValue)}
                                      placeholder="Auto"
                                    />
                                  </div>
                                ) : (
                                  <div className={cn("grid items-center gap-1", hasAuto && "grid-cols-[46px_minmax(0,1fr)]")}>
                                    {hasAuto && (
                                      <button
                                        className={cn(
                                          "h-5 rounded border px-1 text-[10px]",
                                          autoSelected ? "border-primary bg-primary/20 text-primary" : "border-border text-muted-foreground",
                                        )}
                                        onClick={() =>
                                          updateEffectParameter(
                                            selectedChainItem.id,
                                            parameter,
                                            autoSelected ? String(parameterSuggestedValue(parameter)) : AUTO_PARAMETER_VALUE,
                                          )
                                        }
                                        type="button"
                                      >
                                        Auto
                                      </button>
                                    )}
                                    <input
                                      className="h-5 w-full rounded border border-input bg-background px-1.5 text-[10px] outline-none focus:ring-1 focus:ring-ring disabled:opacity-50"
                                      disabled={autoSelected}
                                      id={inputId}
                                      onChange={(event) => updateEffectParameter(selectedChainItem.id, parameter, event.target.value)}
                                      placeholder={autoSelected ? "Auto" : undefined}
                                      type="text"
                                      value={autoSelected ? "" : String(editableValue)}
                                    />
                                  </div>
                                )}
                              </div>
                            </div>
                            {parameter.description && (
                              <div className="h-3 truncate text-[9px] leading-3 text-muted-foreground" title={parameter.description}>
                                {parameter.description}
                                {parameter.unit ? ` (${parameter.unit})` : ""}
                              </div>
                            )}
                          </div>
                        )
                      })
                    ) : (
                      <div className="rounded-md border border-dashed border-border p-3 text-center text-xs text-muted-foreground">
                        Select a chain row to edit parameters.
                      </div>
                    )}
                  </div>
                </section>
              </div>
            </TabsContent>

            <TabsContent value="media" className="min-h-0 flex-1 p-2">
              <div className="grid gap-2">
                {[
                  ["Path", project.media_path ? compactMiddle(project.media_path, 82) : "No media"],
                  ["Duration", formatSeconds(summary.duration)],
                  ["Video", summary.video],
                  ["Audio", summary.audio],
                  ["Preset", project.selected_preset],
                ].map(([label, value]) => (
                  <div key={label} className="rounded-md border border-border bg-background px-3 py-2">
                    <div className="text-[10px] font-medium uppercase text-muted-foreground">{label}</div>
                    <div className="mt-1 truncate text-sm">{value}</div>
                  </div>
                ))}
              </div>
              <div className="mt-3 rounded-md border border-border bg-background">
                <div className="border-b border-border px-2 py-1.5 text-xs font-medium text-muted-foreground">Export command</div>
	                <pre className="max-h-40 overflow-auto p-2 font-mono text-[11px] leading-relaxed text-zinc-300">
	                  {commandPreview.length ? formattedCommandPreview : "Start an export to inspect the FFmpeg command."}
	                </pre>
              </div>
            </TabsContent>

            <TabsContent value="logs" className="min-h-0 flex-1 p-2">
              <div className="flex h-full min-h-0 flex-col gap-2">
                <section className="flex min-h-40 flex-[0.85] flex-col overflow-hidden rounded-md border border-border bg-background">
                  <div className="flex items-center justify-between gap-2 border-b border-border px-2 py-1.5">
                    <div className="flex min-w-0 items-center gap-2 text-xs font-medium text-muted-foreground">
                      <Braces className="size-3.5" />
                      <span>Script preview</span>
                      {scriptValidation && <span className="truncate text-[10px] font-normal">{scriptValidation}</span>}
                    </div>
                    <Button
                      disabled={isValidatingScript || !hasMedia}
                      onClick={() => void validateScriptChain()}
                      size="sm"
                      title={hasMedia ? "Validate generated scripts" : "Import media before validation"}
                      variant="outline"
                    >
                      {isValidatingScript ? "Checking" : "Validate"}
                    </Button>
                  </div>
                  <pre className="min-h-0 flex-1 overflow-auto p-2 font-mono text-[11px] leading-relaxed text-zinc-300">{script}</pre>
                </section>
                <section className="grid min-h-0 flex-1 content-start gap-1 overflow-auto">
                {logs.map((line) => (
                  <pre key={line} className="overflow-hidden text-ellipsis rounded border border-border bg-background p-2 font-mono text-[11px] text-muted-foreground">
                    {line}
                  </pre>
                ))}
                </section>
              </div>
            </TabsContent>
          </Tabs>
        </aside>
      </section>
    </main>
  )
}
