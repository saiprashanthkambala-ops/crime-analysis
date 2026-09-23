import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api } from '../api'
import { Spinner, ErrorBox, Panel, StrengthBadge, Empty } from '../components/ui'
import { useI18n } from '../i18n'

export default function RelationshipDetail() {
  const { t } = useI18n()
  const { relId } = useParams()
  const [rel, setRel] = useState(null)
  const [err, setErr] = useState('')
  const [saving, setSaving] = useState(false)
  const [note, setNote] = useState('')

  const load = () => api(`/relationships/${relId}`).then(setRel).catch((e) => setErr(e.message))
  useEffect(() => { load() }, [relId])

  const decide = async (decision) => {
    setSaving(true)
    try {
      await api(`/relationships/${relId}/feedback`, {
        method: 'POST', body: JSON.stringify({ decision, note }),
      })
      setNote('')
      await load()
    } catch (e) { setErr(e.message) } finally { setSaving(false) }
  }

  if (err) return <ErrorBox message={err} />
  if (!rel) return <Spinner />

  const s = rel.signals

  return (
    <div className="page app-section-page">
      <div className="rel-header">
        <div className="rel-person">
          <Link className="link" to={`/persons/${rel.person_a.id}`}>{rel.person_a.name}</Link>
        </div>
        <div className="rel-center">
          <div className="rel-link-symbol">↔</div>
          <StrengthBadge strength={rel.strength} />
          <div className="muted small">{t('evidence_strength_score', { score: rel.score })}</div>
        </div>
        <div className="rel-person">
          <Link className="link" to={`/persons/${rel.person_b.id}`}>{rel.person_b.name}</Link>
        </div>
      </div>

      <div className="two-col">
        <Panel title={t('panel_why_surfaced')}>
          <ul className="signal-list">
            {s.calls > 0 && <li><span className="sig-count">{s.calls}</span> {t('signal_call_interactions')}</li>}
            {s.transactions > 0 && <li><span className="sig-count">{s.transactions}</span> {t('signal_transaction_interactions')}</li>}
            {s.location_overlaps > 0 && <li><span className="sig-count">{s.location_overlaps}</span> {t('signal_location_overlaps')}</li>}
            {s.shared_identifiers?.length > 0 && (
              <li>{t('signal_shared_ids_prefix')}{s.shared_identifiers.join(', ')}</li>
            )}
            {s.case_overlaps > 0 && <li><span className="sig-count">{s.case_overlaps}</span> {t('signal_shared_cases')}</li>}
            {s.calls + s.transactions + s.location_overlaps + (s.shared_identifiers?.length || 0) + s.case_overlaps === 0 && (
              <li className="muted">{t('no_supporting_signals')}</li>
            )}
          </ul>
        </Panel>

        <Panel title={t('panel_uncertainties')}>
          <ul className="signal-list muted">
            <li>{t('uncertainty_sources_count', { count: rel.sources.length })}</li>
            <li>{t('uncertainty_ownership')}</li>
            <li>{t('uncertainty_colocation')}</li>
          </ul>
        </Panel>
      </div>

      <Panel title={t('panel_sources')}>
        {rel.sources.length === 0 && <Empty message={t('no_sources_records')} />}
        <div className="source-list">
          {rel.sources.map((src) => <div key={src} className="source-chip mono">{src}</div>)}
        </div>
      </Panel>

      <Panel title={t('panel_temporal_context')}>
        {rel.dates.length === 0
          ? <Empty message={t('no_known_dates')} />
          : <div className="mono">{rel.dates.join('  →  ')}</div>}
      </Panel>

      <Panel title={t('panel_supporting_evidence')}>
        {rel.evidence.length === 0 && <Empty message={t('no_evidence_records')} />}
        <table className="table">
          <thead>
            <tr>
              <th>{t('col_id')}</th>
              <th>{t('col_type')}</th>
              <th>{t('col_source')}</th>
              <th>{t('col_date')}</th>
              <th>{t('col_time')}</th>
            </tr>
          </thead>
          <tbody>
            {rel.evidence.map((e) => (
              <tr key={e.id}>
                <td className="mono">{e.id}</td>
                <td className="muted">{e.type}</td>
                <td className="mono">{e.source}</td>
                <td className="mono">{e.date}</td>
                <td className="mono">{e.time || <span className="muted">{t('unavailable')}</span>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Panel>

      <Panel title={t('panel_investigator_decision')}>
        <div className="decision-row">
          <button className="btn btn-ok" disabled={saving} onClick={() => decide('relevant')}>{t('btn_decision_relevant')}</button>
          <button className="btn btn-bad" disabled={saving} onClick={() => decide('incorrect')}>{t('btn_decision_incorrect')}</button>
          <button className="btn btn-warn" disabled={saving} onClick={() => decide('needs_review')}>{t('btn_decision_needs_review')}</button>
          {rel.decision && <span className="muted">{t('current_decision_label', { decision: <b>{rel.decision.replace('_', ' ')}</b> })}</span>}
        </div>
        <textarea
          placeholder={t('decision_note_placeholder')}
          value={note}
          onChange={(e) => setNote(e.target.value)}
          rows={2}
          style={{ marginBottom: 8 }}
        />
        <div className="small muted">{t('feedback_disclaimer')}</div>
      </Panel>
    </div>
  )
}
