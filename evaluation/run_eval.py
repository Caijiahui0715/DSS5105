"""Run DSS5105 evaluation cases against the real FastAPI server.

Requires a running `python server.py` and an existing, dedicated evaluation account.
No agent internals are imported. Saves every turn's raw reply and recommendation data.
"""
import argparse
import csv
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def request_json(base, method, path, payload=None, token=None, timeout=30):
    data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode('utf-8')
    headers = {'Accept': 'application/json'}
    if data is not None:
        headers['Content-Type'] = 'application/json'
    if token:
        headers['Authorization'] = 'Bearer ' + token
    req = Request(base + path, data=data, headers=headers, method=method)
    try:
        with urlopen(req, timeout=timeout) as res:
            return json.loads(res.read().decode('utf-8'))
    except HTTPError as e:
        raise RuntimeError(f'{method} {path}: HTTP {e.code}: {e.read().decode("utf-8", "replace")[:400]}') from e


def send_sse(base, thread_id, message, language, token, timeout):
    path = f'/api/conversations/{thread_id}/messages'
    payload = json.dumps({'message': message, 'language': language}, ensure_ascii=False).encode('utf-8')
    req = Request(base + path, data=payload, headers={
        'Authorization': 'Bearer ' + token,
        'Content-Type': 'application/json',
        'Accept': 'text/event-stream',
    }, method='POST')
    event_name = None
    data_lines = []
    progress = []
    reply = None
    error = None

    def consume():
        nonlocal event_name, data_lines, reply, error
        if not data_lines:
            event_name = None
            return
        raw = '\n'.join(data_lines)
        try:
            value = json.loads(raw)
        except json.JSONDecodeError:
            value = raw
        if event_name == 'progress':
            progress.append(value)
        elif event_name == 'reply':
            reply = value
        elif event_name == 'error':
            error = value
        event_name, data_lines = None, []

    try:
        with urlopen(req, timeout=timeout) as res:
            for raw_line in res:
                line = raw_line.decode('utf-8', 'replace').rstrip('\r\n')
                if not line:
                    consume()
                    if reply is not None or error is not None:
                        break
                elif line.startswith('event:'):
                    event_name = line[6:].strip()
                elif line.startswith('data:'):
                    data_lines.append(line[5:].lstrip())
            consume()
    except HTTPError as e:
        raise RuntimeError(f'POST {path}: HTTP {e.code}: {e.read().decode("utf-8", "replace")[:400]}') from e
    if error is not None:
        raise RuntimeError(f'Agent error event: {error}')
    if reply is None:
        raise RuntimeError('No SSE reply event received (connection ended or timed out).')
    return reply, progress


def listing_ids(recommendations):
    """Best-effort ID extraction; full raw recommendations are always retained."""
    ids = []
    def walk(obj):
        if isinstance(obj, dict):
            if obj.get('listing_id') is not None:
                ids.append(str(obj['listing_id']))
            for key, value in obj.items():
                if key != 'listing_id' and isinstance(value, (dict, list)):
                    walk(value)
        elif isinstance(obj, list):
            for value in obj:
                walk(value)
    walk(recommendations)
    return list(dict.fromkeys(ids))


def main():
    p = argparse.ArgumentParser(description='Call the real DSS5105 Agent and save evaluation responses.')
    p.add_argument('--cases', default='cases_DEFGH.json')
    p.add_argument('--base-url', default='http://127.0.0.1:8000')
    p.add_argument('--language', choices=['zh', 'en'], default='en')
    p.add_argument('--runs', type=int, default=1)
    p.add_argument('--limit', type=int, default=0, help='Only the first N cases; 0 means all')
    p.add_argument('--ids', nargs='*', help='Optional case IDs, e.g. D01 G02')
    p.add_argument('--timeout', type=int, default=240)
    p.add_argument('--out-dir', default='eval_runs')
    p.add_argument('--faculty', help='Optional exact faculty name from GET /api/faculties')
    args = p.parse_args()
    if args.runs < 1 or args.limit < 0:
        p.error('--runs must be >= 1 and --limit must be >= 0')
    username = os.getenv('EVAL_USERNAME')
    password = os.getenv('EVAL_PASSWORD')
    if not username or not password:
        p.error('Set EVAL_USERNAME and EVAL_PASSWORD for an existing, dedicated test account (not your personal account).')
    base = args.base_url.rstrip('/')
    cases = json.loads(Path(args.cases).read_text(encoding='utf-8'))
    if args.ids:
        wanted = set(args.ids)
        cases = [case for case in cases if case['id'] in wanted]
        missing = wanted - {case['id'] for case in cases}
        if missing:
            p.error('Unknown case IDs: ' + ', '.join(sorted(missing)))
    if args.limit:
        cases = cases[:args.limit]
    if not cases:
        p.error('No cases selected')

    login = request_json(base, 'POST', '/api/token', {'username': username, 'password': password})
    token = login['token']
    if args.faculty:
        request_json(base, 'PUT', '/api/me/faculty', {'faculty': args.faculty}, token)
    # Dedicated test account only: prevent long-term memory from influencing new cases.
    request_json(base, 'PUT', '/api/me/auto-save', {'on': False}, token)
    request_json(base, 'PUT', '/api/me/memory', {'on': False}, token)

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    jsonl_path = out / f'agent_results_{stamp}.jsonl'
    csv_path = out / f'agent_results_{stamp}.csv'
    cols = ['case_id', 'category', 'run', 'turn', 'thread_id', 'query', 'status', 'listing_ids', 'agent_response', 'preferences', 'error']
    count = 0
    with jsonl_path.open('w', encoding='utf-8') as jf, csv_path.open('w', newline='', encoding='utf-8-sig') as cf:
        writer = csv.DictWriter(cf, fieldnames=cols)
        writer.writeheader()
        for case in cases:
            turns = case.get('turns_en' if args.language == 'en' else 'turns') or case.get('turns') or []
            for run in range(1, args.runs + 1):
                thread_id = None
                try:
                    created = request_json(base, 'POST', '/api/conversations', {'language': args.language}, token)
                    thread_id = created['id']
                except Exception as e:
                    print(f'ERROR {case["id"]} run {run}: cannot create conversation: {e}', file=sys.stderr)
                    continue
                for turn, query in enumerate(turns, 1):
                    start = time.monotonic()
                    reply = None
                    progress = []
                    error = None
                    state = None
                    try:
                        reply, progress = send_sse(base, thread_id, query, args.language, token, args.timeout)
                        state = request_json(base, 'GET', f'/api/conversations/{thread_id}', token=token)
                    except (RuntimeError, URLError, TimeoutError, OSError) as e:
                        error = str(e)
                    recommendations = (reply or {}).get('recommendations')
                    record = {
                        'case_id': case['id'], 'category': case['category'], 'run': run, 'turn': turn,
                        'thread_id': thread_id, 'query': query,
                        'status': 'ok' if error is None else 'error',
                        'agent_response': (reply or {}).get('text'),
                        'listing_ids': listing_ids(recommendations),
                        'recommendations': recommendations,
                        'comparison': (reply or {}).get('comparison'),
                        'preferences': (reply or {}).get('preferences'),
                        'steps': (reply or {}).get('steps'),
                        'progress': progress,
                        'conversation_state': state,
                        'duration_seconds': round(time.monotonic() - start, 2),
                        'error': error,
                    }
                    jf.write(json.dumps(record, ensure_ascii=False, default=str) + '\n')
                    jf.flush()
                    writer.writerow({
                        'case_id': case['id'], 'category': case['category'], 'run': run,
                        'turn': turn, 'thread_id': thread_id, 'query': query,
                        'status': record['status'],
                        'listing_ids': ';'.join(record['listing_ids']),
                        'agent_response': record['agent_response'] or '',
                        'preferences': json.dumps(record['preferences'], ensure_ascii=False, default=str),
                        'error': error or '',
                    })
                    cf.flush()
                    count += 1
                    print(f'{case["id"]} run={run} turn={turn}: {record["status"]}, {len(record["listing_ids"])} IDs, {record["duration_seconds"]}s', flush=True)
                    if error:
                        break
    print(f'Finished {count} turns.\nJSONL: {jsonl_path}\nCSV:   {csv_path}')
    print('No automatic scores have been assigned. Review recommendation structures and human-score outputs before grading.')


if __name__ == '__main__':
    main()
