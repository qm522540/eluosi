const ComingSoon = ({ title }) => (
  <div style={{
    display: 'flex', flexDirection: 'column', alignItems: 'center',
    justifyContent: 'center', padding: '80px 0', color: '#999',
  }}>
    <div style={{ fontSize: 48, marginBottom: 20 }}>🚧</div>
    <div style={{ fontSize: 18, fontWeight: 500, color: '#333', marginBottom: 8 }}>
      {title}功能正在规划中
    </div>
    <div style={{ fontSize: 14, marginBottom: 24 }}>
      我们正在设计最适合你的展示方式，敬请期待
    </div>
    <div style={{
      padding: '12px 24px', background: '#fafafa', borderRadius: 8,
      fontSize: 13, color: '#999', border: '1px dashed #d9d9d9',
    }}>
      如有具体需求欢迎随时反馈
    </div>
  </div>
)

export default ComingSoon
