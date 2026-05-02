import { useState } from 'react'
import { Outlet, useNavigate, useLocation } from 'react-router-dom'
import { Layout, Menu, Avatar, Dropdown, Typography, theme } from 'antd'
import {
  DashboardOutlined,
  FundOutlined,
  ShoppingOutlined,
  SearchOutlined,
  BarChartOutlined,
  SettingOutlined,
  LogoutOutlined,
  UserOutlined,
  MenuFoldOutlined,
  MenuUnfoldOutlined,
  AppstoreOutlined,
  PartitionOutlined,
  NotificationOutlined,
  DollarOutlined,
  LineChartOutlined,
  KeyOutlined,
  CopyOutlined,
  AuditOutlined,
  FileSearchOutlined,
} from '@ant-design/icons'
import { useAuthStore } from '@/stores/authStore'

const { Header, Sider, Content } = Layout
const { Text } = Typography

const menuItems = [
  {
    key: '/',
    icon: <DashboardOutlined />,
    label: '首页大盘',
  },
  {
    key: 'ads-group',
    icon: <FundOutlined />,
    label: '广告管理',
    children: [
      { key: '/ads', icon: <NotificationOutlined />, label: '推广信息' },
      { key: '/ads/bid-management', icon: <DollarOutlined />, label: '出价管理' },
    ],
  },
  {
    key: 'products-group',
    icon: <ShoppingOutlined />,
    label: '商品管理',
    children: [
      { key: '/products', icon: <AppstoreOutlined />, label: '商品列表' },
      { key: '/products/mapping', icon: <PartitionOutlined />, label: '映射管理' },
    ],
  },
  {
    key: 'seo-group',
    icon: <SearchOutlined />,
    label: 'SEO管理',
    children: [
      { key: '/seo/optimize', icon: <FundOutlined />, label: '优化建议' },
      { key: '/seo/health', icon: <DashboardOutlined />, label: '健康诊断' },
      { key: '/seo/tracking', icon: <LineChartOutlined />, label: '排名追踪' },
      { key: '/seo/report', icon: <BarChartOutlined />, label: '效果报表' },
    ],
  },
  {
    key: 'reports-group',
    icon: <BarChartOutlined />,
    label: '数据报表',
    children: [
      { key: '/reports/keywords', icon: <KeyOutlined />, label: '关键词统计' },
      { key: '/reports/search-insights', icon: <SearchOutlined />, label: '搜索词洞察' },
      { key: '/reports', icon: <LineChartOutlined />, label: '综合报表' },
    ],
  },
  {
    key: 'clone-group',
    icon: <CopyOutlined />,
    label: '店铺克隆',
    children: [
      { key: '/clone/tasks', icon: <CopyOutlined />, label: '克隆任务' },
      { key: '/clone/pending', icon: <AuditOutlined />, label: '待审核商品' },
      { key: '/clone/logs', icon: <FileSearchOutlined />, label: '克隆日志' },
    ],
  },
  {
    key: '/settings',
    icon: <SettingOutlined />,
    label: '系统设置',
  },
]

const AppLayout = () => {
  const [collapsed, setCollapsed] = useState(false)
  const navigate = useNavigate()
  const location = useLocation()
  const { user, logout } = useAuthStore()
  const { token: { colorBgContainer, borderRadiusLG } } = theme.useToken()

  const handleMenuClick = ({ key }) => {
    if (!key.startsWith('/')) return
    navigate(key)
  }

  const handleLogout = () => {
    logout()
    navigate('/login', { replace: true })
  }

  const userMenuItems = [
    {
      key: 'user',
      icon: <UserOutlined />,
      label: user?.username || '用户',
      disabled: true,
    },
    { type: 'divider' },
    {
      key: 'logout',
      icon: <LogoutOutlined />,
      label: '退出登录',
      danger: true,
      onClick: handleLogout,
    },
  ]

  return (
    <Layout style={{ minHeight: '100vh' }}>
      <Sider
        trigger={null}
        collapsible
        collapsed={collapsed}
        breakpoint="lg"
        onBreakpoint={(broken) => setCollapsed(broken)}
        style={{ background: colorBgContainer }}
      >
        <div style={{
          height: 64,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          borderBottom: '1px solid #f0f0f0',
        }}>
          <Text strong style={{ fontSize: collapsed ? 14 : 16 }}>
            {collapsed ? 'AI' : 'AI运营系统'}
          </Text>
        </div>
        <Menu
          mode="inline"
          selectedKeys={[location.pathname]}
          defaultOpenKeys={[
            location.pathname.startsWith('/products') && 'products-group',
            location.pathname.startsWith('/ads') && 'ads-group',
            location.pathname.startsWith('/reports') && 'reports-group',
            location.pathname.startsWith('/seo') && 'seo-group',
          ].filter(Boolean)}
          items={menuItems}
          onClick={handleMenuClick}
          style={{ borderRight: 0 }}
        />
      </Sider>
      <Layout>
        <Header style={{
          padding: '0 24px',
          background: colorBgContainer,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          borderBottom: '1px solid #f0f0f0',
        }}>
          <div
            style={{ fontSize: 18, cursor: 'pointer' }}
            onClick={() => setCollapsed(!collapsed)}
          >
            {collapsed ? <MenuUnfoldOutlined /> : <MenuFoldOutlined />}
          </div>
          <Dropdown menu={{ items: userMenuItems }} placement="bottomRight">
            <div style={{ cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 8 }}>
              <Avatar icon={<UserOutlined />} style={{ backgroundColor: '#7265e6' }} />
              {user?.username && <Text>{user.username}</Text>}
            </div>
          </Dropdown>
        </Header>
        <Content style={{
          margin: 24,
          padding: 24,
          background: colorBgContainer,
          borderRadius: borderRadiusLG,
          minHeight: 280,
          overflow: 'auto',
        }}>
          <Outlet />
        </Content>
      </Layout>
    </Layout>
  )
}

export default AppLayout
