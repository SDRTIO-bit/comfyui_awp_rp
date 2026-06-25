import type { PageState } from '../types'

interface Props {
  state: PageState
  onSend: () => void
}

export default function InputDock({ state, onSend }: Props) {
  const hint = '写下你的行动、对白，或让故事自行推进'

  return (
    <div className="py-3 px-8 md:px-12 border-t border-[var(--color-border-light)] bg-gradient-to-t from-[var(--color-bg-app)] max-w-[820px] mx-auto w-full">
      {state === 'active' && (
        <>
          <div className="text-[11px] text-[var(--color-text-3)] mb-2">{hint}</div>
          <div className="flex gap-2 items-end">
            <textarea
              className="flex-1 bg-[var(--color-bg-surface)] border border-[var(--color-border)] rounded-md text-[15px] leading-relaxed py-2.5 px-3.5 resize-none min-h-[44px] max-h-[120px] outline-none transition-colors focus:border-[rgba(124,138,255,0.2)] placeholder:text-[var(--color-text-3)] text-[var(--color-text)] font-sans"
              placeholder="下一步行动……"
              rows={1}
            />
            <button
              className="bg-[var(--color-accent-dim)] text-[var(--color-text)] rounded-md py-2.5 px-5 text-[13px] cursor-pointer font-medium tracking-wide hover:bg-[var(--color-accent)] transition-colors whitespace-nowrap h-[44px]"
              onClick={onSend}
            >
              发送
            </button>
          </div>
          <div className="flex justify-center pt-1 pb-0.5">
            <button className="bg-transparent border border-[var(--color-border)] text-[var(--color-text-2)] rounded-md py-1.5 px-5 text-xs cursor-pointer hover:border-[rgba(124,138,255,0.2)] hover:text-[var(--color-accent)] transition-all">
              让故事继续
            </button>
          </div>
        </>
      )}

      {state === 'generating' && (
        <>
          <div className="text-[11px] text-[var(--color-text-3)] mb-2">{hint}</div>
          <div className="flex items-center gap-2.5 py-3.5 text-[13px] text-[var(--color-accent)]">
            <span className="w-[7px] h-[7px] rounded-full bg-[var(--color-accent)] animate-pulse" />
            正在生成……
          </div>
        </>
      )}

      {state === 'error' && (
        <>
          <div className="text-[11px] text-[var(--color-text-3)] mb-2">{hint}</div>
          <div className="flex gap-2 items-end">
            <textarea
              className="flex-1 bg-[var(--color-bg-surface)] border border-[var(--color-border)] rounded-md text-[15px] leading-relaxed py-2.5 px-3.5 resize-none min-h-[44px] max-h-[120px] outline-none transition-colors focus:border-[rgba(124,138,255,0.2)] placeholder:text-[var(--color-text-3)] text-[var(--color-text)] font-sans"
              placeholder="下一步行动……"
              rows={1}
            />
            <button
              className="bg-[var(--color-accent-dim)] text-[var(--color-text)] rounded-md py-2.5 px-5 text-[13px] cursor-pointer font-medium tracking-wide hover:bg-[var(--color-accent)] transition-colors whitespace-nowrap h-[44px]"
              onClick={onSend}
            >
              发送
            </button>
          </div>
          <div className="flex items-center gap-2.5 py-2.5 px-3.5 mt-2 bg-[rgba(224,85,85,0.04)] border border-[rgba(224,85,85,0.12)] rounded-md text-[var(--color-err)] text-xs">
            <span>生成失败：LLM 连接超时</span>
            <button className="ml-auto bg-transparent border border-[rgba(224,85,85,0.2)] text-[var(--color-err)] rounded px-2.5 py-1 text-[11px] cursor-pointer hover:bg-[rgba(224,85,85,0.08)] transition-colors">
              重试
            </button>
          </div>
        </>
      )}
    </div>
  )
}
