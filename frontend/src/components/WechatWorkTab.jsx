import { useState } from 'react'
import { Card, Form, Input, Button, Space, Alert, Descriptions, Tag, Divider, message, Typography } from 'antd'
import {
  WechatOutlined, LinkOutlined, SafetyOutlined,
  CheckCircleOutlined, CloseCircleOutlined, SendOutlined,
} from '@ant-design/icons'

const { Text, Paragraph } = Typography

const WechatWorkTab = () => {
  const [botForm] = Form.useForm()
  const [appForm] = Form.useForm()
  const [botTesting, setBotTesting] = useState(false)
  const [botStatus, setBotStatus] = useState(null)

  const handleTestBot = async () => {
    try {
      const values = await botForm.validateFields()
      setBotTesting(true)
      setBotStatus(null)

      // 直接调用webhook测试
      try {
        const resp = await fetch(values.webhook_url, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            msgtype: 'text',
            text: { content: '俄罗斯电商AI运营系统 - 连接测试成功' },
          }),
        })
        const data = await resp.json()
        if (data.errcode === 0) {
          setBotStatus('success')
          message.success('群机器人消息发送成功，请查看企业微信群')
        } else {
          setBotStatus('error')
          message.error(`发送失败: ${data.errmsg}`)
        }
      } catch (err) {
        setBotStatus('error')
        message.error('Webhook地址无法访问，请检查URL')
      }
    } catch (err) {
      if (err.errorFields) return
    } finally {
      setBotTesting(false)
    }
  }

  const handleSaveApp = async () => {
    try {
      await appForm.validateFields()
      message.info('企业微信应用配置保存功能即将上线')
    } catch (err) {
      if (err.errorFields) return
    }
  }

  return (
    <div>
      <Alert
        message="企业微信对接说明"
        description="配置企业微信后，系统会自动将ROI告警、日报、任务失败等重要通知推送到企业微信群或指定用户。"
        type="info"
        showIcon
        style={{ marginBottom: 24 }}
      />

      {/* 群机器人配置 */}
      <Card
        title={
          <Space>
            <WechatOutlined style={{ color: '#07C160' }} />
            群机器人 Webhook
          </Space>
        }
        extra={
          botStatus === 'success' ? (
            <Tag icon={<CheckCircleOutlined />} color="success">已连通</Tag>
          ) : botStatus === 'error' ? (
            <Tag icon={<CloseCircleOutlined />} color="error">连接失败</Tag>
          ) : null
        }
        style={{ marginBottom: 24 }}
      >
        <Paragraph type="secondary" style={{ marginBottom: 16 }}>
          在企业微信群中添加「群机器人」，获取 Webhook 地址后填写到下方。系统会通过此机器人推送告警和日报。
        </Paragraph>

        <Form form={botForm} layout="vertical">
          <Form.Item
            name="webhook_url"
            label="Webhook URL"
            rules={[
              { required: true, message: '请输入Webhook URL' },
              { type: 'url', message: 'URL格式不正确' },
            ]}
          >
            <Input
              prefix={<LinkOutlined />}
              placeholder="https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxxxx"
              style={{ fontFamily: 'monospace' }}
            />
          </Form.Item>

          <Space>
            <Button
              type="primary"
              icon={<SendOutlined />}
              loading={botTesting}
              onClick={handleTestBot}
            >
              发送测试消息
            </Button>
          </Space>
        </Form>

        <Divider />

        <Text type="secondary">设置步骤：</Text>
        <ol style={{ color: '#666', paddingLeft: 20, marginTop: 8 }}>
          <li>打开企业微信，进入目标群聊</li>
          <li>点击群设置 → 群机器人 → 添加机器人</li>
          <li>输入机器人名称（如"AI运营助手"），创建后复制Webhook地址</li>
          <li>粘贴到上方输入框，点击「发送测试消息」验证</li>
        </ol>
      </Card>

      {/* 应用消息配置 */}
      <Card
        title={
          <Space>
            <SafetyOutlined style={{ color: '#1890ff' }} />
            企业微信应用消息
          </Space>
        }
      >
        <Paragraph type="secondary" style={{ marginBottom: 16 }}>
          配置企业微信自建应用后，可向指定用户推送消息（如审批通知、个人日报）。需要企业微信管理员在后台创建应用并获取以下信息。
        </Paragraph>

        <Form form={appForm} layout="vertical">
          <div style={{ display: 'flex', gap: 16 }}>
            <Form.Item
              name="corp_id"
              label="企业ID (Corp ID)"
              style={{ flex: 1 }}
              rules={[{ required: true, message: '请输入企业ID' }]}
            >
              <Input placeholder="ww1234567890abcdef" style={{ fontFamily: 'monospace' }} />
            </Form.Item>
            <Form.Item
              name="agent_id"
              label="应用ID (Agent ID)"
              style={{ flex: 1 }}
              rules={[{ required: true, message: '请输入应用ID' }]}
            >
              <Input placeholder="1000001" style={{ fontFamily: 'monospace' }} />
            </Form.Item>
          </div>

          <Form.Item
            name="secret"
            label="应用Secret"
            rules={[{ required: true, message: '请输入应用Secret' }]}
          >
            <Input.Password placeholder="应用的Secret密钥" style={{ fontFamily: 'monospace' }} />
          </Form.Item>

          <Button type="primary" onClick={handleSaveApp}>
            保存配置
          </Button>
        </Form>

        <Divider />

        <Text type="secondary">获取方式：</Text>
        <Descriptions column={1} size="small" bordered style={{ marginTop: 8 }}>
          <Descriptions.Item label="企业ID">
            企业微信管理后台 → 我的企业 → 企业信息 → 企业ID
          </Descriptions.Item>
          <Descriptions.Item label="应用ID">
            管理后台 → 应用管理 → 自建应用 → 应用详情页的AgentId
          </Descriptions.Item>
          <Descriptions.Item label="Secret">
            管理后台 → 应用管理 → 自建应用 → 应用详情页的Secret
          </Descriptions.Item>
        </Descriptions>
      </Card>
    </div>
  )
}

export default WechatWorkTab
