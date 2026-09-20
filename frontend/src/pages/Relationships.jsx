import { useEffect, useState, useMemo } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api'
import { Spinner, ErrorBox, Panel, StrengthBadge } from '../components/ui'
import { useI18n } from '../i18n'

const FILTER_KEYS = [
  { value: '', key: 'filter_all', defaultLabel: 'All' },
  { value: 'STRONG', key: 'filter_strong', defaultLabel: 'STRONG' },
  { value: 'MODERATE', key: 'filter_moderate', defaultLabel: 'MODERATE' },
  { value: 'WEAK', key: 'filter_weak', defaultLabel: 'WEAK' },
  { value: 'INSUFFICIENT EVIDENCE', key: 'filter_insufficient', defaultLabel: 'INSUFFICIENT EVIDENCE' },
]

const SIGNAL_KEYS = [
  { value: '', key: 'signal_all', defaultLabel: 'All types' },
  { value: 'call', key: 'signal_calls', defaultLabel: 'Calls' },
  { value: 'transaction', key: 'signal_transactions', defaultLabel: 'Transactions' },
  { value: 'location', key: 'signal_location', defaultLabel: 'Location' },
  { value: 'shared_identifier', key: 'signal_shared_identifier', defaultLabel: 'Shared identifier' },
  { value: 'case', key: 'signal_shared_case', defaultLabel: 'Shared case' },
]

export default function Relationships() {
  const { t } = useI18n()
  const [rels, setRels] = useState(null)
  const [cases, setCases] = useState([])
  const [err, setErr] = useState('')
  const [filter, setFilter] = useState('')
  const [signal, setSignal] = useState('')
  const [caseId, setCaseId] = useState('')

  useEffect(() => {
    api('/relationships').then(setRels).catch((e) => setErr(e.message))
    api('/cases').then(setCases).catch(() => {})
  }, [])

  if (err) return <ErrorBox message={err} />
  if (!rels) return <Spinner />

  const shown = rels.filter((r) => {
    if (filter && r.strength !== filter) return false
    if (signal && !(r.types || []).includes(signal)) return false
    if (caseId && !(r.case_ids || []).includes(caseId)) return false
    return true
  })

  return (
    <div className="page">
      <h2>{t('relationships_title')}</h2>
      <p className="muted">
        {t('relationships_subtitle')}
      </p>

      <div className="filter-row">
        {FILTER_KEYS.map((f) => (
          <button
            key={f.value || 'all'}
            className={`btn ${filter === f.value ? 'btn-primary' : 'btn-ghost'}`}
            onClick={() => setFilter(f.value)}
          >
            {t(f.key, null, f.defaultLabel)}
          </button>
        ))}
        <select value={signal} onChange={(e) => setSignal(e.target.value)} className="select-inline">
          {SIGNAL_KEYS.map((s) => (
            <option key={s.value} value={s.value}>
              {t(s.key, null, s.defaultLabel)}
            </option>
          ))}
        </select>
        <select value={caseId} onChange={(e) => setCaseId(e.target.value)} className="select-inline">
          <option value="">{t('all_cases_option')}</option>
          {cases.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
        </select>
      </div>

      <Panel title={t('count_relationships_title', { count: shown.length })}>
        <table className="table">
          <thead>
            <tr>
              <th>{t('col_person_a')}</th>
              <th>{t('col_person_b')}</th>
              <th>{t('col_strength')}</th>
              <th>{t('col_score')}</th>
              <th>{t('col_signals')}</th>
              <th>{t('col_decision')}</th>
            </tr>
          </thead>
          <tbody>
            {shown.map((r) => (
              <tr key={r.id}>
                <td><Link className="link" to={`/persons/${r.person_a.id}`}>{r.person_a.name}</Link></td>
                <td><Link className="link" to={`/persons/${r.person_b.id}`}>{r.person_b.name}</Link></td>
                <td><StrengthBadge strength={r.strength} /></td>
                <td className="mono">{r.score}</td>
                <td className="muted">
                  {r.signals.calls}c · {r.signals.transactions}t · {r.signals.location_overlaps}l
                </td>
                <td>{r.decision ? <span className="badge decision-badge">{r.decision}</span> : <span className="muted">—</span>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Panel>
    </div>
  )
}
