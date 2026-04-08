import { useState } from 'react'

function highlightPHI(text, entities) {
  if (!entities || entities.length === 0) return [{ text, hi: false }]
  const sorted = [...entities].sort((a, b) => b.original.length - a.original.length)
  let parts = [{ text, hi: false, type: null }]

  for (const entity of sorted) {
    if (!entity.original) continue
    const next = []
    for (const part of parts) {
      if (part.hi) { next.push(part); continue }
      const idx = part.text.indexOf(entity.original)
      if (idx === -1) { next.push(part); continue }
      if (idx > 0) next.push({ text: part.text.slice(0, idx), hi: false })
      next.push({ text: entity.original, hi: true, type: entity.phi_type })
      const after = part.text.slice(idx + entity.original.length)
      if (after) next.push({ text: after, hi: false })
    }
    parts = next
  }
  return parts
}

const RISK_COLOR = {
  CRITICAL: 'text-red-600',
  HIGH: 'text-orange-500',
  MEDIUM: 'text-yellow-600',
  LOW: 'text-green-600',
}

export default function ComparisonView({ result }) {
  const [highlight, setHighlight] = useState(true)
  const { text, phi_entities, statistics, audit } = result
  const hasEntities = phi_entities?.length > 0
  const parts = highlight && hasEntities ? highlightPHI(text.original, phi_entities) : null

  return (
    <div className="bg-white border border-gray-200 rounded-lg p-6">
      {/* Meta row */}
      <div className="flex items-center justify-between mb-4">
        <div className="text-sm text-gray-500 space-x-2">
          <span className="font-medium text-gray-800">{audit.filename}</span>
          <span>&middot;</span>
          <span>{statistics.total_phi_found} PHI found</span>
          <span>&middot;</span>
          <span className={`font-medium ${RISK_COLOR[statistics.risk_level] || 'text-gray-600'}`}>
            {statistics.risk_level} risk
          </span>
          <span>&middot;</span>
          <span>{audit.processing_time_ms} ms</span>
          {audit.ocr_used && (
            <span className="bg-gray-100 text-gray-600 text-xs px-2 py-0.5 rounded ml-1">OCR</span>
          )}
        </div>
        {hasEntities && (
          <button
            onClick={() => setHighlight(v => !v)}
            className="text-xs text-teal-700 hover:underline"
          >
            {highlight ? 'Hide' : 'Show'} highlights
          </button>
        )}
      </div>

      {!hasEntities ? (
        <p className="text-sm text-gray-500 py-4 text-center">
          No PHI detected in this document.
        </p>
      ) : (
        <div className="grid grid-cols-2 gap-4">
          {/* Original */}
          <div>
            <p className="text-xs font-medium text-gray-500 uppercase tracking-wide mb-2">Original</p>
            <div
              className="border border-gray-200 rounded bg-gray-50 p-3 font-mono text-xs leading-relaxed whitespace-pre-wrap overflow-y-auto"
              style={{ maxHeight: '420px' }}
            >
              {parts
                ? parts.map((p, i) =>
                    p.hi
                      ? <mark key={i} className="bg-amber-100 text-amber-800 rounded px-0.5 not-italic" title={p.type}>{p.text}</mark>
                      : <span key={i}>{p.text}</span>
                  )
                : text.original}
            </div>
          </div>

          {/* De-identified */}
          <div>
            <p className="text-xs font-medium text-gray-500 uppercase tracking-wide mb-2">De-identified</p>
            <div
              className="border border-gray-200 rounded bg-gray-50 p-3 font-mono text-xs leading-relaxed whitespace-pre-wrap overflow-y-auto"
              style={{ maxHeight: '420px' }}
            >
              {text.redacted}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
