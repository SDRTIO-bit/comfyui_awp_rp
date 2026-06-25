/* Types shared across the RP UI */

export interface CardMeta {
  card_id: string
  manifest: {
    name: string
    description?: string
    worldbook_entry_count: number
    default_greeting_id?: string
  }
  imported_at: string
}

export interface SessionMeta {
  session_id: string
  turn_count: number
  updated_at: string
  card_id?: string
  card_name?: string
}

export interface WorldbookEntry {
  id: string
  title?: string
  content: string
  tags: string[]
  priority: number
  activation: 'const' | 'select' | 'off'
  enabled: boolean
}

export interface PresetMeta {
  id: string
  name: string
}

export interface WorkflowMeta {
  filename: string
  node_count: number
  link_count: number
  inputs: unknown[]
  outputs: unknown[]
}

export interface WorkflowRole {
  role: string
  label: string
  node_id: number
  node_type: string
  confidence: 'high' | 'low'
  input_type: 'textarea' | 'select' | 'text'
  options_from?: string
  override_inputs?: string[]
  supports_agent_loop?: boolean
}

export interface WorkflowAnalysis {
  filename: string
  node_count: number
  roles: WorkflowRole[]
  unmatched: { node_id: number; type: string; reason: string }[]
}

export interface TurnData {
  index: number
  action: string
  narrative: string
}

export type PageState = 'active' | 'generating' | 'error' | 'empty'

export type ResourceType = 'cards' | 'sessions' | 'worldbook' | 'presets' | 'workflows'
