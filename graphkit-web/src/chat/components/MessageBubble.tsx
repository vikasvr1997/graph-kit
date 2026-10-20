import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import type { ChatMessage } from '../types'
import { ChartRenderer } from './ChartRenderer'

interface Props {
  message: ChatMessage
  streaming?: boolean
  variantIndex: number
  variantCount: number
  onNavigateVariant: (delta: 1 | -1) => void
  onCopy: () => void
  onShare: () => void
  onRegenerate?: () => void
  onEdit?: () => void
}

export function MessageBubble({
  message, streaming, variantIndex, variantCount, onNavigateVariant, onCopy, onShare, onRegenerate, onEdit,
}: Props) {
  const isUser = message.role === 'user'

  return (
    <div className={`flex w-full gap-3 ${isUser ? 'justify-end' : ''}`}>
      <div className={`min-w-0 flex-1 ${isUser ? 'flex flex-col items-end' : ''}`}>
        {!isUser && message.model && (
          <p className="mb-1 text-xs text-muted">{message.model}</p>
        )}

        <div
          {...(!isUser ? { 'aria-live': streaming ? 'polite' : undefined } : {})}
          className={`rounded-2xl px-4 py-3 text-sm ${isUser ? 'bg-accent text-white' : 'card text-text'} ${isUser ? 'max-w-[85%]' : 'w-full'}`}
        >
          {message.error ? (
            <p className="text-red">{message.error}</p>
          ) : isUser ? (
            <p className="whitespace-pre-wrap">{message.text}</p>
          ) : (
            <div className="prose-chat">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{message.text || (streaming ? '...' : '')}</ReactMarkdown>
            </div>
          )}

          {message.chart && <div className="mt-3"><ChartRenderer spec={message.chart} /></div>}

          {!!message.references?.length && (
            <p className="mt-2 border-t border-border/60 pt-2 text-xs text-muted">
              Sources: {message.references.join(', ')}
            </p>
          )}
        </div>

        {!streaming && (
          <div className={`mt-1 flex items-center gap-2 text-xs text-muted ${isUser ? '' : ''}`}>
            {variantCount > 1 && (
              <span className="flex items-center gap-1">
                <button onClick={() => onNavigateVariant(-1)} aria-label="Previous response" className="hover:text-text">‹</button>
                {variantIndex + 1}/{variantCount}
                <button onClick={() => onNavigateVariant(1)} aria-label="Next response" className="hover:text-text">›</button>
              </span>
            )}
            <button onClick={onCopy} className="hover:text-text">Copy</button>
            <button onClick={onShare} className="hover:text-text">Share</button>
            {isUser && onEdit && <button onClick={onEdit} className="hover:text-text">Edit</button>}
            {!isUser && onRegenerate && <button onClick={onRegenerate} className="hover:text-text">Regenerate</button>}
          </div>
        )}
      </div>
    </div>
  )
}
