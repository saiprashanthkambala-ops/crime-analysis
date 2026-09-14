const TOKEN_KEY = 'crime_analysis_token'

export function getToken() { return localStorage.getItem(TOKEN_KEY) }
export function setToken(token) { localStorage.setItem(TOKEN_KEY, token) }
export function clearToken() {
  localStorage.removeItem(TOKEN_KEY)
  localStorage.removeItem('crime_analysis_user')
}

export async function api(path, options = {}) {
  const headers = { 'Content-Type': 'application/json', ...(options.headers || {}) }
  const token = getToken()
  if (token) headers['Authorization'] = 'Bearer ' + token
  const res = await fetch('/api' + path, { ...options, headers })
  if (res.status === 401) {
    clearToken()
    if (window.location.pathname !== '/login') window.location.href = '/login'
    throw new Error('Unauthorized')
  }
  if (!res.ok) {
    let detail = 'Request failed (' + res.status + ')'
    try {
      const body = await res.json()
      if (body.detail) detail = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail)
    } catch (_) {}
    throw new Error(detail)
  }
  if (res.status === 204) return null
  return res.json()
}

export async function streamAnalysisChat(caseIds, message, onToken, options = {}) {
  const controller = new AbortController()
  const timeout = window.setTimeout(
    () => controller.abort(),
    options.timeoutMs || 90000
  )

  try {
    const token = getToken()
    const res = await fetch('/api/analysis/chat', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: 'Bearer ' + token } : {}),
      },
      body: JSON.stringify({ case_ids: caseIds, message }),
      signal: controller.signal,
    })

    if (res.status === 401) {
      clearToken()
      if (window.location.pathname !== '/login') window.location.href = '/login'
      throw new Error('Unauthorized')
    }

    if (!res.ok) {
      let detail = 'Chat request failed (' + res.status + ')'
      try {
        const body = await res.json()
        if (body.detail) detail = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail)
      } catch (_) {}
      throw new Error(detail)
    }

    if (!res.body) throw new Error('Streaming is not supported by this browser.')

    const reader = res.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    let context = null

    while (true) {
      const { value, done } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })

      const lines = buffer.split('\n')
      buffer = lines.pop() || ''

      for (const line of lines) {
        if (!line.trim()) continue
        const event = JSON.parse(line)
        if (event.type === 'token') {
          onToken(event.content || '')
        } else if (event.type === 'done') {
          context = event.context || null
        } else if (event.type === 'error') {
          throw new Error(event.detail || 'NVIDIA streaming request failed.')
        }
      }
    }

    if (buffer.trim()) {
      const event = JSON.parse(buffer)
      if (event.type === 'token') onToken(event.content || '')
      else if (event.type === 'done') context = event.context || null
      else if (event.type === 'error') throw new Error(event.detail || 'NVIDIA streaming request failed.')
    }

    return { context }
  } finally {
    window.clearTimeout(timeout)
  }
}

export class ApiError extends Error {
  constructor(detail, status, body) {
    const message = typeof detail === 'string' ? detail : (detail && (detail.message || detail.example)) || 'Import failed (' + status + ')'
    super(message)
    this.status = status
    this.body = body || null
  }
}

function apiUpload(path, formData, onProgress) {
  return new Promise((resolve, reject) => {
    const token = getToken()
    const xhr = new XMLHttpRequest()
    xhr.open('POST', '/api' + path)
    if (token) xhr.setRequestHeader('Authorization', 'Bearer ' + token)
    if (onProgress) xhr.upload.onprogress = (e) => { if (e.lengthComputable) onProgress(Math.round((e.loaded / e.total) * 100)) }
    xhr.onload = () => {
      let body = null
      try { body = JSON.parse(xhr.responseText) } catch (_) {}
      if (xhr.status >= 200 && xhr.status < 300) resolve(body)
      else reject(new ApiError(body && body.detail, xhr.status, body))
    }
    xhr.onerror = () => reject(new Error('Network error during upload — is the server running?'))
    xhr.send(formData)
  })
}

export function uploadFile(caseId, file) {
  const form = new FormData()
  form.append('file', file)
  return apiUpload('/cases/' + caseId + '/upload', form)
}

export function importPreflight(caseId, files) {
  const form = new FormData()
  files.forEach((f) => form.append('files', f))
  return apiUpload('/cases/' + caseId + '/imports/preflight', form)
}
export function importDatasets(caseId, files, mappings, onProgress) {
  const form = new FormData()
  files.forEach((f) => form.append('files', f))
  if (mappings?.length) form.append('mapping', JSON.stringify(mappings))
  return apiUpload('/cases/' + caseId + '/imports', form, onProgress)
}
export function getImports(caseId) { return api('/cases/' + caseId + '/imports') }
export function retryImport(docId) { return api('/documents/' + docId + '/retry', { method: 'POST' }) }
export function getDocStatus(docId) { return api('/documents/' + docId + '/status') }
