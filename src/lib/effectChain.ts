import type { EffectChainItem } from "@/types/domain"

export function removeChainItem(chain: EffectChainItem[], itemId: string) {
  return chain.filter((item) => item.id !== itemId)
}

export function toggleChainItem(chain: EffectChainItem[], itemId: string) {
  return chain.map((item) => (item.id === itemId ? { ...item, enabled: !item.enabled } : item))
}

export function moveChainItem(chain: EffectChainItem[], draggedId: string, targetId: string) {
  if (draggedId === targetId) return chain

  const fromIndex = chain.findIndex((item) => item.id === draggedId)
  const targetIndex = chain.findIndex((item) => item.id === targetId)

  if (fromIndex < 0 || targetIndex < 0) return chain

  const next = [...chain]
  const [dragged] = next.splice(fromIndex, 1)
  next.splice(Math.min(targetIndex, next.length), 0, dragged)
  return next
}

export function updateChainParameter(
  chain: EffectChainItem[],
  itemId: string,
  parameterName: string,
  value: string | number | boolean,
) {
  return chain.map((item) =>
    item.id === itemId
      ? {
          ...item,
          parameters: {
            ...item.parameters,
            [parameterName]: value,
          },
        }
      : item,
  )
}
