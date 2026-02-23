"""
渠道管理器

封装租户、项目和 API Key 的管理逻辑。
"""

from typing import Optional

from engrama.logger import get_logger
from engrama.models import ApiKey, Project, Tenant
from engrama.store.meta_store import MetaStore

logger = get_logger(__name__)


class ChannelManager:
    """
    渠道管理器

    提供租户注册、项目管理和 API Key 管理的业务接口。
    """

    def __init__(self, meta_store: Optional[MetaStore] = None):
        self._meta_store = meta_store or MetaStore()

    # ----------------------------------------------------------
    # 租户管理
    # ----------------------------------------------------------

    def register_tenant(self, name: str) -> Tenant:
        """注册新租户"""
        return self._meta_store.create_tenant(name)

    def get_tenant(self, tenant_id: str) -> Optional[Tenant]:
        """获取租户信息"""
        return self._meta_store.get_tenant(tenant_id)

    def list_tenants(self) -> list[Tenant]:
        """列出所有租户"""
        return self._meta_store.list_tenants()

    def delete_tenant(self, tenant_id: str) -> bool:
        """删除租户（级联吊销 Key + 删除项目 + 删除租户，不清理 ChromaDB）"""
        return self._meta_store.delete_tenant(tenant_id)

    # ----------------------------------------------------------
    # 项目管理
    # ----------------------------------------------------------

    def create_project(self, tenant_id: str, name: str) -> Project:
        """创建项目"""
        return self._meta_store.create_project(tenant_id, name)

    def get_project(self, project_id: str) -> Optional[Project]:
        """获取项目信息"""
        return self._meta_store.get_project(project_id)

    def list_projects(self, tenant_id: str) -> list[Project]:
        """列出租户下的所有项目"""
        return self._meta_store.list_projects(tenant_id)

    def delete_project(self, project_id: str, tenant_id: str) -> bool:
        """删除项目（需验证 tenant_id 归属）"""
        return self._meta_store.delete_project(project_id, tenant_id=tenant_id)

    # ----------------------------------------------------------
    # API Key 管理
    # ----------------------------------------------------------

    def generate_api_key(self, tenant_id: str, project_id: str, user_id: str = None) -> ApiKey:
        """生成 API Key（可选绑定 user_id）"""
        return self._meta_store.generate_api_key(tenant_id, project_id, user_id=user_id)

    def verify_api_key(self, key: str) -> Optional[ApiKey]:
        """验证 API Key"""
        return self._meta_store.verify_api_key(key)

    def revoke_api_key(self, key_id: str) -> bool:
        """按 key_id 吊销 API Key"""
        return self._meta_store.revoke_api_key(key_id)

    def list_api_keys(self, project_id: str) -> list[dict]:
        """列出项目下所有 API Key"""
        return self._meta_store.list_api_keys(project_id)
