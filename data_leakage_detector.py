"""
데이터 누수(leakage) / 정합성 탐지기

세 가지 패턴을 점검합니다.

1) PII 노출 누수  : 민감 컬럼(이메일/연락처/주민번호 등 패턴 매칭)이
                    마스킹 정책 없이 노출 스키마(ANALYTICS/MART/PUBLIC)에 그대로 적재되는 경우
2) 행수 이상치    : 전일 대비 row count 가 임계값 이상 급변 (중복적재/유실 의심)
3) NULL 비율 급증 : 민감/핵심 컬럼의 NULL 비율이 전일 대비 급등 (소스 매핑 단절 의심)
"""
import re
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Dict, List

from guard.snowflake_client import SnowflakeClient
from config import GuardPolicy


@dataclass
class LeakageResult:
    table_fqn: str
    pii_exposure: List[Dict[str, str]] = field(default_factory=list)
    row_count_anomaly: Dict = field(default_factory=dict)
    null_rate_spikes: List[Dict] = field(default_factory=list)
    checked_at: str = ""

    @property
    def has_findings(self) -> bool:
        return bool(self.pii_exposure or self.row_count_anomaly or self.null_rate_spikes)

    def to_dict(self):
        return asdict(self)


def _is_pii_column(column_name: str, patterns: List[str]) -> bool:
    name = column_name.lower()
    return any(re.match(p, name) for p in patterns)


def _get_pii_columns(client: SnowflakeClient, database: str, schema: str, table: str, policy: GuardPolicy) -> List[str]:
    sql = f"""
        SELECT COLUMN_NAME
        FROM {database}.INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s
    """
    columns = [r["COLUMN_NAME"] for r in client.query(sql, (schema, table))]
    return [c for c in columns if _is_pii_column(c, policy.pii_patterns)]


def check_pii_exposure(
    client: SnowflakeClient, database: str, schema: str, table: str, policy: GuardPolicy, pii_columns: List[str]
) -> List[Dict[str, str]]:
    """노출 스키마에 마스킹 정책이 적용되지 않은 민감 컬럼이 있는지 점검"""
    if schema.upper() not in [s.upper() for s in policy.exposed_schemas] or not pii_columns:
        return []

    policy_sql = """
        SELECT REF_COLUMN_NAME
        FROM SNOWFLAKE.ACCOUNT_USAGE.POLICY_REFERENCES
        WHERE REF_DATABASE_NAME = %s AND REF_SCHEMA_NAME = %s AND REF_ENTITY_NAME = %s
          AND POLICY_KIND = 'MASKING_POLICY'
    """
    try:
        masked = {r["REF_COLUMN_NAME"] for r in client.query(policy_sql, (database, schema, table))}
    except Exception:
        # ACCOUNT_USAGE 조회 권한이 없는 환경에서는 보수적으로 '미적용'으로 간주
        masked = set()

    return [
        {"column": c, "table": f"{database}.{schema}.{table}", "risk": "PII_NO_MASKING_POLICY"}
        for c in pii_columns
        if c not in masked
    ]


def check_row_count_anomaly(client: SnowflakeClient, database: str, schema: str, table: str, policy: GuardPolicy) -> Dict:
    table_fqn = f"{database}.{schema}.{table}"
    today_count = client.query(f"SELECT COUNT(*) AS ROW_COUNT FROM {database}.{schema}.{table}")[0]["ROW_COUNT"]

    try:
        prev_rows = client.query(
            "SELECT ROW_COUNT FROM META_GUARD.ROW_COUNT_HISTORY WHERE TABLE_FQN = %s "
            "ORDER BY CHECKED_AT DESC LIMIT 1",
            (table_fqn,),
        )
    except Exception:
        prev_rows = []

    client.execute(
        "INSERT INTO META_GUARD.ROW_COUNT_HISTORY (TABLE_FQN, ROW_COUNT, CHECKED_AT) "
        "VALUES (%s, %s, CURRENT_TIMESTAMP())",
        (table_fqn, today_count),
    )

    if not prev_rows or prev_rows[0]["ROW_COUNT"] == 0:
        return {}

    prev_count = prev_rows[0]["ROW_COUNT"]
    drift_pct = abs(today_count - prev_count) / prev_count * 100
    if drift_pct >= policy.row_count_drift_threshold_pct:
        return {
            "table": table_fqn,
            "previous_count": prev_count,
            "current_count": today_count,
            "drift_pct": round(drift_pct, 1),
        }
    return {}


def check_null_rate_spikes(
    client: SnowflakeClient, database: str, schema: str, table: str, columns: List[str], policy: GuardPolicy
) -> List[Dict]:
    table_fqn = f"{database}.{schema}.{table}"
    findings = []
    for col in columns:
        row = client.query(
            f"SELECT COUNT(*) AS TOTAL, COUNT_IF({col} IS NULL) AS NULLS FROM {database}.{schema}.{table}"
        )[0]
        if row["TOTAL"] == 0:
            continue
        null_rate = row["NULLS"] / row["TOTAL"] * 100

        try:
            prev = client.query(
                "SELECT NULL_RATE FROM META_GUARD.NULL_RATE_HISTORY "
                "WHERE TABLE_FQN = %s AND COLUMN_NAME = %s ORDER BY CHECKED_AT DESC LIMIT 1",
                (table_fqn, col),
            )
        except Exception:
            prev = []

        client.execute(
            "INSERT INTO META_GUARD.NULL_RATE_HISTORY (TABLE_FQN, COLUMN_NAME, NULL_RATE, CHECKED_AT) "
            "VALUES (%s, %s, %s, CURRENT_TIMESTAMP())",
            (table_fqn, col, null_rate),
        )

        if prev:
            spike = null_rate - prev[0]["NULL_RATE"]
            if spike >= policy.null_rate_spike_threshold_pct:
                findings.append(
                    {
                        "column": col,
                        "before_pct": round(prev[0]["NULL_RATE"], 1),
                        "after_pct": round(null_rate, 1),
                        "spike_pct": round(spike, 1),
                    }
                )
    return findings


def detect_leakage(client: SnowflakeClient, database: str, schema: str, table: str, policy: GuardPolicy) -> LeakageResult:
    table_fqn = f"{database}.{schema}.{table}"
    pii_columns = _get_pii_columns(client, database, schema, table, policy)

    pii = check_pii_exposure(client, database, schema, table, policy, pii_columns)
    row_anomaly = check_row_count_anomaly(client, database, schema, table, policy)
    null_spikes = check_null_rate_spikes(client, database, schema, table, pii_columns, policy)

    return LeakageResult(
        table_fqn=table_fqn,
        pii_exposure=pii,
        row_count_anomaly=row_anomaly,
        null_rate_spikes=null_spikes,
        checked_at=datetime.utcnow().isoformat(),
    )
