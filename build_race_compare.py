#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
BOAT RACE AI
終了済みレース照合ページ生成

既存の予測処理・直前収集処理には手を加えず、
公開済みのファミリーページと公開CSVを使って、

・朝予測
・最終直前予測
・実際の1～3着
・TOP3整合
・TOP3完全一致
・1着一致
・3連単結果
・3連単払戻
・締切前3連単オッズ

を race_compare.html に表示する。
"""

from __future__ import annotations

import csv
import html
import io
import re
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


JST = timezone(timedelta(hours=9))

PUBLIC_DATA_BASE = (
    "https://raw.githubusercontent.com/"
    "BoatraceCSV/boatracecsv.github.io/main/data"
)

VENUE_CODES = {
    "桐生": "01",
    "戸田": "02",
    "江戸川": "03",
    "平和島": "04",
    "多摩川": "05",
    "浜名湖": "06",
    "蒲郡": "07",
    "常滑": "08",
    "津": "09",
    "三国": "10",
    "びわこ": "11",
    "住之江": "12",
    "尼崎": "13",
    "鳴門": "14",
    "丸亀": "15",
    "児島": "16",
    "宮島": "17",
    "徳山": "18",
    "下関": "19",
    "若松": "20",
    "芦屋": "21",
    "福岡": "22",
    "唐津": "23",
    "からつ": "23",
    "大村": "24",
}

CODE_TO_VENUE = {
    code: name
    for name, code in VENUE_CODES.items()
    if name != "からつ"
}


# =========================================================
# 共通
# =========================================================

def fetch_text(url: str) -> str:
    req = Request(
        url,
        headers={"User-Agent": "boatrace-family-view/1.0"},
    )

    try:
        with urlopen(req, timeout=30) as response:
            return response.read().decode("utf-8-sig")

    except (HTTPError, URLError, TimeoutError):
        return ""


def read_csv(text: str):
    if not text.strip():
        return []

    return list(csv.DictReader(io.StringIO(text)))


def clean_html(value: str) -> str:
    value = re.sub(r"<[^>]+>", "", value or "")
    return html.unescape(value).strip()


def escape(value) -> str:
    if value is None:
        return ""
    return html.escape(str(value))


# =========================================================
# index.html から予測を読み取る
# =========================================================

def parse_prediction_page(page: str):

    date_match = re.search(
        r"最終更新\s*"
        r"(\d{4})/(\d{2})/(\d{2})\s+"
        r"([0-9:]+)\s+JST",
        page,
    )

    if not date_match:
        return None, []

    ymd = "".join(
        date_match.group(i)
        for i in (1, 2, 3)
    )

    cards = []

    articles = re.findall(
        r'<article class="race-card">'
        r'([\s\S]*?)'
        r'</article>',
        page,
    )

    for article in articles:

        race_name_match = re.search(
            r'<div class="race-name">\s*'
            r'([^<]+?)'
            r'\s*</div>',
            article,
        )

        badge_match = re.search(
            r'<div class="badge\s+(live|morning)">\s*'
            r'([^<]+?)'
            r'\s*</div>',
            article,
        )

        deadline_match = re.search(
            r'<div class="deadline">\s*'
            r'([^<]+?)'
            r'\s*</div>',
            article,
        )

        if not race_name_match or not badge_match:
            continue

        race_name = clean_html(
            race_name_match.group(1)
        )

        race_match = re.match(
            r"(.+?)\s+(\d+)R$",
            race_name,
        )

        if not race_match:
            continue

        venue = race_match.group(1).strip()
        race_no = int(race_match.group(2))

        venue_code = VENUE_CODES.get(venue)

        if not venue_code:
            continue

        race_code = (
            f"{ymd}"
            f"{venue_code}"
            f"{race_no:02d}"
        )

        picks = []

        pick_pattern = re.compile(
            r'<span class="pick-name">\s*'
            r'(\d)号艇\s*'
            r'([^<]*?)'
            r'</span>\s*'
            r'<span class="score">\s*'
            r'([^<]+?)'
            r'\s*</span>'
        )

        for match in pick_pattern.finditer(article):

            boat = int(match.group(1))
            name = clean_html(match.group(2))

            try:
                score = float(
                    clean_html(match.group(3))
                )
            except ValueError:
                score = None

            picks.append(
                {
                    "boat": boat,
                    "name": name,
                    "score": score,
                }
            )

        cards.append(
            {
                "race_code": race_code,
                "date": ymd,
                "venue": venue,
                "venue_code": venue_code,
                "race": race_no,
                "deadline": (
                    clean_html(deadline_match.group(1))
                    if deadline_match
                    else ""
                ),
                "stage": badge_match.group(1),
                "top3": picks[:3],
            }
        )

    return ymd, cards


# =========================================================
# Git履歴から
# 朝予測 / 最終直前予測 を復元
# =========================================================

def get_index_history():

    try:
        commits = subprocess.check_output(
            [
                "git",
                "rev-list",
                "-n600",
                "HEAD",
                "--",
                "index.html",
            ],
            text=True,
        ).splitlines()

    except Exception:
        commits = []

    pages = []

    # 古いもの → 新しいもの
    for commit in reversed(commits):

        try:
            page = subprocess.check_output(
                [
                    "git",
                    "show",
                    f"{commit}:index.html",
                ],
                text=True,
                stderr=subprocess.DEVNULL,
            )

            pages.append(page)

        except Exception:
            pass

    # 現在のindex.htmlも追加
    path = Path("index.html")

    if path.exists():
        pages.append(
            path.read_text(
                encoding="utf-8"
            )
        )

    return pages


def collect_predictions(target_ymd: str):

    predictions = {}

    for page in get_index_history():

        ymd, cards = parse_prediction_page(page)

        if ymd != target_ymd:
            continue

        for card in cards:

            race_code = card["race_code"]

            if race_code not in predictions:

                predictions[race_code] = {
                    "race_code": race_code,
                    "venue": card["venue"],
                    "race": card["race"],
                    "deadline": card["deadline"],
                    "morning": None,
                    "live": None,
                }

            row = predictions[race_code]

            if card["deadline"]:
                row["deadline"] = card["deadline"]

            # 朝予測
            if card["stage"] == "morning":

                # 直前予測になる前の
                # 最後の朝予測を残す
                if row["live"] is None:
                    row["morning"] = card

            # 直前予測
            elif card["stage"] == "live":

                # 新しいものが来るたび更新
                # → 最終的に締切前最後の直前予測になる
                row["live"] = card

    return predictions


# =========================================================
# CSV
# =========================================================

def latest_by_race(rows):

    output = {}

    for row in rows:

        race_code = row.get(
            "レースコード",
            "",
        )

        if not race_code:
            continue

        previous = output.get(race_code)

        if (
            previous is None
            or row.get("取得日時", "")
            >= previous.get("取得日時", "")
        ):
            output[race_code] = row

    return output


# =========================================================
# TOP3評価
# =========================================================

def evaluate_top3(prediction, actual):

    if not prediction:
        return None

    picks = prediction.get(
        "top3",
        [],
    )

    if len(picks) < 3:
        return None

    predicted = [
        int(x["boat"])
        for x in picks[:3]
    ]

    overlap = len(
        set(predicted)
        & set(actual)
    )

    return {
        "predicted": predicted,

        "overlap_count": overlap,

        "overlap_rate":
            overlap / 3 * 100,

        "exact":
            set(predicted)
            == set(actual),

        "winner":
            predicted[0]
            == actual[0],
    }


# =========================================================
# 締切何分前のオッズか
# =========================================================

def odds_minutes_before(
    ymd,
    deadline,
    obtained_at,
):

    if not deadline or not obtained_at:
        return None

    try:

        deadline_dt = datetime.strptime(
            ymd + deadline,
            "%Y%m%d%H:%M",
        ).replace(
            tzinfo=JST
        )

        obtained_dt = datetime.fromisoformat(
            obtained_at.replace(
                "Z",
                "+00:00",
            )
        ).astimezone(JST)

        diff = (
            deadline_dt
            - obtained_dt
        ).total_seconds() / 60

        return round(diff, 1)

    except Exception:
        return None


# =========================================================
# 結果・払戻・オッズ統合
# =========================================================

def build_race_data(
    target_ymd,
    predictions,
):

    yyyy = target_ymd[:4]
    mm = target_ymd[4:6]
    dd = target_ymd[6:8]

    date_path = (
        f"{yyyy}/{mm}/{dd}"
    )

    result_url = (
        f"{PUBLIC_DATA_BASE}"
        f"/results/realtime/"
        f"{date_path}.csv"
    )

    payout_url = (
        f"{PUBLIC_DATA_BASE}"
        f"/results/payouts/"
        f"{date_path}.csv"
    )

    odds_url = (
        f"{PUBLIC_DATA_BASE}"
        f"/previews/od3/"
        f"{date_path}.csv"
    )

    results = latest_by_race(
        read_csv(
            fetch_text(result_url)
        )
    )

    payouts = latest_by_race(
        read_csv(
            fetch_text(payout_url)
        )
    )

    odds = latest_by_race(
        read_csv(
            fetch_text(odds_url)
        )
    )

    race_rows = []

    for race_code, result in results.items():

        actual = []

        valid = True

        for rank in range(1, 4):

            value = result.get(
                f"{rank}着_艇番",
                "",
            )

            try:
                actual.append(
                    int(value)
                )

            except Exception:
                valid = False
                break

        if not valid:
            continue

        names = [
            result.get(
                f"{rank}着_選手名",
                "",
            )
            .replace("　", " ")
            .strip()
            for rank in range(1, 4)
        ]

        pred = predictions.get(
            race_code,
            {},
        )

        payout = payouts.get(
            race_code,
            {},
        )

        odds_row = odds.get(
            race_code,
            {},
        )

        trifecta = "-".join(
            str(x)
            for x in actual
        )

        # 3連単払戻
        payout_value = payout.get(
            "3連単_払戻金",
            "",
        )

        try:
            payout_yen = int(
                float(
                    str(
                        payout_value
                    ).replace(",", "")
                )
            )
        except Exception:
            payout_yen = None

        # 実際に的中した組番の
        # 締切前3連単オッズ
        odds_key = (
            f"3連単_{trifecta}"
        )

        odds_value = odds_row.get(
            odds_key,
            "",
        )

        try:
            odds_number = float(
                odds_value
            )
        except Exception:
            odds_number = None

        venue_code = (
            race_code[8:10]
        )

        venue = (
            pred.get("venue")
            or CODE_TO_VENUE.get(
                venue_code,
                venue_code,
            )
        )

        try:
            race_no = int(
                race_code[-2:]
            )
        except Exception:
            race_no = 0

        deadline = (
            pred.get("deadline")
            or result.get(
                "締切時刻",
                "",
            )
        )

        race_rows.append(
            {
                "race_code":
                    race_code,

                "venue":
                    venue,

                "race":
                    pred.get(
                        "race"
                    )
                    or race_no,

                "deadline":
                    deadline,

                "result_time":
                    result.get(
                        "結果記録時刻",
                        "",
                    ),

                "technique":
                    result.get(
                        "決まり手",
                        "",
                    ).strip(),

                "actual":
                    actual,

                "actual_names":
                    names,

                "morning":
                    pred.get(
                        "morning"
                    ),

                "live":
                    pred.get(
                        "live"
                    ),

                "morning_eval":
                    evaluate_top3(
                        pred.get(
                            "morning"
                        ),
                        actual,
                    ),

                "live_eval":
                    evaluate_top3(
                        pred.get(
                            "live"
                        ),
                        actual,
                    ),

                "trifecta":
                    trifecta,

                "payout":
                    payout_yen,

                "odds":
                    odds_number,

                "odds_time":
                    odds_row.get(
                        "取得日時",
                        "",
                    ),

                "odds_minutes":
                    odds_minutes_before(
                        target_ymd,
                        deadline,
                        odds_row.get(
                            "取得日時",
                            "",
                        ),
                    ),
            }
        )

    # 新しいレースを上に
    race_rows.sort(
        key=lambda x:
            x["race_code"],
        reverse=True,
    )

    return race_rows


# =========================================================
# HTML
# =========================================================

def prediction_html(prediction):

    if not prediction:
        return (
            '<span class="missing">'
            "予測なし"
            "</span>"
        )

    picks = prediction.get(
        "top3",
        [],
    )

    if not picks:
        return (
            '<span class="missing">'
            "予測なし"
            "</span>"
        )

    parts = []

    for pick in picks:

        boat = pick["boat"]
        name = escape(
            pick.get(
                "name",
                "",
            )
        )

        score = pick.get(
            "score"
        )

        if score is None:
            score_text = ""
        else:
            score_text = (
                f" {score:.1f}"
            )

        parts.append(
            f'<span class="boat">'
            f'<b>{boat}</b>号艇 '
            f'{name}'
            f'<small>'
            f'{score_text}'
            f'</small>'
            f'</span>'
        )

    return (
        '<span class="arrow">'
        " → "
        "</span>"
    ).join(parts)


def evaluation_html(data):

    if not data:

        return (
            '<span class="missing">'
            "未評価"
            "</span>"
        )

    exact = (
        "○"
        if data["exact"]
        else "×"
    )

    winner = (
        "○"
        if data["winner"]
        else "×"
    )

    return (
        f'<span class="tag">'
        f'TOP3 '
        f'{data["overlap_count"]}/3 '
        f'({data["overlap_rate"]:.1f}%)'
        f'</span>'

        f'<span class="tag">'
        f'完全一致 {exact}'
        f'</span>'

        f'<span class="tag">'
        f'1着一致 {winner}'
        f'</span>'
    )


def aggregate(
    race_rows,
    key,
):

    values = [
        row[key]
        for row in race_rows
        if row.get(key)
    ]

    if not values:

        return {
            "count": 0,
            "overlap": None,
            "exact": None,
            "winner": None,
        }

    count = len(values)

    overlap = sum(
        x["overlap_rate"]
        for x in values
    ) / count

    exact = sum(
        100
        if x["exact"]
        else 0
        for x in values
    ) / count

    winner = sum(
        100
        if x["winner"]
        else 0
        for x in values
    ) / count

    return {
        "count": count,
        "overlap": overlap,
        "exact": exact,
        "winner": winner,
    }


def percent(value):

    if value is None:
        return "—"

    return f"{value:.1f}%"


def render_html(
    target_ymd,
    race_rows,
):

    morning_summary = aggregate(
        race_rows,
        "morning_eval",
    )

    live_summary = aggregate(
        race_rows,
        "live_eval",
    )

    generated = datetime.now(
        JST
    ).strftime(
        "%H:%M"
    )

    cards = []

    for row in race_rows:

        actual_parts = []

        for boat, name in zip(
            row["actual"],
            row["actual_names"],
        ):

            actual_parts.append(
                f'<span class="boat">'
                f'<b>{boat}</b>号艇 '
                f'{escape(name)}'
                f'</span>'
            )

        actual_html = (
            '<span class="arrow">'
            " → "
            "</span>"
        ).join(actual_parts)

        if row["payout"] is None:
            payout = "—"
        else:
            payout = (
                f'{row["payout"]:,}円'
            )

        if row["odds"] is None:
            odds = "—"
        else:
            odds = (
                f'{row["odds"]:g}倍'
            )

        odds_note = ""

        if row["odds_minutes"] is not None:

            minutes = row[
                "odds_minutes"
            ]

            if minutes >= 0:

                odds_note = (
                    f"締切"
                    f"{minutes:g}分前"
                )

            else:

                odds_note = (
                    f"締切"
                    f"{abs(minutes):g}分後"
                )

        cards.append(
            f"""
<article class="race-card">

    <div class="race-head">

        <div>
            <div class="race-title">
                {escape(row["venue"])}
                {row["race"]}R
            </div>

            <div class="sub">
                締切
                {escape(row["deadline"])}
                ／
                結果
                {escape(row["result_time"])}
                ／
                {escape(row["technique"])}
            </div>
        </div>

        <div class="combo">
            {escape(row["trifecta"])}
        </div>

    </div>


    <div class="actual">

        <div class="label">
            実結果
        </div>

        <div>
            {actual_html}
        </div>

    </div>


    <div class="prediction-row">

        <div class="label">
            朝予測
        </div>

        <div>
            {prediction_html(row["morning"])}
        </div>

        <div class="metrics">
            {evaluation_html(row["morning_eval"])}
        </div>

    </div>


    <div class="prediction-row">

        <div class="label">
            直前予測
        </div>

        <div>
            {prediction_html(row["live"])}
        </div>

        <div class="metrics">
            {evaluation_html(row["live_eval"])}
        </div>

    </div>


    <div class="money-grid">

        <div class="money-box">

            <span>
                3連単払戻
            </span>

            <strong>
                {payout}
            </strong>

        </div>


        <div class="money-box">

            <span>
                結果3連単の締切前オッズ
            </span>

            <strong>
                {odds}
            </strong>

            <small>
                {escape(odds_note)}
            </small>

        </div>

    </div>

</article>
"""
        )

    if not cards:

        cards_html = """
<div class="empty">
    現在、結果確定済みレースはありません。
</div>
"""

    else:

        cards_html = "".join(
            cards
        )

    display_date = (
        f"{target_ymd[:4]}/"
        f"{target_ymd[4:6]}/"
        f"{target_ymd[6:8]}"
    )

    return f"""<!doctype html>

<html lang="ja">

<head>

<meta charset="utf-8">

<meta name="viewport"
      content="width=device-width,initial-scale=1">

<meta name="robots"
      content="noindex,nofollow">

<meta http-equiv="refresh"
      content="300">

<title>
レース照合
</title>


<style>

:root {{
    --bg:#f4f6f8;
    --card:#ffffff;
    --text:#111827;
    --muted:#667085;
    --line:#e5e7eb;
    --chip:#f3f4f6;
    --blue:#2563eb;
}}

* {{
    box-sizing:border-box;
}}

body {{
    margin:0;
    background:var(--bg);
    color:var(--text);

    font-family:
        -apple-system,
        BlinkMacSystemFont,
        "Segoe UI",
        "Hiragino Sans",
        "Noto Sans JP",
        sans-serif;
}}

.wrap {{
    width:min(
        980px,
        100%
    );

    margin:auto;

    padding:
        16px
        12px
        50px;
}}

h1 {{
    margin:0;
    font-size:24px;
}}

.meta {{
    margin-top:5px;
    color:var(--muted);
    font-size:12px;
}}

.nav {{
    display:grid;

    grid-template-columns:
        repeat(
            4,
            minmax(
                0,
                1fr
            )
        );

    gap:6px;

    margin:
        14px
        0;

    padding:6px;

    border:
        1px solid
        var(--line);

    border-radius:14px;

    background:
        var(--card);
}}

.nav a {{
    display:flex;

    justify-content:center;
    align-items:center;

    min-height:44px;

    padding:
        7px
        3px;

    border-radius:10px;

    color:
        var(--text);

    text-decoration:none;

    text-align:center;

    font-size:12px;

    font-weight:800;
}}

.nav a.active {{
    background:
        var(--blue);

    color:white;
}}

.note {{
    margin:
        10px
        0
        14px;

    color:
        var(--muted);

    font-size:12px;

    line-height:1.6;
}}

.summary {{
    display:grid;

    grid-template-columns:
        repeat(
            3,
            minmax(
                0,
                1fr
            )
        );

    gap:8px;

    margin-bottom:14px;
}}

.summary-box {{
    padding:12px;

    background:
        var(--card);

    border:
        1px solid
        var(--line);

    border-radius:12px;
}}

.summary-box span {{
    display:block;

    color:
        var(--muted);

    font-size:11px;
}}

.summary-box strong {{
    display:block;

    margin-top:4px;

    font-size:19px;
}}

.race-card {{
    margin-bottom:12px;

    padding:14px;

    background:
        var(--card);

    border:
        1px solid
        var(--line);

    border-radius:14px;
}}

.race-head {{
    display:flex;

    justify-content:
        space-between;

    gap:10px;
}}

.race-title {{
    font-size:18px;

    font-weight:900;
}}

.sub {{
    margin-top:3px;

    color:
        var(--muted);

    font-size:11px;
}}

.combo {{
    white-space:nowrap;

    font-size:20px;

    font-weight:900;
}}

.actual {{
    margin-top:11px;

    padding:10px;

    background:
        var(--chip);

    border-radius:10px;

    line-height:1.6;
}}

.label {{
    margin-bottom:4px;

    color:
        var(--muted);

    font-size:11px;

    font-weight:800;
}}

.prediction-row {{
    display:grid;

    grid-template-columns:
        64px
        minmax(
            0,
            1fr
        );

    gap:
        5px
        10px;

    padding:
        10px
        0;

    border-bottom:
        1px solid
        var(--line);

    font-size:14px;

    line-height:1.6;
}}

.prediction-row .label {{
    margin:0;
}}

.metrics {{
    grid-column:2;

    display:flex;

    flex-wrap:wrap;

    gap:5px;
}}

.tag {{
    padding:
        3px
        7px;

    background:
        var(--chip);

    border-radius:
        999px;

    font-size:11px;

    font-weight:700;
}}

.boat small {{
    color:
        var(--muted);
}}

.arrow {{
    color:
        var(--muted);
}}

.missing {{
    color:
        var(--muted);

    font-size:12px;
}}

.money-grid {{
    display:grid;

    grid-template-columns:
        repeat(
            2,
            minmax(
                0,
                1fr
            )
        );

    gap:8px;

    margin-top:10px;
}}

.money-box {{
    padding:10px;

    background:
        var(--chip);

    border-radius:10px;
}}

.money-box span,
.money-box small {{
    display:block;

    color:
        var(--muted);

    font-size:11px;
}}

.money-box strong {{
    display:block;

    margin-top:3px;

    font-size:18px;
}}

.empty {{
    padding:30px;

    background:
        var(--card);

    border:
        1px solid
        var(--line);

    border-radius:14px;

    text-align:center;

    color:
        var(--muted);
}}


@media (
    max-width:600px
) {{

    .summary {{
        grid-template-columns:
            1fr;
    }}

    .money-grid {{
        grid-template-columns:
            1fr;
    }}

    .nav a {{
        font-size:11px;
    }}
}}


@media (
    prefers-color-scheme:dark
) {{

    :root {{
        --bg:#0f1115;
        --card:#171a21;
        --text:#f3f4f6;
        --muted:#a8b0bd;
        --line:#2a3039;
        --chip:#222833;
        --blue:#3b82f6;
    }}
}}

</style>

</head>


<body>

<div class="wrap">


<h1>
レース照合
</h1>


<div class="meta">

{display_date}

・確定
{len(race_rows)}R

・更新
{generated}
JST

</div>


<nav class="nav">

<a href="index.html">
最新予想
</a>

<a href="results.html">
結果・成績
</a>

<a href="analysis.html">
AI分析
</a>

<a href="race_compare.html"
   class="active">
レース照合
</a>

</nav>


<div class="note">

終了したレースについて、
朝予測・最終直前予測と
実際の結果を照合します。

オッズは公開データに保存された
締切前スナップショットです。

払戻金は確定結果です。

</div>


<section class="summary">


<div class="summary-box">

<span>
確定レース
</span>

<strong>
{len(race_rows)}R
</strong>

</div>


<div class="summary-box">

<span>
朝
TOP3整合 /
完全一致
</span>

<strong>
{percent(morning_summary["overlap"])}
/
{percent(morning_summary["exact"])}
</strong>

<span>
{morning_summary["count"]}R
</span>

</div>


<div class="summary-box">

<span>
直前
TOP3整合 /
完全一致
</span>

<strong>
{percent(live_summary["overlap"])}
/
{percent(live_summary["exact"])}
</strong>

<span>
{live_summary["count"]}R
</span>

</div>


</section>


{cards_html}


</div>

</body>

</html>
"""


# =========================================================
# MAIN
# =========================================================

def main():

    now = datetime.now(
        JST
    )

    target_ymd = now.strftime(
        "%Y%m%d"
    )

    print(
        "対象日:",
        target_ymd,
    )

    predictions = collect_predictions(
        target_ymd
    )

    print(
        "予測履歴:",
        len(predictions),
        "レース",
    )

    race_rows = build_race_data(
        target_ymd,
        predictions,
    )

    print(
        "結果確定:",
        len(race_rows),
        "レース",
    )

    output = render_html(
        target_ymd,
        race_rows,
    )

    Path(
        "race_compare.html"
    ).write_text(
        output,
        encoding="utf-8",
    )

    print(
        "race_compare.html:",
        "PASS",
    )


if __name__ == "__main__":
    main()