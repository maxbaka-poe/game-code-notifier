#!/usr/bin/env python3
"""Notify Discord when new redemption codes appear."""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from html.parser import HTMLParser
from pathlib import Path


STATE_PATH = Path(__file__).parent / "data" / "seen_codes.json"
USER_AGENT = "Mozilla/5.0 (compatible; GameCodeNotifier/1.0; +https://github.com/)"

HOYO_GAMES = {
    "genshin": {
        "name": "原神",
        "api_game": "genshin",
        "color": 0x4EA4C8,
        "redeem": "https://genshin.hoyoverse.com/ja/gift?code={code}",
    },
    "starrail": {
        "name": "崩壊：スターレイル",
        "api_game": "hkrpg",
        "color": 0x8B78D0,
        "redeem": "https://hsr.hoyoverse.com/gift?code={code}",
    },
    "zenless": {
        "name": "ゼンレスゾーンゼロ",
        "api_game": "nap",
        "color": 0xF2A900,
        "redeem": "https://zenless.hoyoverse.com/redemption?code={code}",
    },
}

ENDFIELD_SOURCE = "https://game8.jp/arknights-endfield/751279"


@dataclass(frozen=True)
class Code:
    game: str
    value: str
    rewards: str = ""
    note: str = ""
    source: str = ""


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
                time.sleep(2 ** attempt)
    raise RuntimeError(f"取得に失敗しました: {url}: {last_error}")


def fetch_hoyo_codes(game: str, api_game: str) -> list[Code]:
    url = "https://hoyo-codes.seria.moe/codes?" + urllib.parse.urlencode({"game": api_game})
    payload = json.loads(request_bytes(url).decode("utf-8"))
    result: list[Code] = []
    for item in payload.get("codes", []):
        value = str(item.get("code", "")).strip().upper()
        if value and item.get("status") == "OK":
            result.append(
                Code(
                    game=game,
                    value=value,
                    rewards=str(item.get("rewards", "")).strip(),
                    source="HoYo Codes API",
                )
            )
    return result


class _EndfieldTableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.in_row = False
        self.row_code = ""
        self.row_text: list[str] = []
        self.rows: list[tuple[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "tr":
            self.in_row = True
            self.row_code = ""
            self.row_text = []
        elif self.in_row and tag == "input":
            classes = (attributes.get("class") or "").split()
            if "a-clipboard__textInput" in classes:
                self.row_code = (attributes.get("value") or "").strip().upper()

    def handle_data(self, data: str) -> None:
        if self.in_row:
            text = " ".join(data.split())
            if text:
                self.row_text.append(text)

    def handle_endtag(self, tag: str) -> None:
        if tag == "tr" and self.in_row:
            if self.row_code:
                self.rows.append((self.row_code, " ".join(self.row_text)))
            self.in_row = False


def fetch_endfield_codes() -> list[Code]:
    page = request_bytes(ENDFIELD_SOURCE).decode("utf-8", "replace")
    marker = page.find("使用可能なシリアルコード")
    if marker < 0:
        raise RuntimeError("エンドフィールドのコード表を発見できませんでした")
    table_start = page.find("<table", marker)
    table_end = page.find("</table>", table_start)
    if table_start < 0 or table_end < 0:
        raise RuntimeError("エンドフィールドのコード表を解析できませんでした")

    parser = _EndfieldTableParser()
    parser.feed(page[table_start : table_end + len("</table>")])
    result: list[Code] = []
    for value, row_text in parser.rows:
        if not re.fullmatch(r"[A-Z0-9]{6,32}", value):
            continue
        clean_text = html.unescape(row_text).strip()
        result.append(
            Code(
                game="endfield",
                value=value,
                note=clean_text[:700],
                source=ENDFIELD_SOURCE,
            )
        )
    if not result:
        raise RuntimeError("エンドフィールドのコードが0件でした。ページ構造を確認してください")
    return result


def load_seen() -> dict[str, list[str]]:
    if not STATE_PATH.exists():
        return {}
    return json.loads(STATE_PATH.read_text(encoding="utf-8"))


def save_seen(codes: list[Code], previous: dict[str, list[str]], successful_games: set[str]) -> None:
    grouped: dict[str, list[str]] = {
        game: list(values) for game, values in previous.items() if game not in successful_games
    }
    for item in codes:
        grouped.setdefault(item.game, []).append(item.value)
    for values in grouped.values():
        values.sort()
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(grouped, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def game_meta(game: str) -> dict[str, object]:
    if game == "endfield":
        return {
            "name": "アークナイツ：エンドフィールド",
            "color": 0xD35D4B,
            "redeem": "",
        }
    return HOYO_GAMES[game]


def discord_payload(item: Code) -> dict[str, object]:
    meta = game_meta(item.game)
    fields: list[dict[str, object]] = [
        {"name": "コード", "value": f"```{item.value}```", "inline": False}
    ]
    if item.rewards:
        fields.append({"name": "報酬", "value": item.rewards[:1000], "inline": False})
    if item.note:
        fields.append({"name": "掲載内容", "value": item.note[:1000], "inline": False})

    redeem_template = str(meta.get("redeem", ""))
    description = "新しい交換コードを検出しました。"
    if redeem_template:
        redeem_url = redeem_template.format(code=urllib.parse.quote(item.value))
        description += f"\n[公式交換ページを開く]({redeem_url})"

    return {
        "username": "Columbina",
        "allowed_mentions": {"parse": []},
        "embeds": [
            {
                "title": f"🎁 {meta['name']}：新しい交換コード",
                "description": description,
                "color": int(meta["color"]),
                "fields": fields,
                "footer": {"text": f"情報源: {item.source}"},
            }
        ],
    }


def send_discord(webhook_url: str, item: Code) -> None:
    body = json.dumps(discord_payload(item), ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        webhook_url,
        data=body,
        headers={"Content-Type": "application/json", "User-Agent": USER_AGENT},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        if response.status not in (200, 204):
            raise RuntimeError(f"Discord通知に失敗しました: HTTP {response.status}")


def send_test_discord(webhook_url: str) -> None:
    body = json.dumps(
        {
            "username": "Columbina",
            "content": "✅ 接続テスト成功：ゲーム交換コード通知を受信できます。",
            "allowed_mentions": {"parse": []},
        },
        ensure_ascii=False,
    ).encode("utf-8")
    request = urllib.request.Request(
        webhook_url,
        data=body,
        headers={"Content-Type": "application/json", "User-Agent": USER_AGENT},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        if response.status not in (200, 204):
            raise RuntimeError(f"Discordテスト通知に失敗しました: HTTP {response.status}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Discordへ送信せず取得結果を表示")
    parser.add_argument("--notify-all", action="store_true", help="既知を含む現在の全コードを通知")
    parser.add_argument("--test-webhook", action="store_true", help="Discordへ接続テストを1件送信")
    args = parser.parse_args()

    all_codes: list[Code] = []
    failures: list[str] = []
    successful_games: set[str] = set()
    for game, meta in HOYO_GAMES.items():
        try:
            all_codes.extend(fetch_hoyo_codes(game, str(meta["api_game"])))
            successful_games.add(game)
        except Exception as exc:  # Keep the other games working if one source fails.
            failures.append(f"{meta['name']}: {exc}")
    try:
        all_codes.extend(fetch_endfield_codes())
        successful_games.add("endfield")
    except Exception as exc:
        failures.append(f"アークナイツ：エンドフィールド: {exc}")

    if not all_codes:
        print("全情報源の取得に失敗しました", file=sys.stderr)
        for failure in failures:
            print(f"- {failure}", file=sys.stderr)
        return 1

    seen = load_seen()
    first_run = not bool(seen)
    new_codes = [
        item
        for item in all_codes
        if item.game in seen and item.value not in set(seen.get(item.game, []))
    ]

    if args.dry_run:
        print(json.dumps([asdict(item) for item in all_codes], ensure_ascii=False, indent=2))
        print(
            f"取得: {len(all_codes)}件 / 新規候補: {len(new_codes)}件 / 初回: {first_run}",
            file=sys.stderr,
        )
        for failure in failures:
            print(f"警告: {failure}", file=sys.stderr)
        return 0
    else:
        webhook_url = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()
        if not webhook_url:
            print("DISCORD_WEBHOOK_URLが設定されていません", file=sys.stderr)
            return 1
        if args.test_webhook:
            send_test_discord(webhook_url)
            print("Discord接続テストを送信しました")
        targets = all_codes if args.notify_all else new_codes
        for item in targets:
            send_discord(webhook_url, item)
            print(f"通知: {game_meta(item.game)['name']} / {item.value}")

    save_seen(all_codes, seen, successful_games)
    print(f"取得: {len(all_codes)}件 / 新規: {len(new_codes)}件 / 初回: {first_run}")
    for failure in failures:
        print(f"警告: {failure}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
