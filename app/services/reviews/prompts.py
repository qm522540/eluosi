"""AI 回复 Prompt 模板 — 俄罗斯语境 友好+温暖 调性

设计原则 (跟用户 5-4 校准):
- 用买家短名 (俄罗斯人评价多用 "Анна" 不用全名), 拉近距离
- emoji 节制 (好评 💛/✨ 各 1 个, 差评 😔, 不滥用)
- 好评: 感谢 + 共情 + 邀请回购
- 中评: 感谢 + 询问改进点
- 差评: 不推诿 + 道歉 + 给具体解决路径 (私信联系)
- 不署名"小张"等假名, 用品牌签名 (从 shop_review_settings.brand_signature 注入)

Few-shot 样板按 sentiment 分组, prompt 拼接时按真实 rating 选样板.
"""

# ==================== Few-shot 样板 ====================

# 好评 (4-5 星): 感谢 + 共情 + 邀请回购
POSITIVE_SAMPLES = [
    {
        "input": "Сережки очень красивые, дочь в восторге!",
        "rating": 5,
        "customer_name": "Анна",
        "output": (
            "Анна, спасибо большое за такой тёплый отзыв! 💛 "
            "Очень рады, что серёжки понравились дочке — это самое приятное, "
            "что мы могли услышать! Будем рады видеть вас снова в нашем магазине ✨"
        ),
    },
    {
        "input": "Качество отличное, доставка быстрая, рекомендую!",
        "rating": 5,
        "customer_name": "",  # Ozon 无买家名
        "output": (
            "Спасибо за прекрасный отзыв! 💛 Очень приятно, что качество и "
            "скорость доставки оправдали ожидания. Заходите к нам ещё — у нас "
            "много новинок ✨"
        ),
    },
]

# 中评 (3 星): 感谢 + 询问具体改进点 + 表达改进意愿
NEUTRAL_SAMPLES = [
    {
        "input": "Нормально, но цвет немного отличается от фото.",
        "rating": 3,
        "customer_name": "Мария",
        "output": (
            "Мария, спасибо, что нашли время оставить отзыв. Очень ценим вашу "
            "обратную связь — постараемся доработать описание и фото, чтобы "
            "цвет соответствовал реальности. Если будут вопросы — пишите нам "
            "в личные сообщения, всегда готовы помочь."
        ),
    },
]

# 差评 (1-2 星): 道歉 + 不推诿 + 具体解决路径 (私信联系)
NEGATIVE_SAMPLES = [
    {
        "input": "Сережка пришла со сколом, расстроена.",
        "rating": 2,
        "customer_name": "Анна",
        "output": (
            "Анна, нам очень жаль, что серёжка пришла повреждённой 😔 "
            "Это абсолютно не тот уровень, к которому мы стремимся. "
            "Пожалуйста, напишите нам в личные сообщения — мы оперативно "
            "решим вопрос заменой или возвратом. Ещё раз приносим искренние "
            "извинения за доставленные неудобства."
        ),
    },
    {
        "input": "Не пришёл заказ, прошло уже 2 недели.",
        "rating": 1,
        "customer_name": "",
        "output": (
            "Здравствуйте! Очень сожалеем о задержке — это совершенно "
            "недопустимо 😔 Пожалуйста, напишите нам в личные сообщения "
            "номер заказа, мы немедленно разберёмся со службой доставки и "
            "найдём решение. Спасибо за терпение и приносим извинения."
        ),
    },
]


# ==================== Prompt 拼装 ====================

def build_reply_prompt(
    *,
    review_text_ru: str,
    rating: int,
    customer_name: str = "",
    product_name: str = "",
    custom_hint: str = "",
    brand_signature: str = "",
) -> str:
    """组装 DeepSeek prompt — 让 AI 出俄语回复

    Args:
        review_text_ru: 买家俄语原文
        rating: 1-5 星
        customer_name: 买家短名 (Ozon 时为空, prompt 里会指引匿名问候)
        product_name: 商品名 (可选, 让 AI 提及更亲切)
        custom_hint: 用户自定义重点 ("提一下我们的 30 天无理由退换" 之类),
                     不为空时 AI 必须包含这个信息
        brand_signature: 店铺签名 ("С любовью, Sharino" 之类)

    Returns:
        完整 prompt 字符串
    """
    # 按 rating 选 few-shot
    if rating >= 4:
        samples = POSITIVE_SAMPLES
        sentiment_hint = "好评 — 感谢 + 共情 + 邀请回购"
    elif rating == 3:
        samples = NEUTRAL_SAMPLES
        sentiment_hint = "中评 — 感谢 + 询问改进点 + 表达改进意愿"
    else:
        samples = NEGATIVE_SAMPLES
        sentiment_hint = "差评 — 道歉(不推诿) + 给具体解决路径(私信联系) + 共情"

    # Few-shot 渲染
    samples_text = "\n\n".join(
        f"【示例 {i+1}】\n买家 ({s['rating']}★ {s['customer_name'] or '匿名'}): {s['input']}\n回复: {s['output']}"
        for i, s in enumerate(samples)
    )

    name_hint = f"使用买家名 «{customer_name}» 直接称呼 (不要 Уважаемый/Уважаемая 等过度正式称谓)" \
        if customer_name else "买家匿名, 用 «Здравствуйте!» 开头"
    product_hint = f"如自然提及商品 «{product_name}» 更佳" if product_name else ""
    custom_hint_text = f"\n【必须包含的重点】: {custom_hint}" if custom_hint else ""
    sig_text = f"\n【结尾签名】: {brand_signature}" if brand_signature else ""

    return f"""你是俄罗斯电商客服, 友好+温暖语气. 给买家评价生成俄语回复.

【调性原则】
- 使用日常友好俄语 (不要书面化老式俄语)
- emoji 节制: 好评 💛/✨/❤ 选 1, 差评 😔, 中评不用
- {name_hint}
- {product_hint}
- {sentiment_hint}
- 长度: 30-80 个俄语单词 (不要长篇大论)
- 不要写英文也不要写中文

{samples_text}

【现在请回复以下评价】
买家 ({rating}★ {customer_name or '匿名'}): {review_text_ru}{custom_hint_text}{sig_text}

只输出俄语回复正文 (一段话), 不要解释, 不要 quote, 不要前缀."""


def build_sentiment_prompt(*, content_ru: str, rating: int) -> str:
    """情感分析 prompt — rating 已经是强信号, content 用来矫正

    例如 rating=5 但 content="商品不错就是物流慢" → neutral 而不是 positive
    """
    return f"""判断以下俄语买家评价的情感倾向. 仅输出 positive / neutral / negative 一个单词.

参考 (rating 是强信号但内容可矫正):
- 4-5★ 默认 positive (除非内容含严重抱怨)
- 3★ 默认 neutral
- 1-2★ 默认 negative (除非内容只是误评)

评价 ({rating}★): {content_ru}

只输出 positive / neutral / negative 三选一, 不要解释."""
