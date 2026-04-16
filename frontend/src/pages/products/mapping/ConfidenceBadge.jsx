import { Tag, Tooltip } from 'antd'
import { CheckCircleFilled, WarningFilled, ExclamationCircleFilled, UserOutlined } from '@ant-design/icons'

// §8.4 置信度可视化 + §2.2 状态机
// is_confirmed=1 → 绿 已确认
// is_confirmed=0 && ai_suggested=0 → 蓝 手动待确认
// is_confirmed=0 && ai_confidence >= 80 → 橙 AI 推荐 请核对
// is_confirmed=0 && ai_confidence < 80 → 红 AI 请仔细核对
const ConfidenceBadge = ({ aiSuggested = 0, confidence = 0, confirmed = 0 }) => {
  if (confirmed) {
    return (
      <Tag color="green" icon={<CheckCircleFilled />}>
        已确认
      </Tag>
    )
  }
  if (!aiSuggested) {
    return (
      <Tag color="blue" icon={<UserOutlined />}>
        手动 · 待确认
      </Tag>
    )
  }
  const conf = Number(confidence) || 0
  if (conf >= 80) {
    return (
      <Tooltip title="AI 置信度较高，但仍建议核对后确认">
        <Tag color="orange" icon={<WarningFilled />}>
          AI {conf}% · 请核对
        </Tag>
      </Tooltip>
    )
  }
  return (
    <Tooltip title="AI 置信度较低，请仔细核对">
      <Tag color="red" icon={<ExclamationCircleFilled />}>
        AI {conf}% · 请仔细核对
      </Tag>
    </Tooltip>
  )
}

export default ConfidenceBadge
