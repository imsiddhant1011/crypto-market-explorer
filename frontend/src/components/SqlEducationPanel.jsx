/**
 * The educational panel: it shows the SQL statement that the backend really
 * executed for the selected timeframe, together with a plain-English
 * explanation and the DBMS concepts involved.
 *
 * The text, the SQL and the concept list all come from the API response
 * (see backend/app/queries.py), so the panel can never show a query that
 * differs from the one that produced the chart.
 */
export default function SqlEducationPanel({ education, loading }) {
  if (!education) {
    return (
      <aside className="panel education">
        <h2>How these candles are calculated</h2>
        <p className="muted">
          {loading
            ? 'Loading the SQL for the selected timeframe…'
            : 'No SQL information available yet.'}
        </p>
      </aside>
    )
  }

  return (
    <aside className="panel education">
      <h2>{education.title}</h2>
      <p className="muted small">
        Executed by PostgreSQL for every request - the chart above is the result of this
        statement.
      </p>

      <pre className="sql">
        <code>{education.sql}</code>
      </pre>

      <div className="parameters">
        <h3>Parameters bound to this statement</h3>
        <p className="muted small">
          The values are sent to PostgreSQL separately from the SQL text. They can never be
          read as SQL syntax, which is how SQL injection is prevented.
        </p>
        <ul className="parameter-list">
          <li>
            <code>symbol</code> = <code>{education.parameters.symbol}</code>
          </li>
          <li>
            <code>window_start</code> = <code>{education.parameters.window_start ?? 'n/a'}</code>
          </li>
          <li>
            <code>window_end</code> = <code>{education.parameters.window_end ?? 'n/a'}</code>
          </li>
        </ul>
      </div>

      <h3>What the query does</h3>
      <p>{education.explanation}</p>

      <h3>OHLCV rules</h3>
      <ul className="rules">
        {education.ohlcv_rules.map((rule) => (
          <li key={rule}>{rule}</li>
        ))}
      </ul>

      <h3>Completeness rule</h3>
      <p>{education.completeness_rule}</p>

      <h3>DBMS concepts demonstrated</h3>
      <dl className="concepts">
        {education.concepts.map((concept) => (
          <div key={concept.name}>
            <dt>{concept.name}</dt>
            <dd>{concept.detail}</dd>
          </div>
        ))}
      </dl>

      <p className="footnote">
        This panel is for learning only: the browser cannot send SQL to the server. The
        backend runs this one predefined, parameterized query per timeframe.
      </p>
    </aside>
  )
}
