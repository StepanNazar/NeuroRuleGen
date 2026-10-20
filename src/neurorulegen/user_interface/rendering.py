"""Jinja rendering and Vite's documented backend manifest integration."""

import json
import os
from functools import cache
from pathlib import Path

from fastapi import Request
from fastapi.templating import Jinja2Templates
from markupsafe import Markup, escape

ROOT = Path(__file__).parent
templates = Jinja2Templates(directory=ROOT / "templates")


@cache
def _load_manifest() -> dict:
    """Read the production manifest once; restart the backend after rebuilding."""
    manifest_path = ROOT / "static/dist/.vite/manifest.json"
    if not manifest_path.exists():
        raise RuntimeError(
            "Assets are missing. Run npm run build or make backend for development."
        )
    return json.loads(manifest_path.read_text())


def vite_assets(entry: str, client: bool = False) -> Markup:
    if os.getenv("UI_DEV") == "1":
        origin = escape(
            os.getenv("VITE_DEV_SERVER_URL", "http://127.0.0.1:5173").rstrip("/")
        )
        prefix = (
            f'<script type="module" src="{origin}/@vite/client"></script>'
            if client
            else ""
        )
        return Markup(
            prefix + f'<script type="module" src="{origin}/{escape(entry)}"></script>'
        )  # noqa: S704 -- escaped asset URL
    # example of manifest structure here: https://vite.dev/guide/backend-integration
    manifest = _load_manifest()
    styles = []
    visited = set()

    def collect(key):
        if key in visited:
            return
        visited.add(key)
        node = manifest[key]
        for dependency in node.get("imports", []):
            collect(dependency)
        for stylesheet in node.get("css", []):
            if stylesheet not in styles:
                styles.append(stylesheet)

    collect(entry)
    tags = "".join(
        f'<link rel="stylesheet" href="/static/dist/{escape(css)}">' for css in styles
    )
    return Markup(
        tags
        + f'<script type="module" src="/static/dist/{escape(manifest[entry]["file"])}"></script>'
    )  # noqa: S704 -- escaped generated paths


templates.env.globals["vite_assets"] = vite_assets


def render(request: Request, page: str, title: str, **context):
    return templates.TemplateResponse(
        request=request,
        name=page,
        context={"title": title, **context},
    )


def pagination(total_items: int, page: int = 1, page_size: int = 5) -> dict:
    """Calculate bounded navigation without loading or slicing any records."""
    page_size = max(1, min(page_size, 100))
    total_pages = max(1, (max(0, total_items) + page_size - 1) // page_size)
    page = max(1, min(page, total_pages))
    visible = {1, total_pages}
    visible.update(range(max(1, page - 2), min(total_pages, page + 2) + 1))
    pages = []
    previous = 0
    for number in sorted(visible):
        # if only one page is skipped - put it back
        if number - previous == 2:
            pages.append(previous + 1)
        elif number - previous > 2:
            pages.append(None)
        pages.append(number)
        previous = number
    return {
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages,
        "pages": pages,
    }


def pagination_context(
    request: Request, total_items: int, key: str = "page", page_size: int = 5
) -> dict:
    """Adapt pagination metadata to GET parameters and Jinja navigation links."""
    size_key = (
        "page_size" if key == "page" else f"{key.removesuffix('_page')}_page_size"
    )
    try:
        page_size = int(request.query_params.get(size_key, page_size))
    except ValueError:
        pass
    try:
        page = int(request.query_params.get(key, 1))
    except ValueError:
        page = 1
    pager = pagination(total_items, page, page_size)

    def page_url(number):
        return str(
            request.url.include_query_params(
                **{key: number, size_key: pager["page_size"]}
            )
        )

    return {
        **pager,
        "page_key": key,
        "size_key": size_key,
        "params": [ # needed for page size selector to preserve params
            (name, value)
            for name, value in request.query_params.multi_items()
            if name not in {key, size_key}
        ],
        "links": [
            {
                "number": n,
                "url": page_url(n) if n is not None else None,
            }
            for n in pager["pages"]
        ],
        "previous_url": page_url(pager["page"] - 1) if pager["page"] > 1 else None,
        "next_url": page_url(pager["page"] + 1)
        if pager["page"] < pager["total_pages"]
        else None,
    }
