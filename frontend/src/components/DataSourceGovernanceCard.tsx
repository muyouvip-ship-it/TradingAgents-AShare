export type DataSourceTone = 'neutral' | 'good' | 'warn' | 'bad' | 'info'

export interface DataSourceGovernanceItem {
  label: string
  value: string
  detail?: string
  tone?: DataSourceTone
}

function toneClasses(tone: DataSourceTone = 'neutral') {
  return {
    neutral: 'border-slate-200 bg-white/80 text-slate-700 dark:border-slate-700 dark:bg-slate-900/60 dark:text-slate-200',
    good: 'border-emerald-200 bg-emerald-50/80 text-emerald-700 dark:border-emerald-500/30 dark:bg-emerald-500/10 dark:text-emerald-200',
    warn: 'border-amber-200 bg-amber-50/85 text-amber-700 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-200',
    bad: 'border-rose-200 bg-rose-50/85 text-rose-700 dark:border-rose-500/30 dark:bg-rose-500/10 dark:text-rose-200',
    info: 'border-blue-200 bg-blue-50/85 text-blue-700 dark:border-blue-500/30 dark:bg-blue-500/10 dark:text-blue-200',
  }[tone]
}

export default function DataSourceGovernanceCard({
  title = '数据源状态',
  description,
  items,
  warnings = [],
}: {
  title?: string
  description?: string
  items: DataSourceGovernanceItem[]
  warnings?: string[]
}) {
  const visibleItems = items.filter(item => String(item.value || '').trim())
  const visibleWarnings = warnings.filter(item => String(item || '').trim())

  if (!visibleItems.length && !visibleWarnings.length) return null

  return (
    <section className="rounded-3xl border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-800 dark:bg-slate-900">
      <div className="flex flex-col gap-2 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <h2 className="text-lg font-semibold text-slate-900 dark:text-slate-100">{title}</h2>
          {description ? (
            <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">{description}</p>
          ) : null}
        </div>
      </div>

      {visibleItems.length ? (
        <div className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-4">
          {visibleItems.map(item => (
            <div
              key={`${item.label}-${item.value}`}
              className={`rounded-2xl border px-4 py-3 ${toneClasses(item.tone)}`}
            >
              <div className="text-[11px] font-semibold tracking-[0.16em] opacity-70">{item.label}</div>
              <div className="mt-2 text-sm font-semibold break-words">{item.value}</div>
              {item.detail ? (
                <div className="mt-2 text-xs leading-5 opacity-80">{item.detail}</div>
              ) : null}
            </div>
          ))}
        </div>
      ) : null}

      {visibleWarnings.length ? (
        <div className="mt-4 space-y-2">
          {visibleWarnings.map((warning, index) => (
            <div
              key={`${warning}-${index}`}
              className="rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-700 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-200"
            >
              {warning}
            </div>
          ))}
        </div>
      ) : null}
    </section>
  )
}
