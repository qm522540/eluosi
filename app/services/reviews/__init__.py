"""店铺评价管理模块 (Review Hub)

模块职责:
- 拉取平台买家评价 (WB / Ozon)
- AI 翻译俄语 → 中文 (复用 ru_zh_dict 缓存)
- AI 情感分析 (rating + content → positive/neutral/negative)
- AI 起草友好+温暖语气的俄语回复 (DeepSeek + few-shot)
- 人工编辑 + 自定义 hint 重新生成
- 一键发送 + 自动回复 (4-5 星走自动, 1-3 星人工)

设计参考: docs/api/reviews.md (待写)
"""
