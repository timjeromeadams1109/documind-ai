from pydantic import BaseSettings

class Settings(BaseSettings):
    app_name: str = "FastAPI JWT"
    admin_email: str = "admin@example.com"
    items_per_user: int = 50
    secret_key: str
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    
    database_url: str

    class Config:
        env_file = ".env"

settings = Settings()