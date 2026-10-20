import { lazy, Suspense, useEffect, useState } from 'react'
import { api } from './shared/api'

const ChatApp = lazy(() => import('./chat/App'))
const WorkflowApp = lazy(() => import('./graph/App'))

export default function App() {
  const [graphkit, setGraphkit] = useState<boolean | null>(null)
  const [chat, setChat] = useState(false)
  const [error, setError] = useState('')
  useEffect(() => {
    api.capabilities().then((c) => { setGraphkit(c.graphkit); setChat(c.chat) })
      .catch((e: Error) => setError(e.message))
  }, [])
  if (error) return <p className="p-6 text-red">Unable to load application: {error}</p>
  if (graphkit === null) return <p className="p-6 text-muted">Loading…</p>
  return <Suspense fallback={<p className="p-6 text-muted">Loading…</p>}>{graphkit ? <WorkflowApp chatEnabled={chat} /> : <ChatApp />}</Suspense>
}
