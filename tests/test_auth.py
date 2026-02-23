"""
验证 Admin Token 鉴权中间件的测试
"""

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from fastapi.responses import JSONResponse

from api.middleware import ApiKeyAuthMiddleware
from engrama import config

@pytest.fixture
def test_app(monkeypatch):
    """构建一个隔离的测试应用用于鉴权中间件测试"""
    monkeypatch.setattr(config, "ADMIN_TOKEN", "super_secret_token_123")
    
    app = FastAPI()
    
    # 手动添加待测中间件
    app.add_middleware(ApiKeyAuthMiddleware)
    
    # 模拟一个渠道管理路由
    @app.post("/v1/channels/tenants")
    async def fake_register_tenant(request: Request):
        return JSONResponse({"id": "fake_tenant_id", "name": "test"})
        
    return app

@pytest.fixture
def client_with_admin_auth(test_app):
    with TestClient(test_app) as client:
        yield client

def test_admin_token_missing(client_with_admin_auth):
    """缺少 admin token 被拦截"""
    resp = client_with_admin_auth.post("/v1/channels/tenants", json={"name": "test"})
    assert resp.status_code == 401
    assert "缺少管理员 Token" in resp.json()["detail"]

def test_admin_token_invalid(client_with_admin_auth):
    """错误的 admin token 被拦截"""
    resp = client_with_admin_auth.post(
        "/v1/channels/tenants", 
        json={"name": "test"}, 
        headers={"X-Admin-Token": "bad_token"}
    )
    assert resp.status_code == 403
    assert "无效的管理员 Token" in resp.json()["detail"]

def test_admin_token_valid(client_with_admin_auth):
    """正确的 admin token 允许放行"""
    resp = client_with_admin_auth.post(
        "/v1/channels/tenants", 
        json={"name": "test"}, 
        headers={"X-Admin-Token": "super_secret_token_123"}
    )
    assert resp.status_code == 200
    assert "id" in resp.json()
