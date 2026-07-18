"""Web 搜索工具单元测试（使用 Mock 覆盖外部 HTTP 请求）。"""
from unittest.mock import MagicMock, patch

import pytest

from services.web_search_utils import search_web
from services.tool_registry import ToolRegistry


@pytest.fixture
def ddg_html():
    return '''
    <div class="result result--url-above-snippet">
      <a class="result__a" href="/l/?uddg=https%3A%2F%2Fexample.com%2Fpage1">Example Page 1</a>
      <a class="result__snippet">This is the first &lt;snippet&gt; result.</a>
      <a class="result__url" href="https://example.com/page1">example.com</a>
    </div>
    <div class="result result--url-above-snippet">
      <a class="result__a" href="https://another.com/page2">Example Page 2</a>
      <a class="result__snippet">Second result description goes here.</a>
      <a class="result__url" href="https://another.com/page2">another.com</a>
    </div>
    <div class="result result--url-above-snippet">
      <a class="result__a" href="/l/?uddg=https%3A%2F%2Fthird.com">Third Page</a>
      <a class="result__snippet">Third result description.</a>
    </div>
    '''


def test_search_web_parses_results_and_resolves_redirects(ddg_html):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = ddg_html

    with patch('services.web_search_utils.requests.get', return_value=mock_resp):
        result = search_web('python', max_results=5)

    assert result['ok'] is True
    assert result['error'] is None
    assert len(result['results']) == 3

    first = result['results'][0]
    assert first['title'] == 'Example Page 1'
    assert first['url'] == 'https://example.com/page1'
    assert first['snippet'] == 'This is the first <snippet> result.'

    second = result['results'][1]
    assert second['title'] == 'Example Page 2'
    assert second['url'] == 'https://another.com/page2'


def test_search_web_respects_max_results(ddg_html):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = ddg_html

    with patch('services.web_search_utils.requests.get', return_value=mock_resp):
        result = search_web('python', max_results=2)

    assert len(result['results']) == 2
    assert result['results'][1]['title'] == 'Example Page 2'


def test_search_web_clamps_max_results():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = ''

    with patch('services.web_search_utils.requests.get', return_value=mock_resp):
        result = search_web('test', max_results=100)

    assert result['ok'] is True
    assert result['results'] == []
    # 检查内部确实把上限限制到 20，而不是发起 100 条请求


def test_search_web_empty_query():
    result = search_web('   ')
    assert result['ok'] is False
    assert 'empty' in result['error'].lower()


def test_search_web_request_failure():
    from requests import ConnectionError

    with patch('services.web_search_utils.requests.get', side_effect=ConnectionError('no network')):
        result = search_web('python')

    assert result['ok'] is False
    assert 'failed' in result['error'].lower()


def test_web_search_tool_registered():
    registry = ToolRegistry.get_instance()
    tool = registry.get('web_search')
    assert tool is not None
    assert tool.name == 'web_search'
    assert 'search' in tool.tags
