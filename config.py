"""
Auto ELT Metadata Guard - 설정 모듈
환경변수를 통해 Snowflake / Slack 접속 정보 및 가드 정책(임계값)을 로드합니다.
"""
import os
from dataclasses import dataclass, field
from typing import List
from dotenv import load_dotenv

load_dotenv()


@dataclass
class SnowflakeConfig:
    account: str = os.getenv("SNOWFLAKE_ACCOUNT", "")
    user: str = os.getenv("SNOWFLAKE_USER", "")
    password: str = os.getenv("SNOWFLAKE_PASSWORD", "")
    role: str = os.getenv("SNOWFLAKE_ROLE", "TRANSFORMER")
    warehouse: str = os.getenv("SNOWFLAKE_WAREHOUSE", "ELT_WH")
    database: str = os.getenv("SNOWFLAKE_DATABASE", "ANALYTICS")


@dataclass
class GuardPolicy:
    # 민감정보로 간주할 컬럼명 패턴 (정규식, lower-case 기준 매칭)
    pii_patterns: List[str] = field(default_factory=lambda: [
        r".*email.*", r".*phone.*", r".*ssn.*", r".*card_?no.*",
        r".*resident.*number.*", r".*address.*", r".*birth.*date.*",
    ])
    # 마스킹 정책 적용이 강제되는 '노출' 스키마 (외부/분석 레이어)
    exposed_schemas: List[str] = field(default_factory=lambda: ["ANALYTICS", "MART", "PUBLIC"])
    # 행수 변동 허용 임계값 (전일 대비 %) - 초과 시 중복적재/유실 의심
    row_count_drift_threshold_pct: float = float(os.getenv("ROW_COUNT_DRIFT_THRESHOLD_PCT", 30))
    # NULL 비율 급증 허용 임계값 (전일 대비 %p)
    null_rate_spike_threshold_pct: float = float(os.getenv("NULL_RATE_SPIKE_THRESHOLD_PCT", 15))
    # 월 비용 예산 (USD) - Cost Spent % 계산용
    monthly_cost_budget_usd: float = float(os.getenv("MONTHLY_COST_BUDGET_USD", 5000))
    credit_price_usd: float = float(os.getenv("SNOWFLAKE_CREDIT_PRICE_USD", 3.0))


@dataclass
class SlackConfig:
    webhook_url: str = os.getenv("SLACK_WEBHOOK_URL", "")
    channel: str = os.getenv("SLACK_CHANNEL", "#data-alerts")


@dataclass
class PathConfig:
    baseline_dir: str = os.getenv("GUARD_BASELINE_DIR", "./baseline")
    sources_yml_path: str = os.getenv(
        "DBT_SOURCES_YML", "./dbt_integration/models/staging/sources_example.yml"
    )


SNOWFLAKE = SnowflakeConfig()
POLICY = GuardPolicy()
SLACK = SlackConfig()
PATHS = PathConfig()

MONITORED_TABLES = [
    t.strip() for t in os.getenv("GUARD_MONITORED_TABLES", "").split(",") if t.strip()
]
