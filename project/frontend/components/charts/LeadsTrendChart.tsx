import {
  AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
} from 'recharts'

interface DataPoint {
  date: string
  leads: number
}

interface LeadsTrendChartProps {
  data: DataPoint[]
}

const CustomTooltip = ({ active, payload, label }: any) => {
  if (!active || !payload?.length) return null
  const d = new Date(label + 'T12:00:00')
  return (
    <div className="bg-white px-3 py-2 rounded-lg shadow-lg border border-gray-200 text-sm">
      <p className="text-gray-500 text-xs mb-0.5">
        {d.toLocaleDateString('pt-BR', { day: '2-digit', month: 'short' })}
      </p>
      <p className="font-semibold text-gray-900">{payload[0].value} leads</p>
    </div>
  )
}

export default function LeadsTrendChart({ data }: LeadsTrendChartProps) {
  const formatXAxis = (value: string) => {
    const d = new Date(value + 'T12:00:00')
    return d.toLocaleDateString('pt-BR', { day: '2-digit', month: '2-digit' })
  }

  return (
    <div className="bg-white rounded-xl border border-gray-200 p-5">
      <h3 className="text-sm font-semibold text-gray-900 mb-4">Leads nos ultimos 30 dias</h3>
      <div className="h-64">
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={data} margin={{ top: 5, right: 5, left: -20, bottom: 0 }}>
            <defs>
              <linearGradient id="leadGradient" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor="#3b82f6" stopOpacity={0.15} />
                <stop offset="95%" stopColor="#3b82f6" stopOpacity={0} />
              </linearGradient>
            </defs>
            <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" vertical={false} />
            <XAxis
              dataKey="date"
              tickFormatter={formatXAxis}
              tick={{ fontSize: 11, fill: '#94a3b8' }}
              axisLine={false}
              tickLine={false}
              interval="preserveStartEnd"
              minTickGap={40}
            />
            <YAxis
              tick={{ fontSize: 11, fill: '#94a3b8' }}
              axisLine={false}
              tickLine={false}
              allowDecimals={false}
            />
            <Tooltip content={<CustomTooltip />} />
            <Area
              type="monotone"
              dataKey="leads"
              stroke="#3b82f6"
              strokeWidth={2}
              fill="url(#leadGradient)"
              dot={false}
              activeDot={{ r: 4, strokeWidth: 2, fill: '#fff', stroke: '#3b82f6' }}
            />
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}
