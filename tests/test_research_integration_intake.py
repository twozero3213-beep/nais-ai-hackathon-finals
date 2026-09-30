"""Intake boundary regression: all HTTP calls mocked except separately recorded public audit."""
# [작성: 0 이영 · Codex] 2026-10-01 02:55 KST — 다운로드·조건·계산·승인·재열기의 경계를 모의 검증하며 실제 비밀번호나 키를 사용하지 않는다.
from copy import deepcopy
import hashlib
import json
from unittest.mock import Mock

import pytest
from core import research_integration_intake as intake
from evidence_gate.spec import empty_spec

RAW = b'id,x,y\na,1,2\nb,2,5\nc,3,5\nd,4,9\n'


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    monkeypatch.setattr(intake, 'source_revision', lambda: 'test-source-sha')
    monkeypatch.setattr(intake, '_reserve_slot', lambda host: None)
    def download(host, path, **kwargs):
        return RAW, {'http_status': 200, 'source_url': 'https://' + host + path,
                     'retrieved_at_kst': '2026-10-01T02:55:00+09:00', 'content_type': 'text/csv'}
    monkeypatch.setattr(intake, '_get_bytes', download)


def record(provider='zenodo'):
    rid, fid, version = ('23', 'file-id', None) if provider == 'zenodo' else ('23', '45', '1.0' if provider == 'dataverse' else '2')
    hosts = {'zenodo': 'zenodo.org', 'figshare': 'figshare.com', 'dataverse': 'dataverse.harvard.edu'}
    return {'id': rid, 'doi': '10.5281/zenodo.23' if provider == 'zenodo' else '10.0000/example',
            'concept_doi': '10.5281/zenodo.22', 'version': version, 'detail_status': 'RETRIEVED',
            'official_url': 'https://' + hosts[provider] + '/records/23',
            'license': {'id': 'cc0-1.0', 'reuse_authorization': 'NOT_CONFIRMED'},
            'access': {'metadata': 'public', 'files': 'open'}, 'custom_terms_present': False,
            'provenance': {'response_sha256': 'a'*64, 'source_url': 'https://' + hosts[provider] + '/api/records/23'},
            'files': [{'id': fid, 'name': 'example.csv', 'size': len(RAW), 'restricted': False,
                       'checksum': {'algorithm': 'md5', 'value': hashlib.md5(RAW).hexdigest(),
                                    'origin': 'repository_computed', 'verified_against_download': False},
                       'supplied_checksum': None}]}


def acquired(provider='zenodo'):
    r = record(provider)
    a = intake.acquisition(provider, r, r['files'][0]['id'])
    assert a['success']
    return r, a


def spec(method='row_count'):
    result = empty_spec('SYNTHETIC-CLAIM')
    result.update(method=method, reported_value=4, filters=[], missing_policy='not_applicable', missing_tokens=[],
                  denominator='all four input rows', unit='observations', data_fingerprint=hashlib.sha256(RAW).hexdigest(),
                  tolerance=0.000001, source_location={'source_id': 'synthetic-paper', 'locator': 'Table 1', 'quote': 'Four observations.'})
    if method == 'mean':
        result.update(variable='x', reported_value=2.5, missing_policy='error')
    if method == 'ols_regression':
        result.update(reported_value=None, outcome='y', predictors=['x'], missing_policy='error',
                      reported={'x': {'b': 2.1, 'se': None, 't': None}})
    if method == 'row_alignment':
        result.update(reported_value=None, data_id_column='id', reference_ids_source='Table 1 IDs')
    return result


PAPER = {'paper_doi': '10.0000/synthetic', 'paper_version': 'published', 'source_url': 'https://example.org/paper', 'source_sha256': 'b'*64}


def verify(a, s=None, **kwargs):
    return intake.verify_download(a['raw_bytes'], a['receipt'], s or spec(), paper_context=PAPER,
                                  conditions_confirmed=True, **kwargs)


def test_checksum_receipt_distinguishes_advertised_and_observed():
    r, a = acquired()
    receipt = a['receipt']
    assert receipt['advertised_checksum']['verified_against_download'] is False
    assert receipt['checksum_comparisons'][0]['verified_against_download'] is True
    assert receipt['actual_sha256'] == hashlib.sha256(RAW).hexdigest()
    assert receipt['approved'] is False and receipt['verified'] is False
    assert 'raw_bytes' not in receipt


@pytest.mark.parametrize('provider,host,path', [
    ('zenodo', 'zenodo.org', '/api/records/23/files/example.csv/content'),
    ('figshare', 'ndownloader.figshare.com', '/files/45'),
    ('dataverse', 'dataverse.harvard.edu', '/api/access/datafile/45?format=original')])
def test_exact_provider_paths(provider, host, path, monkeypatch):
    seen = []
    monkeypatch.setattr(intake, '_get_bytes', lambda h, p: (seen.append((h,p)) or RAW, {'http_status':200, 'source_url':'https://'+h+p}))
    r = record(provider)
    assert intake.acquisition(provider,r,r['files'][0]['id'])['success']
    assert seen == [(host, path)]


@pytest.mark.parametrize('change,error', [
    ('unknown_license','LICENSE_NOT_AUTHORIZED'), ('restricted','FILE_NOT_PUBLIC'),
    ('link_only','FILE_NOT_PUBLIC'), ('ambiguous_public','FILE_NOT_PUBLIC'),
    ('oversize','ADVERTISED_SIZE_INVALID'), ('zip','CSV_FILE_REQUIRED'),
    ('draft','FIXED_RECORD_DETAIL_REQUIRED'), ('concept','FIXED_RECORD_VERSION_REQUIRED'),
    ('custom_terms','LICENSE_NOT_AUTHORIZED'), ('wrong_host','OFFICIAL_RECORD_URL_INVALID'),
    ('no_provenance','METADATA_RECEIPT_REQUIRED')])
def test_metadata_blocks_before_network(change,error,monkeypatch):
    r=record()
    if change=='unknown_license': r['license']['id']='other-open'
    if change=='restricted': r['files'][0]['restricted']=True
    if change=='link_only': r['files'][0]['link_only']=True
    if change=='ambiguous_public': r['files'][0]['restricted']=None
    if change=='oversize': r['files'][0]['size']=intake.MAX_BYTES+1
    if change=='zip': r['files'][0]['name']='archive.zip'
    if change=='draft': r['detail_status']='NOT_FETCHED'
    if change=='concept': r['doi']=r['concept_doi']
    if change=='custom_terms': r['custom_terms_present']=True
    if change=='wrong_host': r['official_url']='https://unlisted.invalid/file'
    if change=='no_provenance': r.pop('provenance')
    network=Mock(side_effect=AssertionError('network must not run'))
    monkeypatch.setattr(intake,'_get_bytes',network)
    result=intake.acquisition('zenodo',r,r['files'][0]['id'])
    assert result['error']==error
    network.assert_not_called()


def test_caller_cannot_replace_record_file_with_download_url():
    r=record(); replacement=deepcopy(r['files'][0]); replacement['url']='https://unlisted.invalid/data.csv'
    assert intake.acquisition('zenodo',r,replacement)['error']=='SELECTED_FILE_NOT_IN_RECORD'


@pytest.mark.parametrize('kind,error', [('checksum','ADVERTISED_CHECKSUM_MISMATCH'), ('size','ADVERTISED_SIZE_MISMATCH')])
def test_bytes_must_match_metadata(kind,error):
    r=record()
    if kind=='checksum': r['files'][0]['checksum']['value']='0'*32
    else: r['files'][0]['size']+=1
    assert intake.acquisition('zenodo',r,r['files'][0]['id'])['error']==error


def test_missing_advertised_checksum_is_never_verified():
    r=record(); r['files'][0]['checksum']=None
    a=intake.acquisition('zenodo',r,r['files'][0]['id'])
    assert a['success']
    assert a['receipt']['checksum_comparisons'][0]=={'status':'NOT_ADVERTISED','verified_against_download':False}


@pytest.mark.parametrize('bad', [b'PK\x03\x04archive', b'<html>not data</html>', b'column\n\x00\n', b'id,id\na,b\n', b'id,x\na\n'])
def test_non_csv_bodies_are_blocked(bad,monkeypatch):
    monkeypatch.setattr(intake,'_get_bytes',lambda *args,**kwargs:(bad, {'http_status':200}))
    r=record(); r['files'][0]['size']=len(bad)
    assert intake.acquisition('zenodo',r,r['files'][0]['id'])['success'] is False


def test_sensitive_body_returns_only_code(monkeypatch):
    bad=('contact\n'+'synthetic'+chr(64)+'example.invalid\n').encode()
    monkeypatch.setattr(intake,'_get_bytes',lambda *args,**kwargs:(bad, {'http_status':200}))
    r=record(); r['files'][0]['size']=len(bad)
    result=intake.acquisition('zenodo',r,r['files'][0]['id'])
    assert result['error']=='SENSITIVE_INPUT' and result['raw_bytes'] is None
    assert 'synthetic' not in json.dumps(result)


@pytest.mark.parametrize('method', ['row_count','mean','ols_regression','row_alignment'])
def test_reuses_supported_deterministic_gate(method):
    _, a=acquired()
    result=verify(a,spec(method),reference_ids=['a','b','c','d'] if method=='row_alignment' else None)
    assert result['success'] and result['can_approve'], result.get('calculation')
    assert result['state']=='NEEDS_HUMAN_REVIEW'
    assert not result['approved'] and not result['verified']


def test_unconfirmed_conditions_do_not_call_engine(monkeypatch):
    _,a=acquired(); engine=Mock(side_effect=AssertionError('engine must not run'))
    monkeypatch.setattr(intake.gate,'evaluate',engine)
    result=intake.verify_download(RAW,a['receipt'],spec(),paper_context=PAPER)
    assert result['error']=='CONDITIONS_NOT_CONFIRMED'
    engine.assert_not_called()


def test_mismatch_cannot_be_approved():
    _,a=acquired(); s=spec(); s['reported_value']=5
    report=verify(a,s)
    assert report['calculation']['verdict']=='MISMATCH' and report['can_approve'] is False
    assert intake.approve_download(report,raw_bytes=RAW,receipt=a['receipt'],spec=s,paper_context=PAPER,
        actor='test-admin',actor_role='ADMIN',confirmed=True,reason='Checked')['success'] is False


@pytest.mark.parametrize('missing',['unit','denominator','missing_policy','source_location'])
def test_incomplete_conditions_block(missing):
    _,a=acquired(); s=spec(); s[missing]=None
    assert verify(a,s)['error']=='SPEC_NOT_READY'


def test_stale_data_receipt_blocks():
    _,a=acquired(); a['raw_bytes']+=b'\n'
    assert verify(a)['error']=='STALE_DATA'


def test_receipt_tamper_blocks():
    _,a=acquired(); a['receipt']['license_policy']='changed'
    assert verify(a)['error']=='RECEIPT_INTEGRITY_INVALID'


def test_current_record_change_blocks():
    r,a=acquired(); r['files'][0]['checksum']['value']='1'*32
    assert verify(a,current_record=r)['error']=='STALE_RECORD'


def approved(a,report=None,**kwargs):
    return intake.approve_download(report or verify(a),raw_bytes=RAW,receipt=a['receipt'],spec=spec(),paper_context=PAPER,
                                  actor='test-admin',actor_role=kwargs.get('role','ADMIN'),confirmed=kwargs.get('confirmed',True),reason='Checked source and conditions')


@pytest.mark.parametrize('role',['VIEWER','ANALYST','REVIEWER','INVALID'])
def test_review_role_is_not_approval(role):
    _,a=acquired()
    assert approved(a,role=role)['error']=='APPROVAL_ROLE_REQUIRED'


def test_explicit_confirmation_required():
    _,a=acquired()
    assert approved(a,confirmed=False)['error']=='EXPLICIT_REVIEW_REQUIRED'


@pytest.mark.parametrize('role',['ADMIN','APPROVER'])
def test_human_approval_bound_to_current_input_only(role):
    _,a=acquired(); result=approved(a,role=role)
    assert result['approved'] and not result['verified']
    assert result['human_approval']['bindings']==result['bindings']
    assert result['state']=='APPROVED_ARITHMETIC_SCOPE'


@pytest.mark.parametrize('dimension',['spec','paper','source','reference'])
def test_each_context_change_invalidates_prior_approval(dimension,monkeypatch):
    _,a=acquired(); report=approved(a); s=spec(); paper=deepcopy(PAPER); refs=None
    if dimension=='spec': s['unit']='changed unit'
    if dimension=='paper': paper['paper_version']='changed revision'
    if dimension=='source': monkeypatch.setattr(intake,'source_revision',lambda:'changed-code')
    if dimension=='reference': refs=['changed']
    result=intake.verify_download(RAW,a['receipt'],s,paper_context=paper,conditions_confirmed=True,
                                 reference_ids=refs,prior_approval=report['human_approval'])
    assert result['error']=='STALE_APPROVAL'


def test_approval_recalculates_and_compares_old_bindings():
    _,a=acquired(); report=verify(a); changed=spec(); changed['unit']='changed'
    result=intake.approve_download(report,raw_bytes=RAW,receipt=a['receipt'],spec=changed,paper_context=PAPER,
                                  actor='test-admin',actor_role='ADMIN',confirmed=True,reason='Checked')
    assert result['error']=='STALE_APPROVAL'


def test_import_is_inactive_even_when_export_has_valid_approval():
    _,a=acquired(); report=approved(a); text=intake.export_report(report)
    assert 'raw_bytes' not in text
    reopened=intake.reopen_report(text)
    assert reopened['state']=='IMPORTED_REVALIDATION_REQUIRED'
    assert not reopened['approved'] and not reopened['can_approve']
    assert reopened['human_approval']['active'] is False


def test_import_tamper_and_duplicate_keys_block():
    _,a=acquired(); report=approved(a); report['spec']['unit']='edited'
    assert intake.reopen_report(json.dumps(report))['error']=='REPORT_INTEGRITY_INVALID'
    assert intake.reopen_report('{"schema":1,"schema":2}')['error']=='DUPLICATE_JSON_KEY'


def test_registration_reuses_repository_metadata_api():
    _,a=acquired(); repo=Mock()
    result=intake.register_download(repo,a['receipt'],'synthetic-dataset','Synthetic CSV')
    repo.add_dataset.assert_called_once_with('synthetic-dataset',hashlib.sha256(RAW).hexdigest(),'Synthetic CSV')
    assert result['approved'] is False


def test_registered_only_exact_source_pair(monkeypatch):
    monkeypatch.setattr(intake,'_get_bytes',Mock(side_effect=AssertionError('No lookup guessing')))
    assert intake.acquisition_registered('UNREGISTERED')['success'] is False
    intake._get_bytes.assert_not_called()


def test_registered_returns_spec_and_derivative_provenance(monkeypatch):
    from finals.finals_cases import load_case
    case=load_case('PENG-RAW-ROWS'); real=case['data_bytes']
    calls=[]
    def download(host,path,**kwargs):
        calls.append((host,path))
        raw=b'Package: palmerpenguins\nLicense: CC0\n' if path==intake.LICENSE_PATH else real
        return raw, {'http_status':200,'source_url':'https://'+host+path,'retrieved_at_kst':'2026-10-01T02:55:00+09:00'}
    monkeypatch.setattr(intake,'_get_bytes',download)
    a=intake.acquisition_registered()
    assert a['success']
    assert calls==[('raw.githubusercontent.com',intake.LICENSE_PATH),('raw.githubusercontent.com',intake.REGISTERED_PATH)]
    assert a['suggested_spec']['reported_value']==344
    assert a['receipt']['source_capture']['kind']=='CONTACTS_REMOVED_PUBLIC_DERIVATIVE'
    assert a['receipt']['source_capture']['original_publisher_bytes_sha256'] is None
    result=intake.verify_download(real,a['receipt'],a['suggested_spec'],paper_context=a['paper_context'],conditions_confirmed=True)
    assert result['calculation']['computed']==344 and not result['approved']


def test_registered_hash_difference_blocks(monkeypatch):
    def download(host,path,**kwargs):
        return (b'License: CC0\n' if path==intake.LICENSE_PATH else RAW),{'http_status':200}
    monkeypatch.setattr(intake,'_get_bytes',download)
    assert intake.acquisition_registered()['success'] is False


def test_registered_license_not_assumed(monkeypatch):
    monkeypatch.setattr(intake,'_get_bytes',lambda *args,**kwargs:(b'License: unclear\n',{'http_status':200}))
    assert intake.acquisition_registered()['success'] is False


def test_transport_redirect_has_no_body_read(monkeypatch):
    monkeypatch.undo()
    monkeypatch.setattr(intake,'_reserve_slot',lambda host:None)
    response=Mock(status=302)
    connection=Mock(); connection.getresponse.return_value=response
    monkeypatch.setattr(intake.http.client,'HTTPSConnection',lambda *args,**kwargs:connection)
    with pytest.raises(intake.IntakeError,match='HTTP_302'):
        intake._get_bytes('zenodo.org','/api/records/23/files/example.csv/content')
    response.read.assert_not_called()
    assert connection.request.call_count==1
    connection.close.assert_called_once()


@pytest.mark.parametrize('host,path', [('unlisted.invalid','/file.csv'),('raw.githubusercontent.com','/arbitrary/repo/main/file.csv'),
                                      ('zenodo.org','//unlisted.invalid/file.csv'),('zenodo.org','/file.csv?api_key=mock-value')])
def test_transport_rejects_unsafe_target_without_network(host,path,monkeypatch):
    monkeypatch.undo()
    network=Mock(side_effect=AssertionError('No network'))
    monkeypatch.setattr(intake.http.client,'HTTPSConnection',network)
    with pytest.raises(intake.IntakeError):
        intake._get_bytes(host,path)
    network.assert_not_called()


def test_unversioned_cc_by_is_not_inferred_as_four():
    r=record(); r['license']['id']='cc-by'
    assert intake.acquisition('zenodo',r,r['files'][0]['id'])['error']=='LICENSE_NOT_AUTHORIZED'
    r['license']['url']='https://creativecommons.org/licenses/by/4.0/'
    assert intake.acquisition('zenodo',r,r['files'][0]['id'])['success']


def test_auth_query_in_record_url_blocks_without_network(monkeypatch):
    r=record(); r['official_url']+='?token=mock-value'
    network=Mock(side_effect=AssertionError('No network'))
    monkeypatch.setattr(intake,'_get_bytes',network)
    assert intake.acquisition('zenodo',r,r['files'][0]['id'])['error']=='OFFICIAL_RECORD_URL_INVALID'
    network.assert_not_called()


def test_transport_fixed_provider_paths_only(monkeypatch):
    monkeypatch.undo()
    network=Mock(side_effect=AssertionError('No network'))
    monkeypatch.setattr(intake.http.client,'HTTPSConnection',network)
    with pytest.raises(intake.IntakeError,match='DOWNLOAD_PATH_NOT_ALLOWED'):
        intake._get_bytes('zenodo.org','/arbitrary/data.csv')
    network.assert_not_called()


def test_declared_paper_hash_is_never_actual_acquisition_proof():
    _,a=acquired(); report=verify(a)
    assert report['paper_source_status']['status']=='NOT_ACQUIRED'
    assert report['paper_source_status']['actual_sha256'] is None
    assert 'PAPER_BYTES_NOT_ACQUIRED' in report['limitations']
    assert report['verified'] is False


def test_registered_paper_hash_must_match_confirmed_derivative(monkeypatch):
    from finals.finals_cases import load_case
    raw=load_case('PENG-RAW-ROWS')['data_bytes']
    monkeypatch.setattr(intake,'_get_bytes',lambda host,path,**kwargs: (b'License: CC0\n' if path==intake.LICENSE_PATH else raw,{'http_status':200}))
    a=intake.acquisition_registered(); paper=deepcopy(a['paper_context']); paper['source_sha256']='f'*64
    report=intake.verify_download(raw,a['receipt'],a['suggested_spec'],paper_context=paper,conditions_confirmed=True)
    assert report['error']=='PAPER_SOURCE_NOT_BOUND'
