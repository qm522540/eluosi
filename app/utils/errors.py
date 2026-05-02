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
    SHOP_NAME_EXISTS = 30005

    # 商品 4xxxx
    PRODUCT_NOT_FOUND = 40001
    PRODUCT_SKU_DUPLICATE = 40002
    LISTING_NOT_FOUND = 40003

    # 广告 5xxxx
    AD_CAMPAIGN_NOT_FOUND = 50001
    AD_STATS_FETCH_FAILED = 50002
    AD_OPTIMIZE_FAILED = 50003
    AD_GROUP_NOT_FOUND = 50004
    AD_KEYWORD_NOT_FOUND = 50005
    AD_RULE_NOT_FOUND = 50006
    AD_BUDGET_ERROR = 50007

    # SEO 6xxxx
    SEO_GENERATE_FAILED = 60001
    SEO_CONTENT_NOT_FOUND = 60002

    # 库存 7xxxx
    INVENTORY_LOW_STOCK = 70001
    PO_NOT_FOUND = 70002

    # 财务 8xxxx
    FINANCE_CALC_FAILED = 80001
    FINANCE_COST_NOT_FOUND = 80002
    FINANCE_INVALID_PERIOD = 80003
    FINANCE_INVALID_CURRENCY = 80004
    FINANCE_DUPLICATE_SNAPSHOT = 80005
    FINANCE_SYNC_FAILED = 80006
    FINANCE_RATE_NOT_FOUND = 80007

    # AI 9xxxx
    AI_MODEL_ERROR = 90001
    AI_TIMEOUT = 90002
    AI_QUOTA_EXCEEDED = 90003

    # AI调价 91xxx
    AI_PRICING_CONFIG_NOT_FOUND = 91001
    AI_PRICING_SUGGESTION_NOT_FOUND = 91002
    AI_PRICING_SUGGESTION_EXPIRED = 91003
    AI_PRICING_INVALID_STATUS = 91004
    AI_PRICING_API_FAILED = 91006

    # 出价管理 92xxx（统一分时调价 + AI调价 + 冲突检测）
    BID_TIME_RULE_NOT_FOUND = 92001
    BID_AI_CONFIG_NOT_FOUND = 92002
    BID_CONFLICT_TIME_AI = 92003        # 分时和AI只能开一个
    BID_SUGGESTION_NOT_FOUND = 92004
    BID_SUGGESTION_EXPIRED = 92005      # 次日即过期
    BID_INVALID_STATUS = 92006
    BID_INVALID_HOURS_CONFIG = 92007    # 24小时未覆盖/重复
    BID_INVALID_RATIO = 92008           # ratio 超出合理范围
    BID_DATA_NOT_READY = 92009          # 首次3个月数据未拉完
    BID_DATA_SYNC_RUNNING = 92010       # 数据同步中
    BID_EXECUTION_FAILED = 92011
    BID_SKU_LOCKED = 92012              # user_managed 锁定

    # 搜索词洞察 93xxx
    SEARCH_INSIGHTS_SUBSCRIPTION_REQUIRED = 93001  # WB Jam / Ozon Premium 未开通
    SEARCH_INSIGHTS_FETCH_FAILED = 93002           # 平台 API 拉取失败（非订阅原因）

    # SEO 优化候选池 94xxx
    SEO_CANDIDATE_NOT_FOUND = 94001
    SEO_CANDIDATE_INVALID_STATUS = 94002           # 状态不允许该操作（已 adopted 不能再 ignore 等）
    SEO_REFRESH_FAILED = 94003                     # 引擎分析失败（数据源异常等）
    SEO_TITLE_GENERATE_FAILED = 94004              # AI 生成标题失败（模型超时 / 返回异常 / 解析失败）
    SEO_PRODUCT_NOT_FOUND = 94005                  # 商品在当前店铺找不到 listing（需先同步商品）

    # 店铺克隆 95xxx（A 店自动跟踪 B 店上新 → 待审核 → 推 A 上架）
    CLONE_TASK_NOT_FOUND = 95001
    CLONE_TASK_DUPLICATE = 95002                   # 同一对 A/B 已存在任务
    CLONE_TASK_INVALID_CONFIG = 95003              # 配置非法（adjust_pct 缺失/超界、A==B 等）
    CLONE_TASK_SOURCE_INVALID = 95004              # 源店铺不可用（不属于本租户/已 inactive）
    CLONE_SCAN_RUNNING = 95005                     # 扫描进行中（Redis 锁未释放）
    CLONE_SOURCE_API_FAILED = 95006                # 拉取 B 店数据失败（凭证失效/限流等）
    CLONE_PENDING_NOT_FOUND = 95007                # 待审核记录不存在
    CLONE_PENDING_INVALID_STATUS = 95008           # 状态不允许该操作（如 published 不能再 reject）
    CLONE_PUBLISH_FAILED = 95009                   # 上架到 A 平台失败
    CLONE_CATEGORY_MAPPING_MISSING = 95010         # 类目映射缺失（跨平台克隆需先建好映射）
    CLONE_TARGET_SHOP_INACTIVE = 95011             # 目标店铺未激活
    CLONE_PENDING_NOT_REJECTED = 95012             # restore 仅适用于 status='rejected' 的记录
    CLONE_AI_REWRITE_FAILED = 95013                # AI 改写失败（已 fallback 到 source 原文，不阻断扫描）


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
    ErrorCode.SHOP_NAME_EXISTS: "店铺名称已存在",
    ErrorCode.PRODUCT_NOT_FOUND: "商品不存在",
    ErrorCode.AD_CAMPAIGN_NOT_FOUND: "广告活动不存在",
    ErrorCode.AD_GROUP_NOT_FOUND: "广告组不存在",
    ErrorCode.AD_KEYWORD_NOT_FOUND: "关键词不存在",
    ErrorCode.AD_OPTIMIZE_FAILED: "出价优化失败",
    ErrorCode.AD_RULE_NOT_FOUND: "自动化规则不存在",
    ErrorCode.AD_BUDGET_ERROR: "预算操作失败",
    ErrorCode.AI_MODEL_ERROR: "AI模型调用失败",
    ErrorCode.AI_TIMEOUT: "AI模型响应超时",
    ErrorCode.AI_PRICING_CONFIG_NOT_FOUND: "调价配置不存在",
    ErrorCode.AI_PRICING_SUGGESTION_NOT_FOUND: "调价建议不存在",
    ErrorCode.AI_PRICING_SUGGESTION_EXPIRED: "调价建议已过期",
    ErrorCode.AI_PRICING_INVALID_STATUS: "当前状态不允许该操作",
    ErrorCode.AI_PRICING_API_FAILED: "调用平台API修改出价失败",
    ErrorCode.FINANCE_CALC_FAILED: "财务计算失败",
    ErrorCode.FINANCE_COST_NOT_FOUND: "费用记录不存在",
    ErrorCode.FINANCE_INVALID_PERIOD: "无效的统计周期",
    ErrorCode.FINANCE_INVALID_CURRENCY: "不支持的货币代码",
    ErrorCode.FINANCE_DUPLICATE_SNAPSHOT: "ROI快照已存在",
    ErrorCode.FINANCE_SYNC_FAILED: "财务数据同步失败",
    ErrorCode.FINANCE_RATE_NOT_FOUND: "汇率配置不存在",
    ErrorCode.BID_TIME_RULE_NOT_FOUND: "分时调价规则不存在",
    ErrorCode.BID_AI_CONFIG_NOT_FOUND: "AI调价配置不存在",
    ErrorCode.BID_CONFLICT_TIME_AI: "分时调价与AI调价互斥，同一店铺只能启用其一",
    ErrorCode.BID_SUGGESTION_NOT_FOUND: "调价建议不存在",
    ErrorCode.BID_SUGGESTION_EXPIRED: "调价建议已过期（次日自动作废）",
    ErrorCode.BID_INVALID_STATUS: "当前状态不允许该操作",
    ErrorCode.BID_INVALID_HOURS_CONFIG: "时段配置非法：24小时未覆盖或存在重复",
    ErrorCode.BID_INVALID_RATIO: "出价系数超出合理范围",
    ErrorCode.BID_DATA_NOT_READY: "店铺历史数据未初始化完成，请稍后",
    ErrorCode.BID_DATA_SYNC_RUNNING: "数据同步进行中",
    ErrorCode.BID_EXECUTION_FAILED: "出价执行失败",
    ErrorCode.BID_SKU_LOCKED: "该SKU已被用户手动管理，不允许自动调价",
    ErrorCode.SEARCH_INSIGHTS_SUBSCRIPTION_REQUIRED: "该功能需开通 WB Jam 或 Ozon Premium 订阅",
    ErrorCode.SEARCH_INSIGHTS_FETCH_FAILED: "搜索词数据拉取失败",
    ErrorCode.SEO_CANDIDATE_NOT_FOUND: "SEO 候选词不存在",
    ErrorCode.SEO_CANDIDATE_INVALID_STATUS: "候选词当前状态不允许该操作",
    ErrorCode.SEO_REFRESH_FAILED: "SEO 候选引擎分析失败",
    ErrorCode.SEO_TITLE_GENERATE_FAILED: "AI 生成标题失败",
    ErrorCode.SEO_PRODUCT_NOT_FOUND: "当前店铺找不到该商品 listing",
    ErrorCode.CLONE_TASK_NOT_FOUND: "克隆任务不存在",
    ErrorCode.CLONE_TASK_DUPLICATE: "该 A/B 店组合已存在克隆任务",
    ErrorCode.CLONE_TASK_INVALID_CONFIG: "克隆任务配置非法",
    ErrorCode.CLONE_TASK_SOURCE_INVALID: "源店铺不可用",
    ErrorCode.CLONE_SCAN_RUNNING: "扫描正在进行中，请稍后再试",
    ErrorCode.CLONE_SOURCE_API_FAILED: "拉取源店铺数据失败",
    ErrorCode.CLONE_PENDING_NOT_FOUND: "待审核记录不存在",
    ErrorCode.CLONE_PENDING_INVALID_STATUS: "当前状态不允许该操作",
    ErrorCode.CLONE_PUBLISH_FAILED: "上架到目标平台失败",
    ErrorCode.CLONE_CATEGORY_MAPPING_MISSING: "类目映射缺失，请先在映射管理中建立 B 平台到 A 平台的对应关系",
    ErrorCode.CLONE_TARGET_SHOP_INACTIVE: "目标店铺未激活",
    ErrorCode.CLONE_PENDING_NOT_REJECTED: "仅可恢复已拒绝的记录",
    ErrorCode.CLONE_AI_REWRITE_FAILED: "AI 改写失败，已使用源商品原文",
}
