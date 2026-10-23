"""How many OneMap routing calls a minute this account gets, for ONEMAP_CALLS_PER_MINUTE in .env.

    python check_onemap_rate.py         # up to 300 walking routes in one minute, 6 at a time

The backend works out routes to a place a user names (place_routes.py) at ONEMAP_CALLS_PER_MINUTE,
240 without it. This asks OneMap for a short walking route as fast as six requests at a time allow,
for at most a minute or 300 calls, and stops at the first "too many requests" (HTTP 429). It prints
how many calls got through and a value to put in .env. The token is loaded as the backend loads it
and never printed. Run it once, not while the backend is busy working out routes.
"""

import threading
import time
from concurrent.futures import ThreadPoolExecutor

from faculties import find_faculty
from onemap import OneMapError, load_token, walking_minutes

_CALLS = 300
_SECONDS = 60
_WORKERS = 6


def main() -> int:
    try:
        token = load_token()
    except OneMapError as error:
        print(f"拿不到 OneMap token：{error}")
        return 1
    # A short walk on campus: from the School of Computing to the Business School.
    start, end = (find_faculty(name) for name in ("School of Computing", "NUS Business School"))
    route = ((start["latitude"], start["longitude"]), (end["latitude"], end["longitude"]))
    lock = threading.Lock()
    done, limited, other_errors = [], [], []
    began = time.monotonic()

    def call(_):
        if limited or time.monotonic() - began > _SECONDS:
            return
        try:
            walking_minutes(*route, token)
        except OneMapError as error:
            with lock:
                (limited if "HTTP 429" in str(error) else other_errors).append((time.monotonic() - began, str(error)[:120]))
            return
        with lock:
            done.append(time.monotonic() - began)

    with ThreadPoolExecutor(max_workers=_WORKERS) as pool:
        list(pool.map(call, range(_CALLS)))
    elapsed = time.monotonic() - began
    if other_errors:
        print(f"有 {len(other_errors)} 次调用出错（不是限流）：{other_errors[0][1]}")
    if limited:
        at = limited[0][0]
        print(f"开始后 {at:.1f} 秒被 OneMap 限流（HTTP 429），之前成功 {len(done)} 次。")
        per_minute = len(done) if at <= 60 else round(len(done) * 60 / at)
        print(f"上限大约是每分钟 {per_minute} 次。建议在 .env 里写 ONEMAP_CALLS_PER_MINUTE={max(int(per_minute * 0.9), 1)}")
    else:
        rate = round(len(done) * 60 / elapsed) if elapsed else len(done)
        print(f"{elapsed:.1f} 秒内成功 {len(done)} 次，没有被限流，相当于每分钟约 {rate} 次。")
        print("上限至少是这么多；保持默认的 240，或者按这个结果写 ONEMAP_CALLS_PER_MINUTE。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
