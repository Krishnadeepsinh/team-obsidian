"use client"

import React from "react"

function renderInlineSegments(text: string) {
  const parts = text.split(/(\[Evidence\s+\d+\]|\*\*[^*]+\*\*|\*[^*]+\*|`[^`]+`)/g)
  return parts.map((part, idx) => {
    if (!part) return null
    if (/^\[Evidence\s+\d+\]$/.test(part)) {
      return (
        <span
          key={idx}
          className="inline-flex items-center px-1.5 py-0.5 mx-0.5 rounded-md bg-violet-100 border border-violet-200 text-violet-700 font-semibold text-[11px] align-baseline"
        >
          {part}
        </span>
      )
    }
    if (part.startsWith("**") && part.endsWith("**") && part.length > 4) {
      return (
        <strong key={idx} className="font-semibold text-slate-900">
          {part.slice(2, -2)}
        </strong>
      )
    }
    if (part.startsWith("*") && part.endsWith("*") && part.length > 2) {
      return (
        <em key={idx} className="text-slate-600 italic">
          {part.slice(1, -1)}
        </em>
      )
    }
    if (part.startsWith("`") && part.endsWith("`") && part.length > 2) {
      return (
        <code key={idx} className="px-1.5 py-0.5 rounded bg-slate-200/70 text-slate-800 font-mono text-[12px]">
          {part.slice(1, -1)}
        </code>
      )
    }
    return <span key={idx}>{part}</span>
  })
}

export function FormattedMarkdown({
  content,
  compact = false,
}: {
  content: string
  compact?: boolean
}) {
  const textSize = compact ? "text-xs" : "text-sm"
  const lines = content.split(/\r?\n/)
  const elements: React.ReactNode[] = []
  let listItems: string[] = []

  const flushList = (keyBase: number) => {
    if (listItems.length === 0) return
    elements.push(
      <ul key={`list-${keyBase}`} className="space-y-1.5 pl-4 my-1.5 list-disc marker:text-violet-500">
        {listItems.map((item, idx) => (
          <li key={idx} className={`${textSize} text-slate-800 leading-relaxed`}>
            {renderInlineSegments(item)}
          </li>
        ))}
      </ul>
    )
    listItems = []
  }

  lines.forEach((rawLine, idx) => {
    const line = rawLine.trim()
    if (!line) {
      flushList(idx)
      return
    }
    if (line.startsWith("### ") || line.startsWith("## ")) {
      flushList(idx)
      const heading = line.replace(/^#{2,3}\s+/, "")
      elements.push(
        <h4 key={`h-${idx}`} className={`${textSize} font-bold text-slate-900 pt-1`}>
          {renderInlineSegments(heading)}
        </h4>
      )
      return
    }
    if (/^[-*•]\s+/.test(line) || /^\d+\.\s+/.test(line)) {
      listItems.push(line.replace(/^([-*•]|\d+\.)\s+/, ""))
      return
    }
    flushList(idx)
    if (line.startsWith("> ")) {
      elements.push(
        <blockquote
          key={`q-${idx}`}
          className="border-l-2 border-violet-300 pl-3 py-0.5 my-1.5 text-xs text-slate-600 italic bg-white/70 rounded-r-lg"
        >
          {renderInlineSegments(line.slice(2))}
        </blockquote>
      )
      return
    }
    elements.push(
      <p key={`p-${idx}`} className={`${textSize} text-slate-800 leading-relaxed`}>
        {renderInlineSegments(line)}
      </p>
    )
  })
  flushList(lines.length)

  return <div className="space-y-1.5">{elements}</div>
}

