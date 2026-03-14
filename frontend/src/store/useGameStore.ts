import { create } from 'zustand'
import type { AgentName, AgentState, AgentStatus, ChatMessage, DocSections, SessionInfo, SessionMeta, VersionEntry } from '../types'

export interface ReviewIssue {
  id: number
  priority: 'P0' | 'P1' | 'P2' | 'P3'
  category: 'gameplay' | 'art' | 'code'
  desc: string
  location?: string
}

export interface ReviewFix {
  issue_id: number
  desc: string
  lines_changed: number
}

export interface DiffLine {
  type: 'add' | 'remove' | 'context'
  content: string
}

export interface DiffHunk {
  header: string
  lines: DiffLine[]
}

const INITIAL_AGENTS: AgentState[] = [
  { name: 'requirement_analyst', label: '需求分析',  icon: '⚙',  status: 'idle', description: '解析用户描述，生成结构化需求' },
  { name: 'gameplay_designer',   label: '玩法设计',  icon: '🎮', status: 'idle', description: '设计卡牌体系、关卡结构、组合机制' },
  { name: 'worldview_builder',   label: '世界观',    icon: '🌍', status: 'idle', description: '构建背景故事、场景风格、叙事方式' },
  { name: 'art_director',        label: '美术资源',  icon: '🎨', status: 'idle', description: '规划素材清单、AI提示词、风格规范' },
  { name: 'tech_architect',      label: '技术方案',  icon: '💻', status: 'idle', description: '输出技术选型、架构设计、代码示例' },
  { name: 'doc_integrator',      label: '文档整合',  icon: '📄', status: 'idle', description: '合并所有模块为完整设计方案' },
]

interface GameStore {
  // 会话
  session: SessionInfo | null
  setSession: (s: SessionInfo | null) => void

  // Agent 状态
  agents: AgentState[]
  updateAgentStatus: (name: AgentName, status: AgentStatus) => void
  resetAgents: () => void

  // 对话消息
  messages: ChatMessage[]
  addMessage: (msg: Omit<ChatMessage, 'id' | 'timestamp'>) => void
  setMessages: (msgs: ChatMessage[]) => void
  streamingText: string
  appendStreamingText: (t: string) => void
  flushStreamingText: () => void

  // 文档各章节
  sections: DocSections
  updateSection: (key: keyof DocSections, content: string) => void

  // 版本历史
  versionHistory: VersionEntry[]
  setVersionHistory: (v: VersionEntry[]) => void

  // UI 状态
  activeSection: keyof DocSections | 'all'
  setActiveSection: (s: keyof DocSections | 'all') => void
  showDiff: boolean
  setShowDiff: (v: boolean) => void
  prevSections: Partial<DocSections>
  snapshotSections: () => void
  isWaitingReview: boolean
  setIsWaitingReview: (v: boolean) => void
  isGenerating: boolean
  setIsGenerating: (v: boolean) => void

  // 历史会话列表
  sessionList: SessionMeta[]
  setSessionList: (list: SessionMeta[]) => void
  removeSessionFromList: (id: string) => void

  // 切换新 session 时全量重置（sessionList 不清空）
  resetForNewSession: () => void

  // 游戏工坊
  gameCode: string
  setGameCode: (c: string) => void
  artAssets: Record<string, string>
  setArtAssets: (a: Record<string, string>) => void
  gameCodeStreaming: string
  appendGameCodeToken: (t: string) => void
  clearGameCodeStreaming: () => void

  // 创建流水线步骤
  // 0: 输入描述  1: 方案生成中  2: 确认方案  3: 游戏生成中  4: 游戏就绪
  pipelineStep: number
  setPipelineStep: (n: number) => void

  // 美术样本（3张）
  artSamples: Record<string, string>   // filename → url_path
  setArtSamples: (a: Record<string, string>) => void
  artSamplesGenerating: boolean
  setArtSamplesGenerating: (v: boolean) => void

  // 代码生成进度
  codeGenProgress: string
  setCodeGenProgress: (s: string) => void
  codeGenDone: boolean
  setCodeGenDone: (v: boolean) => void

  // 美术生成进度
  artGenItems: Array<{ filename: string; url_path: string; category: string; error?: string }>
  artGenTotal: number
  setArtGenTotal: (n: number) => void
  addArtGenItem: (item: { filename: string; url_path: string; category: string; error?: string }) => void
  resetArtGen: () => void
  artGenDone: boolean
  setArtGenDone: (v: boolean) => void

  // 代码审查
  reviewInProgress: boolean
  setReviewInProgress: (v: boolean) => void
  reviewDone: boolean
  setReviewDone: (v: boolean) => void
  reviewIssues: ReviewIssue[]
  addReviewIssue: (issue: ReviewIssue) => void
  reviewFixes: ReviewFix[]
  addReviewFix: (fix: ReviewFix) => void
  reviewDiff: DiffHunk[]
  setReviewDiff: (d: DiffHunk[]) => void
  reviewSummary: string
  setReviewSummary: (s: string) => void
  reviewChangedLines: number
  setReviewChangedLines: (n: number) => void

  // 代码实时修改
  modifyInProgress: boolean
  setModifyInProgress: (v: boolean) => void
  modifyAnalysis: string
  setModifyAnalysis: (s: string) => void
  modifyResults: Array<{ index: number; file: string; ok: boolean; reason: string }>
  addModifyResult: (r: { index: number; file: string; ok: boolean; reason: string }) => void
  modifyChangedFiles: string[]
  setModifyChangedFiles: (f: string[]) => void
  modifyHistory: Array<{ instruction: string; changedFiles: string[]; timestamp: number }>
  addModifyHistory: (h: { instruction: string; changedFiles: string[] }) => void
  resetModify: () => void
}

export const useGameStore = create<GameStore>((set, get) => ({
  session: null,
  setSession: (s) => set({ session: s }),

  agents: INITIAL_AGENTS,
  updateAgentStatus: (name, status) =>
    set((state) => ({
      agents: state.agents.map((a) => (a.name === name ? { ...a, status } : a)),
    })),
  resetAgents: () => set({ agents: INITIAL_AGENTS.map((a) => ({ ...a, status: 'idle' })) }),

  messages: [],
  addMessage: (msg) =>
    set((state) => ({
      messages: [
        ...state.messages,
        { ...msg, id: crypto.randomUUID(), timestamp: Date.now() },
      ],
    })),
  setMessages: (msgs) => set({ messages: msgs }),
  streamingText: '',
  appendStreamingText: (t) => set((s) => ({ streamingText: s.streamingText + t })),
  flushStreamingText: () => {
    const text = get().streamingText
    if (!text) return
    get().addMessage({ role: 'ai', content: text })
    set({ streamingText: '' })
  },

  sections: { gameplay: '', worldview: '', art: '', tech: '', final: '' },
  updateSection: (key, content) =>
    set((s) => ({ sections: { ...s.sections, [key]: content } })),

  versionHistory: [],
  setVersionHistory: (v) => set({ versionHistory: v }),

  activeSection: 'all',
  setActiveSection: (s) => set({ activeSection: s }),
  showDiff: false,
  setShowDiff: (v) => set({ showDiff: v }),
  prevSections: {},
  snapshotSections: () => set((s) => ({ prevSections: { ...s.sections } })),

  isWaitingReview: false,
  setIsWaitingReview: (v) => set({ isWaitingReview: v }),
  isGenerating: false,
  setIsGenerating: (v) => set({ isGenerating: v }),

  sessionList: [],
  setSessionList: (list) => set({ sessionList: list }),
  removeSessionFromList: (id) =>
    set((s) => ({ sessionList: s.sessionList.filter((m) => m.session_id !== id) })),

  resetForNewSession: () =>
    set({
      session:             null,
      agents:              INITIAL_AGENTS.map((a) => ({ ...a, status: 'idle' })),
      messages:            [],
      streamingText:       '',
      sections:            { gameplay: '', worldview: '', art: '', tech: '', final: '' },
      versionHistory:      [],
      activeSection:       'all',
      showDiff:            false,
      prevSections:        {},
      isWaitingReview:     false,
      isGenerating:        false,
      gameCode:            '',
      artAssets:           {},
      gameCodeStreaming:   '',
      pipelineStep:        0,
      artSamples:          {},
      artSamplesGenerating: false,
      codeGenProgress:     '',
      codeGenDone:         false,
      artGenItems:         [],
      artGenTotal:         0,
      artGenDone:          false,
      reviewInProgress:    false,
      reviewDone:          false,
      reviewIssues:        [],
      reviewFixes:         [],
      reviewDiff:          [],
      reviewSummary:       '',
      reviewChangedLines:  0,
      modifyInProgress:    false,
      modifyAnalysis:      '',
      modifyResults:       [],
      modifyChangedFiles:  [],
      modifyHistory:       [],
      // sessionList 不清空，保留历史记录
    }),

  gameCode: '',
  setGameCode: (c) => set({ gameCode: c }),
  artAssets: {},
  setArtAssets: (a) => set({ artAssets: a }),
  gameCodeStreaming: '',
  appendGameCodeToken: (t) => set((s) => ({ gameCodeStreaming: s.gameCodeStreaming + t })),
  clearGameCodeStreaming: () => set({ gameCodeStreaming: '' }),

  pipelineStep: 0,
  setPipelineStep: (n) => set({ pipelineStep: n }),

  artSamples: {},
  setArtSamples: (a) => set({ artSamples: a }),
  artSamplesGenerating: false,
  setArtSamplesGenerating: (v) => set({ artSamplesGenerating: v }),

  codeGenProgress: '',
  setCodeGenProgress: (s) => set({ codeGenProgress: s }),
  codeGenDone: false,
  setCodeGenDone: (v) => set({ codeGenDone: v }),

  artGenItems: [],
  artGenTotal: 0,
  setArtGenTotal: (n) => set({ artGenTotal: n }),
  addArtGenItem: (item) => set((s) => ({ artGenItems: [...s.artGenItems, item] })),
  resetArtGen: () => set({ artGenItems: [], artGenTotal: 0, artGenDone: false }),
  artGenDone: false,
  setArtGenDone: (v) => set({ artGenDone: v }),

  reviewInProgress: false,
  setReviewInProgress: (v) => set({ reviewInProgress: v }),
  reviewDone: false,
  setReviewDone: (v) => set({ reviewDone: v }),
  reviewIssues: [],
  addReviewIssue: (issue) => set((s) => ({ reviewIssues: [...s.reviewIssues, issue] })),
  reviewFixes: [],
  addReviewFix: (fix) => set((s) => ({ reviewFixes: [...s.reviewFixes, fix] })),
  reviewDiff: [],
  setReviewDiff: (d) => set({ reviewDiff: d }),
  reviewSummary: '',
  setReviewSummary: (s) => set({ reviewSummary: s }),
  reviewChangedLines: 0,
  setReviewChangedLines: (n) => set({ reviewChangedLines: n }),

  modifyInProgress: false,
  setModifyInProgress: (v) => set({ modifyInProgress: v }),
  modifyAnalysis: '',
  setModifyAnalysis: (s) => set({ modifyAnalysis: s }),
  modifyResults: [],
  addModifyResult: (r) => set((s) => ({ modifyResults: [...s.modifyResults, r] })),
  modifyChangedFiles: [],
  setModifyChangedFiles: (f) => set({ modifyChangedFiles: f }),
  modifyHistory: [],
  addModifyHistory: (h) => set((s) => ({
    modifyHistory: [...s.modifyHistory, { ...h, timestamp: Date.now() }],
  })),
  resetModify: () => set({
    modifyInProgress: false,
    modifyAnalysis: '',
    modifyResults: [],
    modifyChangedFiles: [],
  }),
}))
