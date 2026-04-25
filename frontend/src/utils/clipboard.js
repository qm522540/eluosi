/**
 * 跨 secure-context 的剪贴板复制工具
 *
 * 背景：navigator.clipboard.writeText 仅在 secure context（HTTPS / localhost）可用，
 * 部署在 HTTP 站点时直接抛 NotAllowedError。fallback 到 textarea + execCommand('copy')
 * 在 HTTP 上仍可用（虽然标准上 deprecated 但所有主流浏览器都还支持）。
 *
 * 返回 boolean：true=复制成功，false=两条路径都失败（让调用方提示用户手动复制）
 */
export async function copyText(text) {
  if (!text) return false

  // 路径 1：现代 API（HTTPS / localhost）
  if (navigator.clipboard && window.isSecureContext) {
    try {
      await navigator.clipboard.writeText(text)
      return true
    } catch {
      // 权限被拒/iframe 限制等，继续 fallback
    }
  }

  // 路径 2：execCommand fallback（HTTP 站点必经路径）
  try {
    const ta = document.createElement('textarea')
    ta.value = text
    // 离屏不可见，避免触发滚动 / 视觉闪烁
    ta.style.position = 'fixed'
    ta.style.left = '-9999px'
    ta.style.top = '0'
    ta.setAttribute('readonly', '')
    document.body.appendChild(ta)
    ta.select()
    ta.setSelectionRange(0, text.length)  // iOS Safari 兼容
    const ok = document.execCommand('copy')
    document.body.removeChild(ta)
    return !!ok
  } catch {
    return false
  }
}
