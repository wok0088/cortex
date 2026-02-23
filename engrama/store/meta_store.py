"""
SQLite 元数据存储

管理租户（Tenant）、项目（Project）和 API Key 的元信息。
使用线程级连接管理，确保并发安全。
"""

import hashlib
import os
import secrets
import sqlite3
import threading
from datetime import datetime, timezone
from typing import Optional

from engrama import config
from engrama.logger import get_logger
from engrama.models import ApiKey, Project, Tenant

logger = get_logger(__name__)


def _hash_key(key: str) -> str:
    """计算 API Key 的 SHA-256 哈希值"""
    return hashlib.sha256(key.encode()).hexdigest()


def _extract_key_id(key: str) -> str:
    """从完整 Key 中提取短标识（前 12 字符，如 'eng_Ab3xYz8w'）"""
    return key[:12]


class MetaStore:
    """
    SQLite 元数据存储

    管理 Engrama 的组织层级：Tenant → Project → API Key。
    使用线程级连接池确保并发安全。
    """

    def __init__(self, db_path: Optional[str] = None):
        """
        初始化 SQLite 数据库连接并创建表

        Args:
            db_path: 数据库文件路径，默认使用配置值
        """
        self._db_path = db_path or str(config.SQLITE_DB_PATH)
        os.makedirs(os.path.dirname(self._db_path), exist_ok=True)
        self._local = threading.local()
        self._init_tables()

    def _get_conn(self) -> sqlite3.Connection:
        """获取当前线程的数据库连接（线程安全）"""
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(self._db_path)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=5000")
            self._local.conn = conn
        return conn

    def _init_tables(self) -> None:
        """创建数据库表"""
        conn = self._get_conn()
        try:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS tenants (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS projects (
                    id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (tenant_id) REFERENCES tenants(id)
                );

                CREATE TABLE IF NOT EXISTS api_keys (
                    key_id TEXT PRIMARY KEY,
                    key_hash TEXT NOT NULL UNIQUE,
                    tenant_id TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    user_id TEXT DEFAULT NULL,
                    created_at TEXT NOT NULL,
                    is_active INTEGER NOT NULL DEFAULT 1,
                    FOREIGN KEY (tenant_id) REFERENCES tenants(id),
                    FOREIGN KEY (project_id) REFERENCES projects(id)
                );

                CREATE INDEX IF NOT EXISTS idx_projects_tenant ON projects(tenant_id);
                CREATE INDEX IF NOT EXISTS idx_api_keys_tenant ON api_keys(tenant_id);
                CREATE INDEX IF NOT EXISTS idx_api_keys_project ON api_keys(project_id);
                CREATE INDEX IF NOT EXISTS idx_api_keys_hash ON api_keys(key_hash);
            """)
            conn.commit()
            logger.info("数据库表初始化完成: %s", self._db_path)
        except Exception as e:
            logger.error("数据库初始化失败: %s", e)
            raise

    # ----------------------------------------------------------
    # 租户管理
    # ----------------------------------------------------------

    def create_tenant(self, name: str) -> Tenant:
        """注册新租户"""
        tenant = Tenant(name=name)
        conn = self._get_conn()
        conn.execute(
            "INSERT INTO tenants (id, name, created_at) VALUES (?, ?, ?)",
            (tenant.id, tenant.name, tenant.created_at.isoformat()),
        )
        conn.commit()
        logger.info("注册租户: id=%s, name=%s", tenant.id, tenant.name)
        return tenant

    def get_tenant(self, tenant_id: str) -> Optional[Tenant]:
        """获取租户信息"""
        conn = self._get_conn()
        row = conn.execute(
            "SELECT id, name, created_at FROM tenants WHERE id = ?",
            (tenant_id,),
        ).fetchone()
        if row is None:
            return None
        return Tenant(
            id=row["id"],
            name=row["name"],
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    def list_tenants(self) -> list[Tenant]:
        """列出所有租户"""
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT id, name, created_at FROM tenants ORDER BY created_at DESC"
        ).fetchall()
        return [
            Tenant(
                id=row["id"],
                name=row["name"],
                created_at=datetime.fromisoformat(row["created_at"]),
            )
            for row in rows
        ]

    def delete_tenant(self, tenant_id: str) -> bool:
        """
        删除租户（级联吊销所有 Key + 删除所有项目 + 删除租户）

        注意：不清理 ChromaDB 向量数据，仅通过 API Key 失效让数据"不可访问"，
        作为误删保护机制。
        """
        conn = self._get_conn()

        # 验证租户存在
        if self.get_tenant(tenant_id) is None:
            return False

        # 级联吊销所有 API Key
        conn.execute("UPDATE api_keys SET is_active = 0 WHERE tenant_id = ?", (tenant_id,))
        revoked_keys = conn.execute(
            "SELECT key_id FROM api_keys WHERE tenant_id = ?", (tenant_id,)
        ).fetchall()
        for row in revoked_keys:
            logger.info("级联吊销 API Key: key_id=%s (租户删除)", row["key_id"])

        # 删除所有项目
        conn.execute("DELETE FROM projects WHERE tenant_id = ?", (tenant_id,))

        # 删除租户
        cursor = conn.execute("DELETE FROM tenants WHERE id = ?", (tenant_id,))
        conn.commit()

        deleted = cursor.rowcount > 0
        if deleted:
            logger.info("删除租户: id=%s", tenant_id)
        return deleted

    # ----------------------------------------------------------
    # 项目管理
    # ----------------------------------------------------------

    def create_project(self, tenant_id: str, name: str) -> Project:
        """创建项目"""
        if self.get_tenant(tenant_id) is None:
            raise ValueError(f"租户不存在: {tenant_id}")

        project = Project(tenant_id=tenant_id, name=name)
        conn = self._get_conn()
        conn.execute(
            "INSERT INTO projects (id, tenant_id, name, created_at) VALUES (?, ?, ?, ?)",
            (project.id, project.tenant_id, project.name, project.created_at.isoformat()),
        )
        conn.commit()
        logger.info("创建项目: id=%s, tenant=%s, name=%s", project.id, tenant_id, project.name)
        return project

    def get_project(self, project_id: str) -> Optional[Project]:
        """获取项目信息"""
        conn = self._get_conn()
        row = conn.execute(
            "SELECT id, tenant_id, name, created_at FROM projects WHERE id = ?",
            (project_id,),
        ).fetchone()
        if row is None:
            return None
        return Project(
            id=row["id"],
            tenant_id=row["tenant_id"],
            name=row["name"],
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    def list_projects(self, tenant_id: str) -> list[Project]:
        """列出租户下的所有项目"""
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT id, tenant_id, name, created_at FROM projects WHERE tenant_id = ? ORDER BY created_at DESC",
            (tenant_id,),
        ).fetchall()
        return [
            Project(
                id=row["id"],
                tenant_id=row["tenant_id"],
                name=row["name"],
                created_at=datetime.fromisoformat(row["created_at"]),
            )
            for row in rows
        ]

    def delete_project(self, project_id: str, tenant_id: str) -> bool:
        """
        删除项目（级联吊销关联的 API Key）

        Args:
            project_id: 项目 ID
            tenant_id: 租户 ID，用于验证项目归属

        注意：不清理 ChromaDB 向量数据，仅通过 API Key 失效让数据"不可访问"。
        """
        conn = self._get_conn()

        # 验证项目存在且属于指定租户
        project = self.get_project(project_id)
        if project is None or project.tenant_id != tenant_id:
            return False

        # 级联吊销关联的 API Key
        conn.execute("UPDATE api_keys SET is_active = 0 WHERE project_id = ?", (project_id,))
        cursor = conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))
        conn.commit()
        deleted = cursor.rowcount > 0
        if deleted:
            logger.info("删除项目: id=%s, tenant=%s", project_id, tenant_id)
        return deleted

    # ----------------------------------------------------------
    # API Key 管理
    # ----------------------------------------------------------

    def generate_api_key(self, tenant_id: str, project_id: str, user_id: str = None) -> ApiKey:
        """
        生成 API Key

        生成原始 Key → 计算 SHA-256 → 只存 key_id + key_hash，不存明文。

        Args:
            tenant_id: 租户 ID
            project_id: 项目 ID
            user_id: 可选，绑定的用户 ID。为 None 时生成项目级 Key（B 端），
                     有值时生成用户级 Key（C 端，user_id 自动绑定）
        """
        if self.get_tenant(tenant_id) is None:
            raise ValueError(f"租户不存在: {tenant_id}")

        project = self.get_project(project_id)
        if project is None or project.tenant_id != tenant_id:
            raise ValueError(f"项目不存在或不属于该租户: {project_id}")

        key_value = f"eng_{secrets.token_urlsafe(32)}"
        key_id = _extract_key_id(key_value)
        key_hash = _hash_key(key_value)

        api_key = ApiKey(
            key=key_value,
            key_id=key_id,
            key_hash=key_hash,
            tenant_id=tenant_id,
            project_id=project_id,
            user_id=user_id,
        )

        conn = self._get_conn()
        conn.execute(
            "INSERT INTO api_keys (key_id, key_hash, tenant_id, project_id, user_id, created_at, is_active) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (api_key.key_id, api_key.key_hash, api_key.tenant_id, api_key.project_id, api_key.user_id, api_key.created_at.isoformat(), 1),
        )
        conn.commit()
        return api_key

    def verify_api_key(self, key: str) -> Optional[ApiKey]:
        """验证 API Key：输入原始 Key → 算哈希 → 按哈希查询"""
        key_hash = _hash_key(key)
        conn = self._get_conn()
        row = conn.execute(
            "SELECT key_id, key_hash, tenant_id, project_id, user_id, created_at, is_active FROM api_keys WHERE key_hash = ? AND is_active = 1",
            (key_hash,),
        ).fetchone()
        if row is None:
            return None
        return ApiKey(
            key=key,
            key_id=row["key_id"],
            key_hash=row["key_hash"],
            tenant_id=row["tenant_id"],
            project_id=row["project_id"],
            user_id=row["user_id"],
            created_at=datetime.fromisoformat(row["created_at"]),
            is_active=bool(row["is_active"]),
        )

    def revoke_api_key(self, key_id: str) -> bool:
        """按 key_id 吊销 API Key"""
        conn = self._get_conn()
        cursor = conn.execute(
            "UPDATE api_keys SET is_active = 0 WHERE key_id = ? AND is_active = 1", (key_id,)
        )
        conn.commit()
        revoked = cursor.rowcount > 0
        if revoked:
            logger.info("吊销 API Key: key_id=%s", key_id)
        return revoked

    def list_api_keys(self, project_id: str) -> list[dict]:
        """
        列出项目下所有 API Key（不暴露哈希和原始值）

        Returns:
            包含 key_id, tenant_id, project_id, user_id, created_at, is_active 的字典列表
        """
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT key_id, tenant_id, project_id, user_id, created_at, is_active FROM api_keys WHERE project_id = ? ORDER BY created_at DESC",
            (project_id,),
        ).fetchall()
        return [
            {
                "key_id": row["key_id"],
                "tenant_id": row["tenant_id"],
                "project_id": row["project_id"],
                "user_id": row["user_id"],
                "created_at": row["created_at"],
                "is_active": bool(row["is_active"]),
            }
            for row in rows
        ]
