import { useState } from 'react'

interface ContextInfo {
  cardName?: string; cardRole?: string; scene?: string; timeOfDay?: string
  sessionId?: string; round?: number; workflowReady?: boolean
}
interface GenParams {
  provider?: string; model?: string; temperature?: number; maxTokens?: number
  contextMode?: string; preset?: string
}
interface NodeMapping {
  userInput?: string; sessionId?: string; cardId?: string; generator?: string
  totalMapped?: number; totalExpected?: number
}
interface RunDetails {
  inputTokens?: number; outputTokens?: number; duration?: string
  retrievalHits?: number; qualityGate?: { passed: boolean }
}
interface LogEntry { time: string; message: string }

interface Props {
  open: boolean; onClose: () => void
  context?: ContextInfo; genParams?: GenParams; nodeMapping?: NodeMapping
  runDetails?: RunDetails; logs?: LogEntry[]
}

type Module = 'context' | 'params' | 'mapping' | 'rundetails' | 'log'

export default function RightPanel({ open, onClose, context = {}, genParams = {}, nodeMapping = {}, runDetails = {}, logs = [] }: Props) {
  const [collapsed, setCollapsed] = useState<Set<Module>>(new Set(['params', 'mapping', 'rundetails', 'log']))
  const toggle = (m: Module) => setCollapsed(prev => { const n = new Set(prev); n.has(m) ? n.delete(m) : n.add(m); return n })
  if (!open) return null

  const hasCtx = context.cardName || context.sessionId
  const hasMap = (nodeMapping.totalExpected ?? 0) > 0
  const hasRun = runDetails.inputTokens !== undefined || runDetails.qualityGate !== undefined

  return (
    <aside className="w-[280px] min-w-[280px] border-l border-[var(--color-border)] bg-[var(--color-bg-surface)] flex flex-col overflow-hidden text-xs z-10">
      <div className="flex justify-between items-center px-3.5 py-2 border-b border-[var(--color-border-light)]">
        <span className="text-xs text-[var(--color-text-3)] font-medium tracking-wide">运行详情</span>
        <button className="bg-transparent border-none text-sm text-[var(--color-text-3)] cursor-pointer px-1" onClick={onClose}>×</button>
      </div>
      <div className="flex-1 overflow-y-auto">
        <Section title="当前上下文" collapsed={collapsed.has('context')} onToggle={() => toggle('context')}>
          {hasCtx ? <>
            {context.cardName && <KV k="角色" v={context.cardRole ? `${context.cardName} · ${context.cardRole}` : context.cardName} />}
            {context.scene && <KV k="场景" v={context.timeOfDay ? `${context.scene} · ${context.timeOfDay}` : context.scene} />}
            {context.sessionId && <KV k="会话" v={context.sessionId} />}
            {context.round != null && <KV k="轮次" v={String(context.round)} />}
            <div className={`flex items-center gap-1.5 py-1 text-[11px] ${context.workflowReady ? 'text-[var(--color-ok)]' : 'text-[var(--color-text-3)]'}`}>
              <span className={`w-[5px] h-[5px] rounded-full ${context.workflowReady ? 'bg-[var(--color-ok)]' : 'bg-[var(--color-text-3)]'}`} />
              {context.workflowReady ? '工作流就绪' : '等待工作流'}
            </div>
          </> : <span className="text-[var(--color-text-3)] text-[11px] italic">暂无</span>}
        </Section>
        <Section title="生成参数" collapsed={collapsed.has('params')} onToggle={() => toggle('params')}>
          {genParams.provider ? <>
            <KV k="Provider" v={genParams.provider} /><KV k="Model" v={genParams.model ?? '—'} />
            <KV k="Temperature" v={genParams.temperature != null ? String(genParams.temperature) : '—'} />
            <KV k="Max Tokens" v={genParams.maxTokens != null ? String(genParams.maxTokens) : '—'} />
            <KV k="上下文模式" v={genParams.contextMode ?? '—'} /><KV k="预设" v={genParams.preset ?? '—'} />
          </> : <span className="text-[var(--color-text-3)] text-[11px] italic">运行后显示</span>}
        </Section>
        <Section title="节点映射" collapsed={collapsed.has('mapping')} onToggle={() => toggle('mapping')}>
          {hasMap ? <>
            <KV k="用户输入" v={nodeMapping.userInput ?? '—'} /><KV k="会话ID" v={nodeMapping.sessionId ?? '—'} />
            <KV k="角色卡" v={nodeMapping.cardId ?? '—'} /><KV k="生成引擎" v={nodeMapping.generator ?? '—'} />
            <div className="text-[10px] text-[var(--color-text-3)] mt-2">自动识别 · {nodeMapping.totalMapped}/{nodeMapping.totalExpected} 已映射</div>
          </> : <span className="text-[var(--color-text-3)] text-[11px] italic">运行后显示</span>}
        </Section>
        <Section title="本轮详情" collapsed={collapsed.has('rundetails')} onToggle={() => toggle('rundetails')}>
          {hasRun ? <>
            {runDetails.inputTokens != null && <KV k="输入Token" v={String(runDetails.inputTokens)} />}
            {runDetails.outputTokens != null && <KV k="输出Token" v={String(runDetails.outputTokens)} />}
            {runDetails.duration && <KV k="生成耗时" v={runDetails.duration} />}
            {runDetails.retrievalHits != null && <KV k="检索命中" v={`${runDetails.retrievalHits}条`} />}
            {runDetails.qualityGate && <KV k="质量门" v={runDetails.qualityGate.passed ? '通过' : '未通过'} vOk={runDetails.qualityGate.passed} />}
          </> : <span className="text-[var(--color-text-3)] text-[11px] italic">运行后显示</span>}
        </Section>
        <Section title="日志" collapsed={collapsed.has('log')} onToggle={() => toggle('log')}>
          {logs.length > 0
            ? <div className="text-[11px] text-[var(--color-text-3)] font-mono max-h-[140px] overflow-y-auto leading-relaxed">{logs.map((l, i) => <div key={i}>[{l.time}] {l.message}</div>)}</div>
            : <span className="text-[var(--color-text-3)] text-[11px] italic">暂无</span>}
        </Section>
      </div>
    </aside>
  )
}

function Section({ title, collapsed, onToggle, children }: { title: string; collapsed: boolean; onToggle: () => void; children: React.ReactNode }) {
  return (
    <div className="border-b border-[var(--color-border-light)]">
      <div className="flex justify-between items-center py-2.5 px-3.5 cursor-pointer select-none text-xs font-medium text-[var(--color-text-3)] tracking-wide hover:text-[var(--color-text-2)] transition-colors" onClick={onToggle}>
        {title}<span className={`text-[9px] transition-transform ${collapsed ? '-rotate-90' : ''}`}>▾</span>
      </div>
      {!collapsed && <div className="px-3.5 pb-3">{children}</div>}
    </div>
  )
}

function KV({ k, v, vOk }: { k: string; v: string; vOk?: boolean }) {
  return (
    <div className="flex justify-between items-baseline py-0.5">
      <span className="text-[var(--color-text-3)] text-[11px]">{k}</span>
      <span className={`text-[var(--color-text-2)] text-[11px] font-[tabnum] text-right ${vOk ? 'text-[var(--color-ok)]' : ''}`}>{v}</span>
    </div>
  )
}
