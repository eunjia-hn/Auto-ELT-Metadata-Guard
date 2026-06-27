"""
CLI 진입점

사용 예:
  python run_guard.py --mode pre-run                    # 모니터링 대상 전체 테이블 점검
  python run_guard.py --table RAW.SALES.ORDERS           # 단일 테이블만 점검
  python run_guard.py --accept RAW.SALES.ORDERS          # breaking 변경 검토 완료 후
                                                          # baseline 재설정 + 격리 해제
"""
import argparse
import sys

from config import SNOWFLAKE, PATHS
from guard.orchestrator import run_all, run_guard
from guard.snowflake_client import get_client
from guard.schema_drift_detector import fetch_current_schema, save_baseline
from guard.auto_remediation import release_quarantine


def accept_change(table_fqn: str):
    db, sch, tbl = table_fqn.split(".")
    with get_client(SNOWFLAKE) as client:
        current = fetch_current_schema(client, db, sch, tbl)
        save_baseline(PATHS.baseline_dir, table_fqn, current)
        release_quarantine(client, table_fqn)
    print(f"[ACCEPTED] {table_fqn} 의 새 스키마를 baseline 으로 반영하고 격리를 해제했습니다.")


def main():
    parser = argparse.ArgumentParser(description="Auto ELT Metadata Guard")
    parser.add_argument("--mode", choices=["pre-run", "post-run"], default="pre-run")
    parser.add_argument("--table", help="단일 테이블만 점검 (DB.SCHEMA.TABLE)")
    parser.add_argument(
        "--accept", help="Breaking 변경을 검토 완료 후 baseline/격리 상태를 재설정 (DB.SCHEMA.TABLE)"
    )
    args = parser.parse_args()

    if args.accept:
        accept_change(args.accept)
        sys.exit(0)

    if args.table:
        db, sch, tbl = args.table.split(".")
        ok = run_guard(db, sch, tbl, source_name=sch.lower())
        sys.exit(0 if ok else 1)

    sys.exit(run_all())


if __name__ == "__main__":
    main()
