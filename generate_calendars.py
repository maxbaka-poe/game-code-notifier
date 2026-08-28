#!/usr/bin/env python3
"""Generate subscribable iCalendar feeds for four live-service games."""

from __future__ import annotations

import hashlib
import html
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path
from zoneinfo import ZoneInfo


OUTPUT_DIR = Path(__file__).parent / "public"
USER_AGENT = "Mozilla/5.0 (compatible; GameEventCalendar/1.0; +https://github.com/)"
JST = ZoneInfo("Asia/Tokyo")
ENDFIELD_SOURCE = "https://game8.jp/arknights-endfield/758288"

GAMES = {
    "genshin": {"name": "原神", "api": "genshin", "color": "#4ea4c8"},
    "starrail": {"name": "崩壊：スターレイル", "api": "starrail", "color": "#8b78d0"},
    "zenless": {"name": "ゼンレスゾーンゼロ", "api": "zenless", "color": "#f2a900"},
    "endfield": {"name": "アークナイツ：エンドフィールド", "color": "#d35d4b"},
}


@dataclass(frozen=True)
class Event:
    game: str
    event_id: str
    title: str
    start: datetime
    end: datetime
    category: str = "イベント"
    description: str = ""
    url: str = ""


def request_bytes(url: str, *, attempts: int = 3) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return response.read()
        except (urllib.error.URLError, TimeoutError) as exc:
            last_error = exc
            if attempt + 1 < attempts:
                time.sleep(2**attempt)
    raise RuntimeError(f"取得に失敗しました: {url}: {last_error}")


def timestamp(value: object) -> datetime | None:
    if value is None:
        return None
    try:
        return datetime.fromtimestamp(int(value), UTC)
    except (TypeError, ValueError, OSError):
        return None


def fetch_hoyo_events(game: str, api_game: str) -> list[Event]:
    url = f"https://api.ennead.cc/mihoyo/{api_game}/calendar?lang=ja-jp"
    payload = json.loads(request_bytes(url).decode("utf-8"))
    result: list[Event] = []
    sections = (("events", "イベント"), ("banners", "跳躍・変調・祈願"), ("challenges", "定期コンテンツ"))
    for section, category in sections:
        for index, item in enumerate(payload.get(section, [])):
            start = timestamp(item.get("start_time"))
            end = timestamp(item.get("end_time"))
            if not start or not end or end <= start:
                continue
            title = str(item.get("name") or item.get("title") or "").strip()
            if not title:
                if item.get("agents"):
                    title = " / ".join(str(x.get("name", "")) for x in item["agents"] if x.get("name"))
                elif item.get("characters"):
                    title = " / ".join(str(x.get("name", "")) for x in item["characters"] if x.get("name"))
            if not title:
                title = f"{category} {index + 1}"
            raw_id = item.get("id") or item.get("banner_type") or index
            result.append(
                Event(
                    game=game,
                    event_id=f"{section}-{raw_id}-{int(start.timestamp())}",
                    title=title,
                    start=start,
                    end=end,
                    category=category,
                    description=str(item.get("description") or "").strip(),
                    url=url,
                )
            )
    return result


class TableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.in_row = False
        self.in_cell = False
        self.cell_text: list[str] = []
        self.row: list[str] = []
        self.rows: list[list[str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "tr":
            self.in_row = True
            self.row = []
        elif self.in_row and tag in {"td", "th"}:
            self.in_cell = True
            self.cell_text = []
        elif self.in_cell and tag == "img":
            alt = dict(attrs).get("alt") or ""
            if alt:
                self.cell_text.append(alt)

    def handle_data(self, data: str) -> None:
        if self.in_cell:
            text = " ".join(data.split())
            if text:
                self.cell_text.append(text)

    def handle_endtag(self, tag: str) -> None:
        if tag in {"td", "th"} and self.in_cell:
            self.row.append(" ".join(self.cell_text).strip())
            self.in_cell = False
        elif tag == "tr" and self.in_row:
            if self.row:
                self.rows.append(self.row)
            self.in_row = False


DATE_RANGE = re.compile(
    r"(?P<sy>20\d{2})/(?P<sm>\d{1,2})/(?P<sd>\d{1,2})"
    r"(?:\([^)]*\))?\s*(?P<sh>\d{1,2}):(?P<smin>\d{2})\s*"
    r"[~〜～]\s*"
    r"(?P<ey>20\d{2})/(?P<em>\d{1,2})/(?P<ed>\d{1,2})"
    r"(?:\([^)]*\))?\s*(?P<eh>\d{1,2}):(?P<emin>\d{2})"
)


def fetch_endfield_events() -> list[Event]:
    page = request_bytes(ENDFIELD_SOURCE).decode("utf-8", "replace")
    marker = page.find(">期間限定イベント一覧</h2>")
    table_start = page.find("<table", marker)
    table_end = page.find("</table>", table_start)
    if marker < 0 or table_start < 0 or table_end < 0:
        raise RuntimeError("エンドフィールドのイベント表を発見できませんでした")
    parser = TableParser()
    parser.feed(page[table_start : table_end + len("</table>")])
    result: list[Event] = []
    for row in parser.rows:
        if len(row) < 2:
            continue
        title = re.sub(r"画像.*$", "", html.unescape(row[0])).strip()
        details = html.unescape(" ".join(row[1:]))
        match = DATE_RANGE.search(details)
        if not title or not match:
            continue
        values = {key: int(value) for key, value in match.groupdict().items()}
        start = datetime(values["sy"], values["sm"], values["sd"], values["sh"], values["smin"], tzinfo=JST)
        end = datetime(values["ey"], values["em"], values["ed"], values["eh"], values["emin"], tzinfo=JST)
        event_id = hashlib.sha256(f"{title}|{start.isoformat()}|{end.isoformat()}".encode()).hexdigest()[:20]
        result.append(
            Event(
                game="endfield",
                event_id=event_id,
                title=title,
                start=start.astimezone(UTC),
                end=end.astimezone(UTC),
                description=details[:800],
                url=ENDFIELD_SOURCE,
            )
        )
    if not result:
        raise RuntimeError("エンドフィールドの期間付きイベントが0件でした")
    return result


def ics_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\n", "\\n").replace(",", "\\,").replace(";", "\\;")


def fold(line: str) -> list[str]:
    # iCalendar recommends 75 octets. Folding by characters is safe for UTF-8 readers
    # and avoids splitting a multibyte character.
    chunks: list[str] = []
    current = ""
    current_bytes = 0
    for char in line:
        size = len(char.encode("utf-8"))
        if current and current_bytes + size > 70:
            chunks.append(current)
            current = " " + char
            current_bytes = 1 + size
        else:
            current += char
            current_bytes += size
    chunks.append(current)
    return chunks


def format_utc(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")


def render_ics(name: str, events: list[Event], generated_at: datetime) -> str:
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Game Event Calendar//JA//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{ics_escape(name)}",
        "X-WR-TIMEZONE:Asia/Tokyo",
        "REFRESH-INTERVAL;VALUE=DURATION:PT6H",
        "X-PUBLISHED-TTL:PT6H",
    ]
    for event in sorted(events, key=lambda item: (item.start, item.end, item.title)):
        game_name = str(GAMES[event.game]["name"])
        description = f"種別: {event.category}"
        if event.description:
            description += f"\n{event.description}"
        lines.extend(
            [
                "BEGIN:VEVENT",
                f"UID:{event.game}-{event.event_id}@game-event-calendar",
                f"DTSTAMP:{format_utc(generated_at)}",
                f"DTSTART:{format_utc(event.start)}",
                f"DTEND:{format_utc(event.end)}",
                f"SUMMARY:{ics_escape(f'【{game_name}】{event.title}')}",
                f"DESCRIPTION:{ics_escape(description)}",
                f"CATEGORIES:{ics_escape(game_name)},{ics_escape(event.category)}",
                f"URL:{ics_escape(event.url)}",
                "STATUS:CONFIRMED",
                "TRANSP:TRANSPARENT",
                "END:VEVENT",
            ]
        )
    lines.append("END:VCALENDAR")
    folded = [part for line in lines for part in fold(line)]
    return "\r\n".join(folded) + "\r\n"


def render_index(counts: dict[str, int], updated: datetime) -> str:
    cards = []
    for game, meta in GAMES.items():
        cards.append(
            f'<li style="border-left:6px solid {meta["color"]}"><b>{html.escape(str(meta["name"]))}</b>'
            f'<span>{counts.get(game, 0)}件</span><a href="{game}.ics">ICS URL</a></li>'
        )
    return f"""<!doctype html>
<html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>ゲームイベントカレンダー</title><style>
body{{font-family:system-ui,sans-serif;max-width:760px;margin:40px auto;padding:0 18px;color:#222}}
ul{{list-style:none;padding:0}}li{{display:grid;grid-template-columns:1fr auto auto;gap:18px;padding:16px;margin:12px 0;background:#f5f5f5}}
a{{color:#0969da}}code{{background:#eee;padding:2px 5px}}small{{color:#666}}
</style></head><body><h1>ゲームイベントカレンダー</h1>
<p>Googleカレンダーの「他のカレンダー」→「URLで追加」に、リンク先URLを登録してください。</p>
<h2>まとめカレンダー</h2>
<ul>
<li style="border-left:6px solid #7857c8"><b>HoYoverse 3作品</b><span>{sum(counts.get(game, 0) for game in ('genshin', 'starrail', 'zenless'))}件</span><a href="hoyoverse.ics">ICS URL</a></li>
<li style="border-left:6px solid {GAMES['endfield']['color']}"><b>アークナイツ：エンドフィールド</b><span>{counts.get('endfield', 0)}件</span><a href="endfield.ics">ICS URL</a></li>
</ul>
<h2>作品別カレンダー</h2><ul>{''.join(cards)}</ul>
<p><small>最終生成: {updated.astimezone(JST).strftime('%Y-%m-%d %H:%M JST')}</small></p>
<p><small>ファン作成の非公式カレンダーです。日時は情報源の更新やメンテナンスで変更される場合があります。</small></p>
</body></html>"""


def main() -> int:
    generated_at = datetime.now(UTC)
    by_game: dict[str, list[Event]] = {game: [] for game in GAMES}
    failures: list[str] = []
    for game in ("genshin", "starrail", "zenless"):
        try:
            by_game[game] = fetch_hoyo_events(game, str(GAMES[game]["api"]))
        except Exception as exc:
            failures.append(f"{GAMES[game]['name']}: {exc}")
    try:
        by_game["endfield"] = fetch_endfield_events()
    except Exception as exc:
        failures.append(f"{GAMES['endfield']['name']}: {exc}")

    if failures:
        raise RuntimeError("イベント取得エラー\n" + "\n".join(failures))

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    # The former four-game feed is intentionally removed: Endfield and
    # HoYoverse calendars are published separately.
    (OUTPUT_DIR / "all.ics").unlink(missing_ok=True)
    hoyoverse_events: list[Event] = []
    all_events: list[Event] = []
    for game, events in by_game.items():
        all_events.extend(events)
        if game != "endfield":
            hoyoverse_events.extend(events)
        (OUTPUT_DIR / f"{game}.ics").write_text(
            render_ics(f"ゲームイベント：{GAMES[game]['name']}", events, generated_at), encoding="utf-8", newline=""
        )
    (OUTPUT_DIR / "hoyoverse.ics").write_text(
        render_ics("ゲームイベント：HoYoverse 3作品", hoyoverse_events, generated_at), encoding="utf-8", newline=""
    )
    (OUTPUT_DIR / "index.html").write_text(
        render_index({game: len(events) for game, events in by_game.items()}, generated_at), encoding="utf-8"
    )
    print(f"Generated {len(all_events)} events: " + ", ".join(f"{game}={len(events)}" for game, events in by_game.items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
