from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    OPENAI_API_KEY: str = ""
    OPENAI_BASE_URL: str = "https://api.openai.com/v1"
    OPENAI_MODEL: str = "gpt-4o"
    # 代码生成 & 代码审查专用模型
    CODE_MODEL: str = "openai/gpt-5.3-codex"
    PORT: int = 8765

    # OpenRouter 可选请求头（使用 OpenRouter 时填写，其他情况留空即可）
    OR_SITE_URL: str = ""
    OR_SITE_NAME: str = ""

    # Doubao 图像生成（游戏素材）
    DOUBAO_API_KEY: str = ""
    DOUBAO_IMAGE_MODEL: str = "doubao-seedream-5-0-260128"
    DOUBAO_BASE_URL: str = "https://ark.cn-beijing.volces.com/api/v3"

    # Nano Banana Pro / Gemini 3 Pro Image（背景 & 关键艺术图）
    NANO_BANANA_PRO_API_KEY: str = ""
    NANO_BANANA_PRO_BASE_URL: str = "https://globalai.vip/v1beta"
    NANO_BANANA_PRO_MODEL: str = "gemini-3-pro-image-preview"

    # 生成图片本地保存目录（相对于 backend/）
    ART_OUTPUT_DIR: str = "static/art"

    @property
    def is_openrouter(self) -> bool:
        return "openrouter.ai" in self.OPENAI_BASE_URL

    class Config:
        env_file = ".env"


settings = Settings()
