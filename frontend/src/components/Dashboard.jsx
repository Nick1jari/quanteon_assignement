import { useState, useEffect, useCallback } from 'react'
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell,
} from 'recharts'
import { getDashboardStats, listReports } from '../api.js'

const COLORS = ['#0f766e', '#0891b2', '#7c3aed', '#db2777', '#d97706', '#16a34a', '#dc2626', '#9333ea']

function StatCard({ label, value }) {
  return (
    <div className="border border-gray-200 rounded p-4 bg-white">
      <p className="text-2xl font-bold text-gray-800">{value}</p>
      <p className="text-xs text-gray-500 mt-1">{label}</p>
    </div>
  )
}

export default function Dashboard() {
  const [stats, setStats] = useState(null)
  const [reports, setReports] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const [s, r] = await Promise.all([getDashboardStats(), listReports(10)])
      setStats(s)
      setReports(r.records || [])
    } catch {
      setError('Failed to load dashboard data.')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  if (loading) {
    return <p className="text-sm text-gray-500 text-center py-12">Loading…</p>
  }

  if (error) {
    return (
      <div className="text-sm text-red-600 py-4">
        {error}
        <button onClick={load} className="underline ml-3">Retry</button>
      </div>
    )
  }

  if (!stats || stats.total_documents === 0) {
    return (
      <div className="bg-white border border-gray-200 rounded-lg p-12 text-center">
        <p className="text-sm text-gray-500">
          No documents processed yet. Upload a document from the De-identify tab to get started.
        </p>
      </div>
    )
  }

  const barData = Object.entries(stats.phi_by_category || {}).map(([name, value]) => ({ name, value }))

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold text-gray-700 uppercase tracking-wide">Compliance Dashboard</h2>
        <button onClick={load} className="text-sm text-teal-700 hover:underline">Refresh</button>
      </div>

      {/* Summary stats */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard label="Documents processed" value={stats.total_documents} />
        <StatCard label="Total PHI redacted" value={stats.total_phi_found} />
        <StatCard label="OCR documents" value={stats.ocr_count} />
        <StatCard label="Avg processing time" value={`${stats.avg_processing_time_ms} ms`} />
      </div>

      {/* Charts */}
      {barData.length > 0 && (
        <div className="bg-white border border-gray-200 rounded-lg p-5">
            <p className="text-sm font-medium text-gray-700 mb-4">PHI by Category</p>
            <ResponsiveContainer width="100%" height={220}>
              <BarChart data={barData} margin={{ top: 0, right: 0, left: -20, bottom: 45 }}>
                <XAxis
                  dataKey="name"
                  tick={{ fontSize: 10 }}
                  angle={-30}
                  textAnchor="end"
                  interval={0}
                />
                <YAxis tick={{ fontSize: 10 }} allowDecimals={false} />
                <Tooltip contentStyle={{ fontSize: 11, borderRadius: 4 }} />
                <Bar dataKey="value" radius={[2, 2, 0, 0]}>
                  {barData.map((_, i) => (
                    <Cell key={i} fill={COLORS[i % COLORS.length]} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
      )}

      {/* Recent documents */}
      {reports.length > 0 && (
        <div className="bg-white border border-gray-200 rounded-lg p-5">
          <p className="text-sm font-medium text-gray-700 mb-4">Recent Documents</p>
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-gray-200 text-left text-gray-500">
                {['File', 'PHI Found', 'Mode', 'OCR', 'Time', 'Processed At'].map((h) => (
                  <th key={h} className="pb-2 pr-4 font-medium">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {reports.map((r) => (
                <tr key={r.id} className="hover:bg-gray-50">
                  <td className="py-2 pr-4 font-medium text-gray-800 max-w-[180px] truncate">{r.filename}</td>
                  <td className="py-2 pr-4 text-red-600 font-bold">{r.phi_count}</td>
                  <td className="py-2 pr-4 text-gray-500">{r.mode}</td>
                  <td className="py-2 pr-4 text-gray-500">{r.ocr_used ? 'Yes' : 'No'}</td>
                  <td className="py-2 pr-4 text-gray-500">{r.processing_time_ms} ms</td>
                  <td className="py-2 text-gray-400">
                    {r.created_at ? new Date(r.created_at).toLocaleString() : '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
