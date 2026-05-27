import { type ClassValue, clsx } from "clsx"
import { twMerge } from "tailwind-merge"

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

export function compactMiddle(value: string, maxLength = 56) {
  if (value.length <= maxLength) return value
  if (maxLength < 8) return value.slice(0, maxLength)
  const keep = maxLength - 3
  const left = Math.ceil(keep / 2)
  const right = Math.floor(keep / 2)
  return `${value.slice(0, left)}...${value.slice(-right)}`
}

export function formatSeconds(value: number) {
  if (!Number.isFinite(value)) return "00:00.000"
  const minutes = Math.floor(value / 60)
  const seconds = value - minutes * 60
  return `${minutes.toString().padStart(2, "0")}:${seconds.toFixed(3).padStart(6, "0")}`
}
