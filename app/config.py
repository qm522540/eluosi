from urllib.parse import quote_plus

from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # 数据库
    DB_HOST: str = "localhost"
    DB_PORT: int = 3306
    DB_NAME: str = "ecommerce_ai"
    DB_USER: str = "root"
    DB_PASSWORD: str = ""

    @property
    def DATABASE_URL(self) -> str:
        password = quote_plus(self.DB_PASSWORD)
        return f"mysql+pymysql://{self.DB_USER}:{password}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}?charset=utf8mb4"

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"

    # JWT
    JWT_SECRET_KEY: str = "change-me"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 1440

    # AI模型
    DEEPSEEK_API_KEY: str = ""
    DEEPSEEK_BASE_URL: str = "https://api.deepseek.com"
    KIMI_API_KEY: str = ""
    KIMI_BASE_URL: str = "https://api.moonshot.cn/v1"
    GLM_API_KEY: str = ""
    GLM_BASE_URL: str = "https://open.bigmodel.cn/api/paas/v4"

    # 企业微信
    WECHAT_WORK_CORP_ID: str = ""
    WECHAT_WORK_AGENT_ID: str = ""
    WECHAT_WORK_SECRET: str = ""
    WECHAT_WORK_BOT_WEBHOOK: str = ""

    # 平台限速
    WB_RATE_LIMIT_PER_MINUTE: int = 60
    OZON_RATE_LIMIT_PER_MINUTE: int = 60
    YANDEX_RATE_LIMIT_PER_MINUTE: int = 60

    # 阿里云 OSS（用于商品图片归档）
    OSS_ENDPOINT: str = ""
    OSS_ACCESS_KEY_ID: str = ""
    OSS_ACCESS_KEY_SECRET: str = ""
    OSS_BUCKET: str = ""
    # CDN 加速域名（可选）；不填则用 OSS 默认域名
    OSS_CDN_DOMAIN: str = ""

    # 环境
    ENV: str = "development"
    DEBUG: bool = True

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


@lru_cache()
def get_settings() -> Settings:
    return Settings()
