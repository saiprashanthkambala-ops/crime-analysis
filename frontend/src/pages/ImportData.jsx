import { Fragment, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import {
  api, ApiError, getDocStatus, getImports, importDatasets, importPreflight, retryImport,
} from '../api'
import { useI18n } from '../i18n'
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
  { labelKey: 'group_cdr', fields: [
    ['caller_name', 'field_caller_name'], ['caller_phone', 'field_caller_phone'],
    ['callee_name', 'field_callee_name'], ['callee_phone', 'field_callee_phone'],
    ['duration', 'field_call_duration'],
  ] },
  { labelKey: 'group_banking', fields: [
    ['sender_name', 'field_sender_name'], ['sender_account', 'field_sender_account'],
    ['receiver_name', 'field_receiver_name'], ['receiver_account', 'field_receiver_account'],
    ['amount', 'field_amount'], ['transaction_id', 'field_transaction_id'],
  ] },
  { labelKey: 'group_person_property', fields: [
    ['person_name', 'field_person_name'], ['phone', 'field_phone'], ['vehicle', 'field_vehicle'],
    ['account', 'field_account'], ['location', 'field_location'],
  ] },
  { labelKey: 'group_datetime', fields: [
    ['date', 'field_date'], ['time', 'field_time'], ['timestamp', 'field_timestamp'],
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
  const { t } = useI18n()
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
      <div className="muted small">{t('mapping_intro_desc')}</div>
      {MAPPING_GROUPS.map((group) => (
        <div key={group.labelKey} className="mapping-group">
          <div className="mapping-group-label">{t(group.labelKey)}</div>
          {group.fields.map(([field, labelKey]) => {
            const value = mapping[field] || ''
            return (
              <div key={field} className="mapping-row">
                <label className="mapping-field">{t(labelKey)}</label>
                <select
                  value={value}
                  onChange={(e) => set(field, e.target.value)}
                >
                  <option value="">{t('not_mapped_option')}</option>
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
  const { t } = useI18n()
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
        setMessage(t('import_batch_finished'))
        setLastImport(null)
      }
    }
  }, [t])

  const waitDoc = useCallback(async (docId) => {
    for (let i = 0; i < 200; i++) {
      const st = await getDocStatus(docId)
      if (TERMINAL.has(st.status)) return st
      await new Promise((r) => setTimeout(r, 900))
    }
    return null
  }, [])

  const resultsByKey = useMemo(() => {
    const out = {}
    files.forEach((f) => { const k = fileKey(f); out[k] = pre[k] || null })
    return out
  }, [files, pre])

  const validCount = files.filter((f) => {
    const r = resultsByKey[fileKey(f)]
    return r && r.ok
  }).length

  const pendingCount = files.length - Object.keys(resultsByKey).length

  /* ------------------------------------------------------------ import */
  const doImport = async () => {
    if (!caseId || !files.length || busy) return
    const eligible = files.filter((f) => (resultsByKey[fileKey(f)] || {}).ok)
    if (!eligible.length) {
      setError(t('pass_validation_first'))
      return
    }

    setBusy('upload')
    setProgress(0)
    setError('')
    setMessage('')
    setPerFileErrors([])

    // assemble mappings matching backend: [{ filename, mapping: {...} }]
    const mappingPayload = eligible
      .map((f) => {
        const k = fileKey(f)
        const m = mappings[k]
        return m && Object.keys(m).length > 0 ? { filename: f.name, mapping: m } : null
      })
      .filter(Boolean)

    try {
      const resp = await importDatasets(caseId, eligible, mappingPayload, (pct) => {
        setProgress(pct)
      })
      setBusy('processing')
      setLastImport({
        ids: (resp.documents || []).map((d) => d.id),
        count: (resp.documents || []).length,
      })
      // Clear queue for successfully imported files
      setFiles([])
      setPre({})
      setMappings({})
      await loadHistory()
    } catch (err) {
      setBusy('')
      if (err instanceof ApiError && err.body && Array.isArray(err.body.errors)) {
        setError(err.message)
        setPerFileErrors(err.body.errors)
      } else {
        setError(err.message || t('import_failed'))
      }
    }
  }

  const doRetry = async (doc) => {
    setRetrying((old) => ({ ...old, [doc.id]: true }))
    try {
      await retryImport(doc.id)
      await loadHistory()
    } catch (err) {
      setError(err.message)
    } finally {
      setRetrying((old) => { const c = { ...old }; delete c[doc.id]; return c })
    }
  }

  const toggleStages = async (doc) => {
    const willOpen = !expanded[doc.id]
    setExpanded((old) => ({ ...old, [doc.id]: willOpen }))
    if (willOpen && !stages[doc.id]) {
      try {
        const info = await getDocStatus(doc.id)
        setStages((old) => ({ ...old, [doc.id]: info.jobs || [] }))
      } catch (_) {}
    }
  }

  const caseName = cases && caseId
    ? (cases.find((c) => c.id === caseId) || {}).name : null

  if (error && !files.length && !history) return <ErrorBox message={error} />
  if (!cases) return <Spinner label={t('loading_cases')} />
  if (!cases.length) {
    return (
      <div className="page">
        <h2>{t('dataset_importer')}</h2>
        <ErrorBox message={t('no_cases_access_warning')} />
      </div>
    )
  }

  const recentDocIds = new Set((lastImport && lastImport.ids) || [])

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h2>{t('dataset_importer')}</h2>
          <p className="muted">
            {t('dataset_importer_desc')}
          </p>
        </div>
        <Link className="btn btn-outline" to={`/cases/${caseId}`}>{t('back_to_case')}</Link>
      </div>

      {/* target case */}
      <Panel title={t('step_target_case')}>
        <div className="case-picker">
          <label>{t('case_select_label')}</label>
          <select value={caseId || ''} onChange={(e) => { setCaseId(e.target.value) }}
            className="select-inline" disabled={!!busy}>
            {cases.map((c) => <option key={c.id} value={c.id}>{c.id} — {c.name}</option>)}
          </select>
          {caseName && <span className="muted small">{t('records_isolated_note')}</span>}
        </div>
      </Panel>

      {/* dropzone */}
      <Panel title={t('step_select_files')}>
        <div
          className={`dropzone ${dragOver ? 'drag-over' : ''} ${busy ? 'disabled' : ''}`}
          onDragOver={(e) => { e.preventDefault(); if (!busy) setDragOver(true) }}
          onDragLeave={() => setDragOver(false)}
          onDrop={onDrop}
          onClick={() => { if (!busy) inputRef.current && inputRef.current.click() }}
        >
          <div className="dropzone-icon">⬆</div>
          <div><b>{t('drag_drop_browse')}</b></div>
          <div className="muted small">
            {t('drag_drop_subtext', { maxMb: MAX_MB })}
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
              const label = !r ? t('validation_pending')
                : !r.ok ? t('validation_not_ready') : r.needs_ocr ? t('validation_ocr_needed') : t('validation_ready')
              return (
                <div key={key} className={`file-row file-${statusCls}`}>
                  <div className="file-main">
                    <span className={`file-type file-type-${(r && r.file_type) || 'unknown'}`}>
                      {(r && r.file_type || '—').toUpperCase()}
                    </span>
                    <div className="file-meta">
                      <span className="file-name">{f.name}</span>
                      <span className="muted small">{fmtBytes(f.size)}
                        {r && r.rows != null && ` · ${t('records_counter', { count: r.rows, suffix: r.rows === 1 ? '' : 's' })}`}
                      </span>
                    </div>
                    <span className={`badge import-${statusCls}`}>{label}</span>
                    <button className="btn btn-ghost file-remove" title={t('remove_file_title')}
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
                          {t('column_mapping_summary', {
                            mapped: Object.keys(mappings[key] || r.mapping || {}).length,
                            total: r.columns.length,
                            suffix: r.columns.length === 1 ? '' : 's',
                            auto: r.mapping && Object.keys(r.mapping).length ? t('auto_detected_tag') : '',
                          })}
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
              {busy === 'upload' ? t('uploading_progress', { progress })
                : busy === 'processing' ? t('processing_progress')
                  : t('import_button_action', { count: validCount, suffix: validCount === 1 ? '' : 's', caseId })}
            </button>
            {busy === 'upload' && (
              <div className="progress"><div className="progress-fill" style={{ width: `${progress}%` }} /></div>
            )}
            <span className="muted small">
              {validCount === 0 ? t('pass_validation_first')
                : pendingCount > 0 ? t('waiting_for_validation') : ''}
            </span>
            {pendingCount > 0 && !busy && (
              <button className="btn btn-outline btn-sm" onClick={revalidate}>
                {t('validate_again')}
              </button>
            )}
          </div>
        )}

        {busy === 'processing' && history && (
          <div className="processing-live">
            <div className="info-box">
              {t('processing_live_banner', { count: history.filter((d) => !TERMINAL.has(d.status)).length })}
            </div>
          </div>
        )}
        {message && <div className="info-box">{message}</div>}
      </Panel>

      {/* last import stats */}
      {history && history.length > 0 && (
        <Panel title={t('import_stats_title')}>
          <div className="stat-grid">
            <StatCard label={t('stat_imports')} value={history.length}
              hint={t('stat_completed_hint', { count: history.filter((d) => d.status === 'completed').length })} />
            <StatCard label={t('stat_records_processed')} value={history.reduce((s, d) => s + (d.records_processed || 0), 0)} />
            <StatCard label={t('stat_entities_discovered')} value={history.reduce((s, d) => s + (d.entities_discovered || 0), 0)} />
            <StatCard label={t('stat_people_identified')} value={history.reduce((s, d) => s + (d.persons_discovered || 0), 0)} />
            <StatCard label={t('stat_evidence_records')} value={history.reduce((s, d) => s + (d.evidence_discovered || 0), 0)} />
            <StatCard label={t('stat_relationship_links')} value={history.reduce((s, d) => s + (d.relationships_discovered || 0), 0)} />
          </div>
        </Panel>
      )}

      {/* import history */}
      <Panel title={t('import_history_title')}
        actions={<Link className="link" to={`/cases/${caseId}`}>{t('case_documents_link')}</Link>}>
        {!history ? <Spinner label={t('loading_stage_log')} />
          : history.length === 0
            ? <div className="empty muted">{t('no_datasets_imported')}</div>
            : (
              <div className="history-scroll">
                <table className="table">
                  <thead>
                    <tr>
                      <th>{t('col_file')}</th><th>{t('col_type')}</th><th>{t('col_uploaded')}</th><th>{t('col_by')}</th>
                      <th>{t('col_status')}</th><th>{t('col_records')}</th><th>{t('col_entities')}</th><th>{t('col_people_short')}</th>
                      <th>{t('col_evidence_short')}</th><th>{t('col_rels_short')}</th><th />
                    </tr>
                  </thead>
                  <tbody>
                    {history.map((d) => {
                      const fresh = recentDocIds.has(d.id) && d.case_id === caseId
                      const stage = t('stage_' + d.status, null, STAGE_LABELS[d.status] || d.status)
                      const open = !!expanded[d.id]
                      const jobLog = stages[d.id] || []
                      return (
                        <Fragment key={d.id}>
                          <tr className={fresh ? 'row-new' : ''}>
                            <td>
                              <div className="mono">{d.filename}</div>
                              {d.mapping && Object.keys(d.mapping).length > 0 && (
                                <div className="small muted">
                                  {t('cols_mapped_to_fields', { count: Object.keys(d.mapping).length })}
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
                              {d.retry_count > 0 && <span className="small muted">{t('retry_counter', { count: d.retry_count })}</span>}
                              {fresh && <span className="badge import-ok">{t('tag_new')}</span>}
                            </td>
                            <td className="mono">{d.records_processed}</td>
                            <td className="mono">{d.entities_discovered}</td>
                            <td className="mono">{d.persons_discovered}</td>
                            <td className="mono">{d.evidence_discovered}</td>
                            <td className="mono">{d.relationships_discovered}</td>
                            <td className="history-actions">
                              <button className="btn btn-ghost btn-sm" onClick={() => toggleStages(d)}>
                                {open ? t('btn_hide_log') : t('btn_log')}
                              </button>
                              {d.status === 'failed' && (
                                <button className="btn btn-warn btn-sm"
                                  disabled={!!retrying[d.id]}
                                  onClick={() => doRetry(d)}>
                                  {retrying[d.id] ? t('btn_retrying') : t('btn_retry')}
                                </button>
                              )}
                            </td>
                          </tr>
                          {open && (
                            <tr className="stage-log-row">
                              <td colSpan={11}>
                                <div className="stage-log">
                                  {jobLog.length === 0
                                    ? <span className="muted small">{t('loading_stage_log')}</span>
                                    : jobLog.map((j, i) => (
                                      <span key={i} className={`stage-chip stage-${j.status || j.stage}`}>
                                        {t('stage_' + (j.stage || j.status), null, STAGE_LABELS[j.stage] || j.stage || j.status)}
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
            {t('failed_imports_hint')}
          </div>
        )}
      </Panel>
    </div>
  )
}
