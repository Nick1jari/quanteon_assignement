import { useState } from 'react'

const RISK_COLOR = {
  CRITICAL: 'text-red-600',
  HIGH: 'text-orange-500',
  MEDIUM: 'text-yellow-600',
  LOW: 'text-green-600',
}

function downloadReport(result) {
  const { audit, statistics, phi_entities } = result
  const lines = [
    'HIPAA DE-IDENTIFICATION AUDIT REPORT',
    '='.repeat(40),
    `File:            ${audit.filename}`,
    `Processed at:    ${audit.processed_at}`,
    `Mode:            ${audit.mode}`,
    `OCR used:        ${audit.ocr_used}`,
    `Processing time: ${audit.processing_time_ms} ms`,
    '',
    'STATISTICS',
    '-'.repeat(40),
    `Total PHI found: ${statistics.total_phi_found}`,
    `Risk level:      ${statistics.risk_level} (score: ${statistics.risk_score}/100)`,
    '',
    'PHI by category:',
    ...Object.entries(statistics.by_category || {}).map(([k, v]) => `  ${k}: ${v}`),
    '',
    'PHI ENTITIES',
    '-'.repeat(40),
    ...(phi_entities.length === 0
      ? ['  None detected.']
      : phi_entities.map(
          (e, i) =>
            `${i + 1}. [${e.phi_type}] "${e.original}" → "${e.replacement}"\n   Context: ${e.context}`
        )),
  ]

  const blob = new Blob([lines.join('\n')], { type: 'text/plain' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `audit-${audit.filename}.txt`
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
}

export default function RedactionReport({ result }) {
  const [downloaded, setDownloaded] = useState(false)
  const { statistics, phi_entities, audit } = result

  const handleDownload = () => {
    downloadReport(result)
    setDownloaded(true)
    setTimeout(() => setDownloaded(false), 2500)
  }

  return (
    <div className="bg-white border border-gray-200 rounded-lg p-6">
      {/* Header */}
      <div className="flex items-center justify-between mb-5">
        <h2 className="text-sm font-semibold text-gray-700 uppercase tracking-wide">
          Redaction Report
        </h2>
        <button
          onClick={handleDownload}
          className="text-sm text-teal-700 hover:underline"
        >
          {downloaded ? 'Downloaded ✓' : 'Download report'}
        </button>
      </div>

      {/* Stat row */}
      <div className="grid grid-cols-4 gap-3 mb-6">
        <div className="border border-gray-200 rounded p-3">
          <p className="text-xl font-bold text-gray-900">{statistics.total_phi_found}</p>
          <p className="text-xs text-gray-500 mt-0.5">PHI found</p>
        </div>
        <div className="border border-gray-200 rounded p-3">
          <p className={`text-xl font-bold ${RISK_COLOR[statistics.risk_level] || 'text-gray-700'}`}>
            {statistics.risk_level}
          </p>
          <p className="text-xs text-gray-500 mt-0.5">Risk level</p>
        </div>
        <div className="border border-gray-200 rounded p-3">
          <p className="text-xl font-bold text-gray-900">
            {statistics.risk_score}
            <span className="text-sm font-normal text-gray-400">/100</span>
          </p>
          <p className="text-xs text-gray-500 mt-0.5">Risk score</p>
        </div>
        <div className="border border-gray-200 rounded p-3">
          <p className="text-xl font-bold text-gray-900">
            {Object.keys(statistics.by_category || {}).length}
          </p>
          <p className="text-xs text-gray-500 mt-0.5">PHI categories</p>
        </div>
      </div>

      {/* PHI entities table */}
      {phi_entities.length === 0 ? (
        <p className="text-sm text-gray-500">No PHI entities detected.</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-gray-200 text-left">
                <th className="pb-2 pr-4 text-gray-500 font-medium w-6">#</th>
                <th className="pb-2 pr-4 text-gray-500 font-medium">Type</th>
                <th className="pb-2 pr-4 text-gray-500 font-medium">Original</th>
                <th className="pb-2 pr-4 text-gray-500 font-medium">Replacement</th>
                <th className="pb-2 text-gray-500 font-medium">Context</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {phi_entities.map((e, i) => (
                <tr key={i} className="hover:bg-gray-50">
                  <td className="py-2 pr-4 text-gray-400">{i + 1}</td>
                  <td className="py-2 pr-4">
                    <span className="font-mono bg-gray-100 text-gray-700 px-1.5 py-0.5 rounded text-xs">
                      {e.phi_type}
                    </span>
                  </td>
                  <td className="py-2 pr-4 font-mono text-red-600 max-w-[160px] truncate">{e.original}</td>
                  <td className="py-2 pr-4 font-mono text-teal-700 max-w-[160px] truncate">{e.replacement}</td>
                  <td className="py-2 text-gray-500 max-w-[200px] truncate">{e.context}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
