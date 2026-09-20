import { useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { api } from '../api'
import { Spinner, ErrorBox, Panel, Empty } from '../components/ui'
import { useI18n } from '../i18n'

export default function SearchPage() {
  const { t } = useI18n()
  const [params] = useSearchParams()
  const q = params.get('q') || ''
  const [res, setRes] = useState(null)
  const [err, setErr] = useState('')

  useEffect(() => {
    if (!q) { setRes({ people: [], entities: [], cases: [] }); return }
    api(`/search?q=${encodeURIComponent(q)}`).then(setRes).catch((e) => setErr(e.message))
  }, [q])

  if (err) return <ErrorBox message={err} />
  if (!res) return <Spinner label={t('loading_default')} />

  const total = res.people.length + res.entities.length + res.cases.length

  return (
    <div className="page">
      <h2>{t('search_results_for', { q })}</h2>
      <p className="muted">{t('matches_count', { count: total })}</p>

      <Panel title={t('panel_people')}>
        {res.people.length === 0 && <Empty message={t('no_matching_people')} />}
        <div className="result-list">
          {res.people.map((p) => (
            <Link key={p.person_id} className="result-item link" to={`/persons/${p.person_id}`}>
              <span className="result-type person">{t('badge_person')}</span> {p.name}
            </Link>
          ))}
        </div>
      </Panel>

      <Panel title={t('panel_identifiers_entities')}>
        {res.entities.length === 0 && <Empty message={t('no_matching_identifiers')} />}
        <div className="result-list">
          {res.entities.map((e) => (
            <Link key={e.id} className="result-item link" to={`/search?q=${encodeURIComponent(e.value)}`}>
              <span className="result-type entity">{e.type}</span> {e.value}
              {e.case_id && <span className="muted small"> · {e.case_id}</span>}
            </Link>
          ))}
        </div>
      </Panel>

      <Panel title={t('panel_cases')}>
        {res.cases.length === 0 && <Empty message={t('no_matching_cases')} />}
        <div className="result-list">
          {res.cases.map((c) => (
            <Link key={c.id} className="result-item link" to={`/cases/${c.id}`}>
              <span className="result-type case">{t('badge_case')}</span> {c.name} <span className="muted small">({c.id})</span>
            </Link>
          ))}
        </div>
      </Panel>
    </div>
  )
}
