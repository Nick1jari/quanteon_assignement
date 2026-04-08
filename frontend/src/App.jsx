import { useState } from 'react'
import UploadPanel from './components/UploadPanel.jsx'
import ComparisonView from './components/ComparisonView.jsx'
import RedactionReport from './components/RedactionReport.jsx'
import Dashboard from './components/Dashboard.jsx'

export default function App() {
  const [tab, setTab] = useState('deidentify')
  const [result, setResult] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  const reset = () => { setResult(null); setError(null) }

  return (
    <div className="min-h-screen bg-gray-50">
      <header className="bg-white border-b border-gray-200">
        <div className="max-w-5xl mx-auto px-6 py-4 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <span className="text-base font-semibold text-gray-900">Medical De-identification</span>
            <span className="text-xs text-gray-400 bg-gray-100 px-2 py-0.5 rounded">HIPAA Safe Harbor</span>
          </div>
          <nav className="flex gap-1">
            {[
              { id: 'deidentify', label: 'De-identify' },
              { id: 'dashboard', label: 'Dashboard' },
            ].map(({ id, label }) => (
              <button
                key={id}
                onClick={() => setTab(id)}
                className={`px-4 py-1.5 text-sm rounded font-medium transition-colors ${
                  tab === id
                    ? 'bg-teal-700 text-white'
                    : 'text-gray-500 hover:text-gray-800 hover:bg-gray-100'
                }`}
              >
                {label}
              </button>
            ))}
          </nav>
        </div>
      </header>

      <main className="max-w-5xl mx-auto px-6 py-8">
        {tab === 'deidentify' ? (
          <div className="space-y-5">
            <UploadPanel
              onResult={setResult}
              onError={setError}
              onReset={reset}
              loading={loading}
              setLoading={setLoading}
            />

            {error && (
              <div className="border border-red-200 bg-red-50 text-red-700 px-4 py-3 rounded text-sm">
                {error}
              </div>
            )}

            {result && (
              <>
                <ComparisonView result={result} />
                <RedactionReport result={result} />
              </>
            )}
          </div>
        ) : (
          <Dashboard />
        )}
      </main>

      <footer className="border-t border-gray-200 mt-12 py-4 text-center text-xs text-gray-400">
        Medical De-identification System
      </footer>
    </div>
  )
}
