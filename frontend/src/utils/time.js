/**
 * 时间显示工具 — 统一用莫斯科时区
 *
 * 后端存的 timestamp 都是 UTC（datetime.now(timezone.utc)）。
 * 前端展示时必须转成莫斯科时间（Europe/Moscow, UTC+3），理由：
 *   1. Celery Beat 和 AI 调价时段系数都按莫斯科时间跑
 *   2. 店铺对接的是俄罗斯平台 WB/Ozon，后台也显示莫斯科时间
 *   3. 用户对照平台后台不需要做时区换算
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
  return dayjs(value).tz(MSK).format(fmt)
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
