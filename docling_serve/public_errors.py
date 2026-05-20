def build_public_http_detail(
    exc: BaseException,
    debug_enabled: bool,
    fallback_message: str,
) -> str:
    if not debug_enabled:
        return fallback_message

    detail = str(exc)
    return detail or fallback_message
