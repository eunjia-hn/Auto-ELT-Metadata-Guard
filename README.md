# Auto ELT Metadata Guard

스키마 변경(drift)과 데이터 누수(leakage)를 **dbt 실행 전에** 사전 탐지하여
정합성 오류가 다운스트림으로 전파되기 전에 차단하고, 안전한 변경(컬럼 추가 등)은
**자동으로 원본(소스) 정의에 반영**하는 메타데이터 가드입니다.

## 구성 요소
| 모듈 | 역할 |
|---|---|
| `guard/schema_drift_detector.py` | INFORMATION_SCHEMA 기준 baseline 대비 컬럼 추가/삭제/타입변경 탐지 |
| `guard/data_leakage_detector.py` | PII 마스킹 미적용 노출, 행수 이상치, NULL 급증 탐지 |
| `guard/cost_monitor.py` | 웨어하우스 월간 크레딧 사용량 → 예산 대비 소진율(%) 계산 |
| `guard/auto_remediation.py` | 안전한 변경은 `sources.yml` 자동 패치 / 위험 변경은 소스 격리(quarantine) |
| `guard/slack_notifier.py` | 점검 결과를 Slack Block Kit 메시지로 발송 |
| `guard/orchestrator.py` | 위 모듈을 조합해 테이블 단위 점검 → 조치 → 알림까지 한 번에 실행 |
| `dbt_integration/macros/test_no_blocked_source.sql` | dbt 레벨 안전망 (격리된 소스면 `dbt build` 자체가 실패) |

## 설치
```bash
pip install -r requirements.txt
cp .env.example .env   # 값 채운 뒤 사용
```
Snowflake에 메타 스키마를 먼저 생성합니다.
```bash
snowsql -f sql/meta_guard_setup.sql
```

## 실행 방법
```bash
# 1) 모니터링 대상 전체 점검 (.env 의 GUARD_MONITORED_TABLES 사용)
python run_guard.py --mode pre-run

# 2) 특정 테이블만 점검
python run_guard.py --table RAW.SALES.ORDERS

# 3) dbt 와 묶어서 실행 (CI/CD, Airflow, dbt Cloud job 등에서 호출)
bash scripts/guarded_dbt_run.sh

# 4) Breaking 변경을 사람이 검토 완료한 뒤 baseline/격리 해제
python run_guard.py --accept RAW.SALES.ORDERS
```

## 동작 정책
- **컬럼 추가** (non-breaking) → 자동으로 `sources.yml`에 컬럼 문서 추가 + baseline 갱신, Slack 알림(✅)
- **컬럼 삭제/타입 변경** (breaking) → `META_GUARD.BLOCKED_SOURCES`에 격리 플래그 기록, baseline은 갱신하지 않음, Slack 알림(🚨)
- **PII 마스킹 미적용 노출 / 행수 이상치 / NULL 급증** → 동일하게 격리 + Slack 알림(🚨)
- 격리된 테이블에 의존하는 모델은 `no_blocked_source` dbt 테스트에 의해 **Python 오케스트레이터를 거치지 않고 `dbt build`를 직접 호출해도** 실패합니다 (이중 안전망).

## 확장 포인트
- `config.py`의 `GuardPolicy` 임계값(행수 변동률, NULL 급증률, PII 패턴, 비용 예산)을 조직 정책에 맞게 조정
- Slack 알림을 채널별로 분리하려면 `SlackConfig`에 라우팅 로직 추가
- 더 정교한 이상치 탐지(표준편차 기반, 계절성 고려)가 필요하면 `data_leakage_detector.py`의 단순 임계값 비교를 통계 모델로 교체
