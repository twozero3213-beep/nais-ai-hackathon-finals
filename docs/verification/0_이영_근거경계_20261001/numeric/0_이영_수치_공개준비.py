# [작성: 0 이영 · Codex · 버전 0] 실제 생성 KST는 공개 파생 결과에 기록한다.
# 이유: unittest 원결과를 보존하고 로컬 절대경로만 상대경로로 바꾼 공개 파생본과 파일 지문을 생성한다.
from datetime import datetime,timedelta,timezone
import argparse
import hashlib
import json
from pathlib import Path
import re

def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--repo',type=Path,required=True)
    args=parser.parse_args()
    out=Path(__file__).resolve().parent
    original=out/'0_이영_수치회귀_results.json'
    public=out/'0_이영_수치회귀_results_public.json'
    if public.exists():raise SystemExit('refusing public derivative overwrite')
    substitutions=[(str(out)+'\\','numeric/'),(str(args.repo.resolve())+'\\','snapshot/'),
                   (out.as_posix()+'/','numeric/'),(args.repo.resolve().as_posix()+'/','snapshot/')]
    def relative(value):
        if isinstance(value,dict):return {key:relative(item) for key,item in value.items()}
        if isinstance(value,list):return [relative(item) for item in value]
        if isinstance(value,str):
            for before,after in substitutions:value=value.replace(before,after)
        return value
    result=relative(json.loads(original.read_text(encoding='utf-8')))
    result['_public_derivative']={'_change_note':'[0 이영] 원실행 결과는 보존하며 traceback의 로컬 절대경로만 상대경로로 치환했다. 실제 계산값/시험/시각/소스·프로토콜 지문은 변경하지 않았다.',
                                  'generated_at_kst':datetime.now(timezone(timedelta(hours=9))).isoformat(timespec='seconds'),
                                  'original_result_sha256':digest(original),'only_path_strings_changed':True}
    text=json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n'
    if re.search(r'\b[A-Z]:[\\/]',text):raise SystemExit('absolute Windows path remains')
    public.write_text(text,encoding='utf-8')
    names=['0_이영_수치경계_검증.py','0_이영_수치경계_protocol.json','0_이영_수치경계_hash.json','0_이영_수치경계_results.json',
           '0_이영_수치회귀_제안.py','0_이영_수치회귀_protocol.json','0_이영_수치회귀_results_public.json','0_이영_수치_공개준비.py']
    files=[]
    for name in names:
        path=out/name
        data=path.read_text(encoding='utf-8')
        if re.search(r'\b[A-Z]:[\\/]',data):raise SystemExit('absolute Windows path in public selection: '+name)
        files.append({'path':'numeric/'+name,'sha256':digest(path),'bytes':path.stat().st_size})
    manifest={'_change_note':'[0 이영] 버전0: 공개할 숫자 실험 파일만 명시적으로 열거한다. 원 회귀 traceback 결과는 로컬 보존하고 공개 목록에서 제외한다.',
              'generated_at_kst':datetime.now(timezone(timedelta(hours=9))).isoformat(timespec='seconds'),
              'commit':'a6729178963392249b14c9dfbd93bf28704262a4','files':files,
              'absolute_windows_paths_in_selected_files':0,'environment_fields':'Python implementation/version, Windows version, pandas/numpy/scipy/jsonschema versions; no hostname or username',
              'raw_regression_result_excluded':True}
    manifest_path=out/'0_이영_수치_公開hash.json'
    manifest_path.write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'public_result_sha256':digest(public),'manifest_sha256':digest(manifest_path),'files':len(files)},ensure_ascii=False))

if __name__=='__main__':main()
