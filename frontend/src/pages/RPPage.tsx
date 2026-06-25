import { useEffect, useReducer, useCallback } from 'react'
import type { PageState, ResourceType, TurnData, CardMeta, SessionMeta, WorldbookEntry, PresetMeta, WorkflowMeta, WorkflowAnalysis } from '../types'
import TopBar from '../components/TopBar'
import LeftRail from '../components/LeftRail'
import ResourcePanel from '../components/ResourcePanel'
import NarrativeFlow from '../components/NarrativeFlow'
import InputDock from '../components/InputDock'
import RightPanel from '../components/RightPanel'

interface State {
  pageState: PageState
  resourceType: ResourceType | null
  inspectorOpen: boolean
  sessionTitle: string
  contextLine: string  // "角色 · 身份 / 场景 · 时间 / 第N轮"
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
}

type Action =
  | { type: 'SET_STATE'; state: PageState }
  | { type: 'TOGGLE_RESOURCE'; resource: ResourceType }
  | { type: 'CLOSE_RESOURCE' }
  | { type: 'TOGGLE_INSPECTOR' }
  | { type: 'SET_DATA'; key: string; data: unknown }
  | { type: 'SET_CONTEXT'; line: string; title: string; round: number }
  | { type: 'SET_CONN'; ok: boolean }

function reducer(state: State, action: Action): State {
  switch (action.type) {
    case 'SET_STATE':
      return { ...state, pageState: action.state }
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
  activeWorkflow: 'rp_full_node_workflow.json',
  currentRound: 0,
  connOk: true,
}

export default function RPPage() {
  const [s, dispatch] = useReducer(reducer, initialState)

  // Load all data on mount
  const fetchData = useCallback(async () => {
    const fetchers: [string, string][] = [
      ['cards', '/api/cards'],
      ['sessions', '/api/sessions'],
      ['presets', '/api/presets'],
      ['workflows', '/api/workflows'],
    ]
    const results = await Promise.allSettled(
      fetchers.map(([key, url]) =>
        fetch(url).then(r => r.json()).then(data => [key, data] as const)
      )
    )
    for (const r of results) {
      if (r.status === 'fulfilled') {
        dispatch({ type: 'SET_DATA', key: r.value[0], data: r.value[1] })
      }
    }

    // Load worldbook for active card
    try {
      const wb = await fetch(`/api/worldbook/${initialState.activeCardId}`).then(r => r.json())
      dispatch({ type: 'SET_DATA', key: 'worldbookEntries', data: wb })
    } catch { /* no worldbook yet */ }

    // Analyze active workflow
    try {
      const ana = await fetch(`/api/workflows/${initialState.activeWorkflow}/analyze`).then(r => r.json())
      dispatch({ type: 'SET_DATA', key: 'analysis', data: ana })
    } catch { /* analysis not available */ }

    // Health check
    try {
      const h = await fetch('/api/health').then(r => r.json())
      dispatch({ type: 'SET_CONN', ok: h.status === 'ok' })
    } catch { dispatch({ type: 'SET_CONN', ok: false }) }
  }, [])

  useEffect(() => { fetchData() }, [fetchData])

  const toggleResource = useCallback((r: ResourceType) => dispatch({ type: 'TOGGLE_RESOURCE', resource: r }), [])
  const closeResource = useCallback(() => dispatch({ type: 'CLOSE_RESOURCE' }), [])
  const toggleInspector = useCallback(() => dispatch({ type: 'TOGGLE_INSPECTOR' }), [])
  const onSend = useCallback(() => dispatch({ type: 'SET_STATE', state: 'generating' }), [])
  // In production, onSend would POST /api/run and handle response

  return (
    <div className="flex flex-col h-full">
      <TopBar
        sessionTitle={s.sessionTitle}
        contextLine={s.contextLine}
        connOk={s.connOk}
        onInspectorToggle={toggleInspector}
      />
      <div className="flex flex-1 overflow-hidden relative">
        <LeftRail
          activeResource={s.resourceType}
          onToggle={toggleResource}
        />
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
          onClose={closeResource}
        />
        <div className="flex-1 flex flex-col overflow-hidden min-w-0">
          <div className="flex-1 overflow-y-auto px-8 md:px-12 py-8">
            {(s.pageState === 'active' || s.pageState === 'generating' || s.pageState === 'error') && s.turns.length > 0 && (
              <NarrativeFlow turns={s.turns} currentIndex={s.turns.length - 1} onInspect={toggleInspector} />
            )}
            {s.pageState === 'empty' && (
              <div className="flex flex-col items-center justify-center h-full text-[var(--color-text-3)] gap-3 text-center">
                <svg width="36" height="36" viewBox="0 0 24 24" fill="none" className="opacity-20">
                  <rect x="3" y="2" width="18" height="20" rx="2" stroke="currentColor" strokeWidth="1.3"/>
                  <line x1="8" y1="7" x2="16" y2="7" stroke="currentColor" strokeWidth="1"/>
                  <line x1="8" y1="11" x2="14" y2="11" stroke="currentColor" strokeWidth="1"/>
                </svg>
                <div className="text-sm max-w-[300px] leading-relaxed">选择一个角色卡和会话，或者新建一个故事来开始。</div>
                <button
                  className="bg-[var(--color-accent-dim)] text-[var(--color-text)] px-6 py-2 rounded-md text-sm mt-2 hover:bg-[var(--color-accent)] transition-colors"
                  onClick={() => dispatch({ type: 'SET_STATE', state: 'active' })}
                >
                  新建会话
                </button>
              </div>
            )}
          </div>
          <InputDock
            state={s.pageState}
            onSend={onSend}
          />
        </div>
        <RightPanel
          open={s.inspectorOpen}
          onClose={toggleInspector}
        />
        {!s.inspectorOpen && (
          <button
            className="absolute right-0 top-1/2 -translate-y-1/2 w-4 h-10 bg-[var(--color-bg-app)] border border-[var(--color-border)] border-r-0 rounded-l flex items-center justify-center cursor-pointer text-[var(--color-text-3)] text-[9px] z-[5] hover:text-[var(--color-text-2)] hover:bg-[var(--color-bg-surface)] transition-colors"
            onClick={toggleInspector}
          >◀</button>
        )}
      </div>
    </div>
  )
}
