#!/usr/bin/env bash
# Auto ELT Metadata Guard 를 적용한 dbt 실행 래퍼
# CI/CD, dbt Cloud job, Airflow 등에서 `dbt build` 대신 이 스크립트를 호출
set -euo pipefail

echo "▶ [1/3] Pre-run Metadata Guard 점검 (스키마 드리프트 / 데이터 누수 / 비용)..."
python run_guard.py --mode pre-run

echo "▶ [2/3] dbt build 실행..."
dbt build

echo "▶ [3/3] Post-run 점검 (비용 재확인)..."
python run_guard.py --mode post-run

echo "✅ 전체 파이프라인 완료"
