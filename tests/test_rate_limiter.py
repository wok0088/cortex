"""
验证速率限制中间件的测试 (RateLimiterMiddleware)
"""

import os
import shutil
import tempfile

import pytest
from fastapi.testclient import TestClient

from engrama import config


@pytest.fixture
def tmp_dir():
    d = tempfile.mkdtemp()
    yield d
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def client_with_rate_limit(tmp_dir, monkeypatch):
    """使用限制频率很低（10次/分）的配置启动客户端"""
    monkeypatch.setattr(config, "RATE_LIMIT_PER_MINUTE", 10)
    monkeypatch.setattr(config, "ADMIN_TOKEN", "")
    monkeypatch.setattr(config, "DATA_DIR", tmp_dir)
    monkeypatch.setattr(config, "CHROMA_PERSIST_DIR", os.path.join(tmp_dir, "chroma_db"))
    monkeypatch.setattr(config, "SQLITE_DB_PATH", os.path.join(tmp_dir, "engrama_meta.db"))

    from api.main import create_app
    app = create_app()
    with TestClient(app) as client:
        yield client


def test_rate_limiter_exceeds_limit(client_with_rate_limit):
    """测试超过频率限制会被拒绝，并测试状态 429"""

    # 获取一个正常的 api key 用于测试
    resp = client_with_rate_limit.post("/v1/channels/tenants", json={"name": "t1"})
    tenant_id = resp.json()["id"]

    resp = client_with_rate_limit.post("/v1/channels/projects", json={"tenant_id": tenant_id, "name": "p1"})
    project_id = resp.json()["id"]

    resp = client_with_rate_limit.post("/v1/channels/api-keys", json={"tenant_id": tenant_id, "project_id": project_id})
    api_key = resp.json()["key"]

    # 模拟发送 12 个请求 (限制为 10)
    status_codes = []

    for _ in range(12):
        resp = client_with_rate_limit.post(
            "/v1/memories",
            json={"user_id": "u1", "content": "测试流量", "memory_type": "factual"},
            headers={"X-API-Key": api_key}
        )
        status_codes.append(resp.status_code)

    # 前 10 次应该成功，最后 2 次应该是 429
    assert status_codes.count(200) == 10
    assert status_codes[-2:] == [429, 429]
