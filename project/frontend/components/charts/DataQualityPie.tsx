import { PieChart, Pie, Cell, ResponsiveContainer, Tooltip } from 'recharts'

interface DataQualityPieProps {
  withPhone: number
  emailOnly: number
}

const COLORS = ['#3b82f6', '#e2e8f0']

const CustomTooltip = ({ active, payload }: any) => {
  if (!active || !payload?.length) return null
  return (
    <div className="bg-white px-3 py-2 rounded-lg shadow-lg border border-gray-200 text-sm">
      <p className="font-semibold text-gray-900">{payload[0].name}: {payload[0].value}</p>
    </div>
  )
}

export default function DataQualityPie({ withPhone, emailOnly }: DataQualityPieProps) {
  const total = withPhone + emailOnly
  if (total === 0) return null

  const data = [
    { name: 'Com Telefone', value: withPhone },
    { name: 'So Email', value: emailOnly },
  ]

  const phonePct = Math.round((withPhone / total) * 100)

  return (
    <div className="bg-white rounded-xl border border-gray-200 p-5">
      <h3 className="text-sm font-semibold text-gray-900 mb-4">Qualidade dos Dados</h3>
      <div className="flex items-center gap-6">
        <div className="w-32 h-32 relative">
          <ResponsiveContainer width="100%" height="100%">
            <PieChart>
              <Pie
                data={data}
                cx="50%"
                cy="50%"
                innerRadius={35}
                outerRadius={55}
                paddingAngle={3}
                dataKey="value"
                strokeWidth={0}
              >
                {data.map((_, index) => (
                  <Cell key={`cell-${index}`} fill={COLORS[index]} />
                ))}
              </Pie>
              <Tooltip content={<CustomTooltip />} />
            </PieChart>
          </ResponsiveContainer>
          <div className="absolute inset-0 flex items-center justify-center">
            <span className="text-lg font-bold text-gray-900">{phonePct}%</span>
          </div>
        </div>
        <div className="space-y-3">
          <div className="flex items-center gap-2">
            <div className="w-3 h-3 rounded-full bg-blue-500" />
            <div>
              <p className="text-sm font-medium text-gray-900">{withPhone} com telefone</p>
              <p className="text-xs text-gray-400">{phonePct}% dos leads</p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <div className="w-3 h-3 rounded-full bg-gray-200" />
            <div>
              <p className="text-sm font-medium text-gray-900">{emailOnly} so email</p>
              <p className="text-xs text-gray-400">{100 - phonePct}% dos leads</p>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
