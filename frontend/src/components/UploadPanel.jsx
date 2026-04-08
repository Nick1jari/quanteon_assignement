import { useState, useCallback } from 'react'
import { useDropzone } from 'react-dropzone'
import { deidentifyFile, parseError } from '../api.js'

const ACCEPTED = {
  'application/pdf': ['.pdf'],
  'image/png': ['.png'],
  'image/jpeg': ['.jpg', '.jpeg'],
  'image/tiff': ['.tiff'],
  'text/plain': ['.txt'],
}

export default function UploadPanel({ onResult, onError, onReset, loading, setLoading }) {
  const [file, setFile] = useState(null)
  const [mode, setMode] = useState('synthetic')

  const onDrop = useCallback((accepted) => {
    if (accepted.length > 0) {
      setFile(accepted[0])
      onReset()
    }
  }, [onReset])

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: ACCEPTED,
    multiple: false,
    maxSize: 20 * 1024 * 1024,
  })

  const handleRemove = (e) => {
    e.stopPropagation()
    setFile(null)
    onReset()
  }

  const handleSubmit = async () => {
    if (!file) return
    setLoading(true)
    try {
      const data = await deidentifyFile(file, mode)
      onResult(data)
    } catch (err) {
      onError(parseError(err))
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="bg-white border border-gray-200 rounded-lg p-6">
      <h2 className="text-sm font-semibold text-gray-700 uppercase tracking-wide mb-4">
        Upload Document
      </h2>

      {/* Dropzone */}
      <div
        {...getRootProps()}
        className={`border-2 border-dashed rounded p-8 text-center cursor-pointer transition-colors ${
          isDragActive
            ? 'border-teal-500 bg-teal-50'
            : file
            ? 'border-gray-300 bg-gray-50'
            : 'border-gray-300 hover:border-teal-400 hover:bg-gray-50'
        }`}
      >
        <input {...getInputProps()} />
        {file ? (
          <div className="flex items-center justify-center gap-3 text-sm">
            <span className="font-medium text-gray-800 truncate max-w-xs">{file.name}</span>
            <span className="text-gray-400 text-xs">({(file.size / 1024).toFixed(0)} KB)</span>
            <button
              onClick={handleRemove}
              className="text-gray-400 hover:text-gray-700 text-xs ml-1"
              title="Remove"
            >
              ✕
            </button>
          </div>
        ) : isDragActive ? (
          <p className="text-sm text-teal-600">Drop the file here</p>
        ) : (
          <div>
            <p className="text-sm text-gray-600">Drag & drop a file, or click to select</p>
            <p className="text-xs text-gray-400 mt-1">PDF, PNG, JPG, TIFF, TXT — max 20 MB</p>
          </div>
        )}
      </div>

      {/* Mode selection */}
      <div className="mt-4 flex items-center gap-6">
        <span className="text-sm text-gray-600 font-medium">Mode:</span>
        {[
          { value: 'synthetic', label: 'Synthetic data', desc: 'Replace PHI with realistic fake data' },
          { value: 'placeholder', label: 'Placeholders', desc: 'Replace PHI with [LABEL] tags' },
        ].map(({ value, label, desc }) => (
          <label key={value} className="flex items-start gap-2 cursor-pointer">
            <input
              type="radio"
              name="mode"
              value={value}
              checked={mode === value}
              onChange={() => setMode(value)}
              className="mt-0.5 accent-teal-700"
            />
            <div>
              <span className="text-sm text-gray-800">{label}</span>
              <p className="text-xs text-gray-400">{desc}</p>
            </div>
          </label>
        ))}
      </div>

      {/* Submit */}
      <div className="mt-5 flex items-center gap-4">
        <button
          onClick={handleSubmit}
          disabled={!file || loading}
          className="px-5 py-2 bg-teal-700 hover:bg-teal-800 disabled:bg-gray-200 disabled:text-gray-400 disabled:cursor-not-allowed text-white text-sm font-medium rounded transition-colors"
        >
          {loading ? 'Processing…' : 'De-identify Document'}
        </button>
        {loading && (
          <span className="text-xs text-gray-400">This may take 10–30 seconds</span>
        )}
      </div>
    </div>
  )
}
