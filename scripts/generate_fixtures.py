"""Generate the committed SYNTHETIC API responses under fixtures/responses/.

Every company, posting, ID and URL produced here is invented. The responses mimic the
shape of the public Greenhouse, Lever and Ashby job-board APIs closely enough to exercise
the real parsing code, and they encode a handful of scripted edge cases the tests rely on:

* northwindrobotics (greenhouse) 4100001: intern posting seen 08-10..08-17, closed 08-24.
* northwindrobotics (greenhouse) 08-17: one job repeated twice in the same response.
* mapleledger (greenhouse) 5200001: seen 08-03..08-10, gone 08-17..08-24, back 08-31..09-07
  (two lifecycle spells).
* auroralabs (lever): ML posting retitled to "Senior ..." from 08-24 onward (one spell).
  On 08-31 the same posting is still listed but arrives with a blank title: a contract
  reject below the reject-ratio gate. It must stay one unbroken spell (observed, just
  unparseable), not close on 08-31 and reopen on 09-07.
* tidewaterlogistics (lever): HTTP 500 on 08-24 - nothing may be "closed" by that failure.
* glaciergames (ashby) 08-10: one job with a blank title (contract reject -> quarantine);
  one job is always ``isListed: false`` and must be filtered out in staging.

Run:  python scripts/generate_fixtures.py   (deterministic; rewrites the directory)
"""

from __future__ import annotations

import html
import json
import random
import shutil
import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "fixtures" / "responses"
SNAPSHOTS = [date(2026, 8, 3) + timedelta(weeks=i) for i in range(6)]
SEED = 20260803

# fmt: off
TITLES = {
    "software": ["Software Engineer", "Backend Developer", "Full Stack Developer"],
    "frontend": ["Frontend Developer", "Mobile Developer (iOS)"],
    "game": ["Gameplay Programmer", "Engine Programmer"],
    "data_eng": ["Data Engineer", "Analytics Engineer"],
    "ml": ["Machine Learning Engineer", "Data Scientist", "Applied Scientist"],
    "analytics": ["Data Analyst", "Business Intelligence Analyst", "Product Analyst"],
    "devops": ["Site Reliability Engineer", "DevOps Engineer", "Platform Engineer"],
    "qa": ["QA Automation Engineer", "Software Developer in Test"],
    "embedded": ["Embedded Software Engineer", "Robotics Software Engineer", "Firmware Engineer"],
    "security": ["Security Engineer", "Application Security Analyst"],
    "product": ["Product Manager", "Technical Product Manager"],
    "design": ["Product Designer", "UX Researcher"],
    "business": ["Account Executive", "Customer Success Manager"],
}

SKILLS = {
    "software": ["Python", "Java", "TypeScript", "React", "PostgreSQL", "Docker", "Kubernetes",
                 "AWS", "REST APIs", "GraphQL", "CI/CD", "Git", "Go", "Spring Boot"],
    "frontend": ["TypeScript", "JavaScript", "React", "Node.js", "GraphQL",
                 "web accessibility (WCAG)", "CI/CD", "Figma"],
    "game": ["C++", "C#", "Unity", "Unreal Engine", "Python", "Git", "Linux"],
    "data_eng": ["Python", "SQL", "dbt", "Airflow", "Spark", "Kafka", "Snowflake", "BigQuery",
                 "Google Cloud (GCP)", "Terraform", "Docker", "data warehousing"],
    "ml": ["Python", "PyTorch", "TensorFlow", "scikit-learn", "machine learning", "statistics",
           "SQL", "pandas", "NumPy", "Kubernetes", "AWS"],
    "analytics": ["SQL", "Excel", "Tableau", "Power BI", "Python", "pandas", "statistics", "dbt",
                  "BigQuery", "A/B testing"],
    "devops": ["Terraform", "Kubernetes", "Docker", "AWS", "Azure", "Google Cloud", "CI/CD",
               "Linux", "Prometheus", "Grafana", "Python", "Go", "Bash"],
    "qa": ["Python", "Selenium", "Playwright", "pytest", "Java", "CI/CD", "JavaScript"],
    "embedded": ["C++", "embedded C", "ROS 2", "Python", "Linux", "Git"],
    "security": ["Python", "Linux", "AWS", "Kubernetes", "Go", "threat modelling"],
    "product": ["SQL", "A/B testing", "Excel", "roadmapping", "user research"],
    "design": ["Figma", "web accessibility (WCAG)", "user research", "prototyping"],
    "business": ["Salesforce", "Excel", "SQL", "a go-to-market plan"],
}

DEPARTMENTS = {
    "software": "Engineering", "frontend": "Engineering", "game": "Engineering",
    "data_eng": "Data", "ml": "Data", "analytics": "Data", "devops": "Infrastructure",
    "qa": "Engineering", "embedded": "Hardware", "security": "Security",
    "product": "Product", "design": "Design", "business": "Revenue",
}

SENIORITY_WEIGHTS = [("intern", 15), ("entry", 15), ("mid", 40), ("senior", 25), ("staff", 5)]

MISSIONS = [
    "help customers ship faster", "make our platform more reliable",
    "turn messy data into decisions", "build the next generation of our product",
    "scale systems that serve millions of requests", "improve the quality of every release",
]
PERKS = [
    "We offer flexible hours and a learning budget.",
    "Excellent communication skills are valued here.",
    "You will join a small, supportive team that pairs often.",
    "We offer health benefits, an RRSP match and four weeks of vacation.",
]


# fmt: on


@dataclass(frozen=True)
class BoardSpec:
    source: str
    board: str
    company: str
    locations: list[str]
    families: list[tuple[str, int]]
    initial: int = 10


# fmt: off
BOARDS = [
    BoardSpec("greenhouse", "northwindrobotics", "Northwind Robotics",
              ["Waterloo, ON, Canada", "Toronto, ON, Canada", "Remote - Canada",
               "Waterloo, ON (Hybrid)"],
              [("embedded", 4), ("software", 3), ("ml", 2), ("qa", 1), ("devops", 1)]),
    BoardSpec("greenhouse", "mapleledger", "Maple Ledger",
              ["Toronto, ON, Canada", "Montreal, QC, Canada", "Remote - Canada", "New York, NY"],
              [("software", 3), ("data_eng", 2), ("analytics", 2), ("security", 1),
               ("product", 1), ("frontend", 1)]),
    BoardSpec("lever", "auroralabs", "Aurora Health Labs",
              ["Vancouver, BC", "Calgary, AB", "Remote (Canada)"],
              [("ml", 3), ("data_eng", 1), ("software", 2), ("devops", 1), ("design", 1),
               ("analytics", 1)]),
    BoardSpec("lever", "tidewaterlogistics", "Tidewater Logistics",
              ["Halifax, NS", "Montreal, QC", "Chicago, IL", "Remote (Canada)"],
              [("analytics", 2), ("software", 2), ("devops", 1), ("business", 2),
               ("data_eng", 1)]),
    BoardSpec("ashby", "glaciergames", "Glacier Games",
              ["Montreal, QC", "Remote - Canada", "Austin, TX"],
              [("game", 4), ("qa", 2), ("design", 1), ("analytics", 1), ("frontend", 1)]),
]
# fmt: on


@dataclass
class Posting:
    pid: str
    title: str
    family: str
    seniority: str
    location: str
    skills: list[str]
    published: datetime
    open_weeks: set[int]
    mission: str
    perk: str
    retitle_from_week: int | None = None
    retitle: str | None = None
    extra: dict = field(default_factory=dict)

    def title_at(self, week: int) -> str:
        if self.retitle_from_week is not None and week >= self.retitle_from_week:
            return self.retitle or self.title
        return self.title


def make_title(rng: random.Random, base: str, seniority: str) -> str:
    term = rng.choice(["Winter 2027", "Summer 2027"])
    if seniority == "intern":
        return rng.choice([f"{base} Intern ({term})", f"{base} Co-op ({term})"])
    if seniority == "entry":
        return rng.choice([f"Junior {base}", f"{base}, New Grad", f"Associate {base}"])
    if seniority == "senior":
        return f"Senior {base}"
    if seniority == "staff":
        return rng.choice([f"Staff {base}", f"Principal {base}"])
    return base


def weighted(rng: random.Random, pairs: list[tuple[str, int]]) -> str:
    names, weights = zip(*pairs, strict=True)
    return rng.choices(names, weights=weights, k=1)[0]


def new_id(rng: random.Random, spec: BoardSpec, counter: list[int]) -> str:
    if spec.source == "greenhouse":
        counter[0] += 1
        return str(counter[0])
    return str(uuid.UUID(int=rng.getrandbits(128), version=4))


def random_posting(rng: random.Random, spec: BoardSpec, counter: list[int], start: int) -> Posting:
    family = weighted(rng, spec.families)
    seniority = weighted(rng, SENIORITY_WEIGHTS)
    title = make_title(rng, rng.choice(TITLES[family]), seniority)
    skills = rng.sample(SKILLS[family], k=min(len(SKILLS[family]), rng.randint(3, 5)))
    lifetime = rng.randint(1, 7)
    open_weeks = {w for w in range(start, start + lifetime) if w < len(SNAPSHOTS)}
    back = rng.randint(7, 60) if start == 0 else rng.randint(1, 6)
    published = datetime.combine(SNAPSHOTS[start] - timedelta(days=back), time(14, 30), UTC)
    return Posting(
        pid=new_id(rng, spec, counter),
        title=title,
        family=family,
        seniority=seniority,
        location=rng.choice(spec.locations),
        skills=skills,
        published=published,
        open_weeks=open_weeks,
        mission=rng.choice(MISSIONS),
        perk=rng.choice(PERKS),
    )


def scenario(rng: random.Random, spec: BoardSpec) -> list[Posting]:
    counter = [{"northwindrobotics": 4100000, "mapleledger": 5200000}.get(spec.board, 0)]
    scripted: list[Posting] = []

    def scripted_posting(title, family, seniority, weeks, location, skills, **kw) -> Posting:
        start = min(weeks)
        published = datetime.combine(SNAPSHOTS[start] - timedelta(days=2), time(9), UTC)
        return Posting(
            pid=new_id(rng, spec, counter),
            title=title,
            family=family,
            seniority=seniority,
            location=location,
            skills=skills,
            published=published,
            open_weeks=set(weeks),
            mission=MISSIONS[0],
            perk=PERKS[0],
            **kw,
        )

    if spec.board == "northwindrobotics":
        scripted.append(
            scripted_posting(
                "Software Engineering Intern (Winter 2027)",
                "software",
                "intern",
                [1, 2],
                "Waterloo, ON, Canada",
                ["Python", "C++", "ROS 2", "Git"],
            )
        )
    if spec.board == "mapleledger":
        scripted.append(
            scripted_posting(
                "Data Analyst",
                "analytics",
                "mid",
                [0, 1, 4, 5],
                "Toronto, ON, Canada",
                ["SQL", "Python", "Tableau", "statistics"],
            )
        )
    if spec.board == "auroralabs":
        scripted.append(
            scripted_posting(
                "Machine Learning Engineer",
                "ml",
                "mid",
                [0, 1, 2, 3, 4, 5],
                "Vancouver, BC",
                ["Python", "PyTorch", "machine learning", "Kubernetes"],
                retitle_from_week=3,
                retitle="Senior Machine Learning Engineer",
            )
        )
    if spec.board == "tidewaterlogistics":
        scripted.append(
            scripted_posting(
                "Data Engineer",
                "data_eng",
                "mid",
                [1, 2, 3, 4],
                "Halifax, NS",
                ["Python", "SQL", "dbt", "Airflow", "Google Cloud (GCP)"],
            )
        )
    if spec.board == "glaciergames":
        scripted.append(
            scripted_posting(
                "Internal Playtest Coordinator",
                "qa",
                "mid",
                list(range(6)),
                "Montreal, QC",
                ["Unity"],
                extra={"isListed": False},
            )
        )

    postings = list(scripted)
    postings += [random_posting(rng, spec, counter, 0) for _ in range(spec.initial)]
    for week in range(1, len(SNAPSHOTS)):
        postings += [random_posting(rng, spec, counter, week) for _ in range(rng.randint(2, 3))]
    return postings


def article(word: str) -> str:
    return "an" if word[0].lower() in "aeiou" else "a"


def description(spec: BoardSpec, p: Posting, title: str) -> tuple[str, str]:
    """(plain text, html) description naming the posting's skills."""
    first, rest = p.skills[0], p.skills[1:]
    reqs = ", ".join(rest[:-1]) + (f" and {rest[-1]}" if len(rest) > 1 else "".join(rest))
    plain = [
        f"{spec.company} is hiring {article(title)} {title} to {p.mission}.",
        f"You will work mostly in {first} with a cross-functional team.",
        f"Requirements: hands-on experience with {reqs}." if rest else "",
        p.perk,
    ]
    plain = [s for s in plain if s]
    markup = "".join(f"<p>{html.escape(s)}</p>" for s in plain)
    return " ".join(plain), markup


def greenhouse_job(spec: BoardSpec, p: Posting, week: int) -> dict:
    title = p.title_at(week)
    _, markup = description(spec, p, title)
    dept = DEPARTMENTS[p.family]
    return {
        "absolute_url": f"https://job-boards.greenhouse.io/{spec.board}/jobs/{p.pid}",
        "company_name": spec.company,
        "content": html.escape(markup),
        "departments": [{"id": 9000 + len(dept), "name": dept, "child_ids": [], "parent_id": None}],
        "first_published": (p.published - timedelta(hours=4)).strftime("%Y-%m-%dT%H:%M:%S")
        + "-04:00",
        "id": int(p.pid),
        "internal_job_id": int(p.pid) + 77000,
        "location": {"name": p.location},
        "metadata": None,
        "requisition_id": f"REQ-{int(p.pid) % 10000:04d}",
        "title": title,
        "updated_at": (p.published + timedelta(days=1, hours=-4)).strftime("%Y-%m-%dT%H:%M:%S")
        + "-04:00",
    }


LEVER_WORKPLACE = {"Remote (Canada)": "remote"}
LEVER_COMMITMENT = {"intern": "Intern"}


def lever_posting(spec: BoardSpec, p: Posting, week: int) -> dict:
    title = p.title_at(week)
    plain, _ = description(spec, p, title)
    intro, *rest = plain.split(". ", 1)
    return {
        "additional": "<div>We are an equal-opportunity employer.</div>",
        "additionalPlain": "We are an equal-opportunity employer.",
        "applyUrl": f"https://jobs.lever.co/{spec.board}/{p.pid}/apply",
        "categories": {
            "allLocations": [p.location],
            "commitment": LEVER_COMMITMENT.get(p.seniority, "Full-time"),
            "department": DEPARTMENTS[p.family],
            "location": p.location,
            "team": DEPARTMENTS[p.family],
        },
        "country": "US" if p.location.endswith(", IL") else "CA",
        "createdAt": int(p.published.timestamp() * 1000),
        "description": f"<div>{html.escape(intro)}.</div>",
        "descriptionPlain": f"{intro}.",
        "hostedUrl": f"https://jobs.lever.co/{spec.board}/{p.pid}",
        "id": p.pid,
        "lists": [{"text": "About the role", "content": f"<li>{html.escape(''.join(rest))}</li>"}],
        "text": title,
        "workplaceType": LEVER_WORKPLACE.get(p.location, "on-site"),
    }


def ashby_job(spec: BoardSpec, p: Posting, week: int) -> dict:
    title = p.title_at(week)
    plain, markup = description(spec, p, title)
    remote = p.location.startswith("Remote")
    job = {
        "id": p.pid,
        "title": title,
        "department": DEPARTMENTS[p.family],
        "team": DEPARTMENTS[p.family],
        "employmentType": "Intern" if p.seniority == "intern" else "FullTime",
        "location": p.location,
        "secondaryLocations": [],
        "publishedAt": p.published.strftime("%Y-%m-%dT%H:%M:%S.000+00:00"),
        "isListed": True,
        "isRemote": remote,
        "workplaceType": "Remote" if remote else "OnSite",
        "jobUrl": f"https://jobs.ashbyhq.com/{spec.board}/{p.pid}",
        "applyUrl": f"https://jobs.ashbyhq.com/{spec.board}/{p.pid}/application",
        "descriptionHtml": markup,
        "descriptionPlain": plain,
    }
    job.update(p.extra)
    return job


def response(spec: BoardSpec, postings: list[Posting], week: int) -> object:
    live = [p for p in postings if week in p.open_weeks]
    if spec.source == "greenhouse":
        jobs = [greenhouse_job(spec, p, week) for p in live]
        if spec.board == "northwindrobotics" and week == 2:
            jobs.append(dict(jobs[3]))  # provider-side duplicate in one response
        return {"jobs": jobs, "meta": {"total": len(jobs)}}
    if spec.source == "lever":
        jobs = [lever_posting(spec, p, week) for p in live]
        if spec.board == "auroralabs" and week == 4:
            jobs[0]["text"] = "   "  # scripted ML posting: still listed, fails the contract
        return jobs
    jobs = [ashby_job(spec, p, week) for p in live]
    if week == 1:
        broken = dict(jobs[-1])
        broken["id"] = "00000000-0000-4000-8000-00000000bad1"
        broken["title"] = "   "
        jobs.append(broken)  # violates the contract -> quarantined, not loaded
    return {"apiVersion": "1", "jobs": jobs}


def main() -> None:
    rng = random.Random(SEED)
    if OUT.exists():
        shutil.rmtree(OUT)
    for spec in BOARDS:
        postings = scenario(rng, spec)
        for week, snapshot in enumerate(SNAPSHOTS):
            target = OUT / snapshot.isoformat() / spec.source / spec.board
            target.parent.mkdir(parents=True, exist_ok=True)
            if spec.board == "tidewaterlogistics" and week == 3:
                target.with_suffix(".status").write_text("500\n")
                continue
            body = response(spec, postings, week)
            target.with_suffix(".json").write_text(
                json.dumps(body, ensure_ascii=False, separators=(",", ":")) + "\n"
            )
    print(f"wrote fixtures for {len(BOARDS)} boards x {len(SNAPSHOTS)} snapshots to {OUT}")


if __name__ == "__main__":
    main()
