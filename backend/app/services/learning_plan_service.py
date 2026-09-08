"""Deterministic learning plan service (Phase 11 + 11.1).

Generates personalized learning plans from skill gap analysis.
Uses deterministic logic for sequencing and prioritization.
LLM may only explain concepts, suggest resources, and rewrite objectives.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.skill_gap import (
    LearningEvidence,
    LearningItem,
    LearningPlan,
    LearningResource,
)
from app.services.skill_gap_service import (
    analyze_skill_gaps,
    get_latest_analysis,
    record_skill_history,
)

# ---------------------------------------------------------------------------
# Prerequisite graph (deterministic)
# ---------------------------------------------------------------------------

# Canonical skill → known prerequisite skills (deterministic graph)
PREREQUISITE_GRAPH: dict[str, list[str]] = {
    "React": ["JavaScript", "HTML", "CSS"],
    "Vue.js": ["JavaScript", "HTML", "CSS"],
    "Angular": ["TypeScript", "HTML", "CSS"],
    "Next.js": ["React", "JavaScript"],
    "Node.js": ["JavaScript"],
    "Express": ["Node.js"],
    "Django": ["Python"],
    "Flask": ["Python"],
    "FastAPI": ["Python"],
    "Spring Boot": ["Java", "Spring"],
    "Spring MVC": ["Java", "Spring"],
    "React Native": ["React", "JavaScript"],
    "TypeScript": ["JavaScript"],
    "Redux": ["React"],
    "Tailwind CSS": ["HTML", "CSS"],
    "Bootstrap": ["HTML", "CSS"],
    "SQL": [],
    "PostgreSQL": ["SQL"],
    "MySQL": ["SQL"],
    "SQL Server": ["SQL"],
    "PL/SQL": ["SQL"],
    "MongoDB": [],
    "Redis": [],
    "Docker": [],
    "Kubernetes": ["Docker"],
    "CI/CD": [],
    "AWS": [],
    "Azure": [],
    "GCP": [],
    "GraphQL": [],
    "REST APIs": [],
    "Microservices": [],
    "Pytest": ["Python"],
    "Jest": ["JavaScript"],
    "Selenium": [],
    "Cypress": [],
    "Playwright": [],
    "JUnit": ["Java"],
    "Git": [],
    "GitHub": [],
    "Linux": [],
    "Hadoop": ["Java", "SQL"],
    "Spark": ["Python"],
    "Apache Kafka": [],
    "Hibernate": ["Java"],
    "OOP": [],
    "Data Structures": [],
    "Algorithms": [],
}


def _get_prerequisites(canonical: str) -> list[str]:
    """Get prerequisite skills for a canonical skill."""
    return PREREQUISITE_GRAPH.get(canonical, [])


# ---------------------------------------------------------------------------
# Learning objective templates (deterministic per skill)
# ---------------------------------------------------------------------------

LEARNING_OBJECTIVES: dict[str, str] = {
    "Python": "Understand Python syntax, data types, control flow, and core libraries",
    "JavaScript": "Understand JavaScript syntax, DOM manipulation, and async programming",
    "TypeScript": "Understand TypeScript type system, interfaces, and generics",
    "React": "Understand component lifecycle, hooks, state management, and JSX",
    "Vue.js": "Understand Vue components, reactivity, and single-file components",
    "Angular": "Understand Angular modules, components, services, and RxJS",
    "Node.js": "Understand Node.js event loop, modules, and package management",
    "Express": "Understand Express routing, middleware, and REST API patterns",
    "Django": "Understand Django ORM, views, templates, and URL routing",
    "Flask": "Understand Flask routing, templates, and extensions",
    "FastAPI": "Understand FastAPI path operations, Pydantic models, and async",
    "Spring Boot": "Understand Spring Boot auto-configuration, REST controllers, and JPA",
    "Java": "Understand Java OOP, collections, streams, and exception handling",
    "SQL": "Understand SQL queries, joins, indexes, and data modeling",
    "PostgreSQL": "Understand PostgreSQL features, extensions, and performance tuning",
    "MySQL": "Understand MySQL syntax, storage engines, and administration",
    "MongoDB": "Understand MongoDB document model, queries, and aggregation",
    "Redis": "Understand Redis data structures, caching patterns, and pub/sub",
    "Docker": "Understand Dockerfiles, container lifecycle, and image management",
    "Kubernetes": "Understand K8s pods, services, deployments, and configuration",
    "AWS": "Understand core AWS services (EC2, S3, RDS, Lambda)",
    "Azure": "Understand Azure services, ARM templates, and resource management",
    "GCP": "Understand GCP compute, storage, and BigQuery services",
    "CI/CD": "Understand continuous integration and deployment pipelines",
    "REST APIs": "Understand RESTful design principles, status codes, and versioning",
    "GraphQL": "Understand GraphQL schema design, resolvers, and client queries",
    "Microservices": "Understand service decomposition, communication patterns, and deployment",
    "Git": "Understand Git branching, merging, rebasing, and conflict resolution",
    "GitHub": "Understand GitHub workflows, PRs, issues, and Actions",
    "Linux": "Understand Linux shell, file system, and process management",
    "HTML": "Understand HTML5 semantics, forms, and accessibility",
    "CSS": "Understand CSS selectors, layout, flexbox, grid, and responsive design",
    "Tailwind CSS": "Understand utility-first CSS and responsive design patterns",
    "Bootstrap": "Understand Bootstrap grid system, components, and theming",
    "React Native": "Understand React Native components, navigation, and platform APIs",
    "Redux": "Understand Redux state management, actions, reducers, and middleware",
    "Pytest": "Understand Pytest fixtures, parametrize, and test organization",
    "Jest": "Understand Jest testing patterns, mocking, and coverage",
    "Selenium": "Understand Selenium WebDriver, locators, and test automation",
    "Cypress": "Understand Cypress commands, selectors, and E2E testing",
    "Playwright": "Understand Playwright page objects, selectors, and cross-browser testing",
    "JUnit": "Understand JUnit annotations, assertions, and test lifecycle",
    "OOP": "Understand encapsulation, inheritance, polymorphism, and abstraction",
    "Data Structures": "Understand arrays, linked lists, trees, graphs, and hash tables",
    "Algorithms": "Understand sorting, searching, recursion, and complexity analysis",
}


# ---------------------------------------------------------------------------
# Task generation (deterministic)
# ---------------------------------------------------------------------------


def _generate_tasks(skill: str, priority: str) -> list[dict]:
    """Generate deterministic learning tasks for a skill."""
    base_tasks = [
        {
            "title": f"Study {skill} fundamentals",
            "description": f"Read documentation and tutorials for {skill}",
            "type": "study",
            "estimated_hours": 4 if priority == "HIGH" else 2,
        },
        {
            "title": f"Build a practice project with {skill}",
            "description": f"Create a small project applying {skill} concepts",
            "type": "practice",
            "estimated_hours": 8 if priority == "HIGH" else 4,
        },
        {
            "title": f"Complete {skill} exercises",
            "description": f"Solve coding challenges using {skill}",
            "type": "exercise",
            "estimated_hours": 3 if priority == "HIGH" else 2,
        },
    ]
    return base_tasks


# ---------------------------------------------------------------------------
# Plan generation
# ---------------------------------------------------------------------------


def generate_learning_plan(
    session: Session,
    job_id: int,
    profile_id: int | None = None,
    resume_id: int | None = None,
) -> LearningPlan:
    """Generate a learning plan from skill gap analysis."""
    analysis = get_latest_analysis(session, job_id)
    if analysis is None:
        analysis = analyze_skill_gaps(session, job_id, profile_id, resume_id)

    missing = analysis.missing_skills or []
    partial = analysis.partial_skills or []
    priorities = analysis.priorities or {}

    # Include both MISSING and PARTIAL skills in the learning plan
    skills_to_learn = list(dict.fromkeys(missing + partial))

    # Deduplicate skills and sort by priority
    priority_order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    sorted_skills = sorted(
        skills_to_learn, key=lambda s: priority_order.get(priorities.get(s, "MEDIUM"), 1)
    )

    # Build prerequisite-resolved order
    resolved: list[str] = []
    seen: set[str] = set()
    for skill in sorted_skills:
        prereqs = _get_prerequisites(skill)
        for prereq in prereqs:
            if prereq not in seen and prereq not in skills_to_learn:
                # Prerequisite not in gap list — it's already known
                continue
            if prereq not in seen:
                resolved.append(prereq)
                seen.add(prereq)
        if skill not in seen:
            resolved.append(skill)
            seen.add(skill)

    from app.models.job import Job
    job = session.get(Job, job_id)
    target_role = job.title if job else None

    total_hours = 0
    items_data: list[dict] = []
    for idx, skill in enumerate(resolved):
        priority = priorities.get(skill, "MEDIUM")
        objective = LEARNING_OBJECTIVES.get(
            skill, f"Learn {skill} fundamentals and practical usage"
        )
        tasks = _generate_tasks(skill, priority)
        hours = sum(t["estimated_hours"] for t in tasks)
        total_hours += hours
        items_data.append({
            "skill": skill,
            "priority": priority,
            "objective": objective,
            "estimated_hours": hours,
            "prerequisites": [p for p in _get_prerequisites(skill) if p in seen and p != skill],
            "tasks": tasks,
            "completion_criteria": f"Complete all tasks and demonstrate {skill} competency",
            "evidence_requirement": (
                f"Provide evidence of {skill} usage"
                " (project, exercise, or certification)"
            ),
            "sort_order": idx,
        })

    plan = LearningPlan(
        job_id=job_id,
        profile_id=profile_id or 0,
        target_role=target_role,
        title=f"Skill Development Plan for {target_role or 'General'}",
        status="NOT_STARTED",
        total_items=len(items_data),
        completed_items=0,
        verified_items=0,
        estimated_effort_hours=total_hours,
    )
    session.add(plan)
    session.flush()

    for item_data in items_data:
        item = LearningItem(
            plan_id=plan.id,
            **item_data,
        )
        session.add(item)

    session.flush()
    return plan


def list_plans(
    session: Session,
    profile_id: int | None = None,
    limit: int = 20,
) -> list[LearningPlan]:
    """List learning plans."""
    stmt = select(LearningPlan)
    if profile_id is not None:
        stmt = stmt.where(LearningPlan.profile_id == profile_id)
    stmt = stmt.order_by(LearningPlan.created_at.desc()).limit(limit)
    return list(session.scalars(stmt).all())


def get_plan(session: Session, plan_id: int) -> LearningPlan | None:
    """Get a single learning plan with items."""
    return session.get(LearningPlan, plan_id)


def list_plan_items(
    session: Session, plan_id: int
) -> list[LearningItem]:
    """List items in a learning plan."""
    stmt = (
        select(LearningItem)
        .where(LearningItem.plan_id == plan_id)
        .order_by(LearningItem.sort_order)
    )
    return list(session.scalars(stmt).all())


def update_item_status(
    session: Session,
    item_id: int,
    status: str,
    profile_id: int | None = None,
) -> LearningItem | None:
    """Update a learning item's status with history tracking."""
    item = session.get(LearningItem, item_id)
    if item is None:
        return None
    valid = {"NOT_STARTED", "IN_PROGRESS", "PRACTICING", "COMPLETED", "VERIFIED"}
    if status not in valid:
        raise ValueError(f"Invalid status: {status}. Must be one of {valid}")

    previous_status = item.status
    item.status = status
    if status == "COMPLETED":
        item.completed_at = datetime.now(timezone.utc)
    elif status == "VERIFIED":
        item.verified_at = datetime.now(timezone.utc)
    session.flush()

    # Record skill history if status actually changed
    if previous_status != status and profile_id:
        record_skill_history(
            session,
            profile_id=profile_id,
            skill=item.skill,
            new_status=status,
            source="LEARNING_PROGRESS",
            reason=f"Learning item status changed from {previous_status} to {status}",
            previous_status=previous_status,
        )

    # Update plan totals
    plan = session.get(LearningPlan, item.plan_id)
    if plan:
        items = list_plan_items(session, plan.id)
        plan.completed_items = sum(1 for i in items if i.status in ("COMPLETED", "VERIFIED"))
        plan.verified_items = sum(1 for i in items if i.status == "VERIFIED")
        active = any(i.status in ("IN_PROGRESS", "PRACTICING") for i in items)
        if plan.completed_items >= plan.total_items and plan.total_items > 0:
            plan.status = "COMPLETED"
        elif plan.completed_items > 0 or active:
            plan.status = "IN_PROGRESS"
        session.flush()

    return item


def add_item_evidence(
    session: Session,
    item_id: int,
    evidence_type: str,
    url: str | None = None,
    description: str | None = None,
) -> "LearningEvidence":
    """Add evidence to a learning item."""
    valid_types = {"PROJECT_URL", "EXERCISE", "CERTIFICATION", "SCREENSHOT", "DESCRIPTION"}
    if evidence_type not in valid_types:
        raise ValueError(f"Invalid evidence_type: {evidence_type}")
    evidence = LearningEvidence(
        item_id=item_id,
        evidence_type=evidence_type,
        url=url,
        description=description,
    )
    session.add(evidence)
    session.flush()
    return evidence


# ---------------------------------------------------------------------------
# URL validation (deterministic)
# ---------------------------------------------------------------------------

_URL_PATTERN = re.compile(
    r"^https?://[^\s/$.?#].[^\s]*$", re.IGNORECASE
)


def _is_valid_url(url: str | None) -> bool:
    """Check if a URL has a valid structure."""
    if not url:
        return True  # URLs are optional
    return bool(_URL_PATTERN.match(url))


# ---------------------------------------------------------------------------
# Learning resource CRUD
# ---------------------------------------------------------------------------

VALID_RESOURCE_TYPES = {
    "DOCUMENTATION", "TUTORIAL", "COURSE", "VIDEO",
    "ARTICLE", "PRACTICE", "PROJECT",
}
VALID_RESOURCE_SOURCES = {"USER", "AI_SUGGESTED"}
VALID_FREE_OR_PAID = {"FREE", "PAID", "UNKNOWN"}
VALID_DIFFICULTY = {"BEGINNER", "INTERMEDIATE", "ADVANCED", "UNKNOWN"}


def add_item_resource(
    session: Session,
    item_id: int,
    title: str,
    resource_type: str,
    url: str | None = None,
    provider: str | None = None,
    description: str | None = None,
    free_or_paid: str = "UNKNOWN",
    difficulty: str = "UNKNOWN",
    source: str = "USER",
) -> LearningResource:
    """Add a learning resource to a learning item."""
    if resource_type not in VALID_RESOURCE_TYPES:
        raise ValueError(
            f"Invalid resource_type: {resource_type}."
            f" Must be one of {VALID_RESOURCE_TYPES}"
        )
    if source not in VALID_RESOURCE_SOURCES:
        raise ValueError(
            f"Invalid source: {source}."
            f" Must be one of {VALID_RESOURCE_SOURCES}"
        )
    if free_or_paid not in VALID_FREE_OR_PAID:
        raise ValueError(f"Invalid free_or_paid: {free_or_paid}")
    if difficulty not in VALID_DIFFICULTY:
        raise ValueError(f"Invalid difficulty: {difficulty}")
    if url and not _is_valid_url(url):
        raise ValueError(f"Invalid URL structure: {url}")

    resource = LearningResource(
        item_id=item_id,
        title=title,
        resource_type=resource_type,
        url=url,
        provider=provider,
        description=description,
        free_or_paid=free_or_paid,
        difficulty=difficulty,
        source=source,
    )
    session.add(resource)
    session.flush()
    return resource


def list_item_resources(
    session: Session,
    item_id: int,
) -> list[LearningResource]:
    """List resources for a learning item."""
    stmt = (
        select(LearningResource)
        .where(LearningResource.item_id == item_id)
        .order_by(LearningResource.created_at)
    )
    return list(session.scalars(stmt).all())


def delete_resource(
    session: Session,
    resource_id: int,
) -> bool:
    """Delete a learning resource. Returns True if deleted."""
    resource = session.get(LearningResource, resource_id)
    if resource is None:
        return False
    session.delete(resource)
    session.flush()
    return True
