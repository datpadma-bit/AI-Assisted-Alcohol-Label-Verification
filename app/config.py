from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    cloudflare_account_id: str = ""
    cloudflare_api_token: str = ""
    clef_base_url: str = ""  # set to self-host; empty = Workers AI
    clef_model: str = "@cf/cloudflare/clef-omni"
    match_threshold: float = 0.90
    mismatch_threshold: float = 0.10
    batch_concurrency: int = 8
    request_timeout_s: float = 20.0
    max_image_side_px: int = 1600

    @property
    def endpoint(self) -> str:
        if self.clef_base_url:
            return self.clef_base_url
        return (
            "https://api.cloudflare.com/client/v4/accounts/"
            f"{self.cloudflare_account_id}/ai/run/{self.clef_model}"
        )


settings = Settings()
