// 平台枚举
export const PLATFORMS = {
  wb: { label: 'Wildberries', color: '#7B2D8E' },
  ozon: { label: 'Ozon', color: '#005BFF' },
  yandex: { label: 'Yandex Market', color: '#FFCC00' },
}

// 店铺状态
export const SHOP_STATUS = {
  active: { label: '正常', color: 'green' },
  inactive: { label: '停用', color: 'default' },
}

// 广告活动状态
export const AD_STATUS = {
  active: { label: '投放中', color: 'green' },
  paused: { label: '已暂停', color: 'orange' },
  archived: { label: '已归档', color: 'default' },
  draft: { label: '草稿', color: 'blue' },
}

// 广告类型
export const AD_TYPES = {
  search: { label: '搜索广告' },
  catalog: { label: '目录广告' },
  product_page: { label: '商品页广告' },
  recommendation: { label: '推荐广告' },
  banner: { label: '横幅广告' },
  video: { label: '视频广告' },
}
