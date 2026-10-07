"""Machine-readable error codes, added WITHOUT changing the error shape.

Spec 017's first attempt made `detail` an object (`{"code", "message"}`) on the
two driver-auth 403s. That shipped nothing and was reverted, because it breaks
in BOTH directions of version skew — and the apps deploy independently of the
backend, so skew is the normal state, not an edge case:

- A NEW app against the OLD server reads a string `detail`, finds no `code`,
  and fails the "not registered" check — which is exactly the bug seen on
  device: a driver with no profile landed on the error screen instead of the
  registration form.
- An OLD app against the NEW server is worse, because it cannot be fixed by
  shipping anything. Sideloaded APKs are not force-updated. The old client
  read `detail` expecting a string, got an object, and fell through to
  "Something went wrong."

So the code travels as a SIBLING of `detail`, never in place of it:

    {"detail": "Not registered as a driver", "code": "driver_not_registered"}

`detail` keeps the exact string it has always had, so every client ever built
still works. `code` is additive, so a client that knows to look for it gets
something stable to branch on. This also keeps the one-consistent-error-shape
convention intact rather than carving out an exception to it.
"""

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse


class CodedHTTPException(HTTPException):
    """An HTTPException that also carries a stable, machine-readable code.

    `detail` stays a human-readable string and remains the only thing a client
    needs for display. The code is for clients that must BRANCH on which error
    this is — today, only the driver app's four-state routing.
    """

    def __init__(self, status_code: int, detail: str, code: str) -> None:
        super().__init__(status_code=status_code, detail=detail)
        self.code = code


async def coded_http_exception_handler(
    request: Request, exc: Exception
) -> JSONResponse:
    """Renders `detail` plus a top-level `code`.

    Registered for CodedHTTPException specifically. Starlette resolves handlers
    by walking the exception's MRO, so this wins over FastAPI's own
    HTTPException handler for this subclass and leaves every other error
    untouched.
    """
    assert isinstance(exc, CodedHTTPException)
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail, "code": exc.code},
        headers=exc.headers,
    )
