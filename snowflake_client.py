"""
Snowflake 연결 및 쿼리 실행 유틸리티
"""
from contextlib import contextmanager
from typing import Any, Dict, List, Optional, Tuple

import snowflake.connector

from config import SnowflakeConfig


class SnowflakeClient:
    def __init__(self, cfg: SnowflakeConfig):
        self.cfg = cfg
        self._conn = None

    def connect(self) -> "SnowflakeClient":
        self._conn = snowflake.connector.connect(
            account=self.cfg.account,
            user=self.cfg.user,
            password=self.cfg.password,
            role=self.cfg.role,
            warehouse=self.cfg.warehouse,
            database=self.cfg.database,
        )
        return self

    def close(self):
        if self._conn:
            self._conn.close()
            self._conn = None

    def query(self, sql: str, params: Optional[Tuple] = None) -> List[Dict[str, Any]]:
        """SELECT 류 쿼리를 실행하고 dict 리스트로 반환"""
        if self._conn is None:
            self.connect()
        cur = self._conn.cursor()
        try:
            cur.execute(sql, params)
            cols = [c[0] for c in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]
        finally:
            cur.close()

    def execute(self, sql: str, params: Optional[Tuple] = None):
        """INSERT/UPDATE/MERGE 류 DML 실행"""
        if self._conn is None:
            self.connect()
        cur = self._conn.cursor()
        try:
            cur.execute(sql, params)
        finally:
            cur.close()


@contextmanager
def get_client(cfg: SnowflakeConfig):
    client = SnowflakeClient(cfg).connect()
    try:
        yield client
    finally:
        client.close()
