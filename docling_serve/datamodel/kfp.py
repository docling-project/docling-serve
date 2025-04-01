from pydantic import AnyUrl, BaseModel


class CallbackSpec(BaseModel):
    url: AnyUrl
    headers: dict[str, str] = {}
    ca_cert: str = ""
