"""轻量级免费 Web 搜索工具 — 多引擎降级方案。

搜索引擎优先级（可通过 settings.json 的 searchEngine 配置覆盖）：
  1. DuckDuckGo HTML — 国际通用，国内不稳定
  2. Bing China (cn.bing.com) — 国内稳定，无需 API key

降级策略：
  - 主引擎请求失败（超时 / 连接错误 / HTTP 非200）时自动切换备用引擎
  - 支持最多 1 次重试（同一引擎）
  - 搜索结果不足时也触发降级（主引擎返回空结果）

代理支持：
  - settings.json 中可配置 searchProxy（如 "http://127.0.0.1:7890"）
  - 所有请求统一走代理，便于国内用户访问 DuckDuckGo

安全性：
  - 请求 query 长度限制（500字符），防止资源消耗
  - 所有 URL 解析均为只读，不执行任何下载/跳转
  - HTML 解析使用保守正则，不引入 BeautifulSoup 等重依赖
"""
import html
import json
import logging
import os
import re
from typing import Any, Dict, List, Optional
from urllib.parse import quote, unquote

import requests

logger = logging.getLogger('services.web_search_utils')

# ── 配置 ──────────────────────────────────────────────────────

_SETTINGS_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'settings.json',
)

# 搜索引擎标识 → 实现函数的映射（初始化时填充）
_ENGINE_REGISTRY: Dict[str, callable] = {}

# 默认引擎降级链：先 DuckDuckGo（国际），后 Bing China（国内）
_DEFAULT_ENGINE_ORDER = ['duckduckgo', 'bing_china']

# 最大 query 长度（防止超长查询消耗资源）
_MAX_QUERY_LENGTH = 500

# 请求超时（秒）
_DEFAULT_TIMEOUT = 15.0

# 最大重试次数（同一引擎）
_MAX_RETRIES = 1

# 共用 User-Agent（模拟主流浏览器，避免被反爬拦截）
_COMMON_HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
        'AppleWebKit/537.36 (KHTML, like Gecko) '
        'Chrome/126.0.0.0 Safari/537.36'
    ),
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
}


def _load_settings() -> dict:
    """读取 settings.json（如不存在则返回空字典）。"""
    try:
        with open(_SETTINGS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _get_proxy() -> Optional[str]:
    """从 settings.json 获取代理配置。"""
    settings = _load_settings()
    proxy = settings.get('searchProxy', '').strip()
    if proxy and proxy.startswith(('http://', 'https://', 'socks5://', 'socks5h://')):
        return proxy
    return None


def _get_engine_order() -> List[str]:
    """从 settings.json 获取搜索引擎优先级列表。"""
    settings = _load_settings()
    engine = settings.get('searchEngine', '').strip().lower()
    if engine and engine in _ENGINE_REGISTRY:
        # 用户指定了单个引擎，降级链仅包含该引擎
        return [engine]
    # 默认降级链
    return _DEFAULT_ENGINE_ORDER


def _get_proxies_dict() -> Optional[Dict[str, str]]:
    """构建 requests 代理字典。"""
    proxy = _get_proxy()
    if proxy:
        return {'http': proxy, 'https': proxy}
    return None


# ── DuckDuckGo HTML 搜索引擎 ────────────────────────────────

_DUCKDUCKGO_URL = 'https://html.duckduckgo.com/html/'


def _search_duckduckgo(query: str, max_results: int, timeout: float) -> Dict[str, Any]:
    """DuckDuckGo HTML 端点搜索（国际环境优先，国内不稳定）。"""
    try:
        resp = requests.get(
            _DUCKDUCKGO_URL,
            params={'q': query, 'kl': 'wt-wt'},  # wt-wt = 全球范围（非 us-en）
            headers=_COMMON_HEADERS,
            timeout=timeout,
            proxies=_get_proxies_dict(),
        )
        resp.raise_for_status()
        resp.encoding = 'utf-8'
    except requests.RequestException as e:
        logger.warning('DuckDuckGo search failed: %s', e)
        return {'ok': False, 'error': str(e), 'results': [], 'engine': 'duckduckgo'}

    results = _parse_duckduckgo_results(resp.text, max_results)
    if not results:
        logger.info('DuckDuckGo returned 0 results for query: %s', query[:50])

    return {
        'ok': True,
        'error': None,
        'results': results,
        'engine': 'duckduckgo',
    }


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


def _resolve_duckduckgo_url(href: str) -> str:
    """DuckDuckGo 的结果链接通常是重定向 URL，尝试解析出真实地址。"""
    match = re.search(r'[?&]uddg=([^&]+)', href)
    if match:
        try:
            return unquote(match.group(1))
        except Exception:
            pass
    return href


# ── Bing China 搜索引擎 ──────────────────────────────────────

_BING_CHINA_URL = 'https://cn.bing.com/search'


def _search_bing_china(query: str, max_results: int, timeout: float) -> Dict[str, Any]:
    """Bing 中国版搜索（国内稳定可达，无需 API key）。

    使用 cn.bing.com 的 HTML 页面，通过正则解析结果。
    此端点在中国大陆网络下稳定可用。
    """
    try:
        resp = requests.get(
            _BING_CHINA_URL,
            params={'q': query, 'count': max_results, 'setlang': 'zh-CN'},
            headers=_COMMON_HEADERS,
            timeout=timeout,
            proxies=_get_proxies_dict(),
        )
        resp.raise_for_status()
        resp.encoding = 'utf-8'
    except requests.RequestException as e:
        logger.warning('Bing China search failed: %s', e)
        return {'ok': False, 'error': str(e), 'results': [], 'engine': 'bing_china'}

    results = _parse_bing_results(resp.text, max_results)
    if not results:
        logger.info('Bing China returned 0 results for query: %s', query[:50])

    return {
        'ok': True,
        'error': None,
        'results': results,
        'engine': 'bing_china',
    }


def _parse_bing_results(html_text: str, max_results: int) -> List[Dict[str, str]]:
    """从 Bing HTML 结果页解析标题、链接和摘要。

    Bing 结果页的核心结构：
    - 结果容器：<li class="b_algo">
    - 标题链接：<h2><a href="...">Title</a></h2>
    - 摘要：<div class="b_caption"><p>...</p> 或 <span class="b_line2">...</span>
    """
    results: List[Dict[str, str]] = []

    # 提取每个结果块 <li class="b_algo">...</li>
    algo_blocks = re.findall(
        r'<li[^>]*class="b_algo"[^>]*>(.*?)</li>',
        html_text,
        re.S | re.I,
    )

    for block in algo_blocks:
        if len(results) >= max_results:
            break

        # 标题 + URL：<h2><a href="URL">Title</a></h2>
        title_match = re.search(
            r'<h2[^>]*>\s*<a[^>]*href="([^"]*)"[^>]*>(.*?)</a>',
            block,
            re.S | re.I,
        )
        if not title_match:
            continue

        raw_url = title_match.group(1)
        raw_title = title_match.group(2)

        # Bing URL 可能包含跟踪参数，提取纯 URL
        url = _resolve_bing_url(raw_url)
        title = _strip_html(raw_title)

        # 摘要：尝试 <p class="b_lineclamp"> 或 <div class="b_caption"> 下的 <p>
        snippet = ''
        snippet_match = re.search(
            r'<p[^>]*class="b_lineclamp[^"]*"[^>]*>(.*?)</p>',
            block,
            re.S | re.I,
        )
        if not snippet_match:
            snippet_match = re.search(
                r'<div[^>]*class="b_caption[^"]*"[^>]*>\s*<p[^>]*>(.*?)</p>',
                block,
                re.S | re.I,
            )
        if not snippet_match:
            # 第三层回退：任何 <p> 标签
            snippet_match = re.search(
                r'<p[^>]*>(.*?)</p>',
                block,
                re.S | re.I,
            )
        if snippet_match:
            snippet = _strip_html(snippet_match.group(1))

        if title or snippet:
            results.append({'title': title, 'url': url, 'snippet': snippet})

    return results


def _resolve_bing_url(raw_url: str) -> str:
    """从 Bing 结果链接提取纯 URL。

    Bing 使用跟踪链接格式，例如：
    - https://cn.bing.com/ck/a?...&u=URLENCODED_REAL_URL&...
    - 直接是原始 URL（少数情况）

    安全性：仅提取 URL，不执行跳转或下载。
    """
    # 尝试提取 Bing 跟踪链接中的 u= 参数
    match = re.search(r'[?&]u=([^&]+)', raw_url)
    if match:
        try:
            decoded = unquote(match.group(1))
            # 验证解码结果是合法 URL
            if decoded.startswith(('http://', 'https://')):
                return decoded
        except Exception:
            pass

    # 如果不是跟踪链接，直接返回原始 URL
    if raw_url.startswith(('http://', 'https://')):
        return raw_url

    return raw_url


# ── 通用工具 ──────────────────────────────────────────────────

def _strip_html(raw: str) -> str:
    """移除 HTML 标签并解码字符实体。"""
    text = re.sub(r'<[^>]+>', '', raw)
    return html.unescape(text).strip()


# ── 引擎注册 ──────────────────────────────────────────────────

_ENGINE_REGISTRY['duckduckgo'] = _search_duckduckgo
_ENGINE_REGISTRY['bing_china'] = _search_bing_china


# ── 公共接口 ──────────────────────────────────────────────────

def search_web(query: str, max_results: int = 5, timeout: float = _DEFAULT_TIMEOUT) -> Dict[str, Any]:
    """使用多引擎降级策略搜索公开网页。

    搜索引擎降级链（可通过 settings.json 的 searchEngine 配置覆盖）：
      - 默认：DuckDuckGo → Bing China（主引擎失败后自动切换备用）
      - 指定引擎：仅使用用户选择的引擎，不做降级

    Args:
        query: 搜索关键词。如需限定站点，可传入 ``xxx site:github.com``。
        max_results: 最多返回几条结果（1-20），默认 5。
        timeout: 单次请求超时秒数（默认 15）。

    Returns:
        统一格式字典::

            {
                'ok': bool,
                'error': str | None,
                'results': [
                    {'title': str, 'url': str, 'snippet': str},
                    ...
                ],
                'engine': str   # 实际使用的搜索引擎名称
            }
    """
    # 输入校验
    query = (query or '').strip()
    if not query:
        return {'ok': False, 'error': 'query is empty', 'results': [], 'engine': ''}
    if len(query) > _MAX_QUERY_LENGTH:
        return {
            'ok': False,
            'error': f'query exceeds max length {_MAX_QUERY_LENGTH}',
            'results': [],
            'engine': '',
        }

    max_results = max(1, min(int(max_results), 20))
    timeout = max(5.0, min(float(timeout), 30.0))

    engine_order = _get_engine_order()
    last_error = None

    for engine_name in engine_order:
        engine_fn = _ENGINE_REGISTRY.get(engine_name)
        if engine_fn is None:
            logger.warning('unknown search engine: %s', engine_name)
            continue

        # 尝试当前引擎（含重试）
        for attempt in range(1 + _MAX_RETRIES):
            result = engine_fn(query, max_results, timeout)

            if result.get('ok') and result.get('results'):
                # 成功且有结果 → 直接返回
                return result

            if result.get('ok') and not result.get('results'):
                # 成功但无结果 → 不再重试同一引擎，尝试降级
                logger.info(
                    'engine %s returned empty results for query: %s (attempt %d)',
                    engine_name, query[:50], attempt + 1,
                )
                last_error = f'{engine_name}: no results found'
                break  # 跳到下一个引擎

            # 请求失败 → 记录错误，重试或降级
            last_error = result.get('error', 'unknown error')
            logger.warning(
                'engine %s attempt %d failed: %s',
                engine_name, attempt + 1, last_error,
            )

        # 当前引擎所有尝试均失败 → 降级到下一个引擎
        logger.info('falling back from %s to next engine', engine_name)

    # 所有引擎都失败
    return {
        'ok': False,
        'error': f'all search engines failed; last error: {last_error}',
        'results': [],
        'engine': '',
    }
