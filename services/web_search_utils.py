"""轻量级免费 Web 搜索工具。

基于 DuckDuckGo HTML 端点实现，无需 API key，适合作为 Agent 的联网搜索能力。
注意：HTML 页面结构可能变化，解析采用保守策略；生产环境如需稳定性，建议接入
SearXNG、Brave Search API 等带官方接口的服务。
"""
import html
import re
from typing import List, Dict, Any
from urllib.parse import unquote

import requests

_DUCKDUCKGO_URL = 'https://html.duckduckgo.com/html/'
_DUCKDUCKGO_HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
        'AppleWebKit/537.36 (KHTML, like Gecko) '
        'Chrome/120.0.0.0 Safari/537.36'
    ),
    'Accept': 'text/html,application/xhtml+xml',
}


def search_web(query: str, max_results: int = 5, timeout: float = 10.0) -> Dict[str, Any]:
    """使用 DuckDuckGo 搜索公开网页。

    Args:
        query: 搜索关键词。如需限定 GitHub 社区内容，可传入 ``xxx site:github.com``。
        max_results: 最多返回几条结果（1-20），默认 5。
        timeout: 请求超时秒数。

    Returns:
        统一格式字典::

            {
                'ok': bool,
                'error': str | None,
                'results': [
                    {'title': str, 'url': str, 'snippet': str},
                    ...
                ]
            }
    """
    query = (query or '').strip()
    if not query:
        return {'ok': False, 'error': 'query is empty', 'results': []}

    max_results = max(1, min(int(max_results), 20))

    try:
        resp = requests.get(
            _DUCKDUCKGO_URL,
            params={'q': query, 'kl': 'us-en'},
            headers=_DUCKDUCKGO_HEADERS,
            timeout=timeout,
        )
        resp.raise_for_status()
    except requests.RequestException as e:
        return {'ok': False, 'error': f'web search request failed: {e}', 'results': []}

    results = _parse_duckduckgo_results(resp.text, max_results)
    return {'ok': True, 'error': None, 'results': results}


def _parse_duckduckgo_results(html_text: str, max_results: int) -> List[Dict[str, str]]:
    """从 DuckDuckGo HTML 结果页解析标题、链接和摘要。"""
    results: List[Dict[str, str]] = []

    # 标题与链接：<a class="result__a" href="...">Title</a>
    title_links = re.findall(
        r'<a[^>]*class="result__a"[^>]*href="([^"]*)"[^>]*>(.*?)</a>',
        html_text,
        re.S | re.I,
    )
    # 摘要：<a class="result__snippet">Snippet</a>
    snippets = re.findall(
        r'<a[^>]*class="result__snippet"[^>]*>(.*?)</a>',
        html_text,
        re.S | re.I,
    )

    for (href, raw_title), raw_snippet in zip(title_links, snippets):
        if len(results) >= max_results:
            break
        title = _strip_html(raw_title)
        snippet = _strip_html(raw_snippet)
        url = _resolve_duckduckgo_url(href)
        if title or snippet:
            results.append({'title': title, 'url': url, 'snippet': snippet})

    return results


def _strip_html(raw: str) -> str:
    """移除 HTML 标签并解码字符实体。"""
    text = re.sub(r'<[^>]+>', '', raw)
    return html.unescape(text).strip()


def _resolve_duckduckgo_url(href: str) -> str:
    """DuckDuckGo 的结果链接通常是重定向 URL，尝试解析出真实地址。"""
    # 常见形式：/l/?uddg=URLENCODED 或 //duckduckgo.com/l/?uddg=...
    match = re.search(r'[?&]uddg=([^&]+)', href)
    if match:
        try:
            return unquote(match.group(1))
        except Exception:
            pass
    return href
