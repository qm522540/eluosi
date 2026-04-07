"""统一错误码定义"""


class ErrorCode:
    # 通用 1xxxx
    SUCCESS = 0
    UNKNOWN_ERROR = 10001
    PARAM_ERROR = 10002
    NOT_FOUND = 10003
    FORBIDDEN = 10004

    # 认证 2xxxx
    AUTH_FAILED = 20001
    TOKEN_EXPIRED = 20002
    TOKEN_INVALID = 20003
    PERMISSION_DENIED = 20004

    # 店铺 3xxxx
    SHOP_NOT_FOUND = 30001
    SHOP_CREDENTIAL_INVALID = 30002
    SHOP_LIMIT_EXCEEDED = 30003
    SHOP_PLATFORM_ERROR = 30004

    # 商品 4xxxx
    PRODUCT_NOT_FOUND = 40001
    PRODUCT_SKU_DUPLICATE = 40002
    LISTING_NOT_FOUND = 40003

    # 广告 5xxxx
    AD_CAMPAIGN_NOT_FOUND = 50001
    AD_STATS_FETCH_FAILED = 50002
    AD_OPTIMIZE_FAILED = 50003

    # SEO 6xxxx
    SEO_GENERATE_FAILED = 60001
    SEO_CONTENT_NOT_FOUND = 60002

    # 库存 7xxxx
    INVENTORY_LOW_STOCK = 70001
    PO_NOT_FOUND = 70002

    # 财务 8xxxx
    FINANCE_CALC_FAILED = 80001

    # AI 9xxxx
    AI_MODEL_ERROR = 90001
    AI_TIMEOUT = 90002
    AI_QUOTA_EXCEEDED = 90003


ERROR_MESSAGES = {
    ErrorCode.SUCCESS: "成功",
    ErrorCode.UNKNOWN_ERROR: "未知错误",
    ErrorCode.PARAM_ERROR: "参数错误",
    ErrorCode.NOT_FOUND: "资源不存在",
    ErrorCode.AUTH_FAILED: "认证失败",
    ErrorCode.TOKEN_EXPIRED: "令牌已过期",
    ErrorCode.PERMISSION_DENIED: "权限不足",
    ErrorCode.SHOP_NOT_FOUND: "店铺不存在",
    ErrorCode.SHOP_CREDENTIAL_INVALID: "店铺API凭证无效",
    ErrorCode.PRODUCT_NOT_FOUND: "商品不存在",
    ErrorCode.AD_CAMPAIGN_NOT_FOUND: "广告活动不存在",
    ErrorCode.AI_MODEL_ERROR: "AI模型调用失败",
    ErrorCode.AI_TIMEOUT: "AI模型响应超时",
}
