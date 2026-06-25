import { useState, useEffect, useCallback } from 'react'
import type { WorldbookEntry } from '../types'

interface Greeting {
  greeting_id: string
  index: number
  label?: string
  content: string
  is_default: boolean
}

interface CardEditorProps {
  cardId: string
  cardName: string
  onClose: () => void
}

type EditorTab = 'greetings' | 'worldbook'

export default function CardEditor({ cardId, cardName, onClose }: CardEditorProps) {
  const [tab, setTab] = useState<EditorTab>('greetings')
  const [greetings, setGreetings] = useState<Greeting[]>([])
  const [worldbook, setWorldbook] = useState<WorldbookEntry[]>([])
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [dirty, setDirty] = useState(false)

  // Load data
  useEffect(() => {
    const loadData = async () => {
      setLoading(true)
      try {
        const [gRes, wbRes] = await Promise.all([
          fetch(`/api/cards/${encodeURIComponent(cardId)}/greetings`),
          fetch(`/api/cards/${encodeURIComponent(cardId)}/worldbook`),
        ])
        const gData = await gRes.json()
        const wbData = await wbRes.json()
        setGreetings(Array.isArray(gData) ? gData : [])
        setWorldbook(Array.isArray(wbData) ? wbData : [])
      } catch (err) {
        console.error('Failed to load card data:', err)
      }
      setLoading(false)
    }
    loadData()
  }, [cardId])

  // Save greetings
  const saveGreetings = useCallback(async () => {
    setSaving(true)
    try {
      const res = await fetch(`/api/cards/${encodeURIComponent(cardId)}/greetings`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ greetings }),
      })
      const result = await res.json()
      if (result.ok) {
        setDirty(false)
      }
    } catch (err) {
      console.error('Failed to save greetings:', err)
    }
    setSaving(false)
  }, [cardId, greetings])

  // Save worldbook
  const saveWorldbook = useCallback(async () => {
    setSaving(true)
    try {
      const res = await fetch(`/api/cards/${encodeURIComponent(cardId)}/worldbook`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ worldbook }),
      })
      const result = await res.json()
      if (result.ok) {
        setDirty(false)
      }
    } catch (err) {
      console.error('Failed to save worldbook:', err)
    }
    setSaving(false)
  }, [cardId, worldbook])

  // Update greeting content
  const updateGreeting = (index: number, content: string) => {
    setGreetings(prev => prev.map((g, i) => i === index ? { ...g, content } : g))
    setDirty(true)
  }

  // Update worldbook entry
  const updateWorldbookEntry = (index: number, field: keyof WorldbookEntry, value: unknown) => {
    setWorldbook(prev => prev.map((e, i) => i === index ? { ...e, [field]: value } : e))
    setDirty(true)
  }

  if (loading) {
    return (
      <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
        <div className="bg-[var(--color-bg-surface)] rounded-lg p-8 text-[var(--color-text-3)]">
          加载中...
        </div>
      </div>
    )
  }

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
      <div className="bg-[var(--color-bg-surface)] rounded-lg w-[90vw] max-w-[1200px] h-[85vh] flex flex-col overflow-hidden border border-[var(--color-border)]">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-[var(--color-border)]">
          <div className="flex items-center gap-4">
            <h2 className="text-lg font-semibold text-[var(--color-text)]">编辑角色卡：{cardName}</h2>
            {dirty && <span className="text-xs text-[var(--color-accent)]">未保存</span>}
          </div>
          <div className="flex items-center gap-3">
            <button
              type="button"
              className="bg-[var(--color-accent-dim)] text-[var(--color-text)] text-sm px-4 py-2 rounded hover:bg-[var(--color-accent)] transition-colors disabled:opacity-50"
              disabled={!dirty || saving}
              onClick={() => tab === 'greetings' ? saveGreetings() : saveWorldbook()}
            >
              {saving ? '保存中...' : '保存'}
            </button>
            <button
              type="button"
              className="text-[var(--color-text-3)] hover:text-[var(--color-text)] text-xl px-2"
              onClick={onClose}
            >
              ×
            </button>
          </div>
        </div>

        {/* Tabs */}
        <div className="flex border-b border-[var(--color-border)]">
          <button
            type="button"
            className={`px-6 py-3 text-sm font-medium transition-colors ${tab === 'greetings' ? 'text-[var(--color-accent)] border-b-2 border-[var(--color-accent)]' : 'text-[var(--color-text-3)] hover:text-[var(--color-text)]'}`}
            onClick={() => setTab('greetings')}
          >
            开场白 ({greetings.length})
          </button>
          <button
            type="button"
            className={`px-6 py-3 text-sm font-medium transition-colors ${tab === 'worldbook' ? 'text-[var(--color-accent)] border-b-2 border-[var(--color-accent)]' : 'text-[var(--color-text-3)] hover:text-[var(--color-text)]'}`}
            onClick={() => setTab('worldbook')}
          >
            世界书 ({worldbook.length})
          </button>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto p-6">
          {tab === 'greetings' ? (
            <GreetingsEditor greetings={greetings} onUpdate={updateGreeting} />
          ) : (
            <WorldbookEditor entries={worldbook} onUpdate={updateWorldbookEntry} />
          )}
        </div>
      </div>
    </div>
  )
}

function GreetingsEditor({ greetings, onUpdate }: { greetings: Greeting[]; onUpdate: (index: number, content: string) => void }) {
  if (greetings.length === 0) {
    return <div className="text-[var(--color-text-3)] italic">此角色卡没有开场白。</div>
  }

  return (
    <div className="space-y-6">
      {greetings.map((greeting, index) => (
        <div key={greeting.greeting_id} className="border border-[var(--color-border)] rounded-lg p-4">
          <div className="flex items-center gap-2 mb-3">
            <span className="text-sm font-medium text-[var(--color-text)]">
              {greeting.label || `开场白 ${greeting.index + 1}`}
            </span>
            {greeting.is_default && (
              <span className="text-[10px] bg-[var(--color-accent-dim)] text-[var(--color-text)] px-2 py-0.5 rounded">
                默认
              </span>
            )}
            <span className="text-[11px] text-[var(--color-text-3)] ml-auto">
              {greeting.content.length} 字
            </span>
          </div>
          <textarea
            className="w-full bg-[var(--color-bg-app)] text-[var(--color-text)] border border-[var(--color-border)] rounded p-3 text-sm leading-relaxed min-h-[120px] resize-y font-inherit"
            value={greeting.content}
            onChange={(e) => onUpdate(index, e.target.value)}
            rows={6}
          />
        </div>
      ))}
    </div>
  )
}

function WorldbookEditor({ entries, onUpdate }: { entries: WorldbookEntry[]; onUpdate: (index: number, field: keyof WorldbookEntry, value: unknown) => void }) {
  if (entries.length === 0) {
    return <div className="text-[var(--color-text-3)] italic">此角色卡没有世界书条目。</div>
  }

  return (
    <div className="space-y-4">
      {entries.map((entry, index) => (
        <div key={entry.id} className="border border-[var(--color-border)] rounded-lg p-4">
          <div className="flex items-center gap-3 mb-3">
            <input
              type="text"
              className="flex-1 bg-[var(--color-bg-app)] text-[var(--color-text)] border border-[var(--color-border)] rounded px-3 py-1.5 text-sm"
              value={entry.title || ''}
              onChange={(e) => onUpdate(index, 'title', e.target.value)}
              placeholder="标题"
            />
            <select
              className="bg-[var(--color-bg-app)] text-[var(--color-text)] border border-[var(--color-border)] rounded px-2 py-1.5 text-sm"
              value={entry.activation}
              onChange={(e) => onUpdate(index, 'activation', e.target.value)}
            >
              <option value="const">常开</option>
              <option value="select">关键词触发</option>
              <option value="off">关闭</option>
            </select>
            <input
              type="number"
              className="w-20 bg-[var(--color-bg-app)] text-[var(--color-text)] border border-[var(--color-border)] rounded px-2 py-1.5 text-sm"
              value={entry.priority}
              onChange={(e) => onUpdate(index, 'priority', parseInt(e.target.value) || 0)}
              placeholder="优先级"
            />
          </div>
          <textarea
            className="w-full bg-[var(--color-bg-app)] text-[var(--color-text)] border border-[var(--color-border)] rounded p-3 text-sm leading-relaxed min-h-[80px] resize-y font-inherit"
            value={entry.content}
            onChange={(e) => onUpdate(index, 'content', e.target.value)}
            rows={4}
          />
          {entry.tags.length > 0 && (
            <div className="mt-2 text-[11px] text-[var(--color-accent-dim)]">
              关键词：{entry.tags.join(', ')}
            </div>
          )}
        </div>
      ))}
    </div>
  )
}
