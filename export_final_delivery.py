"""Export a typed V1 handoff; no factual imputation or schema expansion."""
import hashlib
import json
from datetime import datetime
from pathlib import Path

from openpyxl import Workbook, load_workbook
from prepare_agent_data import META, missing, sheet

ROOT = Path(__file__).resolve().parent
OUT = ROOT / 'output-final-delivery'
NUMERIC = {'rent_monthly_sgd', 'bedrooms', 'bathrooms', 'area_sqm', 'mrt_distance_m', 'mrt_minutes_reported', 'tenant_count_reported'}
COUNTS = {'bedrooms', 'bathrooms', 'mrt_minutes_reported', 'tenant_count_reported'}
REQUIRED = {'listing_id', 'title', 'listing_url', 'rent_monthly_sgd', 'district_code', 'address'}


def main():
    source = ROOT / 'output-final-v1/rental_dataset_v1.json'
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    data = json.loads(source.read_text(encoding='utf-8'))
    rows = data['listings']
    data['schema_version'] = '1.0'
    assert len(rows) == 600 and len(rows[0]) == 30
    assert len({r['listing_id'] for r in rows}) == 600
    assert len({r['listing_url'] for r in rows}) == 600
    assert {r['listing_id'] for r in data['listing_metadata']} == {r['listing_id'] for r in rows}
    assert len(data['listing_metadata']) == 600
    districts = {r['district_code'] for r in data['district_lookup']}
    assert len(districts) == 28
    original_values = json.loads(json.dumps(rows))
    for r in rows:
        assert all(not missing(r[f]) for f in REQUIRED)
        assert isinstance(r['listing_id'], str) and r['listing_id'].isdigit()
        assert r['listing_url'].startswith('https://www.propertyguru.com.sg/listing/')
        assert r['listing_url'].endswith('-' + r['listing_id'])
        assert r['district_code'] in districts
        for f in NUMERIC:
            v = r[f]
            assert v is None or (type(v) in (int, float) and v >= 0), (r['listing_id'], f)
            if f in COUNTS and v is not None:
                assert v == int(v), (r['listing_id'], f)
                r[f] = int(v)
        datetime.fromisoformat(r['listed_date'])
        datetime.fromisoformat(r['collected_at'])
    decisions = json.loads((ROOT / 'output-final-v1/field_decisions_v1.json').read_text(encoding='utf-8'))
    reasons = {r['field']: r['reason_zh'] for r in decisions}
    contracts = []
    for table in ('listings', 'listing_metadata', 'district_lookup'):
        records = data[table]
        for f in records[0]:
            value_type = 'integer' if f in COUNTS else 'decimal' if f in NUMERIC else 'date_string' if f == 'listed_date' else 'timestamp_string' if f == 'collected_at' else 'string_array' if f == 'review_flags' else 'string'
            role = META[f]['decision_role']
            # Ingestion requirements are independent of runtime user constraints.
            required = f in REQUIRED if table == 'listings' else f == 'listing_id' if table == 'listing_metadata' else True
            nullable = f in NUMERIC and not required
            contracts.append(dict(table=table, field=f, meaning_zh=META[f]['meaning_zh'],
                                  value_type=value_type, required_for_ingestion=required, allows_null=nullable,
                                  missing_rule='null' if f in NUMERIC else 'not_allowed' if required or f in ('listed_date', 'collected_at') else 'empty_array_means_no_recorded_flags' if f == 'review_flags' else 'unknown',
                                  decision_role=role, valid_count=sum(not missing(r[f]) and r[f] != [] for r in records),
                                  null_count=sum(r[f] is None for r in records),
                                  unknown_count=sum(r[f] == 'unknown' for r in records),
                                  observed_values=sorted({r[f] for r in records if isinstance(r[f], str)}) if len({str(r[f]) for r in records}) <= 30 else 'see_data',
                                  usage_notes_zh=reasons.get(f, META[f]['meaning_zh'])))
    provenance = json.loads((ROOT / 'output-agent/provenance.json').read_text(encoding='utf-8'))
    assert {r['listing_id'] for r in provenance} == {r['listing_id'] for r in rows}
    assert len(provenance) == 600
    report = dict(schema_version='1.0', row_count=600, main_fields=30, district_count=28,
                  required_missing_count=0, duplicate_ids=0, duplicate_urls=0,
                  numeric_null_cells=sum(r[f] is None for r in rows for f in NUMERIC),
                  rows_with_review_flags=sum(bool(r['review_flags']) for r in data['listing_metadata']),
                  factual_imputations=0, deleted_records=0, source_sha256=before,
                  checks=['types', 'dates', 'unique_ids_and_urls', 'metadata_and_district_links', 'Excel_JSON_agreement', 'source_unchanged'],
                  caveat='Data integrity checks pass; missing evidence, snapshot age and review flags still limit recommendations.')
    OUT.mkdir(exist_ok=True)
    for name, obj in [('rental_data_v1.json', data), ('field_dictionary_v1.json', contracts),
                      ('source_evidence_v1.json', provenance), ('validation_report.json', report)]:
        (OUT / name).write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding='utf-8')
    wb = Workbook()
    wb.remove(wb.active)
    for table in ('listings', 'listing_metadata', 'district_lookup'):
        sheet(wb, table, data[table])
    sheet(wb, 'Read_Me', [
        dict(item='import', meaning='Import rental_data_v1.json. Workbook mirrors types: numeric missing cells are blank; categorical missing values are unknown.'),
        dict(item='joins', meaning='Join listing_metadata by listing_id and district_lookup by district_code; inspect review_flags before claiming matches.'),
        dict(item='missing', meaning='Never substitute zero/mean for missing numbers. Missing hard-constraint evidence requires confirmation.'),
        dict(item='provenance', meaning='source_evidence_v1.json is joined by listing_id. Original card text and extraction evidence are preserved.'),
        dict(item='scope', meaning='Typed V1 development handoff, not verified live inventory and not complete coverage of the Product Guide.'),
    ])
    data_path = OUT / 'NUS_Rental_Data_V1_Typed.xlsx'
    wb.save(data_path)
    dictionary_wb = Workbook()
    dictionary_wb.remove(dictionary_wb.active)
    sheet(dictionary_wb, 'Main_30_Fields', [c for c in contracts if c['table'] == 'listings'])
    sheet(dictionary_wb, 'Auxiliary_Fields', [c for c in contracts if c['table'] != 'listings'])
    sheet(dictionary_wb, 'Read_Me', [
        dict(item='required_vs_hard', meaning='required_for_ingestion is a storage requirement, not a user hard constraint. A nullable field can still be a hard requirement for a query.'),
        dict(item='observed_values', meaning='Examples present in this snapshot, not an exhaustive future enumeration.'),
        dict(item='types', meaning='Dates use ISO strings. collected_at has no confirmed timezone; do not silently assume a local timezone or UTC.'),
    ])
    dictionary_wb.save(OUT / 'NUS_Rental_Field_Dictionary_V1.xlsx')
    (OUT / 'START_HERE_ZH.md').write_text('''# 最终 V1 数据交付（当前已有字段范围）

本目录作为本轮统一交付入口，旧目录留作历史记录。主表 600 条、30 字段，另附来源/质量表和分区字典。

## 文件

- NUS_Rental_Data_V1_Typed.xlsx：数据表，数值是真数字，数值缺失为空白；ID 为文本。
- NUS_Rental_Field_Dictionary_V1.xlsx：独立字段字典，主字段和辅助字段分开，含中英文含义、类型、入库必填性、缺失规则、有效数量和限制。
- rental_data_v1.json：B/C 优先使用的程序导入文件，listings / listing_metadata / district_lookup 三组数据。
- field_dictionary_v1.json：可读取的字段契约；observed_values 仅是当前出现值，不是未来完整枚举。
- source_evidence_v1.json：按 listing_id 关联的原文、来源和提取依据，供核对推荐与排查问题。
- validation_report.json：数量、类型、关联和缺失检查报告。

## B/C 接入约定

1. listing_id 按文本保存，作为主表唯一键。listing_metadata 通过同名键关联；district_lookup 通过 district_code 关联。
2. 数值 null 导入为数据库 NULL，分类 unknown 仍为字符串；不要混入数值列，不填 0、不插补均值。
3. 当前入库必填：listing_id、title、listing_url、rent_monthly_sgd、district_code、address。必填与硬条件不同；卧室可缺失，但用户要求卧室数量时必须核实。
4. 出现硬条件缺失或相关矛盾 -> needs_confirmation；已知符合 -> pass；已知不符 -> fail。不可自动放宽硬条件。
5. 推荐接口同时读取质量表 review_flags。人数标签范围未确认，不代表已有租客或确定容量；性别偏好不是排他限制。
6. 数值缺失的排序单独处理，不把 null 当成零或最大最小值。用户界面可显示“未注明”。
7. listed_date 是广告日期；collected_at 是采集时间，当前时间字符串无确认时区，不自行补上时区。不是实时可租证明。
8. 不直接将所有非空值称为已核实事实：日期缺年份、平台标签、可能建设中的车站等均需要看字段说明和原文。

## 足以支持的工作

- 数据库表结构、导入、关联、基础检索接口。
- 基于广告月租、已知出租范围和卧室等字段的筛选原型。
- Agent 需求解析、三态筛选、解释引用、未知信息提示。
- 小组样例演示、单元测试和初步评审。

## 尚不足以完成的需求

- 地图定位：现有字段缺少可靠经纬度；以后可新增独立位置补充表，但不混入此次 30 字段。
- 到 NUS 的通勤排序：缺少具体 NUS 目的地、出行方式、时间和可验证路线；MRT 分钟数不能代替 NUS 通勤。
- 精确入住日期、可入住人数、租期和完整生活规则：现有证据稀疏或范围不明，需要房源详情补查。
- 总成本比较：缺少水电、押金、中介费等；月租不是完整总费用，也不能直接按卧室数分摊。
- 实时有效性：历史网页快照不能保证今天仍在出租。
- 项目整体评估：仍需小组构造测试需求和预期结果，核对检索、排序和解释；本次数据检查不是推荐系统验收。

## 建议开发顺序

先冻结当前数据契约，让 B/C 开始数据库和检索/Agent 原型；同时优先补位置与通勤、出租范围、入住限制等决定项目效果的事实。
不能为了填满空值而生成不存在的数据，也不应把本次 V1 文件称为已覆盖整个 Product Guide 的完整最终数据。
''', encoding='utf-8')
    # Confirm every data worksheet cell, including native numbers and actual blanks.
    check = load_workbook(data_path, read_only=True)
    for table in ('listings', 'listing_metadata', 'district_lookup'):
        ws = check[table]
        assert ws.max_row == len(data[table]) + 1
        for cells, expected in zip(ws.iter_rows(min_row=2), data[table]):
            values = [json.dumps(v, ensure_ascii=False) if isinstance(v, (list, dict)) else v for v in expected.values()]
            assert [c.value for c in cells] == values
    check.close()
    assert rows == original_values  # int/float conversion preserves numeric meaning.
    assert hashlib.sha256(source.read_bytes()).hexdigest() == before
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
