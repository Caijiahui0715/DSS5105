"""Run 20 DSS5105 ranking cases with isolated, explicit registered profiles.

Requires: run_eval.py in the same folder; openpyxl in your Python environment.
Uses the real server's profile, faculty, conversation and SSE endpoints.
WARNING: Resets profile of the dedicated EVAL account for every case.
"""
import argparse
import csv
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from openpyxl import load_workbook
from run_eval import request_json, send_sse, listing_ids


def load_profiles(path):
    wb = load_workbook(path, read_only=True, data_only=True)
    ws = wb['Registered Profiles 20']
    ws.reset_dimensions()
    rows = ws.iter_rows(values_only=True)
    headers = next(rows)
    return {str(d['Case ID']): d for vals in rows if (d := dict(zip(headers, vals))).get('Case ID')}


def load_queries(path):
    data = json.loads(Path(path).read_text(encoding='utf-8-sig'))
    return {x['case_id']: x for x in data['answers']}


def turns_for(item):
    if item.get('queries'):
        return [x['query'] for x in sorted(item['queries'], key=lambda x: x['turn'])]
    return [item['query']]


def initial_profile(row):
    values = {'max_price_sgd': int(row['Registered Budget SGD']),
              'rental_scope': str(row['Registered Rental Scope'])}
    n = row['Registered Min Bedrooms']
    if n not in ('', None) and int(n) > 0:
        values['min_bedrooms'] = int(n)
    lease = str(row['Registered Lease Length'] or '').strip().lower()
    if lease == '12 months':
        values['lease_months'] = 12
    elif lease not in ('', 'no preference / blank'):
        raise ValueError('Unsupported registered lease length: ' + lease)
    faculty = str(row['Registered Faculty'] or '').strip()
    if faculty.lower() in ('not selected', '', 'none'):
        faculty = None
    return values, faculty



def reset_account(base, token, row):
    """Reset and verify the dedicated test account profile."""

    profile, faculty = initial_profile(row)

    # 1. Enable memory and auto-save
    request_json(base, 'PUT', '/api/me/memory',
                 {'on': True}, token)
    request_json(base, 'PUT', '/api/me/auto-save',
                 {'on': True}, token)

    # 2. Delete old profile
    request_json(base, 'DELETE', '/api/me/profile',
                 token=token)

    # 3. Set faculty and initial profile
    request_json(base, 'PUT', '/api/me/faculty',
                 {'faculty': faculty}, token)

    saved = request_json(
        base, 'PUT', '/api/me/profile',
        {'changes': profile}, token
    )

    # 4. Read the actual saved profile
    actual = saved.get('preferences', {})

    print("\n=== PROFILE RESET VERIFICATION ===")
    print("Expected profile:", profile)
    print("Actual profile:", actual)

    # 5. Check expected fields
    for k, v in profile.items():
        if actual.get(k) != v:
            raise RuntimeError(
                f"FAIL: {k}: expected {v!r}, "
                f"got {actual.get(k)!r}"
            )

    # 6. Check for unexpected residual constraints
    # These are candidate neutral defaults;
    # confirm them against the backend schema.
    allowed_defaults = {
        "min_bedrooms": (None, 0, "no_minimum"),
        "lease_months": (None, 0, "any"),
    }

    unexpected = {}

    for k, v in actual.items():
        if k in profile:
            continue

        if k in allowed_defaults and v in allowed_defaults[k]:
            continue

        if v is None or v == "" or v == "unknown":
            continue

        unexpected[k] = v

    if unexpected:
        raise RuntimeError(
            f"FAIL: Unexpected profile fields: {unexpected}"
        )

    # 7. Verify faculty
    actual_faculty = request_json(
        base, 'GET', '/api/me', token=token
    ).get('faculty')

    if faculty != actual_faculty:
        raise RuntimeError(
            f"FAIL: Faculty mismatch: "
            f"{faculty!r} != {actual_faculty!r}"
        )

    print("PASS: Expected profile fields verified")
    print("PASS: No unexpected constraints detected")
    print("PASS: Faculty verified")
    print("==================================\n")

    return saved, actual_faculty


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--profiles', default='DSS5105_20_Initial_Registered_Profiles_Defined.xlsx')
    p.add_argument('--gold-queries', default='DSS5105_47_Gold_Answers.json', help='Used ONLY for query text; NOT for scoring')
    p.add_argument('--base-url', default='http://127.0.0.1:8000')
    p.add_argument('--ids', nargs='*')
    p.add_argument('--runs', type=int, default=1)
    p.add_argument('--timeout', type=int, default=240)
    p.add_argument('--out-dir', default='eval_runs_profile20')
    p.add_argument('--execute', action='store_true', help='Required to permit resetting the dedicated account and calling Agent')
    args = p.parse_args()
    profiles = load_profiles(args.profiles)
    queries = load_queries(args.gold_queries)
    ids = args.ids or list(profiles)
    if args.runs < 1 or any(cid not in profiles or cid not in queries for cid in ids):
        p.error('Invalid --runs or case ID')
    plan = []
    for cid in ids:
        profile, faculty = initial_profile(profiles[cid])
        plan.append((cid, profile, faculty, turns_for(queries[cid])))
    print('Planned tests (each run resets the dedicated account profile):')
    for cid, profile, faculty, turns in plan:
        print(f'  {cid}: {len(turns)} turn(s), profile={profile}, faculty={faculty!r}')
    if not args.execute:
        print('DRY RUN ONLY. Add --execute to run the real Agent. WARNING: deletes/replaces the EVAL account profile.')
        return
    if os.getenv('EVAL_CONFIRM_RESET') != 'YES':
        p.error('Set EVAL_CONFIRM_RESET=YES to confirm resetting the dedicated evaluation account profile.')
    user, pwd = os.getenv('EVAL_USERNAME'), os.getenv('EVAL_PASSWORD')
    if not user or not pwd:
        p.error('Set EVAL_USERNAME and EVAL_PASSWORD for a DEDICATED evaluation account.')
    base = args.base_url.rstrip('/')
    token = request_json(base, 'POST', '/api/token', {'username': user, 'password': pwd})['token']
    out = Path(args.out_dir); out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    jsonl = out / f'agent_profile20_{stamp}.jsonl'
    csvfile = out / f'agent_profile20_{stamp}.csv'
    cols = ['case_id','run','turn','query','status','thread_id','listing_ids','agent_response','profile_before','profile_after','preferences','duration_seconds','error']
    with jsonl.open('w',encoding='utf-8') as jf, csvfile.open('w',encoding='utf-8-sig',newline='') as cf:
        writer = csv.DictWriter(cf,fieldnames=cols); writer.writeheader()
        for cid, profile, faculty, turns in plan:
            for run in range(1,args.runs+1):
                thread_id = None
                try:
                    before, faculty_actual = reset_account(base, token, profiles[cid])
                    thread_id = request_json(base,'POST','/api/conversations',{'language':'en'},token)['id']
                    for turn, query in enumerate(turns,1):
                        t0=time.monotonic(); error=None; reply={}; progress=[]; state={}
                        try:
                            reply,progress=send_sse(base,thread_id,query,'en',token,args.timeout)
                            state=request_json(base,'GET',f'/api/conversations/{thread_id}',token=token)
                        except Exception as e:
                            error=str(e)
                        after=request_json(base,'GET','/api/me/profile',token=token)
                        rec=reply.get('recommendations') or state.get('recommendations')
                        record={'case_id':cid,'run':run,'turn':turn,'query':query,'status':'error' if error else 'ok',
                                'thread_id':thread_id,'listing_ids':listing_ids(rec),'agent_response':reply.get('text'),
                                'recommendations':rec,'comparison':reply.get('comparison'),'preferences':state.get('preferences') or reply.get('preferences'),
                                'profile_before':before if turn==1 else None,'profile_after':after,
                                'registered_faculty':faculty_actual,'conversation_state':state,'progress':progress,
                                'duration_seconds':round(time.monotonic()-t0,2),'error':error}
                        jf.write(json.dumps(record,ensure_ascii=False,default=str)+'\n');jf.flush()
                        writer.writerow({k: (';'.join(record[k]) if k=='listing_ids' else
                                           json.dumps(record[k],ensure_ascii=False,default=str) if k in ('profile_before','profile_after','preferences') else
                                           record.get(k)) for k in cols});cf.flush()
                        print(f'{cid} run={run} turn={turn}: {record["status"]}, {len(record["listing_ids"])} IDs, {record["duration_seconds"]}s',flush=True)
                        if error: break
                except Exception as e:
                    print(f'ERROR {cid} run={run}: {e}',file=sys.stderr)
                    # Stop immediately if profile reset fails; otherwise later tests would be contaminated.
                    raise
    print('Results:',jsonl,csvfile,sep='\n')

if __name__=='__main__':
    main()
