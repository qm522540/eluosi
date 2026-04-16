/**
 * WB 商品图片组件
 * WB 的 basket 编号需要猜测，这里根据 vol 估算初始 basket，onError 时探测相邻 basket
 */
import { useState, useEffect, useRef } from 'react'

const _wbImgCache = {}

const _getWbImgInfo = (nmId) => {
  const id = Number(nmId)
  if (!id) return null
  return { id, vol: Math.floor(id / 100000), part: Math.floor(id / 1000) }
}

const _buildWbImgUrl = (vol, part, id, basket) =>
  `https://basket-${String(basket).padStart(2, '0')}.wbbasket.ru/vol${vol}/part${part}/${id}/images/c246x328/1.webp`

const _guessBasket = (vol) => {
  const thresholds = [143, 287, 431, 719, 1007, 1061, 1115, 1169, 1313, 1601, 1655, 1919, 2045, 2189, 2405, 2621, 2837]
  for (let i = 0; i < thresholds.length; i++) {
    if (vol <= thresholds[i]) return i + 1
  }
  return Math.min(18 + Math.floor((vol - 2838) / 350), 60)
}

export default function WbProductImg({ nmId, size = 36 }) {
  const [src, setSrc] = useState(null)
  const [loaded, setLoaded] = useState(false)
  const [failed, setFailed] = useState(false)
  const triedRef = useRef(0)
  const infoRef = useRef(null)

  useEffect(() => {
    const info = _getWbImgInfo(nmId)
    if (!info) { setFailed(true); return }
    infoRef.current = info
    triedRef.current = 0
    setLoaded(false)
    setFailed(false)
    if (_wbImgCache[nmId]) { setSrc(_wbImgCache[nmId]); setLoaded(true) }
    else setSrc(_buildWbImgUrl(info.vol, info.part, info.id, _guessBasket(info.vol)))
  }, [nmId])

  if (failed || !src) {
    return (
      <div style={{
        width: size, height: size, borderRadius: 4,
        background: '#f0f0f0', display: 'flex',
        alignItems: 'center', justifyContent: 'center',
        fontSize: 11, color: '#bbb', flexShrink: 0,
      }}>无图</div>
    )
  }

  return (
    <img
      src={src}
      alt=""
      style={{
        width: size, height: size, borderRadius: 4, objectFit: 'cover',
        flexShrink: 0, display: loaded ? 'block' : 'none',
        background: '#f5f5f5',
      }}
      onError={() => {
        triedRef.current++
        const info = infoRef.current
        if (!info) { setFailed(true); return }
        const base = _guessBasket(info.vol)
        const offsets = [0, -1, 1, -2, 2, -3, 3, -4, 4, -5, 5, -6, 6, -7, 7, -8, 8]
        if (triedRef.current >= offsets.length) { setFailed(true); return }
        const next = base + offsets[triedRef.current]
        if (next < 1 || next > 65) { setFailed(true); return }
        setSrc(_buildWbImgUrl(info.vol, info.part, info.id, next))
      }}
      onLoad={() => { setLoaded(true); _wbImgCache[nmId] = src }}
    />
  )
}
