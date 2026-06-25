import type { ResourceType } from '../types'

const ICONS: Record<ResourceType, JSX.Element> = {
  cards: <svg viewBox="0 0 16 16" fill="none" className="w-[15px] h-[15px]"><rect x="2" y="1" width="12" height="14" rx="1.5" stroke="currentColor" strokeWidth="1.1"/><line x1="6" y1="4" x2="10" y2="4" stroke="currentColor" strokeWidth="0.9"/><line x1="6" y1="7" x2="10" y2="7" stroke="currentColor" strokeWidth="0.9"/><line x1="6" y1="10" x2="8" y2="10" stroke="currentColor" strokeWidth="0.9"/></svg>,
  sessions: <svg viewBox="0 0 16 16" fill="none" className="w-[15px] h-[15px]"><circle cx="8" cy="8" r="6" stroke="currentColor" strokeWidth="1.1"/><circle cx="8" cy="5" r="1.1" fill="currentColor"/><path d="M8 7.5v3.5" stroke="currentColor" strokeWidth="1.1" strokeLinecap="round"/></svg>,
  worldbook: <svg viewBox="0 0 16 16" fill="none" className="w-[15px] h-[15px]"><rect x="1.5" y="2.5" width="13" height="11" rx="1.5" stroke="currentColor" strokeWidth="1.1"/><line x1="5" y1="1" x2="5" y2="15" stroke="currentColor" strokeWidth="0.8" opacity="0.4"/><line x1="7" y1="6" x2="11" y2="6" stroke="currentColor" strokeWidth="0.8"/><line x1="7" y1="8" x2="10" y2="8" stroke="currentColor" strokeWidth="0.8"/></svg>,
  presets: <svg viewBox="0 0 16 16" fill="none" className="w-[15px] h-[15px]"><rect x="1" y="1" width="14" height="14" rx="2" stroke="currentColor" strokeWidth="1.1"/><circle cx="5.5" cy="5.5" r="1.5" fill="currentColor" opacity="0.45"/><circle cx="10.5" cy="10.5" r="1.5" fill="currentColor" opacity="0.45"/><line x1="6.5" y1="6.5" x2="9.5" y2="9.5" stroke="currentColor" strokeWidth="1"/></svg>,
  workflows: <svg viewBox="0 0 16 16" fill="none" className="w-[15px] h-[15px]"><circle cx="3" cy="5" r="1.5" fill="currentColor"/><circle cx="13" cy="5" r="1.5" fill="currentColor" opacity="0.45"/><circle cx="8" cy="12" r="1.5" fill="currentColor" opacity="0.25"/><line x1="4.3" y1="5.5" x2="11.7" y2="5.5" stroke="currentColor" strokeWidth="1"/><line x1="12" y1="6.5" x2="9.5" y2="10.8" stroke="currentColor" strokeWidth="1"/></svg>,
}

const LABELS: Record<ResourceType, string> = {
  cards: '角色卡', sessions: '会话', worldbook: '世界书', presets: '预设', workflows: '工作流',
}

const ORDER: ResourceType[] = ['cards', 'sessions', 'worldbook', 'presets', 'workflows']

interface Props {
  activeResource: ResourceType | null
  onToggle: (r: ResourceType) => void
}

export default function LeftRail({ activeResource, onToggle }: Props) {
  return (
    <nav className="w-11 min-w-11 flex flex-col items-center pt-1.5 gap-0.5 border-r border-[var(--color-border)] bg-[var(--color-bg-app)] z-10">
      {ORDER.map(r => (
        <button
          key={r}
          className={`w-[34px] h-[34px] flex items-center justify-center rounded-md cursor-pointer border-none bg-transparent relative transition-all ${activeResource === r ? 'text-[var(--color-accent)] bg-[var(--color-accent-soft)]' : 'text-[var(--color-text-3)] hover:text-[var(--color-text-2)] hover:bg-[var(--color-bg-hover)]'}`}
          onClick={() => onToggle(r)}
        >
          {ICONS[r]}
          <span className="absolute left-[42px] top-1/2 -translate-y-1/2 bg-[var(--color-bg-raised)] text-[var(--color-text-2)] text-[11px] py-1 px-2 rounded whitespace-nowrap pointer-events-none opacity-0 group-hover:opacity-100 transition-opacity border border-[var(--color-border)] z-30" style={{ opacity: 0 }}>
            {LABELS[r]}
          </span>
        </button>
      ))}
    </nav>
  )
}
