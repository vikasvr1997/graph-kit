import type { User } from 'firebase/auth'
import { useEffect, useState } from 'react'
import { ChatView } from './components/ChatView'
import { onAuthChange } from './firebase'

export default function ChatApp() {
  const [user, setUser] = useState<User | null>(null)
  useEffect(() => onAuthChange(setUser), [])
  return <ChatView workspace="chat" user={user} graphEnabled={false} />
}
