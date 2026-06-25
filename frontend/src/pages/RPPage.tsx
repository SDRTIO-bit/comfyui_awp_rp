import { useEffect, useReducer, useCallback, useMemo, useState } from 'react'
import type {
  PageState,
  ResourceType,
  TurnData,
  CardMeta,
  SessionMeta,
  WorldbookEntry,
  PresetMeta,
  WorkflowMeta,
  WorkflowAnalysis,
} from '../types'
import TopBar from '../components/TopBar'
import LeftRail from '../components/LeftRail'
import ResourcePanel from '../components/ResourcePanel'
import NarrativeFlow from '../components/NarrativeFlow'
import InputDock from '../components/InputDock'
import RightPanel from '../components/RightPanel'
import CardEditor from '../components/CardEditor'

interface State {
  pageState: PageState
  resourceType: ResourceType | null
  inspectorOpen: boolean
  sessionTitle: string
  contextLine: string
  turns: TurnData[]
  cards: CardMeta[]
  sessions: SessionMeta[]
  worldbookEntries: WorldbookEntry[]
  presets: PresetMeta[]
  workflows: WorkflowMeta[]
  analysis: WorkflowAnalysis | null
  activeCardId: string
  activeSessionId: string
  activePresetId: string
  activeWorkflow: string
  currentRound: number
  connOk: boolean
  errorMessage: string
  logs: { time: string; message: string }[]
}

interface RunResponse {
  ok: boolean
  prompt_id?: string
  outputs?: Record<string, string>
  error?: string
}

type Action =
  | { type: 'SET_STATE'; state: PageState }
  | { type: 'TOGGLE_RESOURCE'; resource: ResourceType }
  | { type: 'CLOSE_RESOURCE' }
  | { type: 'TOGGLE_INSPECTOR' }
  | { type: 'SET_DATA'; key: string; data: unknown }
  | { type: 'SET_CONTEXT'; line: string; title: string; round: number }
  | { type: 'SET_CONN'; ok: boolean }
  | { type: 'RESET_SESSION' }
  | { type: 'ADD_TURN'; turn: TurnData }
  | { type: 'SET_ERROR'; message: string }
  | { type: 'LOG'; message: string }

function reducer(state: State, action: Action): State {
  switch (action.type) {
    case 'SET_STATE':
      return { ...state, pageState: action.state, errorMessage: action.state === 'error' ? state.errorMessage : '' }
    case 'TOGGLE_RESOURCE':
      return { ...state, resourceType: state.resourceType === action.resource ? null : action.resource }
    case 'CLOSE_RESOURCE':
      return { ...state, resourceType: null }
    case 'TOGGLE_INSPECTOR':
      return { ...state, inspectorOpen: !state.inspectorOpen }
    case 'SET_DATA':
      return { ...state, [action.key]: action.data }
    case 'SET_CONTEXT':
      return { ...state, contextLine: action.line, sessionTitle: action.title, currentRound: action.round }
    case 'SET_CONN':
      return { ...state, connOk: action.ok }
    case 'RESET_SESSION':
      return { ...state, pageState: 'active', turns: [], currentRound: 0, errorMessage: '' }
    case 'ADD_TURN':
      return {
        ...state,
        pageState: 'active',
        turns: [...state.turns, action.turn],
        currentRound: action.turn.index,
        errorMessage: '',
      }
    case 'SET_ERROR':
      return { ...state, pageState: 'error', errorMessage: action.message }
    case 'LOG':
      return {
        ...state,
        logs: [...state.logs.slice(-19), { time: new Date().toLocaleTimeString(), message: action.message }],
      }
    default:
      return state
  }
}

const initialState: State = {
  pageState: 'empty',
  resourceType: null,
  inspectorOpen: false,
  sessionTitle: 'Story Workshop',
  contextLine: '',
  turns: [],
  cards: [],
  sessions: [],
  worldbookEntries: [],
  presets: [],
  workflows: [],
  analysis: null,
  activeCardId: 'card_demo_001',
  activeSessionId: 'rp-session-001',
  activePresetId: 'long-narrative-v1',
  activeWorkflow: 'rp_agent_web_v1.json',
  currentRound: 0,
  connOk: true,
  errorMessage: '',
  logs: [],
}

async function fetchJson<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init)
  const data = await response.json().catch(() => ({}))
  if (!response.ok) {
    throw new Error(typeof data.error === 'string' ? data.error : `HTTP ${response.status}`)
  }
  return data as T
}

function buildRoles(state: State, text: string) {
  return {
    user_input: text,
    session_id: state.activeSessionId,
    card_id: state.activeCardId,
    preset: state.activePresetId,
    generator: {
      provider: 'deepseek',
      model: 'deepseek-chat',
      profile: 'rp-writer',
      preset_id: state.activePresetId,
      context_mode: 'full_context',
      temperature: 0.85,
      max_tokens: 2048,
      enable_agent_loop: true,
      max_iterations: 5,
      skill_ids: 'rp_thinking_flow,hard_gates_full',
    },
  }
}

function pickNarrative(result: RunResponse): string {
  const outputs = Object.entries(result.outputs ?? {})
  
  // 优先查找 OutputRenderer 节点的输出（通常是 14 或 17 号节点）
  const outputRenderer = outputs.find(([key]) => /^(14|17)\//.test(key))
  if (outputRenderer && typeof outputRenderer[1] === 'string' && outputRenderer[1].trim()) {
    return outputRenderer[1].trim()
  }
  
  // 其次查找包含 'text' 的输出
  const textOutput = outputs.find(([key]) => /text/i.test(key))
  if (textOutput && typeof textOutput[1] === 'string' && textOutput[1].trim()) {
    return textOutput[1].trim()
  }
  
  // 最后查找任何非空字符串输出
  const anyOutput = outputs.find(([, value]) => typeof value === 'string' && value.trim().length > 0)
  return anyOutput?.[1]?.trim() || `运行完成，prompt_id=${result.prompt_id ?? 'unknown'}，但没有文本输出。`
}

function roleNode(analysis: WorkflowAnalysis | null, role: string) {
  const item = analysis?.roles.find(r => r.role === role)
  return item ? `#${item.node_id} ${item.node_type}` : '未识别'
}

export default function RPPage() {
  const [s, dispatch] = useReducer(reducer, initialState)
  const [editingCardId, setEditingCardId] = useState<string | null>(null)

  const activeCard = useMemo(
    () => s.cards.find(c => c.card_id === s.activeCardId),
    [s.cards, s.activeCardId],
  )
  const activeSession = useMemo(
    () => s.sessions.find(item => item.session_id === s.activeSessionId),
    [s.sessions, s.activeSessionId],
  )

  const loadWorldbook = useCallback(async (cardId: string) => {
    try {
      const wb = await fetchJson<WorldbookEntry[]>(`/api/worldbook/${encodeURIComponent(cardId)}`)
      dispatch({ type: 'SET_DATA', key: 'worldbookEntries', data: wb })
    } catch (err) {
      dispatch({ type: 'LOG', message: `世界书加载失败：${err instanceof Error ? err.message : String(err)}` })
    }
  }, [])

  const loadSessionHistory = useCallback(async (sessionId: string) => {
    try {
      const history = await fetchJson<{ turns: TurnData[]; turn_count: number }>(`/api/session/${encodeURIComponent(sessionId)}`)
      if (history.turns && history.turns.length > 0) {
        // 加载历史对话
        for (const turn of history.turns) {
          dispatch({ type: 'ADD_TURN', turn })
        }
        dispatch({ type: 'SET_CONTEXT', title: 'Story Workshop', line: `${sessionId} / 第 ${history.turn_count} 轮`, round: history.turn_count })
        dispatch({ type: 'LOG', message: `已加载会话 ${sessionId} 的 ${history.turn_count} 轮历史对话` })
      }
    } catch (err) {
      // 如果 API 不存在或出错，静默处理
      console.log('Failed to load session history:', err)
    }
  }, [])

  const loadAnalysis = useCallback(async (workflow: string) => {
    try {
      const ana = await fetchJson<WorkflowAnalysis>(`/api/workflows/${encodeURIComponent(workflow)}/analyze`)
      dispatch({ type: 'SET_DATA', key: 'analysis', data: ana })
    } catch (err) {
      dispatch({ type: 'SET_DATA', key: 'analysis', data: null })
      dispatch({ type: 'LOG', message: `工作流分析失败：${err instanceof Error ? err.message : String(err)}` })
    }
  }, [])

  const fetchData = useCallback(async () => {
    const fetchers: [string, string][] = [
      ['cards', '/api/cards'],
      ['sessions', '/api/sessions'],
      ['presets', '/api/presets'],
      ['workflows', '/api/workflows'],
    ]
    const results = await Promise.allSettled(
      fetchers.map(([key, url]) => fetchJson<unknown>(url).then(data => [key, data] as const)),
    )

    let cardId = initialState.activeCardId
    let sessionId = initialState.activeSessionId
    for (const result of results) {
      if (result.status !== 'fulfilled') continue
      const [key, data] = result.value
      dispatch({ type: 'SET_DATA', key, data })
      if (key === 'cards' && Array.isArray(data) && data.length > 0) {
        cardId = (data[0] as CardMeta).card_id
        dispatch({ type: 'SET_DATA', key: 'activeCardId', data: cardId })
      }
      if (key === 'sessions' && Array.isArray(data) && data.length > 0) {
        sessionId = (data[0] as SessionMeta).session_id
        dispatch({ type: 'SET_DATA', key: 'activeSessionId', data: sessionId })
      }
    }

    await Promise.allSettled([loadWorldbook(cardId), loadAnalysis(initialState.activeWorkflow)])

    try {
      const health = await fetchJson<{ status: string }>('/api/health')
      dispatch({ type: 'SET_CONN', ok: health.status === 'ok' })
    } catch {
      dispatch({ type: 'SET_CONN', ok: false })
    }
    dispatch({ type: 'LOG', message: `数据已加载：${sessionId}` })
  }, [loadAnalysis, loadWorldbook])

  useEffect(() => { fetchData() }, [fetchData])

  const runAction = useCallback(async (text: string) => {
    const action = text.trim()
    if (!action || s.pageState === 'generating') return

    dispatch({ type: 'SET_STATE', state: 'generating' })
    dispatch({ type: 'LOG', message: `提交工作流：${s.activeWorkflow}` })

    try {
      const result = await fetchJson<RunResponse>('/api/run-roles', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          workflow: s.activeWorkflow,
          roles: buildRoles(s, action),
        }),
      })
      if (!result.ok) {
        throw new Error(result.error || '工作流运行失败')
      }
      const turn: TurnData = {
        index: s.turns.length + 1,
        action,
        narrative: pickNarrative(result),
      }
      dispatch({ type: 'ADD_TURN', turn })
      dispatch({ type: 'SET_CONTEXT', title: 'Story Workshop', line: `${s.activeSessionId} / 第 ${turn.index} 轮`, round: turn.index })
      dispatch({ type: 'LOG', message: `运行完成：${result.prompt_id ?? 'no prompt_id'}` })
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err)
      dispatch({ type: 'SET_ERROR', message })
      dispatch({ type: 'LOG', message: `运行失败：${message}` })
    }
  }, [s])

  const startNewSession = useCallback(() => {
    dispatch({ type: 'RESET_SESSION' })
    dispatch({ type: 'LOG', message: '已新建会话草稿' })
  }, [])

  const toggleResource = useCallback((r: ResourceType) => dispatch({ type: 'TOGGLE_RESOURCE', resource: r }), [])
  const closeResource = useCallback(() => dispatch({ type: 'CLOSE_RESOURCE' }), [])
  const toggleInspector = useCallback(() => dispatch({ type: 'TOGGLE_INSPECTOR' }), [])
  const retryLast = useCallback((action?: string) => {
    const text = action ?? s.turns.at(-1)?.action ?? '让故事继续。'
    void runAction(text)
  }, [runAction, s.turns])

  const selectCard = useCallback((cardId: string) => {
    dispatch({ type: 'SET_DATA', key: 'activeCardId', data: cardId })
    void loadWorldbook(cardId)
  }, [loadWorldbook])

  const importCard = useCallback(async () => {
    // Create file input element
    const input = document.createElement('input')
    input.type = 'file'
    input.accept = '.json,.png'
    input.onchange = async (e) => {
      const file = (e.target as HTMLInputElement).files?.[0]
      if (!file) return
      
      dispatch({ type: 'LOG', message: `正在导入角色卡：${file.name}` })
      
      try {
        const formData = new FormData()
        formData.append('file', file)
        
        const result = await fetchJson<{ ok: boolean; card_id?: string; name?: string; error?: string }>('/api/cards/import', {
          method: 'POST',
          body: formData,
        })
        
        if (result.ok && result.card_id) {
          dispatch({ type: 'LOG', message: `角色卡导入成功：${result.name}` })
          // Refresh cards list
          const cards = await fetchJson<CardMeta[]>('/api/cards')
          dispatch({ type: 'SET_DATA', key: 'cards', data: cards })
          // Select the imported card
          dispatch({ type: 'SET_DATA', key: 'activeCardId', data: result.card_id })
          void loadWorldbook(result.card_id)
        } else {
          dispatch({ type: 'LOG', message: `导入失败：${result.error}` })
        }
      } catch (err) {
        dispatch({ type: 'LOG', message: `导入错误：${err instanceof Error ? err.message : String(err)}` })
      }
    }
    input.click()
  }, [loadWorldbook])

  const selectSession = useCallback((sessionId: string) => {
    dispatch({ type: 'SET_DATA', key: 'activeSessionId', data: sessionId })
    dispatch({ type: 'SET_STATE', state: 'active' })
    // 加载历史对话
    void loadSessionHistory(sessionId)
  }, [loadSessionHistory])

  const selectPreset = useCallback((presetId: string) => {
    dispatch({ type: 'SET_DATA', key: 'activePresetId', data: presetId })
  }, [])

  const selectWorkflow = useCallback((workflow: string) => {
    dispatch({ type: 'SET_DATA', key: 'activeWorkflow', data: workflow })
    void loadAnalysis(workflow)
  }, [loadAnalysis])

  const contextLine = useMemo(() => {
    const parts = [
      activeCard?.manifest.name,
      activeSession?.session_id ?? s.activeSessionId,
      s.currentRound > 0 ? `第 ${s.currentRound} 轮` : null,
      s.activeWorkflow,
    ].filter(Boolean)
    return parts.join(' / ')
  }, [activeCard, activeSession, s.activeSessionId, s.activeWorkflow, s.currentRound])

  const nodeMapping = useMemo(() => ({
    userInput: roleNode(s.analysis, 'user_input'),
    sessionId: roleNode(s.analysis, 'session_id'),
    cardId: roleNode(s.analysis, 'card_id'),
    generator: roleNode(s.analysis, 'generator'),
    totalMapped: s.analysis?.roles.length ?? 0,
    totalExpected: 5,
  }), [s.analysis])

  const editingCard = useMemo(
    () => s.cards.find(c => c.card_id === editingCardId),
    [s.cards, editingCardId],
  )

  const openCardEditor = useCallback((cardId: string) => {
    setEditingCardId(cardId)
  }, [])

  const closeCardEditor = useCallback(() => {
    setEditingCardId(null)
    // Refresh cards and worldbook after editing
    void fetchData()
  }, [fetchData])

  return (
    <div className="flex flex-col h-full">
      <TopBar
        sessionTitle={s.sessionTitle}
        contextLine={contextLine || s.contextLine}
        connOk={s.connOk}
        onInspectorToggle={toggleInspector}
      />
      <div className="flex flex-1 overflow-hidden relative">
        <LeftRail activeResource={s.resourceType} onToggle={toggleResource} />
        <ResourcePanel
          open={s.resourceType !== null}
          type={s.resourceType}
          cards={s.cards}
          sessions={s.sessions}
          worldbookEntries={s.worldbookEntries}
          presets={s.presets}
          workflows={s.workflows}
          activeCardId={s.activeCardId}
          activeSessionId={s.activeSessionId}
          activePresetId={s.activePresetId}
          activeWorkflow={s.activeWorkflow}
          onSelectCard={selectCard}
          onSelectSession={selectSession}
          onSelectPreset={selectPreset}
          onSelectWorkflow={selectWorkflow}
          onImportCard={importCard}
          onEditCard={openCardEditor}
          onClose={closeResource}
        />
        <div className="flex-1 flex flex-col overflow-hidden min-w-0">
          <div className="flex-1 overflow-y-auto px-8 md:px-12 py-8">
            {s.turns.length > 0 && (
              <NarrativeFlow
                turns={s.turns}
                currentIndex={s.turns.length - 1}
                onInspect={toggleInspector}
                onRetry={retryLast}
              />
            )}
            {s.pageState === 'empty' && (
              <div className="flex flex-col items-center justify-center h-full text-[var(--color-text-3)] gap-3 text-center">
                <svg width="36" height="36" viewBox="0 0 24 24" fill="none" className="opacity-20">
                  <rect x="3" y="2" width="18" height="20" rx="2" stroke="currentColor" strokeWidth="1.3" />
                  <line x1="8" y1="7" x2="16" y2="7" stroke="currentColor" strokeWidth="1" />
                  <line x1="8" y1="11" x2="14" y2="11" stroke="currentColor" strokeWidth="1" />
                </svg>
                <div className="text-sm max-w-[300px] leading-relaxed">
                  选择一个角色卡和会话，或者新建一个故事来开始。
                </div>
                <button
                  type="button"
                  className="bg-[var(--color-accent-dim)] text-[var(--color-text)] px-6 py-2 rounded-md text-sm mt-2 hover:bg-[var(--color-accent)] transition-colors"
                  onClick={startNewSession}
                >
                  新建会话
                </button>
              </div>
            )}
          </div>
          <InputDock
            state={s.pageState}
            errorMessage={s.errorMessage}
            onSend={runAction}
            onContinue={() => runAction('让故事继续。')}
            onRetry={() => retryLast()}
          />
        </div>
        <RightPanel
          open={s.inspectorOpen}
          onClose={toggleInspector}
          context={{
            cardName: activeCard?.manifest.name,
            sessionId: s.activeSessionId,
            round: s.currentRound,
            workflowReady: Boolean(s.analysis),
          }}
          genParams={{
            provider: 'deepseek',
            model: 'deepseek-chat',
            temperature: 0.85,
            maxTokens: 2048,
            contextMode: 'full_context',
            preset: s.activePresetId,
          }}
          nodeMapping={nodeMapping}
          logs={s.logs}
        />
        {!s.inspectorOpen && (
          <button
            type="button"
            className="absolute right-0 top-1/2 -translate-y-1/2 w-4 h-10 bg-[var(--color-bg-app)] border border-[var(--color-border)] border-r-0 rounded-l flex items-center justify-center cursor-pointer text-[var(--color-text-3)] text-[9px] z-[5] hover:text-[var(--color-text-2)] hover:bg-[var(--color-bg-surface)] transition-colors"
            onClick={toggleInspector}
            aria-label="打开运行详情"
          >
            ◀
          </button>
        )}
      </div>
      {editingCardId && editingCard && (
        <CardEditor
          cardId={editingCardId}
          cardName={editingCard.manifest.name}
          onClose={closeCardEditor}
        />
      )}
    </div>
  )
}
