"""Render an audit as one self-contained HTML page: no scripts, no external files, safe to email or print to PDF.

Video titles and client names are typed by other people, so every piece of text is escaped. The page contains no
JavaScript, so a hostile title cannot run anything even if an escape were missed.
"""
from html import escape

STRENGTH_LABEL = {
    "solid": "Solid evidence", "suggestive": "Suggestive", "weak": "Weak: a hint only",
    "not_enough_data": "Not enough data", "info": "Fact",
}

_CSS = """
body{font:15px/1.5 system-ui,Segoe UI,sans-serif;color:#1d1d22;max-width:820px;margin:2rem auto;padding:0 1rem}
h1{margin:0 0 .2rem}h2{margin:0;font-size:1.1rem}.sub{color:#666;margin:0 0 1.5rem}
section{border:1px solid #ddd;border-radius:8px;padding:1rem 1.2rem;margin:0 0 1rem;break-inside:avoid}
.head{display:flex;justify-content:space-between;gap:1rem;align-items:baseline}
.badge{font-size:.75rem;border-radius:999px;padding:.1rem .6rem;background:#eee;white-space:nowrap}
.solid{background:#d9f5e3}.suggestive{background:#dbeafe}.weak{background:#fdf0c8}
table{width:100%;border-collapse:collapse;margin:.6rem 0;font-size:.9rem}
th,td{text-align:right;padding:.25rem .4rem;border-top:1px solid #eee}th:first-child,td:first-child{text-align:left}
th{color:#666;font-weight:500}ul{color:#666;font-size:.8rem;margin:.6rem 0 0;padding-left:1.1rem}
footer{color:#666;font-size:.8rem;margin-top:2rem}
"""


def _num(value: float) -> str:
    return f"{value:,.0f}" if abs(value) >= 100 else f"{value:,.1f}"


def _table(headers: list[str], rows: list[list[str]]) -> str:
    if not rows:
        return ""
    head = "".join(f"<th>{escape(h)}</th>" for h in headers)
    body = "".join("<tr>" + "".join(f"<td>{escape(str(c))}</td>" for c in row) + "</tr>" for row in rows)
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def _title(row: dict) -> str:
    return row.get("title") or row["video_id"]


def _extra(finding: dict) -> str:
    key, d = finding["key"], finding["details"]
    if key == "performance" and d.get("best"):
        cols = ["Video", "Views", "Typical for age", "Versus typical"]

        def table(rows):
            cells = [[_title(r), _num(r["views"]), _num(r["expected"]), f"{r['index']:.1f}x"] for r in rows]
            return _table(cols, cells)

        return "<p><b>Doing best for their age</b></p>" + table(d["best"]) + \
               "<p><b>Doing worst for their age</b></p>" + table(d["worst"])
    if key == "click_through" and d.get("candidates"):
        rows = [[_title(r), _num(r["impressions"]), f"{r['ctr']:.1f}%", _num(r["views"])] for r in d["candidates"]]
        return _table(["Video", "Impressions", "Click rate", "Views"], rows)
    if key == "retention" and d.get("candidates"):
        return _table(["Video", "Views", "Average % viewed"],
                      [[_title(r), _num(r["views"]), f"{r['percent_viewed']:.0f}%"] for r in d["candidates"]])
    if key == "title_features":
        rows = [[r["feature"], f"{r['n_with']} / {r['n_without']}",
                 "-" if r["ratio"] is None else f"{r['ratio']:.2f}x",
                 "-" if r["p_adjusted"] is None else f"{r['p_adjusted']:.3f}"] for r in d["features"]]
        return _table(["Title has", "Videos with / without", "Index ratio", "Adjusted p"], rows)
    if key == "duration":
        rows = [[r["format"], r["videos"], "-" if r["rho"] is None else f"{r['rho']:.2f}",
                 "-" if r["rho"] is None else f"{r['low']:.2f} to {r['high']:.2f}"] for r in d["formats"]]
        return _table(["Format", "Videos", "Rank correlation", "95% range"], rows)
    return ""


def render_html(audit: dict, client_name: str) -> str:
    cards = []
    for f in audit["findings"]:
        caveats = "".join(f"<li>{escape(c)}</li>" for c in f["caveats"])
        cards.append(
            f'<section><div class="head"><h2>{escape(f["title"])}</h2>'
            f'<span class="badge {escape(f["strength"])}">{escape(STRENGTH_LABEL.get(f["strength"], f["strength"]))}'
            f"</span></div><p>{escape(f['headline'])}</p>{_extra(f)}"
            f"{f'<ul>{caveats}</ul>' if caveats else ''}</section>"
        )
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>Channel audit: {escape(client_name)}</title><style>{_CSS}</style></head><body>"
        f"<h1>Channel audit</h1><p class=\"sub\">{escape(client_name)} · {audit['videos']} videos · "
        f"ages measured to {escape(str(audit['as_of']))} ({escape(audit['as_of_source'])})</p>"
        + "".join(cards)
        + "<footer>Every figure is computed from the channel's YouTube Studio export; none is written by a model. "
        "The label on each finding says how far to trust it. Findings describe patterns in past videos, not causes."
        "</footer></body></html>"
    )
