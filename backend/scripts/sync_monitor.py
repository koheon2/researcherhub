"""
sync_researchers 진행상황 모니터 — http://localhost:9999
"""
import json
import re
import subprocess
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

PROGRESS_FILE = Path(__file__).resolve().parent.parent / "data" / "sync_progress.json"
LOG_FILE = Path("/tmp/sync_researchers.log")
TOTAL_FILES = 546


def parse_log():
    if not LOG_FILE.exists():
        return []
    lines = LOG_FILE.read_text(errors="replace").splitlines()
    start_idx = 0
    for i, l in enumerate(lines):
        if "Starting sync" in l:
            start_idx = i
    return lines[start_idx:]


def get_stats():
    lines = parse_log()

    done_count = 0
    if PROGRESS_FILE.exists():
        try:
            done_count = len(json.loads(PROGRESS_FILE.read_text()).get("done", []))
        except Exception:
            pass

    grand_kept = 0
    eta_min = 0
    for l in reversed(lines):
        m = re.search(r"(\d[\d,]*) CS researchers so far.*ETA: (\d+)min", l)
        if m:
            grand_kept = int(m.group(1).replace(",", ""))
            eta_min = int(m.group(2))
            break

    # 파일 처리 로그 파싱 — 속도 계산용
    file_entries = []  # (timestamp, elapsed_sec, total_records, kept, fname)
    for l in lines:
        m = re.search(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}).*\[(.+?)\] ([\d,]+) → ([\d,]+) CS.*in (\d+)s", l)
        if m:
            try:
                ts = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S")
                file_entries.append({
                    "ts": ts,
                    "fname": m.group(2),
                    "total": int(m.group(3).replace(",", "")),
                    "kept": int(m.group(4).replace(",", "")),
                    "elapsed": int(m.group(5)),
                })
            except Exception:
                pass

    # 최근 10개 파일 기반 처리 속도 (records/s, MB/s 추정)
    recent_entries = file_entries[-10:]
    records_per_sec = 0
    mbps = 0
    if len(recent_entries) >= 2:
        total_records = sum(e["total"] for e in recent_entries)
        total_elapsed = sum(e["elapsed"] for e in recent_entries)
        if total_elapsed > 0:
            records_per_sec = total_records / total_elapsed
            # gzip JSON 기준 약 300 bytes/record 추정
            mbps = records_per_sec * 300 / 1024 / 1024

    # stall 감지: 마지막 로그 업데이트 이후 경과 시간
    stall_sec = 0
    last_log_ts = None
    if file_entries:
        last_log_ts = file_entries[-1]["ts"]
        stall_sec = (datetime.now() - last_log_ts).total_seconds()

    running = bool(subprocess.run(
        ["pgrep", "-f", "sync_researchers_from_s3"],
        capture_output=True
    ).stdout.strip())

    return {
        "done": done_count,
        "total": TOTAL_FILES,
        "pending": TOTAL_FILES - done_count,
        "pct": round(done_count / TOTAL_FILES * 100, 1),
        "researchers": grand_kept,
        "eta_min": eta_min,
        "running": running,
        "records_per_sec": round(records_per_sec),
        "mbps": round(mbps, 2),
        "stall_sec": round(stall_sec),
        "last_log_ts": last_log_ts.strftime("%H:%M:%S") if last_log_ts else "-",
        "recent": file_entries[-20:],
    }


HTML = """<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta http-equiv="refresh" content="10">
<title>Sync Monitor</title>
<style>
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{ background: #0a0a0f; color: #e0e0e0; font-family: 'Courier New', monospace; padding: 24px; }}
h1 {{ color: #7dd3fc; font-size: 1.4rem; margin-bottom: 16px; }}
.badges {{ display: flex; gap: 10px; margin-bottom: 20px; align-items: center; }}
.status {{ display: inline-block; padding: 3px 10px; border-radius: 12px; font-size: 0.75rem; }}
.running {{ background: #064e3b; color: #34d399; }}
.stopped {{ background: #450a0a; color: #f87171; }}
.stall {{ background: #451a03; color: #fb923c; }}
.grid {{ display: grid; grid-template-columns: repeat(5, 1fr); gap: 12px; margin-bottom: 20px; }}
.card {{ background: #111827; border: 1px solid #1f2937; border-radius: 8px; padding: 14px; }}
.card .label {{ color: #6b7280; font-size: 0.72rem; margin-bottom: 5px; text-transform: uppercase; letter-spacing: 0.05em; }}
.card .value {{ font-size: 1.5rem; font-weight: bold; color: #f9fafb; }}
.card .sub {{ color: #9ca3af; font-size: 0.75rem; margin-top: 4px; }}
.card.warn .value {{ color: #fb923c; }}
.progress-bar {{ background: #1f2937; border-radius: 4px; height: 8px; margin-bottom: 20px; overflow: hidden; }}
.progress-fill {{ background: linear-gradient(90deg, #3b82f6, #7c3aed); height: 100%; border-radius: 4px; }}
.log {{ background: #111827; border: 1px solid #1f2937; border-radius: 8px; padding: 14px; max-height: 420px; overflow-y: auto; }}
.log-title {{ color: #6b7280; font-size: 0.72rem; text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 10px; }}
.line {{ font-size: 0.76rem; color: #9ca3af; line-height: 1.7; display: flex; gap: 10px; }}
.line .ts {{ color: #4b5563; min-width: 70px; }}
.line .fname {{ color: #60a5fa; min-width: 220px; }}
.line .speed {{ color: #a78bfa; min-width: 70px; text-align: right; }}
.kept {{ color: #34d399; }}
.zero {{ color: #374151; }}
.footer {{ color: #4b5563; font-size: 0.7rem; margin-top: 16px; display: flex; gap: 20px; }}
</style>
</head>
<body>
<h1>ResearcherHub Sync Monitor</h1>
<div class="badges">
  <span class="status {status_cls}">{status_txt}</span>
  {stall_badge}
</div>
<div class="grid">
  <div class="card">
    <div class="label">완료 파일</div>
    <div class="value">{done}</div>
    <div class="sub">/ {total} 파일</div>
  </div>
  <div class="card">
    <div class="label">진행률</div>
    <div class="value">{pct}%</div>
    <div class="sub">{pending} 파일 남음</div>
  </div>
  <div class="card">
    <div class="label">수집 연구자</div>
    <div class="value">{researchers_fmt}</div>
    <div class="sub">CS/AI 필터 통과</div>
  </div>
  <div class="card {speed_warn}">
    <div class="label">처리 속도</div>
    <div class="value">{records_per_sec_fmt}</div>
    <div class="sub">records/s · {mbps} MB/s est.</div>
  </div>
  <div class="card">
    <div class="label">예상 완료까지</div>
    <div class="value">{eta_h}h {eta_m}m</div>
    <div class="sub">마지막 갱신 {last_log_ts}</div>
  </div>
</div>
<div class="progress-bar"><div class="progress-fill" style="width:{pct}%"></div></div>
<div class="log">
  <div class="log-title">최근 처리 파일 (최신순)</div>
  {log_lines}
</div>
<div class="footer">
  <span>페이지 갱신: {ts}</span>
  <span>스트리밍 방식 (다운로드 + 필터링 동시)</span>
</div>
</body>
</html>"""


def render(stats):
    log_html = ""
    for e in reversed(stats["recent"]):
        rec_per_s = round(e["total"] / e["elapsed"]) if e["elapsed"] > 0 else 0
        cls = "kept" if e["kept"] > 0 else "zero"
        log_html += (
            f'<div class="line">'
            f'<span class="ts">{e["ts"].strftime("%H:%M:%S")}</span>'
            f'<span class="fname">{e["fname"]}</span>'
            f'<span>{e["total"]:,} → <span class="{cls}">{e["kept"]:,} CS</span></span>'
            f'<span class="speed">{rec_per_s:,}/s</span>'
            f'<span style="color:#4b5563">{e["elapsed"]}s</span>'
            f'</div>\n'
        )

    stall_badge = ""
    if stats["running"] and stats["stall_sec"] > 120:
        mins = stats["stall_sec"] // 60
        stall_badge = f'<span class="status stall">⚠ {mins}분째 응답 없음 — S3 hang 의심</span>'

    return HTML.format(
        status_cls="running" if stats["running"] else "stopped",
        status_txt="● 실행 중" if stats["running"] else "○ 정지됨",
        stall_badge=stall_badge,
        done=stats["done"],
        total=stats["total"],
        pct=stats["pct"],
        pending=stats["pending"],
        researchers_fmt=f"{stats['researchers']:,}",
        records_per_sec_fmt=f"{stats['records_per_sec']:,}",
        mbps=stats["mbps"],
        speed_warn="warn" if stats["records_per_sec"] < 500 and stats["running"] else "",
        eta_h=stats["eta_min"] // 60,
        eta_m=stats["eta_min"] % 60,
        last_log_ts=stats["last_log_ts"],
        log_lines=log_html or '<div class="line" style="color:#4b5563">로그 없음</div>',
        ts=time.strftime("%H:%M:%S"),
    )


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def do_GET(self):
        if self.path == "/api":
            body = json.dumps(get_stats(), ensure_ascii=False, default=str).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
        else:
            body = render(get_stats()).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    port = 9999
    print(f"Monitor → http://localhost:{port}")
    HTTPServer(("", port), Handler).serve_forever()
