import { Fragment, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import {
  api, ApiError, getDocStatus, getImports, importDatasets, importPreflight, retryImport,
} from '../api'
import { Spinner, ErrorBox, Panel, StatCard } from '../components/ui'

/* ------------------------------------------------------------------ config */
const ACCEPT = '.pdf,.csv,.json,.txt,.text'
const MAX_MB = 25 // must match backend MAX_UPLOAD_MB default
const TERMINAL = new Set(['completed', 'failed'])

const STAGE_LABELS = {
  queued: 'Queued', uploaded: 'Uploaded', validating: 'Validating',
  parsing: 'Parsing', ocr_processing: 'OCR', extracting: 'Extracting',
  normalizing: 'Normalizing', resolving: 'Resolving', analyzing: 'Analyzing',
  completed: 'Completed', failed: 'Failed',
}

/* Canonical Crime Analysis fields offered for CSV column mapping (mirrors
   backend/app/services/dataset_import.py). */
const MAPPING_GROUPS = [
  { label: 'Call records (CDR)', fields: [
    ['caller_name', 'Caller name'], ['caller_phone', 'Caller phone'],
    ['callee_name', 'Receiver/callee name'], ['callee_phone', 'Receiver/callee phone'],
    ['duration', 'Call duration'],
  ] },
  { label: 'Transactions / banking', fields: [
    ['sender_name', 'Sender name'], ['sender_account', 'Sender account'],
    ['receiver_name', 'Receiver name'], ['receiver_account', 'Receiver account'],
    ['amount', 'Transaction amount'], ['transaction_id', 'Transaction ID'],
  ] },
  { label: 'Person & property', fields: [
    ['person_name', 'Person name'], ['phone', 'Phone number'], ['vehicle', 'Vehicle'],
    ['account', 'Bank account'], ['location', 'Location'],
  ] },
  { label: 'Date & time', fields: [
    ['date', 'Date'], ['time', 'Time'], ['timestamp', 'Date/time (single column)'],
  ] },
]

function fmtBytes(n) {
  if (!n) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB']
  const i = Math.min(units.length - 1, Math.floor(Math.log(n) / Math.log(1024)))
  return `${(n / (1024 ** i)).toFixed(i === 0 ? 0 : 1)} ${units[i]}`
}

function fileKey(f) { return `${f.name}|${f.size}|${f.lastModified || 0}` }

function quickIssues(f) {
  const ext = '.' + (f.name.split('.').pop() || '').toLowerCase()
  const issues = []
  if (!['.pdf', '.csv', '.json', '.txt', '.text'].includes(ext)) {
    issues.push('Unsupported file type. Supported formats: PDF, CSV, JSON, TXT.')
  }
  if (f.size === 0) issues.push('File is empty.')
  if (f.size > MAX_MB * 1024 * 1024) {
    issues.push(`File exceeds the maximum allowed size (${MAX_MB} MB).`)
  }
  return issues
}

/* -------------------------------------------------------------- Mapping UI */
function MappingEditor({ columns, mapping, onChange }) {
  const set = (field, col) => {
    const next = { ...mapping }
    if (col === '') {
      delete next[field]
    } else {
      // keep each column mapped at most once
      Object.keys(next).forEach((k) => { if (next[k] === col) delete next[k] })
      next[field] = col
    }
    onChange(next)
  }
  return (
    <div className="mapping-editor">
      <div className="muted small">Original CSV values are always preserved — mapped
        columns feed the Crime Analysis extraction pipeline (auto-detected where possible).
      </div>
      {MAPPING_GROUPS.map((group) => (
        <div key={group.label} className="mapping-group">
          <div className="mapping-group-label">{group.label}</div>
          {group.fields.map(([field, label]) => {
            const value = mapping[field] || ''
            return (
              <div key={field} className="mapping-row">
                <label className="mapping-field">{label}</label>
                <select
                  value={value}
                  onChange={(e) => set(field, e.target.value)}
                >
                  <option value="">— not mapped —</option>
                  {columns.map((c, i) => (
                    <option key={`${c}-${i}`} value={c}>[{i}] {c}</option>
                  ))}
                </select>
              </div>
            )
          })}
        </div>
      ))}
    </div>
  )
}

/* ------------------------------------------------------------ Main page */
export default function ImportData() {
  const params = useParams()
  const routeCaseId = params.caseId || null

  const [cases, setCases] = useState(null)
  const [caseId, setCaseId] = useState(null)
  const [history, setHistory] = useState(null)
  const [files, setFiles] = useState([])          // selected File objects
  const [pre, setPre] = useState({})              // fileKey -> server preflight
  const [mappings, setMappings] = useState({})    // fileKey -> {field: column}
  const [dragOver, setDragOver] = useState(false)
  const [busy, setBusy] = useState('')            // '' | 'upload' | 'processing'
  const [progress, setProgress] = useState(0)
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')
  const [perFileErrors, setPerFileErrors] = useState([])
  const [lastImport, setLastImport] = useState(null)
  const [retrying, setRetrying] = useState({})
  const [expanded, setExpanded] = useState({})   // docId -> show stage log
  const [stages, setStages] = useState({})       // docId -> jobs[]
  const inputRef = useRef(null)
  const busyRef = useRef(busy)
  busyRef.current = busy
  const caseIdRef = useRef(caseId)
  caseIdRef.current = caseId

  /* ------------------------------------------------------ case loading */
  const loadCases = useCallback(async () => {
    try {
      const list = await api('/cases')
      setCases(list)
      const preferred = routeCaseId && list.some((c) => c.id === routeCaseId)
        ? routeCaseId : (list[0] && list[0].id)
      setCaseId((prev) => prev || preferred)
    } catch (e) { setError(e.message) }
  }, [routeCaseId])

  useEffect(() => { loadCases() }, [loadCases])

  const loadHistory = useCallback(async (cid) => {
    if (!cid) return
    try { setHistory((await getImports(cid)).imports) } catch (e) { /* case may change */ }
  }, [])

  useEffect(() => {
    if (caseId) { setHistory(null); loadHistory(caseId) }
  }, [caseId, loadHistory])

  /* ------------------------------------------------------ file validation */
  const runPreflight = useCallback(async (cid, currentFiles) => {
    if (!cid || !currentFiles.length) return
    const needServer = currentFiles.filter((f) => quickIssues(f).length === 0)
    if (!needServer.length) return
    try {
      const res = await importPreflight(cid, needServer)
      setPre((old) => {
        const next = { ...old }
        res.files.forEach((item, i) => {
          const key = fileKey(needServer[i])
          next[key] = { state: 'done', ...item }
        })
        return next
      })
    } catch (e) {
      const bodyErrors = (e instanceof ApiError && e.body && e.body.errors) || []
      setError(`Pre-flight validation failed: ${bodyErrors.length
        ? bodyErrors.map((x) => `${x.filename}: ${x.error}`).join(' · ')
        : e.message}`)
    }
  }, [])

  useEffect(() => {
    if (!caseId) return
    // mark all current files as validating, then ask the server
    setPre((old) => {
      const next = { ...old }
      files.forEach((f) => {
        const key = fileKey(f)
        const q = quickIssues(f)
        if (q.length) {
          next[key] = { state: 'done', ok: false, filename: f.name,
                        file_type: null, size: f.size, errors: q,
                        warnings: [], needs_ocr: false }
        } else if (!next[key] || next[key].state === 'pending') {
          next[key] = { state: 'pending', filename: f.name, file_type: null,
                        size: f.size, errors: [], warnings: [] }
        }
      })
      return next
    })
    runPreflight(caseId, files)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [caseId, files, runPreflight])

  const revalidate = () => {
    setError(''); setPerFileErrors([])
    setPre((old) => {
      const next = { ...old }
      files.forEach((f) => { next[fileKey(f)] = { state: 'pending', filename: f.name } })
      return next
    })
    runPreflight(caseId, files)
  }

  /* ------------------------------------------------------ file selection */
  const addFiles = (list) => {
    const fresh = [...list].filter((f) => !files.some((x) => fileKey(x) === fileKey(f)))
    if (!fresh.length) return
    setFiles((old) => [...old, ...fresh])
    setError('')
    setPerFileErrors([])
    setLastImport(null)
  }

  const removeFile = (key) => {
    setFiles((old) => old.filter((f) => fileKey(f) !== key))
    setPre((old) => { const n = { ...old }; delete n[key]; return n })
    setMappings((old) => { const n = { ...old }; delete n[key]; return n })
  }

  const onDrop = (e) => {
    e.preventDefault(); setDragOver(false)
    addFiles(Array.from(e.dataTransfer.files || []))
  }

  /* ------------------------------------------------------ processing watch */
  const pollHistory = useCallback(async (cid, { untilDone = false } = {}) => {
    const h = (await getImports(cid)).imports
    setHistory(h)
    if (untilDone) {
      const active = h.filter((d) => !TERMINAL.has(d.status))
      if (!active.length && busyRef.current === 'processing') {
        setBusy('')
        setMessage('Import batch finished.')
        setLastImport(null)
      }
    }
  }, [])

  const waitDoc = useCallback(async (docId) => {
    for (let i = 0; i < 200; i++) {
      const st = await getDocStatus(docId)
      if (TERMINAL.has(st.status)) return st
      await new Promise((r) => setTimeout(r, 900))
    }
    return null
  }, [])

  useEffect(() => {
    if (busy !== 'processing') return
    const timer = setInterval(() => {
      if (caseIdRef.current) pollHistory(caseIdRef.current, { untilDone: true })
    }, 1200)
    return () => clearInterval(timer)
  }, [busy, pollHistory])

  /* ------------------------------------------------------ do the import */
  const doImport = async () => {
    if (!caseId || busy) return
    setError(''); setPerFileErrors([]); setMessage(''); setLastImport(null)
    const selected = files.filter((f) => {
      const r = pre[fileKey(f)]
      return r && r.state === 'done' && r.ok
    })
    if (!selected.length) return
    setBusy('upload'); setProgress(0)
    const order = selected.map((f) => fileKey(f))
    const mappingArr = order.map((k) => mappings[k] || {})
    try {
      const res = await importDatasets(caseId, selected, mappingArr, setProgress)
      const ids = (res.imports || []).map((d) => d.id)
      setBusy('processing')
      setProgress(100)
      setMessage(res.imports.length
        ? `${res.imports.length} file${res.imports.length > 1 ? 's' : ''} accepted — processing now…`
        : 'Import finished.')
      setLastImport({ ids, count: res.imports.length, ts: Date.now() })
      await pollHistory(caseId, { untilDone: true })
      setFiles([]); setPre({}); setMappings({})
    } catch (e) {
      setBusy('')
      if (e instanceof ApiError && e.body && Array.isArray(e.body.errors)) {
        setError(e.message)
        setPerFileErrors(e.body.errors)
      } else {
        setError(e.message)
      }
    }
  }

  /* ------------------------------------------------------ retry one file */
  const doRetry = async (doc) => {
    if (retrying[doc.id]) return
    setRetrying((r) => ({ ...r, [doc.id]: true }))
    setError('')
    try {
      await retryImport(doc.id)
      setMessage(`Retrying ${doc.filename}…`)
      const st = await waitDoc(doc.id)
      setMessage(st && st.status === 'completed'
        ? `${doc.filename} completed after retry.` : `Retry of ${doc.filename} finished.`)
      if (caseIdRef.current) pollHistory(caseIdRef.current)
    } catch (e) {
      setError(e.message)
    } finally {
      setRetrying((r) => ({ ...r, [doc.id]: false }))
    }
  }

  /* ------------------------------------- expandable per-import stage log */
  const toggleStages = async (doc) => {
    const open = !expanded[doc.id]
    setExpanded((old) => ({ ...old, [doc.id]: open }))
    if (open && !stages[doc.id]) {
      try {
        const st = await getDocStatus(doc.id)
        setStages((old) => ({ ...old, [doc.id]: st.jobs || [] }))
      } catch (e) { /* endpoint may be unavailable; nothing to show */ }
    }
  }

  /* ------------------------------------------------------ derived values */
  const resultsByKey = useMemo(() => {
    const out = {}
    files.forEach((f) => { const k = fileKey(f); out[k] = pre[k] || null })
    return out
  }, [files, pre])

  const validCount = useMemo(
    () => files.filter((f) => { const r = pre[fileKey(f)]; return r && r.ok }).length,
    [files, pre],
  )
  const pendingCount = files.filter((f) => {
    const r = pre[fileKey(f)]; return !r || r.state === 'pending'
  }).length

  const caseName = cases && caseId
    ? (cases.find((c) => c.id === caseId) || {}).name : null

  if (error && !files.length && !history) return <ErrorBox message={error} />
  if (!cases) return <Spinner label="Loading cases…" />
  if (!cases.length) {
    return (
      <div className="page">
        <h2>Dataset Importer</h2>
        <ErrorBox message="You do not have access to any cases yet. Ask an administrator to assign you to a case." />
      </div>
    )
  }

  const recentDocIds = new Set((lastImport && lastImport.ids) || [])

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h2>Dataset Importer</h2>
          <p className="muted">
            Import investigation datasets — PDF (incl. scanned/OCR), CSV, JSON, TXT —
            and run them through the Crime Analysis pipeline. Data is always treated as
            evidence to be validated, never as automatically true.
          </p>
        </div>
        <Link className="btn btn-outline" to={`/cases/${caseId}`}>← Back to case</Link>
      </div>

      {/* target case */}
      <Panel title="1 · Target case">
        <div className="case-picker">
          <label>Case</label>
          <select value={caseId || ''} onChange={(e) => { setCaseId(e.target.value) }}
            className="select-inline" disabled={!!busy}>
            {cases.map((c) => <option key={c.id} value={c.id}>{c.id} — {c.name}</option>)}
          </select>
          {caseName && <span className="muted small">All records stay isolated to this case.</span>}
        </div>
      </Panel>

      {/* dropzone */}
      <Panel title="2 · Select files">
        <div
          className={`dropzone ${dragOver ? 'drag-over' : ''} ${busy ? 'disabled' : ''}`}
          onDragOver={(e) => { e.preventDefault(); if (!busy) setDragOver(true) }}
          onDragLeave={() => setDragOver(false)}
          onDrop={onDrop}
          onClick={() => { if (!busy) inputRef.current && inputRef.current.click() }}
        >
          <div className="dropzone-icon">⬆</div>
          <div><b>Drag &amp; drop files here</b> or <span className="link">browse</span></div>
          <div className="muted small">
            PDF · scanned PDF (OCR) · CSV · JSON · TXT — up to {MAX_MB} MB per file,
            multiple files allowed
          </div>
          <input ref={inputRef} type="file" multiple accept={ACCEPT} hidden
            onChange={(e) => { addFiles(Array.from(e.target.files || [])); e.target.value = '' }}
          />
        </div>

        {files.length > 0 && (
          <div className="file-queue">
            {files.map((f) => {
              const key = fileKey(f)
              const r = resultsByKey[key]
              const isCsv = r && r.ok && r.file_type === 'csv' && r.columns && r.columns.length
              const issues = (r && r.errors) || []
              const warns = (r && r.warnings) || []
              const statusCls = !r ? 'pending' : !r.ok ? 'bad' : r.needs_ocr ? 'warn' : 'ok'
              const label = !r ? 'Validating…'
                : !r.ok ? 'Not ready' : r.needs_ocr ? 'OCR needed' : 'Ready'
              return (
                <div key={key} className={`file-row file-${statusCls}`}>
                  <div className="file-main">
                    <span className={`file-type file-type-${(r && r.file_type) || 'unknown'}`}>
                      {(r && r.file_type || '—').toUpperCase()}
                    </span>
                    <div className="file-meta">
                      <span className="file-name">{f.name}</span>
                      <span className="muted small">{fmtBytes(f.size)}
                        {r && r.rows != null && ` · ${r.rows} record${r.rows === 1 ? '' : 's'}`}
                      </span>
                    </div>
                    <span className={`badge import-${statusCls}`}>{label}</span>
                    <button className="btn btn-ghost file-remove" title="Remove"
                      onClick={(e) => { e.stopPropagation(); removeFile(key) }}>✕</button>
                  </div>

                  {issues.length > 0 && (
                    <ul className="file-issues">
                      {issues.map((msg, i) => <li key={i}>⚠ {msg}</li>)}
                    </ul>
                  )}
                  {warns.length > 0 && (
                    <ul className="file-warnings">
                      {warns.map((msg, i) => <li key={i}>ℹ {msg}</li>)}
                    </ul>
                  )}

                  {isCsv && (
                    <div className="mapping-wrap">
                      <details>
                        <summary>
                          Column mapping — {Object.keys(mappings[key] || r.mapping || {}).length}
                          {' '}of {r.columns.length} column{r.columns.length === 1 ? '' : 's'} mapped
                          {r.mapping && Object.keys(r.mapping).length
                            ? ' (auto-detected)' : ''}
                        </summary>
                        <MappingEditor columns={r.columns}
                          mapping={mappings[key] || r.mapping || {}}
                          onChange={(m) => setMappings((old) => ({ ...old, [key]: m }))} />
                      </details>
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        )}

        {perFileErrors.length > 0 && (
          <ErrorBox message={error} />
        )}
        {perFileErrors.length > 0 && (
          <div className="panel-error-list">
            {perFileErrors.map((e, i) => (
              <div key={i} className="error-line">
                <b className="mono">{e.filename}</b> — {e.error}
              </div>
            ))}
          </div>
        )}
        {error && perFileErrors.length === 0 && <ErrorBox message={error} />}

        {files.length > 0 && (
          <div className="import-actions">
            <button className="btn btn-primary btn-lg"
              disabled={busy || validCount === 0 || pendingCount > 0}
              onClick={doImport}>
              {busy === 'upload' ? `Uploading… ${progress}%`
                : busy === 'processing' ? 'Processing…'
                  : `Import ${validCount} file${validCount === 1 ? '' : 's'} into ${caseId}`}
            </button>
            {busy === 'upload' && (
              <div className="progress"><div className="progress-fill" style={{ width: `${progress}%` }} /></div>
            )}
            <span className="muted small">
              {validCount === 0 ? 'Files above need to pass validation first.'
                : pendingCount > 0 ? 'Waiting for validation…' : ''}
            </span>
            {pendingCount > 0 && !busy && (
              <button className="btn btn-outline btn-sm" onClick={revalidate}>
                Validate again
              </button>
            )}
          </div>
        )}

        {busy === 'processing' && history && (
          <div className="processing-live">
            <div className="info-box">
              <b>Processing…</b> {history.filter((d) => !TERMINAL.has(d.status)).length}
              {' '}file(s) in the pipeline. This page refreshes automatically.
            </div>
          </div>
        )}
        {message && <div className="info-box">{message}</div>}
      </Panel>

      {/* last import stats */}
      {history && history.length > 0 && (
        <Panel title="Import statistics (this case)">
          <div className="stat-grid">
            <StatCard label="Imports" value={history.length}
              hint={`${history.filter((d) => d.status === 'completed').length} completed`} />
            <StatCard label="Records processed" value={history.reduce((s, d) => s + (d.records_processed || 0), 0)} />
            <StatCard label="Entities discovered" value={history.reduce((s, d) => s + (d.entities_discovered || 0), 0)} />
            <StatCard label="People identified" value={history.reduce((s, d) => s + (d.persons_discovered || 0), 0)} />
            <StatCard label="Evidence records" value={history.reduce((s, d) => s + (d.evidence_discovered || 0), 0)} />
            <StatCard label="Relationship links" value={history.reduce((s, d) => s + (d.relationships_discovered || 0), 0)} />
          </div>
        </Panel>
      )}

      {/* import history */}
      <Panel title="Import history"
        actions={<Link className="link" to={`/cases/${caseId}`}>Case documents →</Link>}>
        {!history ? <Spinner label="Loading history…" />
          : history.length === 0
            ? <div className="empty muted">No datasets imported into this case yet.</div>
            : (
              <div className="history-scroll">
                <table className="table">
                  <thead>
                    <tr>
                      <th>File</th><th>Type</th><th>Uploaded</th><th>By</th>
                      <th>Status</th><th>Records</th><th>Entities</th><th>People</th>
                      <th>Evidence</th><th>Rels</th><th />
                    </tr>
                  </thead>
                  <tbody>
                    {history.map((d) => {
                      const fresh = recentDocIds.has(d.id) && d.case_id === caseId
                      const stage = STAGE_LABELS[d.status] || d.status
                      const open = !!expanded[d.id]
                      const jobLog = stages[d.id] || []
                      return (
                        <Fragment key={d.id}>
                          <tr className={fresh ? 'row-new' : ''}>
                            <td>
                              <div className="mono">{d.filename}</div>
                              {d.mapping && Object.keys(d.mapping).length > 0 && (
                                <div className="small muted">
                                  {Object.keys(d.mapping).length} column(s) mapped to Crime Analysis fields
                                </div>
                              )}
                              {d.error && <div className="import-error-line small">✕ {d.error}</div>}
                              {(d.warnings || []).map((w, i) => (
                                <div key={i} className="import-warn-line small muted">⚠ {w}</div>
                              ))}
                              {d.sha256 && <div className="hash-mono">sha {d.sha256.slice(0, 12)}…</div>}
                            </td>
                            <td><span className={`file-type file-type-${d.file_type}`}>{d.file_type}</span></td>
                            <td className="muted small">
                              {d.created_at ? new Date(d.created_at).toLocaleString() : '—'}
                            </td>
                            <td className="muted">{d.uploaded_by_name || '—'}</td>
                            <td>
                              <span className={`badge status-${d.status}`}>{stage}</span>
                              {d.retry_count > 0 && <span className="small muted"> · retry {d.retry_count}</span>}
                              {fresh && <span className="badge import-ok">new</span>}
                            </td>
                            <td className="mono">{d.records_processed}</td>
                            <td className="mono">{d.entities_discovered}</td>
                            <td className="mono">{d.persons_discovered}</td>
                            <td className="mono">{d.evidence_discovered}</td>
                            <td className="mono">{d.relationships_discovered}</td>
                            <td className="history-actions">
                              <button className="btn btn-ghost btn-sm" onClick={() => toggleStages(d)}>
                                {open ? 'Hide log' : 'Log'}
                              </button>
                              {d.status === 'failed' && (
                                <button className="btn btn-warn btn-sm"
                                  disabled={!!retrying[d.id]}
                                  onClick={() => doRetry(d)}>
                                  {retrying[d.id] ? 'Retrying…' : 'Retry'}
                                </button>
                              )}
                            </td>
                          </tr>
                          {open && (
                            <tr className="stage-log-row">
                              <td colSpan={11}>
                                <div className="stage-log">
                                  {jobLog.length === 0
                                    ? <span className="muted small">Loading stage log…</span>
                                    : jobLog.map((j, i) => (
                                      <span key={i} className={`stage-chip stage-${j.status || j.stage}`}>
                                        {STAGE_LABELS[j.stage] || j.stage || j.status}
                                      </span>
                                    ))}
                                  {jobLog.length > 0 && (
                                    <span className="muted small">
                                      {jobLog[0].message ? ` · ${jobLog[0].message}` : ''}
                                    </span>
                                  )}
                                </div>
                              </td>
                            </tr>
                          )}
                        </Fragment>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            )}
        {history && history.some((d) => d.status === 'failed') && (
          <div className="muted small history-hint">
            Failed imports keep their source file so they can be retried after the
            underlying problem is fixed (e.g. installing OCR software).
          </div>
        )}
      </Panel>
    </div>
  )
}
