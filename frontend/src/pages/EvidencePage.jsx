import { useEffect, useState } from 'react'
import { api } from '../api'
import { Spinner, ErrorBox, Panel } from '../components/ui'
import { useI18n } from '../i18n'

export default function EvidencePage() {
  const { t } = useI18n()
  const [evidence, setEvidence] = useState(null)
  const [err, setErr] = useState('')

  useEffect(() => { api('/evidence').then(setEvidence).catch((e) => setErr(e.message)) }, [])

  if (err) return <ErrorBox message={err} />
  if (!evidence) return <Spinner />

  return (
    <div className="page">
      <h2>{t('evidence_title')}</h2>
      <p className="muted">{t('evidence_subtitle', { count: evidence.length })}</p>
      <Panel title={t('evidence_records_panel')}>
        <table className="table">
          <thead>
            <tr>
              <th>{t('col_id')}</th>
              <th>{t('col_type')}</th>
              <th>{t('col_person_a')}</th>
              <th>{t('col_person_b')}</th>
              <th>{t('col_source')}</th>
              <th>{t('col_date')}</th>
              <th>{t('col_time')}</th>
              <th>{t('col_confidence')}</th>
            </tr>
          </thead>
          <tbody>
            {evidence.map((e) => (
              <tr key={e.id}>
                <td className="mono">{e.id}</td>
                <td className="muted">{e.type}</td>
                <td className="mono">{e.person_a}</td>
                <td className="mono">{e.person_b}</td>
                <td className="mono">{e.source}</td>
                <td className="mono">{e.date}</td>
                <td className="mono">{e.time || <span className="muted">{t('unavailable')}</span>}</td>
                <td className="mono">{e.confidence}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Panel>
    </div>
  )
}
