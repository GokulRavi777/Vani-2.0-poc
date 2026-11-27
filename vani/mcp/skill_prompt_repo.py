"""
Database repository for MotherSkill -> SubSkill hierarchy and Few-Shot Question Generation Prompts.
"""

import json
from typing import Any, Dict, List, Optional
from sqlalchemy.orm import Session

from backend.app.database import Base, SessionLocal, engine
from backend.app.models import MotherSkill, SubSkill


_BASE_FEW_SHOT_TEMPLATE = """### ROLE & OBJECTIVE
You are VANI, a senior technical interviewer conducting a live voice-based technical assessment.
Your task is to generate ONE original, conversational, high-signal spoken technical question tailored to the candidate's active skill, specialization, and target difficulty.

### ACTIVE SESSION CONTEXT
- Mother Skill: {skill}
- Sub-Skill Specialization: {sub_skill}
- Focus Topic: {topic}
- Target Difficulty: {difficulty}
- Previously Asked Questions / IDs (DO NOT REPEAT): {previously_asked_questions}
- Concepts Already Explored: {concepts_explored}
- Remaining Primary Question Slots: {remaining_primary_allowance}

### FEW-SHOT EXAMPLES (Follow this exact reasoning & JSON structure)
{examples}

### QUALITY & VOICE CONSTRAINTS
1. Ask exactly ONE focused question on "{topic}" within {sub_skill} ({skill}) — never combine two questions or use more than one "?".
2. Keep the question concise and natural for speech (15–35 words), with zero markdown, bullet points, asterisks, or code syntax.
3. Test conceptual understanding, trade-offs, or real-world reasoning — never rote syntax memorization.
4. Do NOT include hints, examples, or answer keywords inside the question.
5. Do NOT repeat or closely paraphrase anything in "Previously Asked Questions".

### OUTPUT FORMAT (Valid JSON only, no markdown fences)
{{
  "question_text": "One clear spoken question ending with a single question mark?",
  "topic": "{topic}",
  "subtopic": "Specific subtopic tested",
  "difficulty": "{difficulty}",
  "expected_concepts": ["concept_1", "concept_2", "concept_3", "concept_4"],
  "question_type": "conceptual"
}}"""


def _fs(topic: str, difficulty: str, q_type: str, question: str, subtopic: str, concepts: List[str]) -> str:
    """Formats a single structured Input -> JSON Output few-shot example with escaped braces."""
    payload = json.dumps(
        {
            "question_text": question,
            "topic": topic,
            "subtopic": subtopic,
            "difficulty": difficulty,
            "expected_concepts": concepts,
            "question_type": q_type,
        },
        indent=2,
    )
    escaped_payload = payload.replace("{", "{{").replace("}", "}}")
    return (
        f"Input: Topic=\"{topic}\" | Difficulty=\"{difficulty}\" | Type=\"{q_type}\"\n"
        f"Output:\n{escaped_payload}"
    )


def _build_prompt(examples: List[str]) -> str:
    return _BASE_FEW_SHOT_TEMPLATE.replace("{examples}", "\n\n".join(examples))


DEFAULT_MOTHER_SKILLS: List[Dict[str, Any]] = [
    {
        "name": "Python",
        "description": "Python ecosystem covering core language fundamentals, Machine Learning, Data Science, and Data Analytics.",
        "sub_skills": [
            {
                "name": "Python Core",
                "description": "Core Python data structures, mutability, dictionaries, functions, scope, and error handling.",
                "topics": [
                    "Data Structures & Mutability",
                    "Dictionaries & Hash Maps",
                    "Functions & Scope",
                    "Control Flow & Error Handling",
                ],
                "difficulty_levels": ["Beginner", "Intermediate"],
                "system_prompt": (
                    "You are VANI, a senior Python technical interviewer. "
                    "Generate one concise, spoken conceptual question that tests real understanding without syntax trivia."
                ),
                "few_shot_prompt": _build_prompt([
                    _fs(
                        "Data Structures & Mutability",
                        "Beginner",
                        "conceptual",
                        "Could you explain the main differences between a list and a tuple in Python, and when you would choose one over the other?",
                        "Lists vs Tuples",
                        ["mutable vs immutable", "hashability", "memory and safety", "use cases"],
                    ),
                    _fs(
                        "Dictionaries & Hash Maps",
                        "Intermediate",
                        "conceptual",
                        "How do Python dictionaries achieve fast key lookups compared to searching through a list?",
                        "Hash Table Lookup",
                        ["hash table", "O(1) average lookup", "hashable keys", "linear scan comparison"],
                    ),
                ]),
            },
            {
                "name": "Machine Learning",
                "description": "Supervised and unsupervised learning, model evaluation, overfitting, and Scikit-Learn workflows.",
                "topics": [
                    "Supervised vs Unsupervised Learning",
                    "Bias-Variance & Overfitting",
                    "Model Evaluation Metrics",
                    "Feature Engineering & Pipelines",
                ],
                "difficulty_levels": ["Junior", "Mid-Level", "Senior"],
                "system_prompt": (
                    "You are VANI, a senior Machine Learning interviewer. "
                    "Generate one clear spoken question on ML theory, evaluation trade-offs, and production pipelines."
                ),
                "few_shot_prompt": _build_prompt([
                    _fs(
                        "Bias-Variance & Overfitting",
                        "Mid-Level",
                        "conceptual",
                        "How do you detect overfitting in a machine learning model, and what techniques do you use to reduce it?",
                        "Overfitting Mitigation",
                        ["training vs validation gap", "regularization", "cross-validation", "early stopping"],
                    ),
                    _fs(
                        "Feature Engineering & Pipelines",
                        "Senior",
                        "scenario",
                        "Why should feature scaling be fitted only on training data inside a pipeline rather than on the full dataset?",
                        "Data Leakage Prevention",
                        ["data leakage", "train-test separation", "fit vs transform", "generalization"],
                    ),
                ]),
            },
            {
                "name": "Data Science",
                "description": "NumPy vectorization, Pandas DataFrames, exploratory data analysis, and statistical testing.",
                "topics": [
                    "NumPy & Vectorization",
                    "Pandas DataFrames & Merging",
                    "Exploratory Data Analysis",
                    "Statistical Hypothesis Testing",
                ],
                "difficulty_levels": ["Junior", "Mid-Level", "Senior"],
                "system_prompt": (
                    "You are VANI, a senior Data Science interviewer. "
                    "Generate one practical spoken question on Python data workflows and statistical reasoning."
                ),
                "few_shot_prompt": _build_prompt([
                    _fs(
                        "NumPy & Vectorization",
                        "Mid-Level",
                        "conceptual",
                        "Why are vectorized NumPy operations significantly faster than standard Python loops on large numerical arrays?",
                        "Vectorized Execution",
                        ["contiguous memory", "C-level loops", "SIMD", "avoiding Python interpreter overhead"],
                    ),
                    _fs(
                        "Statistical Hypothesis Testing",
                        "Mid-Level",
                        "conceptual",
                        "How would you explain a p-value in plain terms when evaluating the results of an experiment?",
                        "Hypothesis Testing",
                        ["null hypothesis", "probability of observed result", "significance threshold", "false positives"],
                    ),
                ]),
            },
            {
                "name": "Data Analytics",
                "description": "Data cleaning, aggregations, cohort/funnel analysis, and translating metrics into business insights.",
                "topics": [
                    "Data Cleaning & Validation",
                    "Grouping & Window Aggregations",
                    "KPI & Funnel Analysis",
                    "Visualization & Storytelling",
                ],
                "difficulty_levels": ["Junior", "Mid-Level"],
                "system_prompt": (
                    "You are VANI, a senior Data Analytics interviewer. "
                    "Generate one practical spoken question on analytical reasoning, data quality, and metrics in Python."
                ),
                "few_shot_prompt": _build_prompt([
                    _fs(
                        "Data Cleaning & Validation",
                        "Junior",
                        "scenario",
                        "When preparing raw sales logs in Python, what checks do you run to catch duplicate records or inconsistent timestamps?",
                        "Data Quality Checks",
                        ["deduplication", "timezone normalization", "null checks", "schema validation"],
                    ),
                    _fs(
                        "KPI & Funnel Analysis",
                        "Mid-Level",
                        "scenario",
                        "If a product funnel shows a sharp drop between signup and first purchase, how would you segment the data to investigate?",
                        "Funnel Diagnostics",
                        ["cohort segmentation", "channel/device breakdown", "conversion rate", "drop-off attribution"],
                    ),
                ]),
            },
        ],
    },
    {
        "name": "Java",
        "description": "Core Java, OOP, JVM internals, collections, and concurrency.",
        "sub_skills": [
            {
                "name": "Java Core",
                "description": "OOP, interfaces, JVM garbage collection, collections, and multithreading.",
                "topics": ["OOP & Interfaces", "JVM & Garbage Collection", "Multithreading & Concurrency", "Collections Framework"],
                "difficulty_levels": ["Junior", "Mid-Level", "Senior"],
                "system_prompt": "You are VANI, a senior Java technical interviewer.",
                "few_shot_prompt": _build_prompt([
                    _fs(
                        "OOP & Interfaces",
                        "Junior",
                        "conceptual",
                        "In Java, when would you choose an interface over an abstract class when designing a shared contract?",
                        "Interfaces vs Abstract Classes",
                        ["multiple inheritance", "shared state vs contract", "default methods", "polymorphism"],
                    ),
                    _fs(
                        "JVM & Garbage Collection",
                        "Mid-Level",
                        "conceptual",
                        "How does Java garbage collection determine which objects in heap memory are eligible to be reclaimed?",
                        "Reachability & GC",
                        ["GC roots", "reachability", "generational heap", "mark and sweep"],
                    ),
                ]),
            }
        ],
    },
    {
        "name": "JavaScript",
        "description": "Modern ECMAScript, Event Loop, closures, promises, and async/await.",
        "sub_skills": [
            {
                "name": "JavaScript Core",
                "description": "Event loop, closures, async/await, and prototypes.",
                "topics": ["Event Loop & Microtasks", "Closures & Scope", "Promises & Async/Await", "Prototypes & Inheritance"],
                "difficulty_levels": ["Junior", "Mid-Level", "Senior"],
                "system_prompt": "You are VANI, a senior JavaScript interviewer.",
                "few_shot_prompt": _build_prompt([
                    _fs(
                        "Event Loop & Microtasks",
                        "Mid-Level",
                        "conceptual",
                        "Why do Promise callbacks execute before scheduled timer callbacks in the JavaScript event loop?",
                        "Microtask vs Macrotask Queue",
                        ["call stack", "microtask queue", "macrotask queue", "event loop priority"],
                    ),
                    _fs(
                        "Closures & Scope",
                        "Junior",
                        "conceptual",
                        "What is a closure in JavaScript, and how can it help encapsulate private state?",
                        "Lexical Scoping",
                        ["lexical scope", "outer function variables", "state encapsulation", "memory retention"],
                    ),
                ]),
            }
        ],
    },
    {
        "name": "React",
        "description": "React component lifecycle, Hooks, Virtual DOM, and performance optimization.",
        "sub_skills": [
            {
                "name": "React Core",
                "description": "Hooks, reconciliation, state management, and memoization.",
                "topics": ["Hooks & Lifecycle", "Virtual DOM & Reconciliation", "State Management & Context", "Performance Optimization"],
                "difficulty_levels": ["Junior", "Mid-Level", "Senior"],
                "system_prompt": "You are VANI, a senior React frontend interviewer.",
                "few_shot_prompt": _build_prompt([
                    _fs(
                        "Hooks & Lifecycle",
                        "Junior",
                        "conceptual",
                        "Why is it important to pass an accurate dependency array to React's useEffect hook?",
                        "Effect Dependencies",
                        ["stale closures", "effect re-execution", "infinite loops", "cleanup"],
                    ),
                    _fs(
                        "Virtual DOM & Reconciliation",
                        "Mid-Level",
                        "conceptual",
                        "Why does React require stable, unique key props when rendering dynamic lists?",
                        "List Reconciliation",
                        ["diffing algorithm", "component identity", "state preservation", "index key pitfalls"],
                    ),
                ]),
            }
        ],
    },
    {
        "name": "SQL",
        "description": "Relational queries, indexing, execution plans, ACID transactions, and normalization.",
        "sub_skills": [
            {
                "name": "SQL Core",
                "description": "Joins, indexing, ACID transactions, and schema design.",
                "topics": ["Joins & Subqueries", "Indexing & Execution Plans", "ACID & Transactions", "Schema Design & Normalization"],
                "difficulty_levels": ["Junior", "Mid-Level", "Senior"],
                "system_prompt": "You are VANI, a senior database engineer interviewer.",
                "few_shot_prompt": _build_prompt([
                    _fs(
                        "Joins & Subqueries",
                        "Junior",
                        "conceptual",
                        "What is the practical difference between an INNER JOIN and a LEFT JOIN when querying related tables?",
                        "Join Semantics",
                        ["matched rows", "unmatched left rows", "NULL padding", "result cardinality"],
                    ),
                    _fs(
                        "Indexing & Execution Plans",
                        "Mid-Level",
                        "conceptual",
                        "How do database indexes speed up read queries, and what trade-off do they introduce for write operations?",
                        "Index Trade-offs",
                        ["B-tree lookup", "avoiding full table scan", "write amplification", "storage overhead"],
                    ),
                ]),
            }
        ],
    },
    {
        "name": "Docker",
        "description": "Containerization principles, Dockerfile optimization, networking, and volumes.",
        "sub_skills": [
            {
                "name": "Docker Core",
                "description": "Containers, multi-stage builds, networking, and volumes.",
                "topics": ["Container Architecture", "Dockerfile Optimization", "Docker Networking", "Storage & Volumes"],
                "difficulty_levels": ["Junior", "Mid-Level", "Senior"],
                "system_prompt": "You are VANI, a senior DevOps interviewer.",
                "few_shot_prompt": _build_prompt([
                    _fs(
                        "Container Architecture",
                        "Junior",
                        "conceptual",
                        "What is the main architectural difference between a Docker container and a traditional virtual machine?",
                        "OS-Level Virtualization",
                        ["shared host kernel", "namespaces and cgroups", "lightweight footprint", "hypervisor comparison"],
                    ),
                    _fs(
                        "Dockerfile Optimization",
                        "Mid-Level",
                        "conceptual",
                        "How do multi-stage Docker builds help reduce the size and attack surface of production images?",
                        "Multi-Stage Builds",
                        ["build vs runtime stages", "artifact copying", "excluding compilers", "layer caching"],
                    ),
                ]),
            }
        ],
    },
]


def _serialize_sub_skill(sub: SubSkill, mother_name: str) -> Dict[str, Any]:
    return {
        "id": sub.id,
        "mother_skill_id": sub.mother_skill_id,
        "mother_skill": mother_name,
        "skill_name": mother_name,
        "sub_skill": sub.name,
        "description": sub.description,
        "topics": json.loads(sub.topics_json or "[]"),
        "difficulty_levels": json.loads(sub.difficulty_levels_json or '["Beginner"]'),
        "system_prompt": sub.system_prompt,
        "few_shot_prompt": sub.few_shot_prompt,
        "is_active": sub.is_active,
    }


def ensure_skill_prompts_seeded(db: Optional[Session] = None) -> int:
    """Creates mother_skills and sub_skills tables if needed and seeds default hierarchy idempotently."""
    Base.metadata.create_all(bind=engine)
    own_session = db is None
    sess = db or SessionLocal()
    inserted_sub_skills = 0
    try:
        existing_mothers = {
            m.name.lower(): m for m in sess.query(MotherSkill).all()
        }
        for m_item in DEFAULT_MOTHER_SKILLS:
            mother = existing_mothers.get(m_item["name"].lower())
            if not mother:
                mother = MotherSkill(
                    name=m_item["name"],
                    description=m_item["description"],
                    is_active=True,
                )
                sess.add(mother)
                sess.flush()
                existing_mothers[m_item["name"].lower()] = mother

            existing_subs = {
                s.name.lower()
                for s in sess.query(SubSkill).filter(SubSkill.mother_skill_id == mother.id).all()
            }
            for s_item in m_item["sub_skills"]:
                if s_item["name"].lower() not in existing_subs:
                    sess.add(
                        SubSkill(
                            mother_skill_id=mother.id,
                            name=s_item["name"],
                            description=s_item["description"],
                            topics_json=json.dumps(s_item["topics"]),
                            difficulty_levels_json=json.dumps(s_item["difficulty_levels"]),
                            system_prompt=s_item["system_prompt"],
                            few_shot_prompt=s_item["few_shot_prompt"],
                            is_active=True,
                        )
                    )
                    inserted_sub_skills += 1
        if inserted_sub_skills:
            sess.commit()
        return inserted_sub_skills
    finally:
        if own_session:
            sess.close()


def list_skills_from_db(db: Optional[Session] = None, query: Optional[str] = None) -> List[Dict[str, Any]]:
    """Lists active mother skills and nested sub-skills from DB, optionally filtered by a search query."""
    ensure_skill_prompts_seeded(db)
    q_clean = query.strip().lower() if query and query.strip() else None
    own_session = db is None
    sess = db or SessionLocal()
    try:
        mothers = (
            sess.query(MotherSkill)
            .filter(MotherSkill.is_active.is_(True))
            .order_by(MotherSkill.name.asc())
            .all()
        )
        results: List[Dict[str, Any]] = []
        for m in mothers:
            active_subs = sorted([s for s in m.sub_skills if s.is_active], key=lambda s: s.id)
            if q_clean:
                mother_matches = q_clean in m.name.lower() or q_clean in (m.description or "").lower()
                matching_subs = [
                    s for s in active_subs
                    if (
                        q_clean in s.name.lower()
                        or q_clean in (s.description or "").lower()
                        or q_clean in (s.topics_json or "").lower()
                    )
                ]
                if not mother_matches and not matching_subs:
                    continue
                chosen_subs = active_subs if mother_matches and not matching_subs else matching_subs
            else:
                chosen_subs = active_subs

            all_topics: List[str] = []
            for s in chosen_subs:
                for t in json.loads(s.topics_json or "[]"):
                    if t not in all_topics:
                        all_topics.append(t)
            results.append({
                "id": m.id,
                "skill_name": m.name,
                "description": m.description,
                "sub_skills": [_serialize_sub_skill(s, m.name) for s in chosen_subs],
                "topics": all_topics,
            })
        return results
    finally:
        if own_session:
            sess.close()


def get_skill_prompt_from_db(
    skill_name: str,
    sub_skill_name: Optional[str] = None,
    sub_skill_index: int = 0,
    db: Optional[Session] = None,
) -> Optional[Dict[str, Any]]:
    """Fetches a sub-skill prompt record from DB by mother skill (+ optional sub-skill) or direct sub-skill name."""
    if not skill_name or not skill_name.strip():
        return None
    ensure_skill_prompts_seeded(db)
    target = skill_name.strip().lower()
    sub_target = sub_skill_name.strip().lower() if sub_skill_name and sub_skill_name.strip() else None

    own_session = db is None
    sess = db or SessionLocal()
    try:
        mothers = sess.query(MotherSkill).filter(MotherSkill.is_active.is_(True)).all()
        # 1. Match mother skill first
        for m in mothers:
            if m.name.lower() == target:
                active_subs = sorted([s for s in m.sub_skills if s.is_active], key=lambda x: x.name)
                if not active_subs:
                    return None
                if sub_target:
                    matched_sub = next((s for s in active_subs if s.name.lower() == sub_target), None)
                    return _serialize_sub_skill(matched_sub, m.name) if matched_sub else None
                chosen = active_subs[sub_skill_index % len(active_subs)]
                return _serialize_sub_skill(chosen, m.name)

        # 2. Fallback: match directly by sub_skill name (e.g. "Machine Learning", "Data Science")
        for m in mothers:
            for s in m.sub_skills:
                if s.is_active and s.name.lower() == target:
                    return _serialize_sub_skill(s, m.name)
        return None
    finally:
        if own_session:
            sess.close()


def upsert_skill_prompt(
    skill_name: str,
    description: str,
    topics: List[str],
    difficulty_levels: List[str],
    system_prompt: str,
    few_shot_prompt: str,
    sub_skill_name: Optional[str] = None,
    mother_description: Optional[str] = None,
    is_active: bool = True,
    db: Optional[Session] = None,
) -> Dict[str, Any]:
    """Inserts or updates a MotherSkill and its SubSkill prompt record in the database."""
    Base.metadata.create_all(bind=engine)
    m_name = skill_name.strip()
    s_name = (sub_skill_name or f"{m_name} Core").strip()
    own_session = db is None
    sess = db or SessionLocal()
    try:
        mother = sess.query(MotherSkill).filter(MotherSkill.name.ilike(m_name)).first()
        if not mother:
            mother = MotherSkill(
                name=m_name,
                description=mother_description or description,
                is_active=True,
            )
            sess.add(mother)
            sess.flush()

        sub = (
            sess.query(SubSkill)
            .filter(SubSkill.mother_skill_id == mother.id, SubSkill.name.ilike(s_name))
            .first()
        )
        if sub:
            sub.description = description
            sub.topics_json = json.dumps(topics)
            sub.difficulty_levels_json = json.dumps(difficulty_levels)
            sub.system_prompt = system_prompt
            sub.few_shot_prompt = few_shot_prompt
            sub.is_active = is_active
            sess.commit()
            sess.refresh(sub)
            return _serialize_sub_skill(sub, mother.name)

        sub = SubSkill(
            mother_skill_id=mother.id,
            name=s_name,
            description=description,
            topics_json=json.dumps(topics),
            difficulty_levels_json=json.dumps(difficulty_levels),
            system_prompt=system_prompt,
            few_shot_prompt=few_shot_prompt,
            is_active=is_active,
        )
        sess.add(sub)
        sess.commit()
        sess.refresh(sub)
        return _serialize_sub_skill(sub, mother.name)
    finally:
        if own_session:
            sess.close()
