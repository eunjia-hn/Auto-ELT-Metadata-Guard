{#
  no_blocked_source

  Python 오케스트레이터를 거치지 않고 누군가 `dbt run`/`dbt build`를 직접 호출하더라도
  안전망이 동작하도록, META_GUARD.BLOCKED_SOURCES 에 활성(IS_ACTIVE=TRUE) 격리 플래그가
  있는 소스에는 빌드가 실패하게 만드는 generic test.

  사용법 (sources.yml):
    tables:
      - name: orders
        tests:
          - no_blocked_source
#}
{% test no_blocked_source(model) %}

select *
from META_GUARD.BLOCKED_SOURCES b
where b.table_fqn = upper('{{ model.database }}.{{ model.schema }}.{{ model.identifier }}')
  and b.is_active = true

{% endtest %}
