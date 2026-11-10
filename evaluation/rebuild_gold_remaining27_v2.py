#!/usr/bin/env python3
"""Rebuild profile-aware Gold for the 27 unsampled DSS5105 cases.
Independent of Agent responses. Strict unknown handling; never treats unknown as pass.
"""
import argparse, csv, hashlib, json, math, re
from pathlib import Path

NUMERIC = {'max_price_sgd':'rent_monthly_sgd_now','min_bedrooms':'bedrooms','max_mrt_minutes':'mrt_minutes_reported','max_mrt_distance_m':'mrt_distance_m','min_area_sqm':'area_sqm'}
UNKNOWN = {'','unknown','nan','none','null','n/a','not stated','not specified'}

def norm(v):
    return '' if v is None else str(v).strip()
def num(v):
    try:
        x=float(norm(v).replace(',',''))
        return x if math.isfinite(x) else None
    except (ValueError,TypeError): return None

def digest(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()

def read_json(p): return json.loads(Path(p).read_text(encoding='utf-8-sig'))

def csvrows(p):
    with open(p,encoding='utf-8-sig',newline='') as f: return list(csv.DictReader(f))

def build_commute(rows):
    result={}
    for r in rows:
        key=(norm(r['listing_id']),norm(r['faculty']).casefold())
        if key in result: raise ValueError('Duplicate commute key '+str(key))
        result[key]=num(r['minutes'])
    return result

def checks_for(row, constraints, faculty, commute):
    checks={}
    def add(key, val, expected, op):
        if val is None or norm(val).casefold() in UNKNOWN:
            checks[key]={'status':'UNKNOWN','actual':None,'expected':expected};return
        ok=op(val,expected)
        checks[key]={'status':'PASS' if ok else 'FAIL','actual':val,'expected':expected}
    for key,field in NUMERIC.items():
        if constraints.get(key) is not None and not (key=='min_bedrooms' and num(constraints[key])==0):
            value=(num(row.get('rent_monthly_sgd_now')) if num(row.get('rent_monthly_sgd_now')) is not None else num(row.get('rent_monthly_sgd'))) if key=='max_price_sgd' else num(row.get(field)); target=num(constraints[key]);
            if target is None:raise ValueError('Invalid constraint '+key)
            add(key,value,target,(lambda a,b:a>=b) if key.startswith('min_') else (lambda a,b:a<=b))
    if constraints.get('max_mrt_minutes') is not None or constraints.get('max_mrt_distance_m') is not None:
        station=norm(row.get('mrt_operation_status')).casefold()
        add('mrt_operating',station,'operational',lambda a,b:a in ('operational','operating','open'))
    for key in ('rental_scope','room_type','district_code'):
        if constraints.get(key) not in (None,'','any'):
            value=norm(row.get(key)).casefold(); target=norm(constraints[key]).casefold()
            add(key,value,target,lambda a,b:a==b)
    if constraints.get('private_bathroom_required'):
        value=norm(row.get('private_bathroom')).casefold()
        add('private_bathroom_required',value,'yes',lambda a,b:a in ('yes','true','private','ensuite','en-suite'))
    if constraints.get('occupant_count') is not None:
        # Occupant count is context for an entire unit, not an invented maximum-capacity gate.
        # No trusted maximum-occupancy field exists in the frozen snapshot.
        checks['occupant_count']={'status':'NOT_EVALUABLE','actual':norm(row.get('tenant_count_reported')) or None,'expected':constraints['occupant_count'],'note':'Informational only: tenant_count_reported is not maximum allowed occupancy. Explicit prohibitions require separate evidence.'}
    if constraints.get('max_commute_minutes') is not None:
        if not faculty:
            checks['max_commute_minutes']={'status':'UNKNOWN','actual':None,'expected':constraints['max_commute_minutes'],'note':'Faculty not specified'}
        else:
            minutes=commute.get((norm(row['listing_id']),faculty.casefold()))
            add('max_commute_minutes',minutes,num(constraints['max_commute_minutes']),lambda a,b:a<=b)
    if constraints.get('lease_months') is not None:
        term=norm(row.get('lease_term')).casefold(); target=int(constraints['lease_months'])
        # "Flexible" is unknown, not guaranteed to accept target term.
        matches=re.findall(r'\d+',term)
        if not term or term in UNKNOWN or 'flexib' in term or 'negotiab' in term:
            status='UNKNOWN'
        elif ('minimum' in term or 'min ' in term or 'at least' in term) and matches:
            status='PASS' if target>=int(matches[0]) else 'FAIL'
        elif re.fullmatch(r'\s*\d+\s*(month|months|mo|mths|year|years)?\s*',term):
            observed=int(matches[0])*(12 if 'year' in term else 1)
            status='PASS' if observed==target else 'FAIL'
        else: status='UNKNOWN'
        checks['lease_months']={'status':status,'actual':term or None,'expected':target,'note':'Conservative lease interpretation; verify ad before final scoring'}
    statuses=[v['status'] for v in checks.values() if v['status']!='NOT_EVALUABLE']
    result='FAIL' if 'FAIL' in statuses else 'UNKNOWN' if 'UNKNOWN' in statuses else 'PASS'
    return result,checks

def counts(records):
    return {status:sum(r['status']==status for r in records) for status in ('PASS','UNKNOWN','FAIL')}

def best_relaxation(rows, original, faculty, commute, field):
    """Enumerate one-field alternatives with explicit PASS vs UNKNOWN separation."""
    if field not in ('max_price_sgd','max_commute_minutes','lease_months'):
        return {'status':'NOT_SUPPORTED','reason':'Unsupported relaxation field'}
    if field=='max_commute_minutes' and not faculty:
        return {'status':'UNVERIFIABLE','reason':'Faculty missing'}
    if field=='lease_months':
        candidates=set()
        for row in rows:
            term=norm(row.get('lease_term')).lower()
            m=re.fullmatch(r'(\d+)\s*(months?|mo|mths|years?)',term)
            if m:
                value=int(m.group(1))*(12 if m.group(2).startswith('year') else 1)
                if value>int(original[field]): candidates.add(value)
        candidates=sorted(candidates)
    elif field=='max_price_sgd':
        candidates=sorted({v for row in rows if (v:=num(row.get('rent_monthly_sgd_now')) if num(row.get('rent_monthly_sgd_now')) is not None else num(row.get('rent_monthly_sgd'))) is not None and v>num(original[field])})
    else:
        candidates=sorted({v for row in rows if (v:=commute.get((norm(row['listing_id']),faculty.casefold()))) is not None and v>num(original[field])})
    first_unknown=None
    for value in candidates:
        changed=dict(original);changed[field]=value
        classified=[(norm(r['listing_id']),*checks_for(r,changed,faculty,commute)) for r in rows]
        passed=[lid for lid,status,_ in classified if status=='PASS']
        pending=[lid for lid,status,_ in classified if status=='UNKNOWN']
        if passed:
            return {'status':'FOUND','field':field,'original':original[field],
                    'minimum_relaxed_value':value,'confirmed_ids':passed,'confirmed_count':len(passed),
                    'needs_confirmation_ids':pending,'note':'One field changed; other explicit hard constraints held fixed; link availability not verified.'}
        if pending and first_unknown is None:
            first_unknown={'value':value,'ids':pending}
    return {'status':'NO_CONFIRMED_SINGLE_FIELD_RELAXATION','field':field,'original':original[field],
            'first_pending_relaxation':first_unknown,
            'note':'No fully confirmed solution; UNKNOWN candidates may exist and should not be called impossible.'}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--gold-queries',default='DSS5105_47_Gold_Answers.json')
    p.add_argument('--profiles27',default='remaining27_profiles_reviewed.json')
    p.add_argument('--listings',default='listings_active_430_exploration.csv')
    p.add_argument('--commute',default='commute_faculty.csv')
    p.add_argument('--rubric',default='gold_answers_remaining27_profile_based.json')
    p.add_argument('--out-dir',default='gold_remaining27_rebuilt')
    args=p.parse_args()
    original=read_json(args.gold_queries);profiles=read_json(args.profiles27);rubric=read_json(args.rubric)
    old={x['case_id']:x for x in original['answers']}
    rubric_cases={x['case_id']:x for x in rubric.get('cases',rubric.get('answers',[]))}
    if len(profiles)!=27 or set(profiles)!=set(rubric_cases):raise ValueError('Profiles/rubric mismatch; expected exactly same 27 IDs')
    listings=csvrows(args.listings);commute=build_commute(csvrows(args.commute))
    if len(listings)!=430:raise ValueError(f'Expected frozen 430 listings, got {len(listings)}')
    if len({norm(r['listing_id']) for r in listings})!=len(listings):raise ValueError('Duplicate listing IDs')
    out=Path(args.out_dir);out.mkdir(parents=True,exist_ok=True)
    results=[]; details=[]
    for cid in sorted(profiles):
        base=rubric_cases[cid].copy(); pr=profiles[cid]; old_case=old[cid]
        registered={'max_price_sgd':pr['Registered Budget SGD'],'rental_scope':pr['Registered Rental Scope'],'min_bedrooms':pr['Registered Min Bedrooms']}
        faculty=norm(pr.get('Registered Faculty'))
        if faculty.casefold() in ('','not selected','none','unknown'):faculty=None
        base['registered_profile_verified_from']=args.profiles27
        base['gold_version']='profile_aware_gold27_v2'
        base['registered_profile']=registered; base['registered_faculty']=faculty
        if cid[0] in 'ABC':
            # Query explicitly overrides registration. Never drop query hard constraints.
            constraints=dict(registered);constraints.update(old_case['gold_profile'])
            if faculty is None and constraints.get('max_commute_minutes') is not None:
                raise ValueError(f'{cid}: commute constraint has no Faculty')
            classified=[]
            for r in listings:
                status,checks=checks_for(r,constraints,faculty,commute)
                lid=norm(r['listing_id']);classified.append({'listing_id':lid,'status':status})
                details.append({'case_id':cid,'listing_id':lid,'status':status,'checks_json':json.dumps(checks,ensure_ascii=False)})
            sets={s:[r['listing_id'] for r in classified if r['status']==s] for s in ('PASS','UNKNOWN','FAIL')}
            base['effective_hard_constraints']=constraints
            base['gold_sets']={'confirmed_ids':sets['PASS'],'needs_confirmation_ids':sets['UNKNOWN'],'excluded_ids':sets['FAIL']}
            base['recomputed_counts']={s:len(sets[s]) for s in sets}
            base['numeric_status']='RECOMPUTED_CONSERVATIVE'
            if cid.startswith('C'):
                relax=old_case.get('relaxation') or {}; field=relax.get('target_field')
                base['single_field_relaxation']=best_relaxation(listings,constraints,faculty,commute,field) if field else {'status':'NOT_SPECIFIED'}
            if 'occupant_count' in constraints:
                base['occupancy_policy']='Informational for entire-unit cases; no verified capacity column; do not block PASS solely for unknown occupancy.'
            if 'lease_months' in constraints:
                base['lease_policy']='Exact stated lease term accepted as evidence; flexible/short-term/missing remains UNKNOWN; contract confirmation required.'
        else:
            base['numeric_status']='BEHAVIORAL_OR_EVIDENCE_GOLD_NO_LISTING_SET'
        # Remove outdated historical snapshot claims from normative scoring fields.
        for key in list(base):
            if key.startswith('historical_') or key in ('gold_evidence_status','review_note'):
                base.pop(key,None)
        if cid in ('C01','C02','C05','C06'):
            relax=base.get('single_field_relaxation',{})
            must=base.get('must',[])
            must=[s for s in must if not any(x in s.lower() for x in ('exact verified compromise','exact evidence-backed next step','verified sgd 3400 ceiling','sgd 750 as the exact','16-minute commute limit','12-month lease as the exact'))]
            must.append('Report strict confirmed matches and distinguish UNKNOWN from confirmed no-solution.')
            must.append('Offer a data-supported single-field compromise, explicitly labeled as a relaxation; do not silently relax other conditions.')
            if relax.get('status')=='FOUND':
                must.append('Evidence-backed minimum single-field relaxation in this snapshot: '+str(relax['field'])+' = '+str(relax['minimum_relaxed_value'])+'; alternative feasible values may also be acceptable unless the query explicitly requires the smallest adjustment.')
            base['must']=list(dict.fromkeys(must))
        base['score_status']='NOT_SCORED'
        results.append(base)
    output={'metadata':{'version':'profile_aware_gold27_rebuilt_v2','count':len(results),'listings':len(listings),'source_sha256':{k:digest(getattr(args,k)) for k in ('gold_queries','profiles27','listings','commute','rubric')},'policy':'Unknown is not pass. Occupancy is non-gating background absent verified max-capacity evidence. Snapshot only; no Agent output used. No live-ad provenance inferred.'},'cases':results}
    (out/'gold_remaining27_rebuilt.json').write_text(json.dumps(output,ensure_ascii=False,indent=2),encoding='utf-8')
    with (out/'gold_listing_checks_7cases.csv').open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=['case_id','listing_id','status','checks_json']);w.writeheader();w.writerows(details)
    with (out/'gold_summary_27.csv').open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=['case_id','category','numeric_status','pass_count','unknown_count','fail_count','relaxation_status','relaxation_value','score_status']);w.writeheader()
        for c in results:
            n=c.get('recomputed_counts',{});r=c.get('single_field_relaxation',{})
            w.writerow({'case_id':c['case_id'],'category':c['case_id'][0],'numeric_status':c['numeric_status'],'pass_count':n.get('PASS',''),'unknown_count':n.get('UNKNOWN',''),'fail_count':n.get('FAIL',''),'relaxation_status':r.get('status',''),'relaxation_value':r.get('minimum_relaxed_value',''),'score_status':'NOT_SCORED'})
    # Single 47-case deliverable: preserve previously audited 20 cases unchanged,
    # while replacing the remaining 27 with recomputed profile-aware cases.
    updated={c['case_id']:c for c in results}
    merged=[]
    for case in original['answers']:
        cid=case['case_id']
        if cid in updated:
            merged.append(updated[cid])
        else:
            old_case=dict(case)
            old_case['gold_version']='prior_20_preserved'
            old_case['verification_scope']='Previously audited 20; not recomputed by this 27-case script. Use separate Gold Audit and human ranking files.'
            merged.append(old_case)
    if len(merged)!=47 or len({c['case_id'] for c in merged})!=47:
        raise ValueError('Merged Gold must contain 47 unique cases')
    full={'metadata':{'version':'DSS5105_47_Gold_Consolidated_v2',
           'case_count':47,'recomputed_profile_aware_cases':27,'preserved_prior_cases':20,
           'source_sha256':output['metadata']['source_sha256'],
           'warning':'The previous 20 cases are preserved, not re-audited; 27-case recalculation is independent of Agent outputs. No raw-ad provenance or live availability verified.'},
           'answers':merged}
    (out/'DSS5105_47_Gold_Consolidated_v2.json').write_text(json.dumps(full,ensure_ascii=False,indent=2),encoding='utf-8')
    (out/'README.txt').write_text('Profile-aware Gold v2. Includes DSS5105_47_Gold_Consolidated_v2.json with 20 previous cases preserved (not re-audited). A/B/C independently checked; D/E/F/H behavioral/evidence rubrics retained. Occupant count is background (no verified max occupancy); explicit bedrooms stay explicit. UNKNOWN never counts as PASS. Flexible/short-term lease remains UNKNOWN. All minimum relaxations are illustrative unless query requires minimum. No Agent API calls.\n',encoding='utf-8')
    print(f'Wrote {len(results)} cases, {len(details)} listing audits; outputs: {out}')
    for c in results:
        if c['case_id'][0] in 'ABC':print(c['case_id'],c['recomputed_counts'],c.get('single_field_relaxation',{}).get('status',''))
if __name__=='__main__':main()
