"""
ELT 비용 모니터링

WAREHOUSE_METERING_HISTORY 기준으로 이번 달(MTD) 사용 크레딧을 집계하고
USD 로 환산하여 예산 대비 소진율(%)을 계산합니다. (UI의 'Cost Spent %' 와 동일한 지표)
"""
from dataclasses import dataclass

from guard.snowflake_client import SnowflakeClient
from config import GuardPolicy, SnowflakeConfig


@dataclass
class CostStatus:
    warehouse: str
    credits_used_mtd: float
    cost_usd_mtd: float
    budget_usd: float
    cost_spent_pct: float


def get_cost_status(client: SnowflakeClient, sf_cfg: SnowflakeConfig, policy: GuardPolicy) -> CostStatus:
    sql = """
        SELECT COALESCE(SUM(CREDITS_USED), 0) AS CREDITS
        FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
        WHERE WAREHOUSE_NAME = %s
          AND START_TIME >= DATE_TRUNC('month', CURRENT_DATE())
    """
    row = client.query(sql, (sf_cfg.warehouse,))[0]
    credits = float(row["CREDITS"])
    cost_usd = credits * policy.credit_price_usd
    pct = (cost_usd / policy.monthly_cost_budget_usd * 100) if policy.monthly_cost_budget_usd else 0.0

    return CostStatus(
        warehouse=sf_cfg.warehouse,
        credits_used_mtd=round(credits, 2),
        cost_usd_mtd=round(cost_usd, 2),
        budget_usd=policy.monthly_cost_budget_usd,
        cost_spent_pct=round(pct, 1),
    )
