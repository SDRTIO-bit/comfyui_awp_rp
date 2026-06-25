import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import RPPage from './pages/RPPage'

function Placeholder({ title }: { title: string }) {
  return (
    <div className="h-full flex items-center justify-center text-[var(--color-text-3)]">
      <div className="text-center">
        <div className="text-2xl mb-3 opacity-20">—</div>
        <div className="text-sm">{title}</div>
        <div className="text-xs mt-1 opacity-50">coming soon</div>
      </div>
    </div>
  )
}

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/rp" element={<RPPage />} />
        <Route path="/workbench" element={<Placeholder title="工作流编辑器" />} />
        <Route path="/resources" element={<Placeholder title="素材管理" />} />
        <Route path="*" element={<Navigate to="/rp" replace />} />
      </Routes>
    </BrowserRouter>
  )
}
