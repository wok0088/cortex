"""
共享测试 Fixtures

提取各测试文件中重复的 tmp_dir fixture，统一在此定义。
"""

import os
import shutil
import tempfile
import pytest

from engrama import config
from qdrant_client import QdrantClient
from psycopg_pool import ConnectionPool
from engrama.store.qdrant_store import COLLECTION_NAME

@pytest.fixture
def tmp_dir(tmp_path):
    return str(tmp_path)

@pytest.fixture(scope="session")
def db_pool():
    """全局共享的 PostgreSQL 连接池"""
    is_test_env = os.getenv("ENGRAMA_ENV") == "test"
    is_test_db = "test" in config.PG_URI.lower()
    
    # 终极安全锁：禁止在非测试环境清理数据
    if not (is_test_env or is_test_db):
        pytest.exit(
            "🚨 危险操作拦截！\n"
            "检测到当前运行环境未明确标记为测试环境 (ENGRAMA_ENV!=test)，且数据库名不含 'test'。\n"
            "为防止误删生产数据，测试已被强制终止！\n"
            "👉 本地跑测试请使用命令: ENGRAMA_ENV=test pytest"
        )
        
    pool = ConnectionPool(config.PG_URI, min_size=1, max_size=5, open=True)
    yield pool
    pool.close()

@pytest.fixture(scope="session")
def qdrant():
    """全局共享的 Qdrant 客户端"""
    client = QdrantClient(
        url=f"http://{config.QDRANT_HOST}:{config.QDRANT_PORT}",
        api_key=config.QDRANT_API_KEY if config.QDRANT_API_KEY else None
    )
    yield client
    client.close()

@pytest.fixture(scope="session", autouse=True)
def ensure_qdrant_collection(qdrant):
    """确保 Qdrant Collection 在测试会话中存在（只创建一次，避免 94 次重建）"""
    from qdrant_client.http import models as rest
    # 先尝试删除旧的，确保干净状态
    try:
        qdrant.delete_collection(COLLECTION_NAME)
    except Exception:
        pass
    qdrant.create_collection(
        collection_name=COLLECTION_NAME,
        vectors_config=rest.VectorParams(
            size=config.EMBEDDING_VECTOR_SIZE,
            distance=rest.Distance.COSINE
        )
    )
    # 建索引（整个测试会话只做一次）
    for field in ["tenant_id", "project_id", "user_id", "memory_type", "session_id"]:
        qdrant.create_payload_index(
            collection_name=COLLECTION_NAME,
            field_name=field,
            field_schema=rest.PayloadSchemaType.KEYWORD
        )
    yield


@pytest.fixture(autouse=True)
def clean_databases(db_pool, qdrant):
    """每次测试前清理数据库，保留 Collection 结构和索引，只清除数据点"""
    # 1. 清理 PostgreSQL 数据
    with db_pool.connection() as conn:
        with conn.cursor() as cur:
            # 使用 CASCADE 级联清理，忽略尚未建表的错误
            try:
                cur.execute("TRUNCATE TABLE memory_fragments, projects, api_keys, tenants CASCADE")
                conn.commit()
            except Exception:
                conn.rollback()

    # 2. 清理 Qdrant Collection 中的所有点（保留结构和索引）
    from qdrant_client.http import models as rest
    try:
        # 滚动获取所有点的 ID 并批量删除
        all_ids = []
        offset = None
        while True:
            records, next_offset = qdrant.scroll(
                collection_name=COLLECTION_NAME,
                limit=1000,
                offset=offset,
                with_payload=False,
                with_vectors=False,
            )
            if not records:
                break
            all_ids.extend([r.id for r in records])
            if next_offset is None:
                break
            offset = next_offset
        if all_ids:
            qdrant.delete(
                collection_name=COLLECTION_NAME,
                points_selector=rest.PointIdsList(points=all_ids),
            )
    except Exception:
        pass

    yield

@pytest.fixture(scope="session", autouse=True)
def setup_test_config():
    """全局设置测试配置，替换原有的 monkeypatch 机制"""
    d = tempfile.mkdtemp()
    config.DATA_DIR = d
    config.ADMIN_TOKEN = ""
    yield
    shutil.rmtree(d, ignore_errors=True)
