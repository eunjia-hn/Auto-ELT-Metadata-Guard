"""
스키마 드리프트(변경) 탐지기

INFORMATION_SCHEMA.COLUMNS 를 기준 스냅샷(baseline, JSON 파일)과 비교하여
컬럼 추가 / 삭제 / 타입변경을 탐지합니다.

- 컬럼 추가              -> Non-breaking. 자동으로 baseline 갱신 + sources.yml 자동 패치 대상
- 컬럼 삭제 / 타입 변경    -> Breaking. baseline 을 갱신하지 않고 차단(quarantine) 대상으로 분류
                            (담당자가 검토 후 run_guard.py --accept 로 직접 해제해야 함)
"""
import json
import os
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Dict, List

from guard.snowflake_client import SnowflakeClient


@dataclass
class DriftResult:
    table_fqn: str
    added_columns: List[str]
    dropped_columns: List[str]
    type_changes: List[Dict[str, str]]
    is_breaking: bool
    checked_at: str

    def to_dict(self):
        return asdict(self)


def _baseline_path(baseline_dir: str, table_fqn: str) -> str:
    safe_name = table_fqn.replace(".", "__")
    return os.path.join(baseline_dir, f"{safe_name}.json")


def fetch_current_schema(client: SnowflakeClient, database: str, schema: str, table: str) -> Dict[str, str]:
    sql = f"""
        SELECT COLUMN_NAME, DATA_TYPE
        FROM {database}.INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s
        ORDER BY ORDINAL_POSITION
    """
    rows = client.query(sql, (schema, table))
    if not rows:
        raise ValueError(f"테이블을 찾을 수 없습니다: {database}.{schema}.{table}")
    return {r["COLUMN_NAME"]: r["DATA_TYPE"] for r in rows}


def load_baseline(baseline_dir: str, table_fqn: str) -> Dict[str, str]:
    path = _baseline_path(baseline_dir, table_fqn)
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f).get("columns", {})


def save_baseline(baseline_dir: str, table_fqn: str, columns: Dict[str, str]):
    os.makedirs(baseline_dir, exist_ok=True)
    path = _baseline_path(baseline_dir, table_fqn)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "table": table_fqn,
                "columns": columns,
                "updated_at": datetime.utcnow().isoformat(),
            },
            f,
            ensure_ascii=False,
            indent=2,
        )


def detect_drift(client: SnowflakeClient, baseline_dir: str, database: str, schema: str, table: str) -> DriftResult:
    table_fqn = f"{database}.{schema}.{table}"
    current = fetch_current_schema(client, database, schema, table)
    baseline = load_baseline(baseline_dir, table_fqn)

    if not baseline:
        # 최초 실행: baseline 이 없으므로 현재 상태를 기준으로 저장하고 정상 처리
        save_baseline(baseline_dir, table_fqn, current)
        return DriftResult(table_fqn, [], [], [], False, datetime.utcnow().isoformat())

    added = [c for c in current if c not in baseline]
    dropped = [c for c in baseline if c not in current]
    type_changes = [
        {"column": c, "before": baseline[c], "after": current[c]}
        for c in current
        if c in baseline and baseline[c] != current[c]
    ]

    is_breaking = bool(dropped) or bool(type_changes)

    if not is_breaking:
        # 컬럼 추가만 있는 경우는 안전하므로 즉시 baseline 으로 수용
        save_baseline(baseline_dir, table_fqn, current)

    return DriftResult(
        table_fqn=table_fqn,
        added_columns=added,
        dropped_columns=dropped,
        type_changes=type_changes,
        is_breaking=is_breaking,
        checked_at=datetime.utcnow().isoformat(),
    )
