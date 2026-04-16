import { useState, useEffect } from 'react'
import {
  Card, Descriptions, Button, Modal, Form, Input, message, Tag, Space,
  Avatar, Divider, Typography, Spin,
} from 'antd'
import {
  UserOutlined, MailOutlined, TeamOutlined, CrownOutlined,
  EditOutlined, LockOutlined, SaveOutlined, CloseOutlined,
} from '@ant-design/icons'
import { getMe, updateProfile, changePassword } from '@/api/auth'
import { formatMoscowTime } from '@/utils/time'
import { useAuthStore } from '@/stores/authStore'

const { Text } = Typography

const roleMap = {
  owner: { label: '所有者', color: 'gold' },
  admin: { label: '管理员', color: 'blue' },
  operator: { label: '运营', color: 'green' },
  viewer: { label: '只读', color: 'default' },
}

const planMap = {
  free: { label: '免费版', color: 'default' },
  basic: { label: '基础版', color: 'blue' },
  pro: { label: '专业版', color: 'purple' },
  enterprise: { label: '企业版', color: 'gold' },
}

const ProfileTab = () => {
  const [userInfo, setUserInfo] = useState(null)
  const [loading, setLoading] = useState(true)
  const { user: storeUser, setAuth, token } = useAuthStore()

  // 编辑状态
  const [editingField, setEditingField] = useState(null)
  const [editValue, setEditValue] = useState('')
  const [saving, setSaving] = useState(false)

  // 修改密码
  const [pwdModalVisible, setPwdModalVisible] = useState(false)
  const [pwdLoading, setPwdLoading] = useState(false)
  const [pwdForm] = Form.useForm()

  useEffect(() => {
    fetchUserInfo()
  }, [])

  const fetchUserInfo = async () => {
    setLoading(true)
    try {
      const res = await getMe()
      setUserInfo(res.data)
    } catch (err) {
      message.error('获取用户信息失败')
    } finally {
      setLoading(false)
    }
  }

  const handleStartEdit = (field, currentValue) => {
    setEditingField(field)
    setEditValue(currentValue || '')
  }

  const handleCancelEdit = () => {
    setEditingField(null)
    setEditValue('')
  }

  const handleSaveField = async () => {
    const value = editValue.trim()
    if (!value) {
      message.warning('内容不能为空')
      return
    }

    if (editingField === 'username' && value.length < 2) {
      message.warning('用户名至少2个字符')
      return
    }

    if (editingField === 'email') {
      const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/
      if (!emailRegex.test(value)) {
        message.warning('邮箱格式不正确')
        return
      }
    }

    setSaving(true)
    try {
      const res = await updateProfile({ [editingField]: value })
      message.success('修改成功')
      // 更新本地状态
      setUserInfo((prev) => ({ ...prev, ...res.data }))
      // 同步更新Zustand store
      setAuth(token, res.data, userInfo?.tenant || null)
      setEditingField(null)
      setEditValue('')
    } catch (err) {
      message.error(err.message || '修改失败')
    } finally {
      setSaving(false)
    }
  }

  const handleChangePassword = async () => {
    try {
      const values = await pwdForm.validateFields()
      setPwdLoading(true)
      await changePassword({
        old_password: values.old_password,
        new_password: values.new_password,
      })
      message.success('密码修改成功')
      setPwdModalVisible(false)
      pwdForm.resetFields()
    } catch (err) {
      if (err.errorFields) return
      message.error(err.message || '密码修改失败')
    } finally {
      setPwdLoading(false)
    }
  }

  if (loading) {
    return <Card><Spin style={{ display: 'block', textAlign: 'center', padding: 40 }} /></Card>
  }

  const user = userInfo || storeUser || {}
  const tenant = userInfo?.tenant || {}
  const role = roleMap[user.role] || { label: user.role, color: 'default' }
  const plan = planMap[tenant.plan] || { label: tenant.plan, color: 'default' }

  const renderEditableField = (field, label, value, icon) => {
    if (editingField === field) {
      return (
        <Space>
          <Input
            value={editValue}
            onChange={(e) => setEditValue(e.target.value)}
            onPressEnter={handleSaveField}
            style={{ width: 220 }}
            autoFocus
            prefix={icon}
          />
          <Button
            type="primary"
            size="small"
            icon={<SaveOutlined />}
            loading={saving}
            onClick={handleSaveField}
          >
            保存
          </Button>
          <Button size="small" icon={<CloseOutlined />} onClick={handleCancelEdit}>
            取消
          </Button>
        </Space>
      )
    }

    return (
      <Space>
        {icon}
        <span>{value}</span>
        <Button
          type="link"
          size="small"
          icon={<EditOutlined />}
          onClick={() => handleStartEdit(field, value)}
        >
          修改
        </Button>
      </Space>
    )
  }

  return (
    <div>
      {/* 个人信息卡片 */}
      <Card title="基本信息">
        <div style={{ display: 'flex', alignItems: 'flex-start', gap: 32, marginBottom: 24 }}>
          <Avatar size={80} icon={<UserOutlined />} style={{ backgroundColor: '#7265e6', flexShrink: 0 }} />
          <div style={{ flex: 1 }}>
            <Space style={{ marginBottom: 12 }}>
              <Tag icon={<CrownOutlined />} color={role.color}>{role.label}</Tag>
              <Tag color={user.status === 'active' ? 'success' : 'error'}>
                {user.status === 'active' ? '账号正常' : '已停用'}
              </Tag>
            </Space>

            <Descriptions column={1} size="small" bordered>
              <Descriptions.Item label="用户名">
                {renderEditableField('username', '用户名', user.username, <UserOutlined />)}
              </Descriptions.Item>
              <Descriptions.Item label="邮箱">
                {renderEditableField('email', '邮箱', user.email, <MailOutlined />)}
              </Descriptions.Item>
              <Descriptions.Item label="用户ID">
                <Text copyable>{user.id}</Text>
              </Descriptions.Item>
              <Descriptions.Item label="角色">
                <Tag color={role.color}>{role.label}</Tag>
              </Descriptions.Item>
              <Descriptions.Item label="最后登录">
                {user.last_login_at ? formatMoscowTime(user.last_login_at) : '未知'}
              </Descriptions.Item>
            </Descriptions>
          </div>
        </div>
      </Card>

      {/* 安全设置 */}
      <Card title="安全设置" style={{ marginTop: 16 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '8px 0' }}>
          <div>
            <div style={{ fontWeight: 500 }}>登录密码</div>
            <Text type="secondary">定期修改密码可以保护账号安全</Text>
          </div>
          <Button icon={<LockOutlined />} onClick={() => setPwdModalVisible(true)}>修改密码</Button>
        </div>
      </Card>

      {/* 租户信息 */}
      {tenant.id && (
        <Card title={<Space><TeamOutlined />企业/租户信息</Space>} style={{ marginTop: 16 }}>
          <Descriptions column={2} bordered size="small">
            <Descriptions.Item label="公司名称">{tenant.name}</Descriptions.Item>
            <Descriptions.Item label="当前套餐">
              <Tag color={plan.color}>{plan.label}</Tag>
            </Descriptions.Item>
            <Descriptions.Item label="最大店铺数">{tenant.max_shops} 个</Descriptions.Item>
            <Descriptions.Item label="租户ID">
              <Text copyable>{tenant.id}</Text>
            </Descriptions.Item>
          </Descriptions>
        </Card>
      )}

      {/* 修改密码弹窗 */}
      <Modal
        title="修改密码"
        open={pwdModalVisible}
        onOk={handleChangePassword}
        confirmLoading={pwdLoading}
        onCancel={() => { setPwdModalVisible(false); pwdForm.resetFields() }}
        width={400}
      >
        <Form form={pwdForm} layout="vertical" style={{ marginTop: 16 }}>
          <Form.Item
            name="old_password"
            label="当前密码"
            rules={[{ required: true, message: '请输入当前密码' }]}
          >
            <Input.Password placeholder="请输入当前密码" />
          </Form.Item>
          <Form.Item
            name="new_password"
            label="新密码"
            rules={[
              { required: true, message: '请输入新密码' },
              { min: 6, message: '密码至少6位' },
            ]}
          >
            <Input.Password placeholder="请输入新密码（至少6位）" />
          </Form.Item>
          <Form.Item
            name="confirm_password"
            label="确认新密码"
            dependencies={['new_password']}
            rules={[
              { required: true, message: '请确认新密码' },
              ({ getFieldValue }) => ({
                validator(_, value) {
                  if (!value || getFieldValue('new_password') === value) {
                    return Promise.resolve()
                  }
                  return Promise.reject(new Error('两次密码不一致'))
                },
              }),
            ]}
          >
            <Input.Password placeholder="请再次输入新密码" />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}

export default ProfileTab
