from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware


class CSRFHeaderProtectionMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        if not self._is_trusted_request(request):
            return JSONResponse(
                status_code=403,
                content={"detail": "CSRF validation failed: untrusted origin or fetch site"}
            )
        return await call_next(request)

    def _is_trusted_request(self, request: Request) -> bool:
        method = request.method.upper()
        if method in {"GET", "HEAD", "OPTIONS", "TRACE"}:
            return True
        sec_fetch_site = request.headers.get("sec-fetch-site")
        if sec_fetch_site:
            # allow only same-origin or none (for direct navigation) requests
            if sec_fetch_site not in {"same-origin", "none"}:
                return False
            return True
        return False