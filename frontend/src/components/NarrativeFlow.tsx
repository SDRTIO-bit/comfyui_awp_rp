import type { TurnData } from '../types'

interface Props {
  turns: TurnData[]
  currentIndex: number
  onInspect: () => void
}

export default function NarrativeFlow({ turns, currentIndex, onInspect }: Props) {
  if (turns.length === 0) return null

  return (
    <div className="max-w-[720px] mx-auto">
      {turns.map((t, i) => {
        const isCurrent = i === currentIndex
        return (
          <div key={t.index} className="group mb-9">
            <div className="flex items-baseline gap-2 mb-2.5">
              <span className={`text-[11px] font-[tabnum] flex-shrink-0 select-none ${isCurrent ? 'text-[var(--color-accent)] font-medium' : 'text-[var(--color-text-3)]'}`}>
                {t.index}
              </span>
              <span className={`text-sm leading-relaxed ${isCurrent ? 'text-[var(--color-text)]' : 'text-[var(--color-text-2)]'}`}>
                {t.action}
              </span>
            </div>
            <div
              className="text-[16px] leading-[1.85] text-[#d4d4dd] pl-[26px] [&_p]:mb-[1.1em] [&_p:last-child]:mb-0"
              dangerouslySetInnerHTML={{ __html: t.narrative }}
            />
            <div className={`flex gap-2 pl-[26px] mt-2 opacity-0 group-hover:opacity-100 transition-opacity ${isCurrent ? 'opacity-100' : ''}`}>
              <button className="bg-transparent border-none text-[11px] text-[var(--color-text-3)] cursor-pointer py-0.5 px-0 hover:text-[var(--color-text-2)] transition-colors">复制</button>
              <button className="bg-transparent border-none text-[11px] text-[var(--color-text-3)] cursor-pointer py-0.5 px-0 hover:text-[var(--color-text-2)] transition-colors">重试</button>
              {isCurrent && (
                <button className="bg-transparent border-none text-[11px] text-[var(--color-accent-dim)] cursor-pointer py-0.5 px-0 hover:text-[var(--color-accent)] transition-colors" onClick={onInspect}>
                  本轮详情
                </button>
              )}
            </div>
          </div>
        )
      })}
    </div>
  )
}
