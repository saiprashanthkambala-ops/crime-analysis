export function getToken() { return null }
export function setToken(_) {}
export function clearToken() {
  localStorage.removeItem('crime_analysis_user')
}

export async function api(path, options = {}) {
  const headers = { 'Content-Type': 'application/json', ...(options.headers || {}) }
  const token = getToken()
  if (token) headers['Authorization'] = 'Bearer ' + token
  const res = await fetch('/api' + path, { ...options, headers, credentials: 'include' })
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
  let abortReason = ''
  let activityTimer = null

  const resetTimer = (ms, reason) => {
    if (activityTimer) window.clearTimeout(activityTimer)
    activityTimer = window.setTimeout(() => {
      abortReason = reason
      controller.abort()
    }, ms)
  }

  // Initial connection & TTFT timeout (30 seconds)
  resetTimer(options.connectTimeoutMs || 30000, 'AI response timed out waiting to start.')

  try {
    const res = await fetch('/api/analysis/chat', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        case_ids: caseIds,
        message,
        history: options.history || [],
        generated_analysis: options.generatedAnalysis || null,
      }),
      signal: controller.signal,
      credentials: 'include',
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

    const contentType = res.headers.get('content-type') || ''
    if (contentType.includes('application/json')) {
      const body = await res.json()
      if (body.answer) onToken(body.answer)
      return { context: body.context || null, mode: body.mode || 'deterministic' }
    }

    // Switch to inter-token idle timeout once stream begins
    resetTimer(options.idleTimeoutMs || 25000, 'AI streaming connection stalled.')

    const reader = res.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    let context = null
    let tool = null
    let mode = null

    while (true) {
      const { value, done } = await reader.read()
      if (done) break
      resetTimer(options.idleTimeoutMs || 25000, 'AI streaming connection stalled.')
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
          tool = event.tool || null
          mode = event.mode || null
        } else if (event.type === 'error') {
          throw new Error(event.detail || 'NVIDIA streaming request failed.')
        }
      }
    }

    if (buffer.trim()) {
      const event = JSON.parse(buffer)
      if (event.type === 'token') onToken(event.content || '')
      else if (event.type === 'done') { context = event.context || null; tool = event.tool || null; mode = event.mode || null }
      else if (event.type === 'error') throw new Error(event.detail || 'NVIDIA streaming request failed.')
    }

    return { context, tool, mode }
  } catch (err) {
    if (controller.signal.aborted) {
      throw new Error(abortReason || 'AI chat request timed out.')
    }
    throw err
  } finally {
    if (activityTimer) window.clearTimeout(activityTimer)
  }
}


export async function streamAnalysisGenerate(caseIds, onToken, options = {}) {
  const controller = new AbortController()
  let abortReason = ''
  let activityTimer = null

  const resetTimer = (ms, reason) => {
    if (activityTimer) window.clearTimeout(activityTimer)
    activityTimer = window.setTimeout(() => {
      abortReason = reason
      controller.abort()
    }, ms)
  }

  // Initial connection & TTFT timeout (30 seconds)
  resetTimer(options.connectTimeoutMs || 30000, 'Analysis generation timed out waiting for AI to start.')

  try {
    const res = await fetch('/api/analysis/generate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ case_ids: caseIds }),
      signal: controller.signal,
      credentials: 'include',
    })
    if (!res.ok) {
      let detail = 'Analysis request failed (' + res.status + ')'
      try {
        const body = await res.json()
        if (body.detail) detail = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail)
      } catch (_) {}
      throw new Error(detail)
    }
    if (!res.body) throw new Error('Streaming is not supported by this browser.')

    // Switch to inter-token idle timeout once stream begins
    resetTimer(options.idleTimeoutMs || 25000, 'Analysis streaming stalled.')

    const reader = res.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    let context = null

    while (true) {
      const { value, done } = await reader.read()
      if (done) break
      resetTimer(options.idleTimeoutMs || 25000, 'Analysis streaming stalled.')
      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split('\n')
      buffer = lines.pop() || ''
      for (const line of lines) {
        if (!line.trim()) continue
        const event = JSON.parse(line)
        if (event.type === 'token') onToken(event.content || '')
        else if (event.type === 'done') context = event.context || null
        else if (event.type === 'error') throw new Error(event.detail || 'Analysis streaming request failed.')
      }
    }
    if (buffer.trim()) {
      const event = JSON.parse(buffer)
      if (event.type === 'token') onToken(event.content || '')
      else if (event.type === 'done') context = event.context || null
      else if (event.type === 'error') throw new Error(event.detail || 'Analysis streaming request failed.')
    }
    return { context, mode: 'streaming' }
  } catch (err) {
    if (controller.signal.aborted) {
      throw new Error(abortReason || 'Analysis generation timed out.')
    }
    throw err
  } finally {
    if (activityTimer) window.clearTimeout(activityTimer)
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
    const xhr = new XMLHttpRequest()
    xhr.open('POST', '/api' + path)
    xhr.withCredentials = true
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
