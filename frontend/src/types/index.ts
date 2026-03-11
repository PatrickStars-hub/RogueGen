export type AgentName =
  | 'requirement_analyst'
  | 'gameplay_designer'
  | 'worldview_builder'
  | 'art_director'
  | 'tech_architect'
  | 'doc_integrator'
  | 'intent_parser'
  | 'surgical_editor'

export type AgentStatus = 'idle' | 'running' | 'done' | 'error'

export interface AgentState {
  name: AgentName
  label: string
  icon: string
  status: AgentStatus
  description: string
}

export interface DocSections {
  gameplay: string
  worldview: string
  art: string
  tech: string
  final: string
}

export interface VersionEntry {
  index: number
  checkpoint_id: string
  stage: string
  versions: Record<string, number>
  iteration_count: number
}

export interface ChatMessage {
  id: string
  role: 'user' | 'system' | 'ai'
  content: string
  timestamp: number
}

export interface SessionInfo {
  session_id: string
  current_stage: string
  versions: Record<string, number>
  confirmed: boolean
}

export interface SessionMeta {
  session_id: string
  title: string
  requirement: string
  stage: string
  confirmed: number   // SQLite 存的是 0/1
  created_at: string
  updated_at: string
}

export type SSEEventType =
  | 'status'
  | 'agent_status'
  | 'section_update'
  | 'token'
  | 'interrupt'
  | 'confirmed'
  | 'intent_parsed'
