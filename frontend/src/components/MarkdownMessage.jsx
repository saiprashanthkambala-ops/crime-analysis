import React from 'react'

function InlineMarkdown({ text }) {
  const parts = String(text).split(/(\*\*[^*]+\*\*|\*[^*]+\*)/g)
  return parts.map((part, i) => {
    if (part.startsWith('**') && part.endsWith('**')) return <strong key={i}>{part.slice(2, -2)}</strong>
    if (part.startsWith('*') && part.endsWith('*')) return <em key={i}>{part.slice(1, -1)}</em>
    return <span key={i}>{part}</span>
  })
}

export default function MarkdownMessage({ text }) {
  const lines = String(text || '').replace(/\r/g, '').split('\n')
  const blocks = []
  let bullets = []

  const flushBullets = () => {
    if (!bullets.length) return
    blocks.push(
      <ul key={'list-' + blocks.length} className="analysis-md-list">
        {bullets.map((item, i) => <li key={i}><InlineMarkdown text={item} /></li>)}
      </ul>
    )
    bullets = []
  }

  lines.forEach((raw, index) => {
    const line = raw.trim()
    if (!line) {
      flushBullets()
      return
    }

    const heading = line.match(/^#{1,3}\s+(.+)$/)
    if (heading) {
      flushBullets()
      blocks.push(<h4 key={'h-' + index} className="analysis-md-heading"><InlineMarkdown text={heading[1]} /></h4>)
      return
    }

    const bullet = line.match(/^[-*]\s+(.+)$/)
    if (bullet) {
      bullets.push(bullet[1])
      return
    }

    flushBullets()
    blocks.push(<p key={'p-' + index} className="analysis-md-paragraph"><InlineMarkdown text={line} /></p>)
  })

  flushBullets()
  return <div className="analysis-markdown">{blocks}</div>
}
