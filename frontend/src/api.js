import axios from 'axios'

const BASE = '/api/v1'

const api = axios.create({ baseURL: BASE, timeout: 120_000 })

/** Normalise error messages for user display. */
export function parseError(err) {
  if (!err.response) {
    // Network failure — backend unreachable
    return 'Cannot reach the server. Make sure the backend is running.'
  }
  const detail = err.response?.data?.detail
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) return detail.map((d) => d.msg).join('; ')
  return `Unexpected error (HTTP ${err.response.status}).`
}

export async function deidentifyFile(file, mode = 'synthetic', onUploadProgress) {
  const form = new FormData()
  form.append('file', file)
  form.append('mode', mode)

  const { data } = await api.post('/deidentify', form, {
    headers: { 'Content-Type': 'multipart/form-data' },
    onUploadProgress,
  })
  return data
}

export async function listReports(limit = 20, offset = 0) {
  const { data } = await api.get('/reports', { params: { limit, offset } })
  return data
}

export async function getReport(id) {
  const { data } = await api.get(`/reports/${id}`)
  return data
}

export async function getDashboardStats() {
  const { data } = await api.get('/dashboard/stats')
  return data
}
