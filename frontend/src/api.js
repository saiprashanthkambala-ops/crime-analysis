const TOKEN_KEY = 'crimelink_token'

export function getToken() {
  return localStorage.getItem(TOKEN_KEY)
}

export function setToken(token) {
  localStorage.setItem(TOKEN_KEY, token)
}

export function clearToken() {
  localStorage.removeItem(TOKEN_KEY)
  localStorage.removeItem('crimelink_user')
}

export async function api(path, options = {}) {
  const headers = { 'Content-Type': 'application/json', ...(options.headers || {}) }
  const token = getToken()
  if (token) headers['Authorization'] = `Bearer ${token}`
  const res = await fetch(`/api${path}`, { ...options, headers })
  if (res.status === 401) {
    clearToken()
    if (window.location.pathname !== '/login') window.location.href = '/login'
    throw new Error('Unauthorized')
  }
  if (!res.ok) {
    let detail = `Request failed (${res.status})`
    try {
      const body = await res.json()
      if (body.detail) detail = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail)
    } catch (_) { /* ignore */ }
    throw new Error(detail)
  }
  if (res.status === 204) return null
  return res.json()
}

export async function uploadFile(caseId, file) {
  const form = new FormData()
  form.append('file', file)
  const token = getToken()
  const res = await fetch(`/api/cases/${caseId}/upload`, {
    method: 'POST',
    headers: token ? { Authorization: `Bearer ${token}` } : {},
    body: form,
  })
  if (!res.ok) {
    let detail = `Upload failed (${res.status})`
    try { const b = await res.json(); if (b.detail) detail = b.detail } catch (_) {}
    throw new Error(detail)
  }
  return res.json()
}

/* --------------------------------------------------------------------------
 * Dataset import API
 *
 * Uploads carry real upload progress via XMLHttpRequest (fetch has none).
 * A rejected batch returns HTTP 400/409 with
 *   detail: { message, errors: [{ filename, error, ... }] }
 * which is surfaced as an ApiError for the UI.
 * ------------------------------------------------------------------------ */
export class ApiError extends Error {
  constructor(detail, status, body) {
    const message = typeof detail === 'string'
      ? detail
      : (detail && (detail.message || detail.example))
        || `Import failed (${status})`
    super(message)
    this.status = status
    this.body = body || null
  }
}

function apiUpload(path, formData, onProgress) {
  return new Promise((resolve, reject) => {
    const token = getToken()
    const xhr = new XMLHttpRequest()
    xhr.open('POST', `/api${path}`)
    if (token) xhr.setRequestHeader('Authorization', `Bearer ${token}`)
    if (onProgress) {
      xhr.upload.onprogress = (e) => {
        if (e.lengthComputable) onProgress(Math.round((e.loaded / e.total) * 100))
      }
    }
    xhr.onload = () => {
      let body = null
      try { body = JSON.parse(xhr.responseText) } catch (_) { /* ignore */ }
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve(body)
      } else {
        reject(new ApiError(body && body.detail, xhr.status, body))
      }
    }
    xhr.onerror = () => reject(new Error('Network error during upload — is the server running?'))
    xhr.send(formData)
  })
}

export function importPreflight(caseId, files) {
  const form = new FormData()
  files.forEach((f) => form.append('files', f))
  return apiUpload(`/cases/${caseId}/imports/preflight`, form)
}

export function importDatasets(caseId, files, mappings, onProgress) {
  const form = new FormData()
  files.forEach((f) => form.append('files', f))
  if (mappings && mappings.length) form.append('mapping', JSON.stringify(mappings))
  return apiUpload(`/cases/${caseId}/imports`, form, onProgress)
}

export function getImports(caseId) {
  return api(`/cases/${caseId}/imports`)
}

export function retryImport(docId) {
  return api(`/documents/${docId}/retry`, { method: 'POST' })
}

export function getDocStatus(docId) {
  return api(`/documents/${docId}/status`)
}
