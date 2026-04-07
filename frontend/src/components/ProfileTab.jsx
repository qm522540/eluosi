import { useState, useEffect } from 'react'
import { Card, Descriptions, Button, Modal, Form, Input, message, Tag, Space, Avatar, Divider } from 'antd'
import { UserOutlined, MailOutlined, TeamOutlined, CrownOutlined, EditOutlined, LockOutlined } from '@ant-design/icons'
import { getMe, changePassword } from '@/api/auth'
import { useAuthStore } from '@/stores/authStore'

const ProfileTab = () => {
  const [userInfo, setUserInfo] = useState(null)
  const [loading, setLoading] = useState(true)
  const [pwdModalVisible, setPwdModalVisible] = useState(false)
  const [pwdForm] = Form.useForm()
  const storeUser = useAuthStore((s) => s.user)

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

  const [pwdLoading, setPwdLoading] = useState(false)

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
    return <Card loading={true} />
  }

  const user = userInfo || storeUser || {}
  const tenant = userInfo?.tenant || {}
  const role = roleMap[user.role] || { label: user.role, color: 'default' }
  const plan = planMap[tenant.plan] || { label: tenant.plan, color: 'default' }

  return (
    <div>
      <Card>
        <div style={{ display: 'flex', alignItems: 'center', gap: 24, marginBottom: 24 }}>
          <Avatar size={72} icon={<UserOutlined />} style={{ backgroundColor: '#7265e6' }} />
          <div>
            <div style={{ fontSize: 20, fontWeight: 600 }}>{user.username}</div>
            <div style={{ color: '#666', marginTop: 4 }}>{user.email}</div>
            <Space style={{ marginTop: 8 }}>
              <Tag icon={<CrownOutlined />} color={role.color}>{role.label}</Tag>
              <Tag color={user.status === 'active' ? 'success' : 'error'}>
                {user.status === 'active' ? '正常' : '停用'}
              </Tag>
            </Space>
          </div>
        </div>

        <Descriptions column={2} bordered size="small">
          <Descriptions.Item label="用户ID">{user.id}</Descriptions.Item>
          <Descriptions.Item label="邮箱">
            <Space>
              <MailOutlined />
              {user.email}
            </Space>
          </Descriptions.Item>
          <Descriptions.Item label="角色">
            <Tag color={role.color}>{role.label}</Tag>
          </Descriptions.Item>
          <Descriptions.Item label="最后登录">
            {user.last_login_at ? new Date(user.last_login_at).toLocaleString('zh-CN') : '未知'}
          </Descriptions.Item>
        </Descriptions>

        <Divider />

        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <span style={{ fontWeight: 500 }}>安全设置</span>
          <Button icon={<LockOutlined />} onClick={() => setPwdModalVisible(true)}>修改密码</Button>
        </div>
      </Card>

      {tenant.id && (
        <Card title={<Space><TeamOutlined />租户信息</Space>} style={{ marginTop: 16 }}>
          <Descriptions column={2} bordered size="small">
            <Descriptions.Item label="公司名称">{tenant.name}</Descriptions.Item>
            <Descriptions.Item label="套餐">
              <Tag color={plan.color}>{plan.label}</Tag>
            </Descriptions.Item>
            <Descriptions.Item label="最大店铺数">{tenant.max_shops} 个</Descriptions.Item>
            <Descriptions.Item label="租户ID">{tenant.id}</Descriptions.Item>
          </Descriptions>
        </Card>
      )}

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
