#!/usr/bin/env python3
"""Gera o painel de atividade do perfil a partir de dados reais do GitHub.

Saidas: assets/hero.svg, assets/marcos.svg, assets/metas.svg
e a tabela de projetos no README.md. Usa apenas a biblioteca padrao.

Uso: GH_TOKEN=<token> python scripts/generate.py
"""
import json
import math
import os
import re
import sys
import urllib.request
from datetime import date, datetime, timedelta, timezone
from html import escape
from pathlib import Path

LOGIN = os.environ.get("PROFILE_LOGIN", "matheusmontagner8")
ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
BRT = timezone(timedelta(hours=-3))  # Brasil: UTC-3 fixo, sem horario de verao

FONT = "ui-monospace,SFMono-Regular,Menlo,Consolas,'Liberation Mono',monospace"
BG, PANEL, BORDER = "#0d1117", "#161b22", "#30363d"
TEXT, MUTED = "#e6edf3", "#8b949e"
GREEN, BLUE = "#3fb950", "#58a6ff"
HEADLINE = "Desenvolvedor Full-Stack · Sistemas ERP · Power BI"

PROFILE_QUERY = """
query($login:String!){user(login:$login){
  name createdAt followers{totalCount}
  repositories(first:100,ownerAffiliations:OWNER,privacy:PUBLIC,isFork:false,
               orderBy:{field:PUSHED_AT,direction:DESC}){nodes{
    name description url stargazerCount pushedAt createdAt
    primaryLanguage{name}
    languages(first:10,orderBy:{field:SIZE,direction:DESC}){edges{size node{name}}}
  }}
}}"""

YEAR_QUERY = """
query($login:String!,$from:DateTime!,$to:DateTime!){user(login:$login){
  contributionsCollection(from:$from,to:$to){
    totalPullRequestContributions totalIssueContributions
    contributionCalendar{weeks{contributionDays{date contributionCount}}}
  }
}}"""


def graphql(token, query, **variables):
    req = urllib.request.Request(
        "https://api.github.com/graphql",
        data=json.dumps({"query": query, "variables": variables}).encode(),
        headers={"Authorization": f"bearer {token}", "User-Agent": "profile-dashboard"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        payload = json.load(resp)
    if payload.get("errors"):
        sys.exit(f"Erro na API do GitHub: {payload['errors']}")
    return payload["data"]["user"]


def fetch(token):
    """Coleta perfil e contribuicoes; a API limita cada consulta a um ano."""
    user = graphql(token, PROFILE_QUERY, login=LOGIN)
    start = datetime.fromisoformat(user["createdAt"].replace("Z", "+00:00"))
    now = datetime.now(timezone.utc)
    days, prs, issues = {}, 0, 0
    while start < now:
        end = min(start + timedelta(days=364), now)
        got = graphql(
            token, YEAR_QUERY, login=LOGIN,
            **{"from": start.isoformat(), "to": end.isoformat()},
        )["contributionsCollection"]
        prs += got["totalPullRequestContributions"]
        issues += got["totalIssueContributions"]
        for week in got["contributionCalendar"]["weeks"]:
            for day in week["contributionDays"]:
                days[date.fromisoformat(day["date"])] = day["contributionCount"]
        start = end + timedelta(seconds=1)
    return user, days, prs, issues


def streaks(days, today):
    """Sequencia atual e recorde. Hoje sem atividade ainda nao quebra a atual."""
    best = run = 0
    for day in sorted(days):
        run = run + 1 if days[day] else 0
        best = max(best, run)
    cursor = today if days.get(today) else today - timedelta(days=1)
    current = 0
    while days.get(cursor):
        current += 1
        cursor -= timedelta(days=1)
    return current, best


def build_stats(user, days, prs, issues, today):
    repos = user["repositories"]["nodes"]
    languages = {}
    for repo in repos:
        for edge in repo["languages"]["edges"]:
            name = edge["node"]["name"]
            languages[name] = languages.get(name, 0) + edge["size"]
    current, best = streaks(days, today)
    contributions = sum(days.values())
    stars = sum(r["stargazerCount"] for r in repos)
    followers = user["followers"]["totalCount"]
    points = (contributions * 10 + prs * 40 + issues * 20 + len(repos) * 100
              + stars * 50 + followers * 30 + best * 20)
    level = math.isqrt(points // 100) + 1
    monday = today - timedelta(days=today.weekday())
    week = [days.get(monday + timedelta(days=i), 0) for i in range(7)]
    return {
        "name": user["name"] or LOGIN, "repos": repos, "languages": languages,
        "contributions": contributions, "prs": prs, "issues": issues,
        "stars": stars, "followers": followers, "current": current, "best": best,
        "active_days": sum(1 for count in days.values() if count),
        "points": points, "level": level,
        "level_floor": 100 * (level - 1) ** 2, "level_ceil": 100 * level ** 2,
        "week_days": sum(1 for count in week if count), "week_total": sum(week),
        "month_repos": sum(
            1 for r in repos
            if r["createdAt"][:7] == today.strftime("%Y-%m")
        ),
        "today": today,
    }


def milestones(s):
    """(titulo, descricao, valor atual, alvo). Descricao cabe em ~27 caracteres."""
    return [
        ("Primeira contribuição", "1 contribuição registrada", s["contributions"], 1),
        ("Consistência inicial", "100 contribuições", s["contributions"], 100),
        ("Volume de entregas", "1.000 contribuições", s["contributions"], 1000),
        ("Constância semanal", "7 dias consecutivos", s["best"], 7),
        ("Constância mensal", "30 dias consecutivos", s["best"], 30),
        ("Atividade contínua", "100 dias com atividade", s["active_days"], 100),
        ("Portfólio público", "5 repositórios públicos", len(s["repos"]), 5),
        ("Diversidade técnica", "5 linguagens diferentes", len(s["languages"]), 5),
        ("Colaboração", "1 pull request", s["prs"], 1),
        ("Gestão de issues", "5 issues abertas", s["issues"], 5),
        ("Reconhecimento", "1 estrela recebida", s["stars"], 1),
        ("Rede profissional", "5 seguidores", s["followers"], 5),
    ]


def text(x, y, content, size=13, fill=TEXT, weight="normal", anchor="start"):
    return (f'<text x="{x}" y="{y}" font-size="{size}" fill="{fill}" '
            f'font-weight="{weight}" text-anchor="{anchor}">{escape(str(content))}</text>')


def bar(x, y, width, height, ratio, color):
    filled = max(0.0, min(1.0, ratio)) * width
    radius = height / 2
    fill = ""
    if filled > 0:
        fill = (f'<rect x="{x}" y="{y}" width="{filled:.1f}" height="{height}" '
                f'rx="{radius}" fill="{color}"/>')
    return (f'<rect x="{x}" y="{y}" width="{width}" height="{height}" rx="{radius}" '
            f'fill="{BORDER}"/>{fill}')


def svg(width, height, body, title):
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" aria-label="{escape(title)}">'
        f'<title>{escape(title)}</title><style>text{{font-family:{FONT}}}</style>'
        f'<rect x="0.5" y="0.5" width="{width - 1}" height="{height - 1}" rx="12" '
        f'fill="{BG}" stroke="{BORDER}"/>{body}</svg>'
    )


AVATAR = """
................
.....HHHHHH.....
....HHHHHHHH....
...HHHHHHHHHH...
...HHSSSSSSHH...
...HSSSSSSSSH...
...HSESSSSESH...
...HSSSSSSSSH...
....SSSMMSSS....
.....SSSSSS.....
...BBBBBBBBBB...
..BBBBBBBBBBBB..
..SBBBGGGGBBBS..
..SBBBGGGGBBBS..
....DDD..DDD....
....DDD..DDD....
""".split()
AVATAR_COLORS = {"H": "#0a0a0a", "S": "#e8b98f", "E": BG, "M": "#a8644a",
                 "B": BLUE, "G": "#f2c94c", "D": "#1f2933"}


def avatar(x, y, pixel):
    rects = []
    for row, line in enumerate(AVATAR):
        for col, char in enumerate(line):
            if char in AVATAR_COLORS:
                rects.append(f'<rect x="{x + col * pixel}" y="{y + row * pixel}" '
                             f'width="{pixel}" height="{pixel}" fill="{AVATAR_COLORS[char]}"/>')
    return "".join(rects)


def hero_svg(s):
    span = s["level_ceil"] - s["level_floor"]
    ratio = (s["points"] - s["level_floor"]) / span
    metrics = [
        (s["contributions"], "Contribuições"),
        (s["active_days"], "Dias ativos"),
        (len(s["repos"]), "Repositórios públicos"),
        (len(s["languages"]), "Linguagens"),
        (f'{s["current"]} dias', "Sequência atual"),
        (f'{s["best"]} dias', "Maior sequência"),
    ]
    score = f'{s["points"]:,} / {s["level_ceil"]:,} pontos'.replace(",", ".")
    body = [
        f'<rect x="24" y="24" width="176" height="176" rx="10" fill="#6e7f96" stroke="{BORDER}"/>',
        avatar(32, 32, 10),
        f'<rect x="24" y="212" width="176" height="44" rx="10" fill="{PANEL}" stroke="{BORDER}"/>',
        text(112, 240, f'Nível {s["level"]}', 18, TEXT, "bold", "middle"),
        text(224, 50, s["name"], 26, TEXT, "bold"),
        text(224, 74, HEADLINE, 14, MUTED),
        text(224, 106, f'Progresso para o nível {s["level"] + 1}', 12, MUTED),
        text(816, 106, score, 12, MUTED, "normal", "end"),
        bar(224, 114, 592, 10, ratio, BLUE),
    ]
    for index, (value, label) in enumerate(metrics):
        x = 224 + (index % 3) * 201.5
        y = 144 + (index // 3) * 60
        body += [
            f'<rect x="{x}" y="{y}" width="189" height="52" rx="8" fill="{PANEL}" stroke="{BORDER}"/>',
            text(x + 14, y + 25, value, 17, TEXT, "bold"),
            text(x + 14, y + 42, label, 11, MUTED),
        ]
    body.append(text(24, 282, "Dados públicos do GitHub", 11, MUTED))
    body.append(text(816, 282, f'Atualizado em {s["today"].strftime("%d/%m/%Y")}', 11, MUTED, "normal", "end"))
    title = f'{s["name"]}: nível {s["level"]}, {s["points"]} pontos'
    return svg(840, 300, "".join(body), title)


def status_mark(cx, cy, done):
    if not done:
        return f'<circle cx="{cx}" cy="{cy}" r="11" fill="none" stroke="{MUTED}" stroke-width="2"/>'
    return (f'<circle cx="{cx}" cy="{cy}" r="12" fill="{GREEN}"/>'
            f'<path d="M{cx - 5} {cy} l3.5 3.5 l6.5 -7" fill="none" stroke="{BG}" '
            f'stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/>')


def milestones_svg(s):
    items = milestones(s)
    reached = sum(1 for item in items if item[2] >= item[3])
    body = [
        text(24, 36, "Marcos", 18, TEXT, "bold"),
        text(816, 36, f"{reached} de {len(items)} alcançados", 13, MUTED, "normal", "end"),
    ]
    for index, (title, desc, value, goal) in enumerate(items):
        x = 16 + (index % 3) * 272
        y = 54 + (index // 3) * 88
        done = value >= goal
        body += [
            f'<rect x="{x}" y="{y}" width="264" height="80" rx="10" fill="{PANEL}" stroke="{BORDER}"/>',
            status_mark(x + 28, y + 32, done),
            text(x + 54, y + 26, title, 13, TEXT, "bold"),
            text(x + 54, y + 44, desc, 11, MUTED),
            bar(x + 54, y + 56, 130, 6, value / goal, GREEN if done else BLUE),
            text(x + 250, y + 63, f"{min(value, goal)}/{goal}", 10, MUTED, "normal", "end"),
        ]
    rows = math.ceil(len(items) / 3)
    return svg(840, 54 + rows * 88 + 8, "".join(body),
               f"Marcos: {reached} de {len(items)} alcançados")


def goals(s):
    pending = [item for item in milestones(s) if item[2] < item[3]]
    pending.sort(key=lambda item: item[2] / item[3], reverse=True)
    rows = [
        ("SEMANAL", "Dias com atividade nesta semana", s["week_days"], 5),
        ("SEMANAL", "Contribuições nesta semana", s["week_total"], 20),
        ("MENSAL", "Novo repositório neste mês", s["month_repos"], 1),
    ]
    if pending:
        title, desc, value, goal = pending[0]
        rows.append(("PRÓXIMO MARCO", f"{title}: {desc}", value, goal))
    return rows


def goals_svg(s):
    rows = goals(s)
    body = [text(24, 36, "Metas em andamento", 18, TEXT, "bold")]
    for index, (kind, label, value, goal) in enumerate(rows):
        y = 56 + index * 46
        done = value >= goal
        body += [
            f'<rect x="16" y="{y}" width="808" height="38" rx="8" fill="{PANEL}" stroke="{BORDER}"/>',
            text(30, y + 24, kind, 11, MUTED, "bold"),
            text(140, y + 24, label, 12, TEXT),
            bar(590, y + 16, 160, 6, value / goal, GREEN if done else BLUE),
            text(810, y + 24, f"{min(value, goal)}/{goal}", 12, MUTED, "normal", "end"),
        ]
    return svg(840, 56 + len(rows) * 46 + 8, "".join(body), "Metas em andamento")


def projects_table(s):
    lines = ["| Projeto | Descrição | Linguagem | Última atualização |", "|---|---|---|---|"]
    for repo in s["repos"]:
        if repo["name"] == LOGIN:
            continue
        language = (repo["primaryLanguage"] or {}).get("name", "—")
        pushed = datetime.fromisoformat(repo["pushedAt"].replace("Z", "+00:00")).astimezone(BRT)
        description = (repo["description"] or "—").replace("|", "\\|")
        lines.append(f'| [{repo["name"]}]({repo["url"]}) | {description} | {language} '
                     f'| {pushed.strftime("%d/%m/%Y")} |')
    return "\n".join(lines)


def update_readme(s):
    path = ROOT / "README.md"
    content = path.read_text(encoding="utf-8")
    block = f"<!-- PROJETOS:START -->\n{projects_table(s)}\n<!-- PROJETOS:END -->"
    updated = re.sub(r"<!-- PROJETOS:START -->.*?<!-- PROJETOS:END -->",
                     lambda _: block, content, flags=re.S)
    path.write_text(updated, encoding="utf-8", newline="\n")


def main():
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not token:
        sys.exit("Defina GH_TOKEN ou GITHUB_TOKEN.")
    user, days, prs, issues = fetch(token)
    stats = build_stats(user, days, prs, issues, datetime.now(BRT).date())
    ASSETS.mkdir(exist_ok=True)
    for name, content in (("hero", hero_svg(stats)),
                          ("marcos", milestones_svg(stats)),
                          ("metas", goals_svg(stats))):
        (ASSETS / f"{name}.svg").write_text(content, encoding="utf-8", newline="\n")
    update_readme(stats)
    print(f'Nível {stats["level"]} | {stats["points"]} pontos | '
          f'{stats["contributions"]} contribuições | sequência {stats["current"]}/{stats["best"]}')


if __name__ == "__main__":
    main()
