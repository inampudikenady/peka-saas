from pydantic import BaseModel


class PlatformLoginRequest(BaseModel):
    username: str
    password: str


class PlatformTokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
