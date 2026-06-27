"""
자동 원본(소스 정의) 수정 모듈

- Non-breaking 변경(컬럼 추가)
    -> dbt sources.yml 에 신규 컬럼 문서를 자동으로 추가 (= '자동으로 원본 수정 적용')
- Breaking 변경(컬럼 삭제/타입변경) 또는 데이터 누수 탐지
    -> 자동 수정하지 않고 META_GUARD.BLOCKED_SOURCES 에 플래그를 기록하여
       다운스트림 dbt 빌드를 차단(quarantine). 사람이 검토 후 명시적으로 해제해야 함.
"""
from datetime import datetime
from typing import List

from ruamel.yaml import YAML

from guard.snowflake_client import SnowflakeClient

yaml = YAML()
yaml.preserve_quotes = True
yaml.indent(mapping=2, sequence=4, offset=2)


def auto_patch_source_yml(sources_yml_path: str, source_name: str, table_name: str, added_columns: List[str]) -> bool:
    """sources.yml 에서 해당 테이블 블록을 찾아 신규 컬럼 문서를 자동 추가"""
    try:
        with open(sources_yml_path, "r", encoding="utf-8") as f:
            data = yaml.load(f)
    except FileNotFoundError:
        return False

    if not data or "sources" not in data:
        return False

    patched = False
    for source in data.get("sources", []):
        if source.get("name") != source_name:
            continue
        for tbl in source.get("tables", []):
            if tbl.get("name") != table_name:
                continue
            tbl.setdefault("columns", [])
            existing = {c["name"] for c in tbl["columns"]}
            for col in added_columns:
                if col not in existing:
                    tbl["columns"].append(
                        {
                            "name": col,
                            "description": (
                                f"[Auto-Guard] {datetime.utcnow().date()} 스키마 드리프트 감지 후 "
                                "자동 추가됨. 컬럼 설명/타입 검토 필요."
                            ),
                        }
                    )
                    patched = True

    if patched:
        with open(sources_yml_path, "w", encoding="utf-8") as f:
            yaml.dump(data, f)
    return patched


def quarantine_table(client: SnowflakeClient, table_fqn: str, reason: str):
    """문제가 탐지된 테이블을 BLOCKED 상태로 기록 -> dbt 커스텀 테스트(no_blocked_source)가
    이를 감지하여 dbt build/test 실행 시 자동으로 실패하도록 함"""
    client.execute(
        """
        MERGE INTO META_GUARD.BLOCKED_SOURCES AS tgt
        USING (SELECT %s AS TABLE_FQN, %s AS REASON) AS src
        ON tgt.TABLE_FQN = src.TABLE_FQN
        WHEN MATCHED THEN UPDATE SET REASON = src.REASON, BLOCKED_AT = CURRENT_TIMESTAMP(), IS_ACTIVE = TRUE
        WHEN NOT MATCHED THEN INSERT (TABLE_FQN, REASON, BLOCKED_AT, IS_ACTIVE)
            VALUES (src.TABLE_FQN, src.REASON, CURRENT_TIMESTAMP(), TRUE)
        """,
        (table_fqn, reason),
    )


def release_quarantine(client: SnowflakeClient, table_fqn: str):
    """이슈가 해소된 뒤 담당자가 검토 완료 시 격리를 해제"""
    client.execute(
        "UPDATE META_GUARD.BLOCKED_SOURCES SET IS_ACTIVE = FALSE WHERE TABLE_FQN = %s",
        (table_fqn,),
    )
