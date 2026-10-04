from pipeline.ownership_inputs import normalize_director_rows, normalize_tdcc_rows
from scripts.fetch_ownership import parse_mops_payload


def test_completed_months_and_official_available_dates():
    from scripts.fetch_ownership import completed_months, parse_tdcc_available_dates
    assert completed_months('2026-10-02') == ['2026-07', '2026-08', '2026-09']
    page = '<select name="scaDate"><option value="20260924">date</option><option value="20260828">date</option><option value="20260731">date</option></select>'
    assert parse_tdcc_available_dates(page) == ['2026-07-31', '2026-08-28', '2026-09-24']


def test_source_scoped_observed_fields_and_proven_market():
    tdcc = normalize_tdcc_rows([{'資料日期':'2026-09-24','證券代號':'1234','持股分級':'15','占集保庫存數比例%':'12'},
                                {'資料日期':'2026-09-24','證券代號':'1234','持股分級':'17','人數':'50'}], market_by_code={'1234':'TPEX'})[0]
    assert tdcc['market'] == 'TPEX'
    assert tdcc['observedFields'] == ['largeHolderPct', 'shareholderCount']
    assert tdcc['sourceDate'] == '2026-09-24' and tdcc['publishedAt'] is None


def test_vice_chair_and_same_identity_are_counted_once():
    rows = [{'資料年月':'11509','公司代號':'2547','職稱':title,'姓名':'甲','目前持股':'100','已發行普通股數':'1000'}
            for title in ['副董事長本人','董事本人']]
    result = normalize_director_rows(rows)[0]
    assert result['directorSupervisorShares'] == 100
    assert result['directorSupervisorPct'] == 10
    assert result['observedFields'] == ['directorSupervisorPct']
    assert result['market'] is None


def test_mops_observes_official_holding_total_without_fabricated_denominator():
    payload = {'result':{'parentCompany':{'data':[['副董事長本人','甲','0','11,905,369']],
                                          'total':{'allDirectorSupervisor':['130,992,090','0','0']}}}}
    row = parse_mops_payload(payload,code='2547',period='2026-09')[0]
    assert row['directorSupervisorShares'] == 11905369
    assert row['officialDirectorSupervisorShares'] == 130992090
    assert row['directorSupervisorPct'] is None and row['directorDenominator'] is None


def test_tdcc_real_csv_date_format_and_mops_zero_holdings():
    row = normalize_tdcc_rows([{'資料日期':'20261002','證券代號':' 3293 ','持股分級':'15','占集保庫存數比例%':'0'}])[0]
    assert row['asOf']=='2026-10-02' and row['largeHolderPct']==0
    director=normalize_director_rows([{'資料年月':'11508','公司代號':'2547','職稱':'董事本人','姓名':'零','目前持股':0,'已發行普通股數':1000}])[0]
    assert director['directorSupervisorShares']==0 and director['directorSupervisorPct']==0


def test_current_issued_snapshot_never_attached_to_historical_holdings():
    from scripts.fetch_ownership import parse_twse_director_rows
    row=parse_twse_director_rows([{'公司代號':'2330','資料年月':'11508','职称':'董事本人','職稱':'董事本人','目前持股':'100'}],
                                 issued_shares_by_code={'2330':1000},dataset='t187ap11_L')[0]
    assert row['directorSupervisorPct'] is None


def test_anonymous_directors_cannot_prove_identity_scope():
    row=normalize_director_rows([{'資料年月':'11508','公司代號':'2330','職稱':'董事本人','目前持股':'100','已發行普通股數':'1000'}])[0]
    assert row['directorIdentityConsistent'] is False and row['directorSupervisorPct'] is None


def test_merge_preserves_latest_publication_cutoff_for_every_source():
    from pipeline.ownership_inputs import merge_ownership_rows
    rows=merge_ownership_rows([{'code':'2330','period':'2026-09','publishedAt':'2026-09-30','largeHolderPct':50}],
                              [{'code':'2330','period':'2026-09','publishedAt':'2026-10-03','directorSupervisorPct':20}])
    assert rows[0]['publishedAt']=='2026-10-03'
    assert len(rows[0]['sourceObservations'])==2
