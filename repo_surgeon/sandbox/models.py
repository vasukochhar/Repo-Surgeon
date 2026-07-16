from pydantic import BaseModel


class SandboxMetadata(BaseModel):
    engine: str
    image: str | None = None
    network_mode: str | None = None
    isolated: bool = True
