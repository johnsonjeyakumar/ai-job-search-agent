"""Deterministic normalization for skills, roles, and locations (Phase 5).

Matching needs a canonical identity per term so that "React.js", "ReactJS"
and "React Js" compare equal. Every comparison documents the original term
it came from, so nothing is ever silently rewritten.
"""
from __future__ import annotations

import re

_WS = re.compile(r"\s+")
_CLEAN = re.compile(r"[^a-z0-9+#.\- ]")


def normalize(text: str | None) -> str:
    """Collapse a term into a canonical lowercase key for comparison."""
    if not text:
        return ""
    lowered = text.lower().strip()
    lowered = _CLEAN.sub(" ", lowered)
    return _WS.sub(" ", lowered).strip(" -")


def normalize_role(text: str | None) -> str:
    """Role identity: lowercase, punctuation-free, tokens only."""
    return normalize(text)


ALIASES: dict[str, str] = {
    # JavaScript ecosystem
    "react.js": "React",
    "reactjs": "React",
    "react js": "React",
    "react": "React",
    "node.js": "Node.js",
    "nodejs": "Node.js",
    "node js": "Node.js",
    "node": "Node.js",
    "express.js": "Express",
    "expressjs": "Express",
    "express js": "Express",
    "express": "Express",
    # TypeScript / JS
    "typescript": "TypeScript",
    "javascript": "JavaScript",
    "js": "JavaScript",
    "ts": "TypeScript",
    # Python
    "python": "Python",
    "python3": "Python",
    # Java / JVM
    "java": "Java",
    "core java": "Java",
    "j2ee": "Java",
    "jsp": "Java",
    "servlets": "Java",
    # Spring
    "spring": "Spring",
    "spring boot": "Spring Boot",
    "springboot": "Spring Boot",
    "spring mvc": "Spring MVC",
    # Databases
    "sql": "SQL",
    "postgres": "PostgreSQL",
    "postgresql": "PostgreSQL",
    "pg": "PostgreSQL",
    "mysql": "MySQL",
    "sql server": "SQL Server",
    "mssql": "SQL Server",
    "mongodb": "MongoDB",
    "mongo": "MongoDB",
    "redis": "Redis",
    "cassandra": "Cassandra",
    "oracle": "Oracle",
    "h2": "H2",
    # Cloud
    "aws": "AWS",
    "aws cloud": "AWS",
    "azure": "Azure",
    "microsoft azure": "Azure",
    "gcp": "GCP",
    "google cloud": "GCP",
    "google cloud platform": "GCP",
    "heroku": "Heroku",
    # Frontend
    "html": "HTML",
    "html5": "HTML",
    "css": "CSS",
    "css3": "CSS",
    "bootstrap": "Bootstrap",
    "tailwind": "Tailwind CSS",
    "tailwindcss": "Tailwind CSS",
    "tailwind css": "Tailwind CSS",
    "jquery": "jQuery",
    "redux": "Redux",
    "react native": "React Native",
    "angular": "Angular",
    "vue": "Vue.js",
    "vue.js": "Vue.js",
    "vuejs": "Vue.js",
    "next.js": "Next.js",
    "nextjs": "Next.js",
    "next js": "Next.js",
    # Backend misc
    "rest": "REST APIs",
    "rest api": "REST APIs",
    "restful": "REST APIs",
    "restful api": "REST APIs",
    "restful apis": "REST APIs",
    "graphql": "GraphQL",
    "microservices": "Microservices",
    "micro service": "Microservices",
    "microservice": "Microservices",
    "docker": "Docker",
    "kubernetes": "Kubernetes",
    "k8s": "Kubernetes",
    "nginx": "Nginx",
    # Testing
    "junit": "JUnit",
    "selenium": "Selenium",
    "pytest": "Pytest",
    "jest": "Jest",
    "mocha": "Mocha",
    "cypress": "Cypress",
    "playwright": "Playwright",
    # Tools
    "git": "Git",
    "github": "GitHub",
    "gitlab": "GitLab",
    "maven": "Maven",
    "gradle": "Gradle",
    "jenkins": "Jenkins",
    "ci/cd": "CI/CD",
    "ci cd": "CI/CD",
    "cicd": "CI/CD",
    "jira": "Jira",
    "linux": "Linux",
    "unix": "Unix",
    "shell scripting": "Shell Scripting",
    "bash": "Bash",
    "powershell": "PowerShell",
    "postman": "Postman",
    "swagger": "Swagger",
    "kafka": "Apache Kafka",
    "aem": "AEM",
    # Concepts
    "oop": "OOP",
    "data structures": "Data Structures",
    "algorithms": "Algorithms",
    "django": "Django",
    "flask": "Flask",
    "fastapi": "FastAPI",
    "hibernate": "Hibernate",
    "oracle pl/sql": "PL/SQL",
    "pl/sql": "PL/SQL",
    "nosql": "NoSQL",
    "hadoop": "Hadoop",
    "spark": "Spark",
}

CANONICAL_NAMES: dict[str, str] = {
    "Python": "Python",
    "Java": "Java",
    "JavaScript": "JavaScript",
    "TypeScript": "TypeScript",
    "React": "React",
    "Node.js": "Node.js",
    "Express": "Express",
    "Spring": "Spring",
    "Spring Boot": "Spring Boot",
    "Spring MVC": "Spring MVC",
    "SQL": "SQL",
    "PostgreSQL": "PostgreSQL",
    "MySQL": "MySQL",
    "SQL Server": "SQL Server",
    "MongoDB": "MongoDB",
    "Redis": "Redis",
    "Cassandra": "Cassandra",
    "Oracle": "Oracle",
    "H2": "H2",
    "AWS": "AWS",
    "Azure": "Azure",
    "GCP": "GCP",
    "Heroku": "Heroku",
    "HTML": "HTML",
    "CSS": "CSS",
    "Bootstrap": "Bootstrap",
    "Tailwind CSS": "Tailwind CSS",
    "jQuery": "jQuery",
    "Redux": "Redux",
    "React Native": "React Native",
    "Angular": "Angular",
    "Vue.js": "Vue.js",
    "Next.js": "Next.js",
    "Django": "Django",
    "Flask": "Flask",
    "FastAPI": "FastAPI",
    "Hibernate": "Hibernate",
    "REST APIs": "REST APIs",
    "GraphQL": "GraphQL",
    "Microservices": "Microservices",
    "Docker": "Docker",
    "Kubernetes": "Kubernetes",
    "Nginx": "Nginx",
    "JUnit": "JUnit",
    "Selenium": "Selenium",
    "Pytest": "Pytest",
    "Jest": "Jest",
    "Mocha": "Mocha",
    "Cypress": "Cypress",
    "Playwright": "Playwright",
    "Git": "Git",
    "GitHub": "GitHub",
    "GitLab": "GitLab",
    "Maven": "Maven",
    "Gradle": "Gradle",
    "Jenkins": "Jenkins",
    "CI/CD": "CI/CD",
    "Jira": "Jira",
    "Linux": "Linux",
    "Unix": "Unix",
    "Shell Scripting": "Shell Scripting",
    "Bash": "Bash",
    "PowerShell": "PowerShell",
    "Postman": "Postman",
    "Swagger": "Swagger",
    "Apache Kafka": "Apache Kafka",
    "AEM": "AEM",
    "OOP": "OOP",
    "Data Structures": "Data Structures",
    "Algorithms": "Algorithms",
    "PL/SQL": "PL/SQL",
    "NoSQL": "NoSQL",
    "Hadoop": "Hadoop",
    "Spark": "Spark",
}


def canonicalize(term: str | None) -> str:
    """Return the canonical display name for a skill term."""
    if not term:
        return ""
    key = normalize(term)
    if key in ALIASES:
        return ALIASES[key]
    # No alias: keep the cleaned term itself (never fabricated).
    return key
