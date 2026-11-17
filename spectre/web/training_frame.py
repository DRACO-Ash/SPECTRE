"""Which requests come from training, marked once for every route (0.47.0 review B1).

A training request reads and writes the sign-in's training planning state, not
its operational one (spectre.web.planning_state.get_session_state). A request
is a training request when it is:

● to a /training route;
● from a page rendered in the training page's console frame, which says so in
  the X-Spectre-Frame header: base.html adds it to the page's hx-headers, and
  core.js to every fetch() the page's scripts make;
● a page load of the console into that frame, asked for as ``?frame=training``
  (static/js/training.js), or, as a fallback for a navigation inside the frame,
  any page load the browser marks ``Sec-Fetch-Dest: iframe``. The console is
  framed by nothing else (X-Frame-Options SAMEORIGIN).

``?frame=training`` counts only in the frame: a request whose Sec-Fetch-Dest
names anything but an iframe (the URL opened in a tab, a bookmark, history) is
operational, so a training console never passes for the operational one; and a
console served to training shows a TRAINING CONSOLE strip in its header
(operator.html) wherever it is open (review S4). Browsers send Sec-Fetch-Dest
only to a trustworthy origin (HTTPS or localhost), so over plain HTTP to any
other host the query alone decides; production is served over TLS (review N2).
"""

from __future__ import annotations

from urllib.parse import parse_qs

from starlette.types import ASGIApp, Receive, Scope, Send

from spectre.web.planning_state import training_request

#: The header, query parameter and value that name the training frame.
FRAME_HEADER = "x-spectre-frame"
FRAME_PARAM = "frame"
FRAME_VALUE = "training"
TRAINING_PREFIX = "/training"
#: HTTP header bytes are Latin-1 (ASGI).
_HEADER_ENCODING = "latin-1"


def is_training_request(path: str, headers: dict[str, str], query: str) -> bool:
    """Whether a request to *path* with these (lower-cased) *headers* and *query* comes from training."""
    if path == TRAINING_PREFIX or path.startswith(TRAINING_PREFIX + "/"):
        return True
    if headers.get(FRAME_HEADER) == FRAME_VALUE:
        return True
    dest = headers.get("sec-fetch-dest")
    if dest is not None:
        return dest == "iframe"
    return FRAME_VALUE in parse_qs(query).get(FRAME_PARAM, [])


class TrainingFrameMiddleware:
    """Serve each HTTP request as a training request or an operational one, by :func:`is_training_request`."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = {k.decode(_HEADER_ENCODING).lower(): v.decode(_HEADER_ENCODING) for k, v in scope.get("headers", [])}
        query = scope.get("query_string", b"").decode(_HEADER_ENCODING)
        with training_request(is_training_request(scope.get("path", ""), headers, query)):
            await self.app(scope, receive, send)
