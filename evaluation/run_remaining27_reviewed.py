"""DSS5105 remaining 27 controlled agent tests. Dry-run is default.

Run beside run_agent_profile20.py and run_eval.py; profile configuration is
remaining27_profiles_reviewed.json. Uses the frozen 47-case query file.
Only use a dedicated disposable evaluation account; --execute resets its profile.
"""
import argparse,csv,hashlib,json,os,sys,time
from pathlib import Path
from datetime import datetime,timezone
from run_agent_profile20 import load_queries, initial_profile, reset_account, turns_for
from run_eval import request_json, send_sse, listing_ids

PRIOR20=set('A01 A02 A04 A05 A06 A08 A09 A10 B01 B02 B03 B04 B06 C03 C04 G01 G02 G03 G04 G05'.split())

def load_plan(args):
    cases=load_queries(args.gold_queries)
    config=json.loads(Path(args.profiles27).read_text(encoding='utf-8-sig'))
    expected=set(cases)-PRIOR20
    if set(config)!=expected or len(cases)!=47:
        raise ValueError(f'Case coverage mismatch: missing={sorted(expected-set(config))}, extra={sorted(set(config)-expected)}')
    ids=args.ids if args.ids else sorted(expected)
    if len(ids)!=len(set(ids)) or any(cid not in expected for cid in ids):
        raise ValueError('Duplicate or invalid --ids')
    for cid in ids:
        row=config[cid]
        profile,faculty=initial_profile(row)
        if not profile.get('max_price_sgd') or profile.get('rental_scope') not in ('room','entire_unit'):
            raise ValueError('Invalid registered profile for '+cid)
        if row.get('seed_context') and not row.get('context_listing_id'):
            raise ValueError('Context seed lacks listing ID: '+cid)
        if cid.startswith('H') and row.get('seed_context'):
            raise ValueError('H cases already contain fixed IDs: '+cid)
    return cases,config,ids

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--gold-queries',default='DSS5105_47_Gold_Answers.json')
    p.add_argument('--profiles27',default='remaining27_profiles_reviewed.json')
    p.add_argument('--listings',default='listings_active_430_exploration.csv')
    p.add_argument('--base-url',default='http://127.0.0.1:8000')
    p.add_argument('--ids',nargs='+')
    p.add_argument('--runs',type=int,default=1)
    p.add_argument('--timeout',type=int,default=240)
    p.add_argument('--out-dir',default='eval_runs_remaining27_reviewed')
    p.add_argument('--execute',action='store_true')
    args=p.parse_args()
    if args.runs<1:p.error('--runs must be >= 1')
    cases,config,ids=load_plan(args)
    listing_file=Path(args.listings)
    if not listing_file.is_file():p.error('Missing frozen listing snapshot: '+str(listing_file))
    with listing_file.open(encoding='utf-8-sig',newline='') as f:
        known={str(r['listing_id']) for r in csv.DictReader(f)}
    for cid in ids:
        r=config[cid];profile,faculty=initial_profile(r)
        if r.get('context_listing_id') and str(r['context_listing_id']) not in known:
            p.error(f'{cid}: context listing not in snapshot')
        print(f'{cid}: turns={len(turns_for(cases[cid]))}, profile={profile}, faculty={faculty!r}, seed={r.get("context_listing_id") if r.get("seed_context") else "none"}')
        print('   ',r.get('evaluation_note',''))
    print(f'Checked {len(ids)} cases. Query/profile SHA256: {sha(args.gold_queries)[:12]} / {sha(args.profiles27)[:12]}')
    if not args.execute:
        print('DRY RUN ONLY. No server calls or profile changes.');return
    if os.getenv('EVAL_CONFIRM_RESET')!='YES':p.error('Set EVAL_CONFIRM_RESET=YES for a dedicated disposable test account')
    username=os.getenv('EVAL_USERNAME');pwd=os.getenv('EVAL_PASSWORD')
    if not username or not pwd:p.error('Set EVAL_USERNAME and EVAL_PASSWORD')
    base=args.base_url.rstrip('/')
    token=request_json(base,'POST','/api/token',{'username':username,'password':pwd})['token']
    out=Path(args.out_dir);out.mkdir(parents=True,exist_ok=True)
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    jp=out/f'agent_remaining27_{stamp}.jsonl';cp=out/f'agent_remaining27_{stamp}.csv'
    manifest={'created_utc':stamp,'cases':ids,'runs':args.runs,'gold_queries_sha256':sha(args.gold_queries),'profiles_sha256':sha(args.profiles27),'listings_sha256':sha(args.listings),'purpose':'Agent outputs only; no automatic correctness scores'}
    (out/f'manifest_{stamp}.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    cols=['case_id','run','turn','kind','query','status','listing_ids','agent_response','profile_before','profile_after','registered_faculty','duration_seconds','error','context_seed_status']
    with jp.open('w',encoding='utf-8') as jf,cp.open('w',encoding='utf-8-sig',newline='') as cf:
        writer=csv.DictWriter(cf,fieldnames=cols);writer.writeheader()
        def save(rec):
            jf.write(json.dumps(rec,ensure_ascii=False,default=str)+'\n');jf.flush()
            writer.writerow({k:(';'.join(rec.get(k,[])) if k=='listing_ids' else json.dumps(rec.get(k),ensure_ascii=False,default=str) if k in ('profile_before','profile_after') else rec.get(k)) for k in cols});cf.flush()
        for cid in ids:
            r=config[cid]
            for run in range(1,args.runs+1):
                try:
                    before,faculty=reset_account(base,token,r)
                    # Independent read-back, including detecting residual restrictions.
                    readback=request_json(base,'GET','/api/me/profile',token=token)
                    expected,_=initial_profile(r)
                    actual=readback.get('preferences',{})
                    if actual!=expected:
                        raise RuntimeError(f'Reset read-back mismatch: expected {expected!r}, actual {actual!r}')
                    thread=request_json(base,'POST','/api/conversations',{'language':'en'},token)['id']
                except Exception as e:
                    save({'case_id':cid,'run':run,'turn':0,'kind':'setup','status':'error','error':str(e)})
                    raise
                seed_status='not_required'
                if r.get('seed_context'):
                    lid=str(r['context_listing_id'])
                    seed=f'For my next question, I mean rental listing ID {lid}. Please identify that listing from your database, and keep it as the subject. Do not invent missing facts.'
                    try:
                        seed_reply,seed_progress=send_sse(base,thread,seed,'en',token,args.timeout)
                        seed_status='ok_unverified'
                        # Log seed explicitly; human must check correct referent before scoring.
                        save({'case_id':cid,'run':run,'turn':0,'kind':'context_seed','query':seed,'status':seed_status,'agent_response':seed_reply.get('text'),'listing_ids':listing_ids(seed_reply.get('recommendations')),'context_seed_status':seed_status,'seed_raw':seed_reply,'progress':seed_progress,'thread_id':thread})
                    except Exception as e:
                        save({'case_id':cid,'run':run,'turn':0,'kind':'context_seed','query':seed,'status':'error','error':str(e)})
                        raise RuntimeError(f'{cid}: context setup failed; stopping batch') from e
                for turn,query in enumerate(turns_for(cases[cid]),1):
                    t0=time.monotonic();reply={};state={};progress=[];error=None
                    try:
                        reply,progress=send_sse(base,thread,query,'en',token,args.timeout)
                        state=request_json(base,'GET',f'/api/conversations/{thread}',token=token)
                    except Exception as e:error=str(e)
                    try:after=request_json(base,'GET','/api/me/profile',token=token)
                    except Exception as e:after={'read_error':str(e)}
                    rec=reply.get('recommendations') or state.get('recommendations')
                    result={'case_id':cid,'run':run,'turn':turn,'kind':'evaluation','query':query,'status':'error' if error else 'ok',
                            'thread_id':thread,'listing_ids':listing_ids(rec),'agent_response':reply.get('text'),'recommendations':rec,
                            'comparison':reply.get('comparison'),'preferences':state.get('preferences') or reply.get('preferences'),
                            'profile_before':before if turn==1 else None,'profile_after':after,'registered_faculty':faculty,
                            'conversation_state':state,'progress':progress,'duration_seconds':round(time.monotonic()-t0,2),
                            'error':error,'context_seed_status':seed_status,'evaluation_note':r.get('evaluation_note')}
                    save(result)
                    print(f'{cid} run={run} turn={turn}: {result["status"]}, {len(result["listing_ids"])} IDs, {result["duration_seconds"]}s',flush=True)
                    if error:raise RuntimeError(f'{cid} failed; stop and inspect output: {error}')
    print('Saved:',jp,cp,sep='\n')

if __name__=='__main__':main()
