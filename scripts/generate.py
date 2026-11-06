#!/usr/bin/env python3
"""Gera a ficha de RPG do perfil a partir de dados reais do GitHub.

Saidas: assets/hero.svg, assets/achievements.svg, assets/quests.svg
e a tabela de dungeons no README.md. Usa apenas a biblioteca padrao.

Uso: GH_TOKEN=<token> python scripts/generate.py
"""
import base64
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
GOLD, GREEN, PURPLE, BLUE, RED = "#f2c94c", "#3fb950", "#a371f7", "#58a6ff", "#f85149"

FRONT = {"HTML", "CSS", "TypeScript", "JavaScript", "Vue", "Svelte"}
DATA = {"Python", "Jupyter Notebook", "PLpgSQL", "SQL", "TSQL", "R"}

PROFILE_QUERY = """
query($login:String!){user(login:$login){
  name createdAt avatarUrl(size:352) followers{totalCount}
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
        headers={"Authorization": f"bearer {token}", "User-Agent": "profile-rpg"},
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


def fetch_avatar(url):
    with urllib.request.urlopen(url, timeout=30) as resp:
        kind = resp.headers.get_content_type()
        return f"data:{kind};base64,{base64.b64encode(resp.read()).decode()}"


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


def player_class(languages):
    names = set(languages)
    if names & FRONT and names & DATA:
        return "Paladino Full-Stack"
    if names & DATA:
        return "Alquimista de Dados"
    if names & FRONT:
        return "Ilusionista de Interfaces"
    return "Aventureiro"


def rank_title(level):
    for minimum, title in ((30, "Lenda"), (20, "Mestre"), (10, "Veterano"), (5, "Aventureiro")):
        if level >= minimum:
            return title
    return "Aprendiz"


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
    xp = (contributions * 10 + prs * 40 + issues * 20 + len(repos) * 100
          + stars * 50 + followers * 30 + best * 20)
    level = math.isqrt(xp // 100) + 1
    monday = today - timedelta(days=today.weekday())
    week = [days.get(monday + timedelta(days=i), 0) for i in range(7)]
    return {
        "name": user["name"] or LOGIN, "avatar": fetch_avatar(user["avatarUrl"]), "repos": repos, "languages": languages,
        "contributions": contributions, "prs": prs, "issues": issues,
        "stars": stars, "followers": followers, "current": current, "best": best,
        "active_days": sum(1 for count in days.values() if count),
        "xp": xp, "level": level,
        "level_floor": 100 * (level - 1) ** 2, "level_ceil": 100 * level ** 2,
        "class": player_class(languages), "rank": rank_title(level),
        "week_days": sum(1 for count in week if count), "week_total": sum(week),
        "month_repos": sum(
            1 for r in repos
            if r["createdAt"][:7] == today.strftime("%Y-%m")
        ),
        "today": today,
    }


def achievements(s):
    """(icone, titulo, descricao, valor atual, meta). Desc cabe em ~27 caracteres."""
    return [
        ("🌱", "Primeiros Passos", "Faça sua 1ª contribuição", s["contributions"], 1),
        ("⚔️", "Centurião", "100 contribuições", s["contributions"], 100),
        ("🏛️", "Lenda dos Commits", "1.000 contribuições", s["contributions"], 1000),
        ("🔥", "Semana em Chamas", "7 dias seguidos", s["best"], 7),
        ("🌋", "Mês Imparável", "30 dias seguidos", s["best"], 30),
        ("📅", "Veterano", "100 dias com atividade", s["active_days"], 100),
        ("🗺️", "Explorador", "5 repositórios públicos", len(s["repos"]), 5),
        ("🧙", "Poliglota", "5 linguagens diferentes", len(s["languages"]), 5),
        ("🤝", "Aliado", "Abra 1 pull request", s["prs"], 1),
        ("🐛", "Caçador de Bugs", "Abra 5 issues", s["issues"], 5),
        ("⭐", "Primeira Estrela", "Ganhe 1 estrela", s["stars"], 1),
        ("👥", "Guilda", "Tenha 5 seguidores", s["followers"], 5),
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


def avatar(data_uri, x, y, size):
    """Foto atual do perfil, embutida porque SVG em <img> nao carrega URLs externas."""
    return (f'<clipPath id="photo"><rect x="{x}" y="{y}" width="{size}" height="{size}" rx="10"/>'
            f'</clipPath><image href="{data_uri}" x="{x}" y="{y}" width="{size}" height="{size}" '
            f'clip-path="url(#photo)" preserveAspectRatio="xMidYMid slice"/>')


def hero_svg(s):
    span = s["level_ceil"] - s["level_floor"]
    ratio = (s["xp"] - s["level_floor"]) / span
    attributes = [
        ("FOR", "Contribuições", s["contributions"] / 10, RED),
        ("DES", "Maior sequência", s["best"] * 3, GREEN),
        ("CON", "Repositórios", len(s["repos"]) * 8, GOLD),
        ("INT", "Linguagens", len(s["languages"]) * 8, BLUE),
        ("SAB", "Dias ativos", s["active_days"] / 3, PURPLE),
        ("CAR", "Estrelas + seguidores", (s["stars"] + s["followers"]) * 5, "#ff7ab6"),
    ]
    body = [
        f'<rect x="24" y="24" width="176" height="176" rx="10" fill="{PANEL}" stroke="{BORDER}"/>',
        avatar(s["avatar"], 24, 24, 176),
        f'<rect x="24" y="212" width="176" height="44" rx="10" fill="{GOLD}"/>',
        text(112, 242, f'NÍVEL {s["level"]}', 22, BG, "bold", "middle"),
        text(224, 52, s["name"], 26, TEXT, "bold"),
        text(224, 78, f'{s["class"]} · {s["rank"]}', 15, GOLD, "bold"),
        text(224, 112, "XP", 12, MUTED, "bold"),
        text(816, 112, f'{s["xp"]:,} / {s["level_ceil"]:,}'.replace(",", "."), 12, MUTED,
             "normal", "end"),
        bar(224, 120, 592, 14, ratio, GREEN),
    ]
    for index, (code, label, value, color) in enumerate(attributes):
        x = 224 + (index // 3) * 304
        y = 164 + (index % 3) * 32
        points = min(99, int(value))
        body += [
            text(x, y, code, 13, color, "bold"),
            text(x + 36, y, label, 11, MUTED),
            text(x + 288, y, points, 13, TEXT, "bold", "end"),
            bar(x, y + 6, 288, 6, points / 99, color),
        ]
    body.append(text(24, 280, f'🔥 Sequência atual: {s["current"]} dias · Recorde: {s["best"]} dias', 12, MUTED))
    body.append(text(816, 280, f'Atualizado em {s["today"].strftime("%d/%m/%Y")}', 11, MUTED, "normal", "end"))
    title = f'{s["name"]}: nível {s["level"]}, {s["class"]}, {s["xp"]} XP'
    return svg(840, 300, "".join(body), title)


def achievements_svg(s):
    items = achievements(s)
    unlocked = sum(1 for item in items if item[3] >= item[4])
    body = [
        text(24, 36, "🏆 Conquistas", 18, TEXT, "bold"),
        text(816, 36, f"{unlocked} de {len(items)} desbloqueadas", 13, GOLD, "bold", "end"),
    ]
    for index, (icon, title, desc, value, goal) in enumerate(items):
        x = 16 + (index % 3) * 272
        y = 54 + (index // 3) * 88
        done = value >= goal
        body.append(f'<g opacity="{1 if done else 0.62}">')
        body.append(f'<rect x="{x}" y="{y}" width="264" height="80" rx="10" fill="{PANEL}" '
                    f'stroke="{GOLD if done else BORDER}"/>')
        body.append(text(x + 14, y + 36, icon if done else "🔒", 24))
        body.append(text(x + 54, y + 26, title, 13, GOLD if done else TEXT, "bold"))
        body.append(text(x + 54, y + 44, desc, 11, MUTED))
        body.append(bar(x + 54, y + 56, 130, 6, value / goal, GREEN if done else BLUE))
        body.append(text(x + 250, y + 63, f"{min(value, goal)}/{goal}", 10, MUTED, "normal", "end"))
        body.append("</g>")
    rows = math.ceil(len(items) / 3)
    return svg(840, 54 + rows * 88 + 8, "".join(body),
               f"Conquistas: {unlocked} de {len(items)} desbloqueadas")


def quests(s):
    locked = [item for item in achievements(s) if item[3] < item[4]]
    locked.sort(key=lambda item: item[3] / item[4], reverse=True)
    rows = [
        ("SEMANAL", "Dias com atividade nesta semana", s["week_days"], 5, BLUE),
        ("SEMANAL", "Contribuições nesta semana", s["week_total"], 20, BLUE),
        ("MENSAL", "Criar um repositório novo neste mês", s["month_repos"], 1, PURPLE),
    ]
    if locked:
        _, title, desc, value, goal = locked[0]
        rows.append(("PRINCIPAL", f"{title}: {desc}", value, goal, GOLD))
    return rows


def quests_svg(s):
    rows = quests(s)
    body = [text(24, 36, "📜 Missões ativas", 18, TEXT, "bold")]
    for index, (kind, label, value, goal, color) in enumerate(rows):
        y = 56 + index * 46
        done = value >= goal
        body += [
            f'<rect x="16" y="{y}" width="808" height="38" rx="8" fill="{PANEL}" stroke="{BORDER}"/>',
            text(30, y + 24, kind, 11, color, "bold"),
            text(116, y + 24, ("✓ " if done else "") + label, 12, GREEN if done else TEXT),
            bar(590, y + 16, 160, 6, value / goal, GREEN if done else color),
            text(810, y + 24, f"{min(value, goal)}/{goal}", 12, MUTED, "normal", "end"),
        ]
    return svg(840, 56 + len(rows) * 46 + 8, "".join(body), "Missões ativas")


def dungeons_table(s):
    lines = ["| Dungeon | Missão | Linguagem | Última exploração |", "|---|---|---|---|"]
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
    block = f"<!-- DUNGEONS:START -->\n{dungeons_table(s)}\n<!-- DUNGEONS:END -->"
    updated = re.sub(r"<!-- DUNGEONS:START -->.*?<!-- DUNGEONS:END -->",
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
                          ("achievements", achievements_svg(stats)),
                          ("quests", quests_svg(stats))):
        (ASSETS / f"{name}.svg").write_text(content, encoding="utf-8", newline="\n")
    update_readme(stats)
    print(f'Nível {stats["level"]} | {stats["xp"]} XP | {stats["class"]} | '
          f'{stats["contributions"]} contribuições | sequência {stats["current"]}/{stats["best"]}')


if __name__ == "__main__":
    main()
