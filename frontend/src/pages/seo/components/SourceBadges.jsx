import { Tag, Tooltip } from 'antd'

const META = {
  'paid:self': {
    label: '付费·本品',
    color: 'magenta',
    tip: '本商品自己的付费广告高ROAS词',
  },
  'paid:category': {
    label: '付费·类目',
    color: 'volcano',
    tip: '同类目≥3个商品共同付费高ROAS的词，当前商品可借势',
  },
  'organic:self': {
    label: '自然·本品',
    color: 'cyan',
    tip: '商品被搜索到的自然流量词（需 WB Jam / Ozon Premium）',
  },
  'organic:category': {
    label: '自然·类目',
    color: 'blue',
    tip: '同类目自然搜索共享词（二期）',
  },
  'wordstat:category': {
    label: 'Wordstat',
    color: 'purple',
    tip: 'Yandex Wordstat 俄罗斯全网搜索量（五期）',
  },
}

const SourceBadges = ({ sources }) => {
  if (!sources || !sources.length) return null
  return (
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
      {sources.map((s, idx) => {
        const key = `${s.type}:${s.scope}`
        const meta = META[key] || { label: key, color: 'default' }
        return (
          <Tooltip key={`${key}-${idx}`} title={meta.tip}>
            <Tag color={meta.color} style={{ margin: 0 }}>
              {meta.label}
            </Tag>
          </Tooltip>
        )
      })}
    </div>
  )
}

export default SourceBadges
