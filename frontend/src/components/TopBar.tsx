interface Props {
  sessionTitle: string
  contextLine: string
  connOk: boolean
  onInspectorToggle: () => void
}

export default function TopBar({ sessionTitle, contextLine, connOk, onInspectorToggle }: Props) {
  return (
    <header className="h-12 min-h-12 flex items-center px-4 gap-0 text-[13px] border-b border-[var(--color-border)] bg-[var(--color-bg-app)] z-20">
      <span className="flex items-center gap-2 text-xs text-[var(--color-text-3)] font-medium tracking-wide mr-4 cursor-pointer whitespace-nowrap hover:text-[var(--color-text-2)] transition-colors">
        <svg width="14" height="14" viewBox="0 0 16 16" fill="none" className="text-[var(--color-accent)] opacity-70">
          <rect x="2" y="2" width="5" height="5" rx="1" fill="currentColor" opacity="0.6"/>
          <rect x="9" y="2" width="5" height="5" rx="1" fill="currentColor"/>
          <rect x="2" y="9" width="5" height="5" rx="1" fill="currentColor"/>
          <rect x="9" y="9" width="5" height="5" rx="1" fill="currentColor" opacity="0.3"/>
        </svg>
        Story Workshop
      </span>
      {contextLine && (
        <div className="flex items-center gap-1.5 text-[12.5px] text-[var(--color-text-2)] whitespace-nowrap overflow-hidden text-ellipsis" dangerouslySetInnerHTML={{ __html: contextLine }} />
      )}
      <div className="flex-1" />
      <span
        className={`w-1.5 h-1.5 rounded-full mr-3 cursor-pointer flex-shrink-0 ${connOk ? 'bg-[var(--color-ok)]' : 'bg-[var(--color-err)]'}`}
        title={connOk ? '服务正常' : '连接异常'}
      />
      <button
        className="bg-transparent border-none text-xs text-[var(--color-text-3)] cursor-pointer py-1 px-2 rounded hover:text-[var(--color-text-2)] hover:bg-[var(--color-bg-hover)] transition-colors"
        onClick={onInspectorToggle}
      >
        详情
      </button>
    </header>
  )
}
