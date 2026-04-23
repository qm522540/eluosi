/**
 * 时间显示工具 — 统一用莫斯科时区
 *
 * 后端存的 timestamp 都是 UTC naive（datetime.now(timezone.utc).replace(tzinfo=None)
 * 或规则 #6 的 utc_now_naive()）。FastAPI 序列化 naive datetime 时不带 Z 尾缀，
 * dayjs 默认把这类字符串当"客户端本地时区"解析，会造成时差（例如客户端 CST
 * 会让 UTC 08:11 被解读为 CST 08:11 = UTC 00:11，再 tz MSK 就变成 MSK 03:11）。
 *
 * 所以必须先 dayjs.utc(value) 强制按 UTC 解析，再 .tz(MSK) 转莫斯科。
 *
 * 背景：2026-04-23 时区 cutover 后真 UTC naive 成为新标准；cutover 前的旧记录
 * （bid_adjustment_logs 等）历史原因存的是 CST 伪 UTC，用 dayjs.utc 解析会显示
 * 错 8 小时 —— 用户端按 id 倒序时这些老记录会被推到末尾，不影响主视图。
 */

import dayjs from 'dayjs'
import utc from 'dayjs/plugin/utc'
import timezone from 'dayjs/plugin/timezone'

dayjs.extend(utc)
dayjs.extend(timezone)

const MSK = 'Europe/Moscow'

/** 完整时间格式: 2026-04-16 15:30 */
export function formatMoscowTime(value, fmt = 'YYYY-MM-DD HH:mm') {
  if (!value) return ''
  return dayjs.utc(value).tz(MSK).format(fmt)
}

/** 短格式（不带年）: 04-16 15:30 */
export function formatMoscowShort(value) {
  return formatMoscowTime(value, 'MM-DD HH:mm')
}

/** 仅时间: 15:30 */
export function formatMoscowHourMinute(value) {
  return formatMoscowTime(value, 'HH:mm')
}

/** 带秒: 2026-04-16 15:30:45 */
export function formatMoscowFull(value) {
  return formatMoscowTime(value, 'YYYY-MM-DD HH:mm:ss')
}
