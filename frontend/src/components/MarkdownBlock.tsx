import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

interface MarkdownBlockProps {
  content: string
  className?: string
  components?: Record<string, unknown>
}

export default function MarkdownBlock({ content, className, components }: MarkdownBlockProps) {
  return (
    <div className={className}>
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
        {content}
      </ReactMarkdown>
    </div>
  )
}
