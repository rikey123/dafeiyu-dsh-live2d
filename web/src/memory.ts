import { apiUrl } from './runtime'
export type Memory = { id: string; content: string; created_at: string }

/** DSH owns plugin memory. Never read the standalone store in that mode. */
export async function localMemories(embedded: boolean): Promise<Memory[]> {
  if (embedded) return []
  const response = await fetch(apiUrl('/api/memories'))
  if (!response.ok) throw new Error(`HTTP ${response.status}`)
  return response.json()
}
