import { useState } from 'react'
import type { ResourceType, CardMeta, SessionMeta, WorldbookEntry, PresetMeta, WorkflowMeta } from '../types'

const LABELS: Record<ResourceType, string> = {
  cards: '角色卡',
  sessions: '会话',
  worldbook: '世界书',
  presets: '预设',
  workflows: '工作流',
}

interface Props {
  open: boolean
  type: ResourceType | null
  cards: CardMeta[]
  sessions: SessionMeta[]
  worldbookEntries: WorldbookEntry[]
  presets: PresetMeta[]
  workflows: WorkflowMeta[]
  activeCardId: string
  activeSessionId: string
  activePresetId: string
  activeWorkflow: string
  onSelectCard: (id: string) => void
  onSelectSession: (id: string) => void
  onSelectPreset: (id: string) => void
  onSelectWorkflow: (filename: string) => void
  onImportCard: () => void
  onEditCard: (id: string) => void
  onClose: () => void
}

export default function ResourcePanel({
  open,
  type,
  cards,
  sessions,
  worldbookEntries,
  presets,
  workflows,
  activeCardId,
  activeSessionId,
  activePresetId,
  activeWorkflow,
  onSelectCard,
  onSelectSession,
  onSelectPreset,
  onSelectWorkflow,
  onImportCard,
  onEditCard,
  onClose,
}: Props) {
  if (!open || !type) return null

  return (
    <aside className="w-[260px] min-w-[260px] border-r border-[var(--color-border)] bg-[var(--color-bg-surface)] flex flex-col overflow-hidden">
      <div className="flex justify-between items-center px-3.5 py-2.5 text-xs text-[var(--color-text-3)] font-medium tracking-wide border-b border-[var(--color-border-light)] min-h-[41px]">
        <span>{LABELS[type]}</span>
        <button type="button" className="bg-transparent border-none text-sm text-[var(--color-text-3)] cursor-pointer px-1" onClick={onClose} aria-label="关闭资源面板">×</button>
      </div>
      <div className="flex-1 overflow-y-auto p-1.5">
        {type === 'cards' && <CardList cards={cards} activeId={activeCardId} onSelect={onSelectCard} onImport={onImportCard} onEdit={onEditCard} />}
        {type === 'sessions' && <SessionList sessions={sessions} activeId={activeSessionId} onSelect={onSelectSession} />}
        {type === 'worldbook' && <WorldbookList entries={worldbookEntries} />}
        {type === 'presets' && <PresetList presets={presets} activeId={activePresetId} onSelect={onSelectPreset} />}
        {type === 'workflows' && <WorkflowList workflows={workflows} activeFilename={activeWorkflow} onSelect={onSelectWorkflow} />}
      </div>
    </aside>
  )
}

function CardList({ cards, activeId, onSelect, onImport, onEdit }: { cards: CardMeta[]; activeId: string; onSelect: (id: string) => void; onImport: () => void; onEdit: (id: string) => void }) {
  return (
    <>
      <div className="px-2 py-2">
        <button
          type="button"
          className="w-full bg-[var(--color-accent-dim)] text-[var(--color-text)] text-xs py-2 px-3 rounded hover:bg-[var(--color-accent)] transition-colors cursor-pointer"
          onClick={onImport}
        >
          + 导入角色卡
        </button>
      </div>
      {cards.length === 0 && <div className="text-xs text-[var(--color-text-3)] italic p-3">暂无角色卡，点击上方按钮导入。</div>}
      {cards.map(card => (
        <div key={card.card_id} className="mb-3 px-1">
          <div className="flex items-center gap-1">
            <button
              type="button"
              className={`flex-1 text-left text-[13px] font-medium py-1.5 px-2 rounded cursor-pointer ${card.card_id === activeId ? 'bg-[var(--color-accent-soft)] text-[var(--color-text)]' : 'text-[var(--color-text)] hover:bg-[var(--color-bg-hover)]'}`}
              onClick={() => onSelect(card.card_id)}
              aria-pressed={card.card_id === activeId}
            >
              {card.manifest.name}
            </button>
            <button
              type="button"
              className="text-[11px] text-[var(--color-text-3)] hover:text-[var(--color-accent)] px-1.5 py-1 rounded hover:bg-[var(--color-bg-hover)] transition-colors"
              onClick={() => onEdit(card.card_id)}
              title="编辑角色卡"
            >
              ✎
            </button>
          </div>
          <div className="text-[11px] text-[var(--color-text-3)] flex flex-col gap-0.5 py-0.5 px-2 pl-5">
            <span>世界书：{card.manifest.worldbook_entry_count} 条</span>
            {card.manifest.description && <span className="truncate">{card.manifest.description}</span>}
          </div>
        </div>
      ))}
    </>
  )
}

function SessionList({ sessions, activeId, onSelect }: { sessions: SessionMeta[]; activeId: string; onSelect: (id: string) => void }) {
  if (sessions.length === 0) return <div className="text-xs text-[var(--color-text-3)] italic p-3">暂无会话</div>
  return (
    <>
      {sessions.map(session => (
        <button
          key={session.session_id}
          type="button"
          className={`w-full text-left flex flex-col gap-0.5 py-2 px-3 rounded cursor-pointer mb-px transition-colors ${session.session_id === activeId ? 'bg-[var(--color-accent-soft)]' : 'hover:bg-[var(--color-bg-hover)]'}`}
          onClick={() => onSelect(session.session_id)}
          aria-pressed={session.session_id === activeId}
        >
          <span className="text-[13px] font-medium flex items-center gap-1.5">
            {session.session_id}
            {session.card_name && <span className="text-[10px] px-1.5 py-px rounded-sm bg-[var(--color-bg-app)] text-[var(--color-text-3)] font-normal">{session.card_name}</span>}
          </span>
          <span className="text-[11px] text-[var(--color-text-3)]">{session.turn_count} 轮</span>
        </button>
      ))}
    </>
  )
}

function WorldbookList({ entries }: { entries: WorldbookEntry[] }) {
  if (entries.length === 0) return <div className="text-xs text-[var(--color-text-3)] italic p-3">暂无世界书条目</div>
  const consts = entries.filter(entry => entry.activation === 'const')
  const selects = entries.filter(entry => entry.activation === 'select')
  const offs = entries.filter(entry => entry.activation === 'off')
  return (
    <>
      {consts.length > 0 && <div className="text-[10px] text-[var(--color-text-3)] uppercase tracking-widest px-2.5 py-2 font-medium">常开</div>}
      {consts.map(entry => <WbEntry key={entry.id} entry={entry} mode="const" />)}
      {selects.length > 0 && <div className="text-[10px] text-[var(--color-text-3)] uppercase tracking-widest px-2.5 py-2 font-medium">关键词触发</div>}
      {selects.map(entry => <WbEntry key={entry.id} entry={entry} mode="select" />)}
      {offs.length > 0 && <div className="text-[10px] text-[var(--color-text-3)] uppercase tracking-widest px-2.5 py-2 font-medium">已关闭</div>}
      {offs.map(entry => <WbEntry key={entry.id} entry={entry} mode="off" />)}
    </>
  )
}

function WbEntry({ entry, mode }: { entry: WorldbookEntry; mode: string }) {
  const [expanded, setExpanded] = useState(false)
  const borderCls = mode === 'const' ? 'border-l-[var(--color-ok)]' : mode === 'select' ? 'border-l-[var(--color-accent-dim)]' : 'border-l-transparent opacity-50'
  return (
    <div className={`py-2 px-2.5 rounded mb-px transition-colors border-l-2 ${borderCls} hover:bg-[var(--color-bg-hover)]`}>
      <div className="flex items-center gap-1.5 text-xs mb-0.5">
        <button
          type="button"
          className="flex-1 text-left flex items-center gap-1.5 cursor-pointer bg-transparent border-none p-0"
          onClick={() => setExpanded(!expanded)}
        >
          <span className="text-[var(--color-text)] font-medium">{entry.title || '(untitled)'}</span>
          <span className="text-[10px] text-[var(--color-text-3)]">p={entry.priority}</span>
          <span className="text-[10px] text-[var(--color-text-3)] ml-auto">{expanded ? '▼' : '▶'}</span>
        </button>
      </div>
      <div className={`text-[11px] text-[var(--color-text-3)] leading-snug ${expanded ? '' : 'line-clamp-2'}`}>
        {entry.content}
      </div>
      {entry.tags.length > 0 && <div className="text-[10px] text-[var(--color-accent-dim)] mt-1">关键词：{entry.tags.join(', ')}</div>}
    </div>
  )
}

function PresetList({ presets, activeId, onSelect }: { presets: PresetMeta[]; activeId: string; onSelect: (id: string) => void }) {
  if (presets.length === 0) return <div className="text-xs text-[var(--color-text-3)] italic p-3">暂无预设</div>
  return (
    <>
      {presets.map(preset => (
        <button
          key={preset.id}
          type="button"
          className={`w-full text-left flex flex-col gap-0.5 py-2 px-3 rounded cursor-pointer mb-px transition-colors ${preset.id === activeId ? 'bg-[var(--color-accent-soft)]' : 'hover:bg-[var(--color-bg-hover)]'}`}
          onClick={() => onSelect(preset.id)}
          aria-pressed={preset.id === activeId}
        >
          <span className="text-[13px] font-medium">{preset.name}</span>
          <span className="text-[11px] text-[var(--color-text-3)]">{preset.id}</span>
        </button>
      ))}
    </>
  )
}

function WorkflowList({ workflows, activeFilename, onSelect }: { workflows: WorkflowMeta[]; activeFilename: string; onSelect: (filename: string) => void }) {
  if (workflows.length === 0) return <div className="text-xs text-[var(--color-text-3)] italic p-3">暂无工作流</div>
  return (
    <>
      {workflows.map(workflow => (
        <button
          key={workflow.filename}
          type="button"
          className={`w-full text-left flex flex-col gap-0.5 py-2 px-3 rounded cursor-pointer mb-px transition-colors ${workflow.filename === activeFilename ? 'bg-[var(--color-accent-soft)]' : 'hover:bg-[var(--color-bg-hover)]'}`}
          onClick={() => onSelect(workflow.filename)}
          aria-pressed={workflow.filename === activeFilename}
        >
          <span className="text-[13px] font-medium break-all">{workflow.filename}</span>
          <span className="text-[11px] text-[var(--color-text-3)]">{workflow.node_count} 节点 / {workflow.inputs.length} 输入 / {workflow.outputs.length} 输出</span>
        </button>
      ))}
    </>
  )
}
