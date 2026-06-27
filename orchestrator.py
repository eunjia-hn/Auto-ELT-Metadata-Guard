"""
Auto ELT Metadata Guard - 오케스트레이터

dbt run 전(pre-run)에 호출되어 스키마 드리프트, 데이터 누수, 비용을 점검하고
필요시 자동 수정(non-breaking) 또는 빌드 차단(breaking/leakage)을 수행한 뒤
Slack 으로 결과를 알립니다.
"""
from typing import List

from config import SNOWFLAKE, POLICY, SLACK, PATHS, MONITORED_TABLES
from guard.snowflake_client import get_client
from guard.schema_drift_detector import detect_drift
from guard.data_leakage_detector import detect_leakage
from guard.cost_monitor import get_cost_status
from guard.auto_remediation import auto_patch_source_yml, quarantine_table
from guard.slack_notifier import build_guard_message, send_slack_alert


def _fmt_drift(drift) -> str:
    if not drift.added_columns and not drift.dropped_columns and not drift.type_changes:
        return "변경 없음"
    parts = []
    if drift.added_columns:
        parts.append(f"➕ 추가: {', '.join(drift.added_columns)}")
    if drift.dropped_columns:
        parts.append(f"⛔ 삭제: {', '.join(drift.dropped_columns)}")
    if drift.type_changes:
        tc = ", ".join(f"{c['column']}({c['before']}→{c['after']})" for c in drift.type_changes)
        parts.append(f"⚠️ 타입변경: {tc}")
    return "\n".join(parts)


def _fmt_leakage(leak) -> str:
    if not leak.has_findings:
        return "이상 없음"
    parts = []
    if leak.pii_exposure:
        cols = ", ".join(p["column"] for p in leak.pii_exposure)
        parts.append(f"🔓 마스킹 미적용 PII 노출: {cols}")
    if leak.row_count_anomaly:
        ra = leak.row_count_anomaly
        parts.append(f"📊 행수 이상: {ra['previous_count']:,} → {ra['current_count']:,} ({ra['drift_pct']}%)")
    for s in leak.null_rate_spikes:
        parts.append(f"🕳 NULL 급증: {s['column']} {s['before_pct']}%→{s['after_pct']}% (+{s['spike_pct']}%p)")
    return "\n".join(parts)


def run_guard(database: str, schema: str, table: str, source_name: str = None) -> bool:
    """
    단일 테이블에 대해 가드를 실행.

    Returns:
        True  -> 정상 (다운스트림 dbt 빌드 진행 가능)
        False -> 차단됨 (CI/파이프라인을 중단해야 함)
    """
    table_fqn = f"{database}.{schema}.{table}"
    with get_client(SNOWFLAKE) as client:
        drift = detect_drift(client, PATHS.baseline_dir, database, schema, table)
        leak = detect_leakage(client, database, schema, table, POLICY)
        cost = get_cost_status(client, SNOWFLAKE, POLICY)

        is_blocked = drift.is_breaking or leak.has_findings
        action_taken = []

        if drift.is_breaking:
            quarantine_table(client, table_fqn, reason="schema_breaking_change")
            action_taken.append("🚫 Breaking 스키마 변경 → 소스 격리(quarantine) 및 dbt 빌드 차단")
        elif drift.added_columns and source_name:
            patched = auto_patch_source_yml(PATHS.sources_yml_path, source_name, table, drift.added_columns)
            if patched:
                action_taken.append(f"🔧 신규 컬럼 {len(drift.added_columns)}개 sources.yml 자동 반영")

        if leak.has_findings:
            quarantine_table(client, table_fqn, reason="data_leakage_detected")
            action_taken.append("🚫 데이터 누수/정합성 이슈 → 소스 격리 및 다운스트림 모델 빌드 차단")

        if not action_taken:
            action_taken.append("정상 — 조치 불필요")

        message = build_guard_message(
            table_fqn=table_fqn,
            drift_summary=_fmt_drift(drift),
            leakage_summary=_fmt_leakage(leak),
            cost_summary=(
                f"{cost.credits_used_mtd} credits / ${cost.cost_usd_mtd} "
                f"(예산 대비 {cost.cost_spent_pct}%)"
            ),
            action_taken="\n".join(action_taken),
            is_blocked=is_blocked,
        )

        # 알림 노이즈를 줄이기 위해 '변경/이슈가 있을 때만' Slack 발송 (정책에 따라 조정 가능)
        if is_blocked or drift.added_columns or leak.has_findings:
            send_slack_alert(SLACK, message)

        return not is_blocked


def run_all(tables: List[str] = None) -> int:
    """CLI 진입점에서 호출. 차단된 테이블이 하나라도 있으면 종료코드 1 반환 (CI 중단용)"""
    targets = tables or MONITORED_TABLES
    if not targets:
        print("[ERROR] 점검할 테이블이 설정되지 않았습니다 (GUARD_MONITORED_TABLES 확인)")
        return 1

    all_ok = True
    for fqn in targets:
        db, sch, tbl = fqn.split(".")
        ok = run_guard(db, sch, tbl, source_name=sch.lower())
        print(f"[{'OK' if ok else 'BLOCKED'}] {fqn}")
        all_ok = all_ok and ok

    return 0 if all_ok else 1
