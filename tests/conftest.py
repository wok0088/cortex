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

@pytest.fixture(autouse=True)
def clean_databases():
    """每次测试前清理数据库，确保真正的隔离"""
    
    # =========================================================================
    # 🚨 终极安全锁 (Safe-Guard)：防止手滑在生产环境跑 pytest 导致删库跑路！
    # =========================================================================
    is_test_env = os.getenv("ENGRAMA_ENV") == "test"
    is_test_db = "test" in config.PG_URI.lower()
    
    # 除非明确配置了 ENGRAMA_ENV=test，或者连接的数据库名字里明确带有 test，否则禁止清理数据
    if not (is_test_env or is_test_db):
        pytest.exit(
            "🚨 危险操作拦截！\n"
            "检测到当前运行环境未明确标记为测试环境 (ENGRAMA_ENV!=test)，且数据库名不含 'test'。\n"
            "为防止误删生产数据，测试已被强制终止！\n"
            "👉 本地跑测试请使用命令: ENGRAMA_ENV=test pytest"
        )
    
    # 1. 清理 PostgreSQL 数据
    pool = ConnectionPool(config.PG_URI, min_size=1, max_size=1, open=True)
    try:
        with pool.connection() as conn:
            with conn.cursor() as cur:
                # 使用 CASCADE 级联清理，忽略尚未建表的错误
                try:
                    cur.execute("TRUNCATE TABLE memory_fragments, projects, api_keys, tenants CASCADE")
                    conn.commit()
                except Exception:
                    conn.rollback()
    finally:
        pool.close()

    # 2. 清理 Qdrant Collection
    qclient = QdrantClient(
        url=f"http://{config.QDRANT_HOST}:{config.QDRANT_PORT}",
        api_key=config.QDRANT_API_KEY if config.QDRANT_API_KEY else None
    )
    try:
        qclient.delete_collection(collection_name=COLLECTION_NAME)
    except Exception:
        pass

    yield

@pytest.fixture
def tmp_dir():
    """创建临时目录，测试后自动清理"""
    d = tempfile.mkdtemp()
    yield d
    shutil.rmtree(d, ignore_errors=True)
