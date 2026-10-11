"""Persona models and library for synthetic world generation.

Authority: docs/EVALUATION_PLAN.md section 2.1 and docs/PACKS_SPEC.md section 6.
Provides 20 realistic Indian student personas (15 development, 5 test).
"""

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class WritingStyle:
    """Writing style parameters for a persona."""

    greetings: list[str]
    signoffs: list[str]
    median_words: int
    formality: float  # In [0.0, 1.0]


@dataclass(frozen=True)
class Contact:
    """Contact entry for a persona."""

    name: str
    email: str
    role: str  # 'professor', 'friend', 'club', 'recruiter', 'service'
    company_or_dept: str = ""
    course: str = ""


@dataclass(frozen=True)
class Persona:
    """Complete profile of a simulated user persona."""

    id: int
    name: str
    email: str
    role: str
    college: str
    department: str
    is_test_persona: bool  # True for personas 15..19
    writing_style: WritingStyle
    contacts: list[Contact]
    origin_sites: list[str]
    courses: list[str]
    folders: list[str] = field(
        default_factory=lambda: [
            "College/Coursework",
            "College/Lab",
            "Projects/Code",
            "Internship/Applications",
            "Personal/Finance",
            "Archive",
        ]
    )

    def get_contacts_by_role(self, role: str) -> list[Contact]:
        """Filter contacts by role."""
        return [c for c in self.contacts if c.role == role]

    def to_dict(self) -> dict[str, Any]:
        """Convert persona to dictionary representation."""
        return {
            "id": self.id,
            "name": self.name,
            "email": self.email,
            "role": self.role,
            "college": self.college,
            "department": self.department,
            "is_test_persona": self.is_test_persona,
            "writing_style": {
                "greetings": self.writing_style.greetings,
                "signoffs": self.writing_style.signoffs,
                "median_words": self.writing_style.median_words,
                "formality": self.writing_style.formality,
            },
            "contacts": [
                {
                    "name": c.name,
                    "email": c.email,
                    "role": c.role,
                    "company_or_dept": c.company_or_dept,
                    "course": c.course,
                }
                for c in self.contacts
            ],
            "origin_sites": self.origin_sites,
            "courses": self.courses,
            "folders": self.folders,
        }


# 20 hand-crafted rich profiles matching Indian student context (15 dev, 5 test)
_STUDENT_NAMES = [
    # 15 Development Personas (0..14)
    ("Meena Krishnamurthy", "meena.k", "Computer Science", "National Institute of Technology"),
    ("Aarav Sharma", "aarav.s", "Electrical Engineering", "Indian Institute of Technology"),
    ("Priya Venkatesh", "priya.v", "Data Science", "Birla Institute of Technology and Science"),
    ("Rohan Deshmukh", "rohan.d", "Mechanical Engineering", "College of Engineering Pune"),
    ("Ananya Sen", "ananya.s", "Information Technology", "Jadavpur University"),
    ("Vikram Malhotra", "vikram.m", "Computer Science", "Delhi Technological University"),
    ("Sneha Nair", "sneha.n", "Biotechnology", "Vellore Institute of Technology"),
    ("Aditya Verma", "aditya.v", "Electronics", "National Institute of Technology"),
    ("Kavya Reddy", "kavya.r", "Computer Science", "IIIT Hyderabad"),
    ("Arjun Patel", "arjun.p", "Civil Engineering", "IIT Bombay"),
    ("Divya Iyer", "divya.i", "Mathematics & Computing", "IIT Madras"),
    ("Manish Gupta", "manish.g", "Computer Science", "NIT Surathkal"),
    ("Neha Joshi", "neha.j", "Chemical Engineering", "IIT Roorkee"),
    ("Siddharth Nair", "sid.nair", "Artificial Intelligence", "IIT Hyderabad"),
    ("Pooja Choudhury", "pooja.c", "Information Science", "RV College of Engineering"),
    # 5 Test Personas (15..19 - strictly held out for final reporting)
    ("Tanvi Bhatt", "tanvi.b", "Computer Science", "IIIT Bangalore"),
    ("Karan Singhania", "karan.s", "Data Engineering", "IIT Kharagpur"),
    ("Isha Mukherjee", "isha.m", "Electrical Engineering", "IIT Kanpur"),
    ("Naveen Sundaram", "naveen.s", "Aerospace Engineering", "IIT Madras"),
    ("Bhavna Saxena", "bhavna.s", "Computer Science", "NIT Trichy"),
]


def _build_persona(pid: int) -> Persona:
    name, uname, dept, college = _STUDENT_NAMES[pid % len(_STUDENT_NAMES)]
    is_test = pid >= 15
    domain = college.lower().replace(" ", "").replace("&", "")[:8] + ".ac.in"
    user_email = f"{uname}@{domain}"

    # Style varies with persona id
    formality = 0.5 + ((pid * 3) % 45) / 100.0  # In [0.50, 0.94]
    median_words = 18 + (pid * 5) % 25

    if formality > 0.75:
        greetings = ["Dear Professor", "Good morning", "Respected Sir/Madam", "Hello Professor"]
        signoffs = [
            f"Best regards,\n{name}",
            f"Sincerely,\n{name}",
            f"Thank you,\n{name}",
        ]
    else:
        greetings = ["Hi", "Hey", "Hello", "Hi everyone"]
        signoffs = [
            f"Thanks,\n{name.split()[0]}",
            f"Cheers,\n{name.split()[0]}",
            f"Best,\n{name}",
        ]

    style = WritingStyle(
        greetings=greetings,
        signoffs=signoffs,
        median_words=median_words,
        formality=round(formality, 2),
    )

    courses = [
        f"{dept[:2].upper()}301 Advanced {dept}",
        f"{dept[:2].upper()}302 Systems & Algorithms",
        "MA201 Linear Algebra & Probability",
        "HS101 Professional Ethics",
    ]

    contacts: list[Contact] = [
        # Professors
        Contact(
            name="Prof. R. Ramanathan",
            email=f"r.ramanathan@{domain}",
            role="professor",
            company_or_dept=dept,
            course=courses[0],
        ),
        Contact(
            name="Prof. Anita Swaminathan",
            email=f"a.swaminathan@{domain}",
            role="professor",
            company_or_dept=dept,
            course=courses[1],
        ),
        Contact(
            name="Prof. S. Chakrabarti",
            email=f"s.chakrabarti@{domain}",
            role="professor",
            company_or_dept="Mathematics",
            course=courses[2],
        ),
        # Friends & Peers
        Contact(
            name="Rahul Krishna",
            email=f"rahul.k@{domain}",
            role="friend",
            company_or_dept=dept,
        ),
        Contact(
            name="Akanksha Roy",
            email="akanksha.roy2026@gmail.com",
            role="friend",
            company_or_dept="Study Group",
        ),
        Contact(
            name="Samir Jain",
            email="samir.jain.tech@outlook.com",
            role="friend",
            company_or_dept="Project Partner",
        ),
        # Student Clubs
        Contact(
            name="Campus Coding Club",
            email=f"codingclub@{domain}",
            role="club",
            company_or_dept="Student Activities",
        ),
        Contact(
            name="Hackathon & Innovation Cell",
            email=f"hackathons@{domain}",
            role="club",
            company_or_dept="Placement Cell",
        ),
        # Recruiters & Internship Orgs
        Contact(
            name="Acme Tech Campus Hiring",
            email="campus-recruitment@acmetech.example.com",
            role="recruiter",
            company_or_dept="Acme Tech",
        ),
        Contact(
            name="Global AI Labs Internships",
            email="internships@ailabs.example.org",
            role="recruiter",
            company_or_dept="Global AI Labs",
        ),
        # Automated Systems & Services
        Contact(
            name="College Academic Portal",
            email=f"noreply-portal@{domain}",
            role="service",
            company_or_dept="Academic Office",
        ),
        Contact(
            name="Library Services",
            email=f"library-alerts@{domain}",
            role="service",
            company_or_dept="Central Library",
        ),
        Contact(
            name="Tech Digest Newsletter",
            email="newsletter@techdigest.example.com",
            role="service",
            company_or_dept="Subscriptions",
        ),
    ]

    origin_sites = [
        f"portal.{domain}",
        f"moodle.{domain}",
        "arxiv.org",
        "github.com",
        "drive.google.com",
        "overleaf.com",
        "kaggle.com",
    ]

    folders = [
        f"College/{courses[0].split()[0]}",
        f"College/{courses[1].split()[0]}",
        "College/Lab_Reports",
        "Projects/Code",
        "Internships/Resumes",
        "Personal/Bills",
        "Downloads/Misc",
    ]

    return Persona(
        id=pid,
        name=name,
        email=user_email,
        role="student",
        college=college,
        department=dept,
        is_test_persona=is_test,
        writing_style=style,
        contacts=contacts,
        origin_sites=origin_sites,
        courses=courses,
        folders=folders,
    )


_ALL_PERSONAS: dict[int, Persona] = {pid: _build_persona(pid) for pid in range(20)}


def get_persona(persona_id: int) -> Persona:
    """Retrieve persona by integer ID (0..19). Defaults to 0 (Meena)."""
    if persona_id not in _ALL_PERSONAS:
        return _build_persona(persona_id)
    return _ALL_PERSONAS[persona_id]


def get_default_persona() -> Persona:
    """Return default development persona 0 (Meena Krishnamurthy)."""
    return get_persona(0)


def list_personas() -> list[Persona]:
    """Return all 20 configured personas."""
    return list(_ALL_PERSONAS.values())
