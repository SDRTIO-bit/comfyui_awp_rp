import type { ResourceType, CardMeta, SessionMeta, WorldbookEntry, PresetMeta, WorkflowMeta } from '../types'

const LABELS: Record<ResourceType, string> = {
  cards: '角色卡', sessions: '会话', worldbook: '世界书', presets: '预设', workflows: '工作流',
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
  onClose: () => void
}

export default function ResourcePanel({ open, type, cards, sessions, worldbookEntries, presets, workflows, activeCardId, activeSessionId, onClose }: Props) {
  if (!open || !type) return null

  return (
    <aside className="w-[260px] min-w-[260px] border-r border-[var(--color-border)] bg-[var(--color-bg-surface)] flex flex-col overflow-hidden">
      <div className="flex justify-between items-center px-3.5 py-2.5 text-xs text-[var(--color-text-3)] font-medium tracking-wide border-b border-[var(--color-border-light)] min-h-[41px]">
        <span>{LABELS[type]}</span>
        <button className="bg-transparent border-none text-sm text-[var(--color-text-3)] cursor-pointer px-1" onClick={onClose}>×</button>
      </div>
      <div className="flex-1 overflow-y-auto p-1.5">
        {type === 'cards' && <CardList cards={cards} activeId={activeCardId} />}
        {type === 'sessions' && <SessionList sessions={sessions} activeId={activeSessionId} />}
        {type === 'worldbook' && <WorldbookList entries={worldbookEntries} />}
        {type === 'presets' && <PresetList presets={presets} />}
        {type === 'workflows' && <WorkflowList workflows={workflows} />}
      </div>
    </aside>
  )
}

function CardList({ cards, activeId }: { cards: CardMeta[]; activeId: string }) {
  if (cards.length === 0) return <div className="text-xs text-[var(--color-text-3)] italic p-3">暂无角色卡</div>
  return (
    <>
      {cards.map(c => (
        <div key={c.card_id} className="mb-3 px-1">
          <div className={`text-[13px] font-medium py-1.5 px-2 rounded cursor-pointer ${c.card_id === activeId ? 'bg-[var(--color-accent-soft)] text-[var(--color-text)]' : 'text-[var(--color-text)] hover:bg-[var(--color-bg-hover)]'}`}>
            {c.manifest.name}
          </div>
          <div className="text-[11px] text-[var(--color-text-3)] flex flex-col gap-0.5 py-0.5 px-2 pl-5">
            <span className="cursor-pointer hover:text-[var(--color-text-2)]">世界书：{c.manifest.worldbook_entry_count}条</span>
            {c.manifest.description && <span className="truncate">{c.manifest.description}</span>}
          </div>
        </div>
      ))}
      <div className="text-xs text-[var(--color-text-3)] italic px-3 py-2.5 cursor-pointer hover:text-[var(--color-text-2)]">+ 导入新角色卡</div>
    </>
  )
}

function SessionList({ sessions, activeId }: { sessions: SessionMeta[]; activeId: string }) {
  if (sessions.length === 0) return <div className="text-xs text-[var(--color-text-3)] italic p-3">暂无会话</div>
  return (
    <>
      {sessions.map(s => (
        <div key={s.session_id} className={`flex flex-col gap-0.5 py-2 px-3 rounded cursor-pointer mb-px transition-colors ${s.session_id === activeId ? 'bg-[var(--color-accent-soft)]' : 'hover:bg-[var(--color-bg-hover)]'}`}>
          <div className="text-[13px] font-medium flex items-center gap-1.5">
            {s.session_id}
            {s.card_name && <span className="text-[10px] px-1.5 py-px rounded-sm bg-[var(--color-bg-app)] text-[var(--color-text-3)] font-normal">{s.card_name}</span>}
          </div>
          <div className="text-[11px] text-[var(--color-text-3)]">{s.turn_count}轮</div>
        </div>
      ))}
      <div className="text-xs text-[var(--color-text-3)] italic px-3 py-2.5 cursor-pointer hover:text-[var(--color-text-2)]">+ 新建会话</div>
    </>
  )
}

function WorldbookList({ entries }: { entries: WorldbookEntry[] }) {
  if (entries.length === 0) return <div className="text-xs text-[var(--color-text-3)] italic p-3">暂无世界书条目</div>
  const consts = entries.filter(e => e.activation === 'const')
  const selects = entries.filter(e => e.activation === 'select')
  const offs = entries.filter(e => e.activation === 'off')
  return (
    <>
      {consts.length > 0 && <div className="text-[10px] text-[var(--color-text-3)] uppercase tracking-widest px-2.5 py-2 font-medium">常开</div>}
      {consts.map(e => <WbEntry key={e.id} entry={e} mode="const" />)}
      {selects.length > 0 && <div className="text-[10px] text-[var(--color-text-3)] uppercase tracking-widest px-2.5 py-2 font-medium">关键词触发</div>}
      {selects.map(e => <WbEntry key={e.id} entry={e} mode="select" />)}
      {offs.length > 0 && <div className="text-[10px] text-[var(--color-text-3)] uppercase tracking-widest px-2.5 py-2 font-medium">已关闭</div>}
      {offs.map(e => <WbEntry key={e.id} entry={e} mode="off" />)}
    </>
  )
}

function WbEntry({ entry, mode }: { entry: WorldbookEntry; mode: string }) {
  const borderCls = mode === 'const' ? 'border-l-[var(--color-ok)]' : mode === 'select' ? 'border-l-[var(--color-accent-dim)]' : 'border-l-transparent opacity-50'
  return (
    <div className={`py-2 px-2.5 rounded cursor-pointer mb-px transition-colors border-l-2 ${borderCls} hover:bg-[var(--color-bg-hover)]`}>
      <div className="flex items-center gap-1.5 text-xs mb-0.5">
        <span className="text-[var(--color-text)] font-medium">{entry.title || '(untitled)'}</span>
        <span className="text-[10px] text-[var(--color-text-3)]">p={entry.priority}</span>
      </div>
      <div className="text-[11px] text-[var(--color-text-3)] leading-snug line-clamp-2">{entry.content}</div>
      {entry.tags.length > 0 && <div className="text-[10px] text-[var(--color-accent-dim)] mt-1">关键词：{entry.tags.join(', ')}</div>}
    </div>
  )
}

function PresetList({ presets }: { presets: PresetMeta[] }) {
  if (presets.length === 0) return <div className="text-xs text-[var(--color-text-3)] italic p-3">暂无预设</div>
  return <>{presets.map(p => (
    <div key={p.id} className="flex flex-col gap-0.5 py-2 px-3 rounded cursor-pointer mb-px hover:bg-[var(--color-bg-hover)] transition-colors">
      <div className="text-[13px] font-medium">{p.name}</div>
      <div className="text-[11px] text-[var(--color-text-3)]">{p.id}</div>
    </div>
  ))}</>
}

function WorkflowList({ workflows }: { workflows: WorkflowMeta[] }) {
  if (workflows.length === 0) return <div className="text-xs text-[var(--color-text-3)] italic p-3">暂无工作流</div>
  return <>{workflows.map(w => (
    <div key={w.filename} className="flex flex-col gap-0.5 py-2 px-3 rounded cursor-pointer mb-px hover:bg-[var(--color-bg-hover)] transition-colors">
      <div className="text-[13px] font-medium">{w.filename}</div>
      <div className="text-[11px] text-[var(--color-text-3)]">{w.node_count}节点 · {w.inputs.length}输入 · {w.outputs.length}输出</div>
    </div>
  ))}</>
}
