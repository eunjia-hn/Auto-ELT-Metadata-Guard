"""
Slack 알림 모듈 (Incoming Webhook 기반 Block Kit 메시지)
"""
import requests

from config import SlackConfig


def _section(text: str) -> dict:
    return {"type": "section", "text": {"type": "mrkdwn", "text": text}}


def build_guard_message(
    table_fqn: str,
    drift_summary: str,
    leakage_summary: str,
    cost_summary: str,
    action_taken: str,
    is_blocked: bool,
) -> dict:
    header_emoji = "🚨" if is_blocked else "✅"
    blocks = [
        _section(f"{header_emoji} *Auto ELT Metadata Guard* — `{table_fqn}`"),
        {"type": "divider"},
        _section(f"*스키마 드리프트*\n{drift_summary}"),
        _section(f"*데이터 누수/정합성*\n{leakage_summary}"),
        _section(f"*비용 현황*\n{cost_summary}"),
        {"type": "divider"},
        _section(f"*조치 내역*\n{action_taken}"),
    ]
    return {"blocks": blocks}


def send_slack_alert(slack_cfg: SlackConfig, message: dict):
    if not slack_cfg.webhook_url:
        print("[WARN] SLACK_WEBHOOK_URL 미설정 - 알림을 건너뜁니다.")
        return
    resp = requests.post(slack_cfg.webhook_url, json=message, timeout=10)
    resp.raise_for_status()
