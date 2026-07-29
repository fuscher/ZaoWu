"""chat apiBase SSRF 防护测试。"""
import pytest

from routes.chat import validate_api_base


def test_validate_public_url_ok():
    valid, err = validate_api_base('https://api.openai.com/v1')
    assert valid is True
    assert err == ''


def test_validate_allows_loopback_ip():
    valid, err = validate_api_base('http://127.0.0.1:8000')
    assert valid is True
    assert err == ''


def test_validate_allows_localhost():
    valid, err = validate_api_base('http://localhost:11434')
    assert valid is True
    assert err == ''


def test_validate_rejects_private_class_a():
    valid, err = validate_api_base('http://10.0.0.1')
    assert valid is False


def test_validate_rejects_private_class_b():
    valid, err = validate_api_base('http://172.16.0.1')
    assert valid is False


def test_validate_rejects_private_class_c():
    valid, err = validate_api_base('http://192.168.1.1')
    assert valid is False


def test_validate_rejects_link_local():
    valid, err = validate_api_base('http://169.254.169.254')
    assert valid is False


def test_validate_rejects_non_http_protocol():
    valid, err = validate_api_base('ftp://example.com')
    assert valid is False
    assert 'http:// or https://' in err


def test_validate_rejects_control_chars():
    valid, err = validate_api_base('http://example.com\n/attacker')
    assert valid is False
    assert 'invalid characters' in err


def test_validate_empty_passes():
    valid, err = validate_api_base('')
    assert valid is True
    assert err == ''
