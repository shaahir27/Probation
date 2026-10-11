"""Offline and cached body pool with deterministic slot substitution.

Authority: docs/PROMPTS.md section 9, docs/EVALUATION_PLAN.md section 2.4.
Enforces zero LLM cost during unit tests and deterministic replay generation.
"""

import random
from dataclasses import dataclass

from probation.synth.personas import Contact, Persona


@dataclass(frozen=True)
class MailTemplate:
    """Template for synthetic email subject and body."""

    id: str
    sender_role: str
    intent: str
    subject_tmpl: str
    body_tmpl: str
    has_deadline: bool = False
    money_involved: bool = False
    urgency: str = "normal"  # 'low', 'normal', 'high'


@dataclass(frozen=True)
class InviteTemplate:
    """Template for synthetic calendar invites."""

    id: str
    purpose: str
    title_tmpl: str
    desc_tmpl: str


# Rich offline template catalog (50+ combinations across student roles and intents)
_MAIL_TEMPLATES: list[MailTemplate] = [
    # Professor Requests (with deadlines -> trigger candidate chains)
    MailTemplate(
        id="PROF_REQ_01",
        sender_role="professor",
        intent="request",
        subject_tmpl="[Action Required] Assignment 3 Submission for {{COURSE}}",
        body_tmpl=(
            "Dear students,\n\nPlease submit your solutions for Assignment 3 by {{DEADLINE}}. "
            "Late submissions will receive a penalty. Refer to the portal for details.\n\n"
            "Regards,\n{{PROFESSOR_NAME}}"
        ),
        has_deadline=True,
        urgency="high",
    ),
    MailTemplate(
        id="PROF_REQ_02",
        sender_role="professor",
        intent="request",
        subject_tmpl="Project Milestone 2 Review: {{COURSE}}",
        body_tmpl=(
            "Hello,\n\nPlease confirm your group's presentation slot for Project Milestone 2 before {{DEADLINE}}. "
            "Ensure your slide deck and repo link are updated.\n\n"
            "Best,\n{{PROFESSOR_NAME}}"
        ),
        has_deadline=True,
        urgency="normal",
    ),
    MailTemplate(
        id="PROF_REQ_03",
        sender_role="professor",
        intent="request",
        subject_tmpl="Lab Viva Schedule and Report Submission",
        body_tmpl=(
            "Dear all,\n\nThe lab reports for {{COURSE}} must be submitted to the TAs by {{DEADLINE}}. "
            "Please bring a printed copy to the lab session.\n\n"
            "Prof. {{PROFESSOR_NAME}}"
        ),
        has_deadline=True,
        urgency="normal",
    ),
    # Professor Notifications
    MailTemplate(
        id="PROF_NOTIF_01",
        sender_role="professor",
        intent="notification",
        subject_tmpl="Extra Class Rescheduled for {{COURSE}}",
        body_tmpl=(
            "Dear students,\n\nOur lecture on {{DATE}} has been rescheduled to Friday at 4 PM in Hall 102. "
            "Please review the uploaded slides beforehand.\n\n"
            "{{PROFESSOR_NAME}}"
        ),
        has_deadline=False,
    ),
    MailTemplate(
        id="PROF_NOTIF_02",
        sender_role="professor",
        intent="notification",
        subject_tmpl="Recommended Reading Material: {{COURSE}}",
        body_tmpl=(
            "Hello class,\n\nI have uploaded supplementary reference papers on the course portal for your mid-semester preparation.\n\n"
            "Best,\n{{PROFESSOR_NAME}}"
        ),
        has_deadline=False,
    ),
    # Friend Chats & Collaboration
    MailTemplate(
        id="FRIEND_CHAT_01",
        sender_role="friend",
        intent="chat",
        subject_tmpl="Study session this weekend for {{COURSE}}?",
        body_tmpl=(
            "Hey {{FIRST_NAME}},\n\nAre you free this Saturday afternoon? A few of us are gathering in the library to go through past exam papers for {{COURSE}}.\n\n"
            "Let me know if you want to join!\n\n{{FRIEND_NAME}}"
        ),
    ),
    MailTemplate(
        id="FRIEND_CHAT_02",
        sender_role="friend",
        intent="chat",
        subject_tmpl="Hackathon team registration",
        body_tmpl=(
            "Hi {{FIRST_NAME}},\n\nDid you see the hackathon announcement? We need one more member for the systems track. Are you interested?\n\n"
            "Cheers,\n{{FRIEND_NAME}}"
        ),
    ),
    MailTemplate(
        id="FRIEND_CHAT_03",
        sender_role="friend",
        intent="chat",
        subject_tmpl="Notes from today's lecture",
        body_tmpl=(
            "Hey, I missed the morning lecture for {{COURSE}}. Could you share your notes when you get a chance?\n\n"
            "Thanks a lot,\n{{FRIEND_NAME}}"
        ),
    ),
    # Recruiter Opportunities
    MailTemplate(
        id="REC_OPP_01",
        sender_role="recruiter",
        intent="opportunity",
        subject_tmpl="Campus Internship Opportunity 2026 - {{COMPANY}}",
        body_tmpl=(
            "Dear {{NAME}},\n\nWe are pleased to invite eligible students from {{COLLEGE}} to apply for our Summer Software Engineering Internship program. "
            "The application deadline is {{DEADLINE}}.\n\n"
            "University Recruiting Team,\n{{COMPANY}}"
        ),
        has_deadline=True,
    ),
    MailTemplate(
        id="REC_OPP_02",
        sender_role="recruiter",
        intent="opportunity",
        subject_tmpl="Invitation to Annual National Hackathon - {{COMPANY}}",
        body_tmpl=(
            "Greetings from {{COMPANY}}!\n\nWe are hosting an AI & Distributed Systems challenge for college students. "
            "Grand prizes and pre-placement interviews await the top teams.\n\n"
            "Best regards,\nCampus Talent Acquisition"
        ),
        has_deadline=True,
    ),
    # Club Announcements & Invitations
    MailTemplate(
        id="CLUB_NOTIF_01",
        sender_role="club",
        intent="notification",
        subject_tmpl="Workshop on Open Source & Cloud Computing",
        body_tmpl=(
            "Hello students,\n\nThe {{CLUB_NAME}} is organizing a hands-on workshop this Wednesday at 5:30 PM. "
            "Bring your laptops with Git and Docker installed.\n\n"
            "See you there,\nCore Team, {{CLUB_NAME}}"
        ),
    ),
    MailTemplate(
        id="CLUB_NOTIF_02",
        sender_role="club",
        intent="notification",
        subject_tmpl="Weekly Coding Contest #14 Announcement",
        body_tmpl=(
            "Greetings coders,\n\nOur weekly algorithms contest will take place this Sunday at 8 PM on the college portal.\n\n"
            "{{CLUB_NAME}}"
        ),
    ),
    # Service Notifications & Receipts
    MailTemplate(
        id="SERV_NOTIF_01",
        sender_role="service",
        intent="notification",
        subject_tmpl="Academic Portal Notice: Semester Registration",
        body_tmpl=(
            "This is an automated notification from {{COLLEGE}} Academic Affairs. "
            "Course registration portal will be open from {{DATE}} to {{DEADLINE}}.\n\n"
            "Do not reply to this email."
        ),
        has_deadline=True,
    ),
    MailTemplate(
        id="SERV_RCPT_01",
        sender_role="service",
        intent="receipt",
        subject_tmpl="Payment Receipt: Hostel & Mess Fee - Transaction #{{TXN_ID}}",
        body_tmpl=(
            "Dear Student,\n\nWe have received your payment of INR {{AMOUNT}} towards Hostel & Mess charges. "
            "Transaction reference: {{TXN_ID}}. A copy has been filed with the accounts office.\n\n"
            "Accounts Department, {{COLLEGE}}"
        ),
        money_involved=True,
    ),
    MailTemplate(
        id="SERV_NEWS_01",
        sender_role="service",
        intent="newsletter",
        subject_tmpl="Tech Pulse Weekly: Advances in Efficient AI & Robotics",
        body_tmpl=(
            "Welcome to this week's issue of Tech Pulse.\n\nHighlights:\n- Next-generation edge models\n"
            "- Systems research developments\n- Upcoming open conferences\n\n"
            "To unsubscribe from this newsletter, click here."
        ),
    ),
    MailTemplate(
        id="SERV_SALES_01",
        sender_role="service",
        intent="sales",
        subject_tmpl="Special Student Discount: 50% Off Cloud Developer Subscriptions",
        body_tmpl=(
            "Upgrade your coding workflow with 50% off professional cloud credits using your {{COLLEGE}} student email ID.\n\n"
            "Limited period promotion. Terms apply."
        ),
    ),
]

_INVITE_TEMPLATES: list[InviteTemplate] = [
    InviteTemplate(
        id="INV_01",
        purpose="office_hours",
        title_tmpl="Office Hours: {{COURSE}} - Prof. {{PROFESSOR_NAME}}",
        desc_tmpl="Weekly office hours for questions regarding lecture concepts and assignments. Room 204 or via Google Meet.",
    ),
    InviteTemplate(
        id="INV_02",
        purpose="lab_session",
        title_tmpl="{{COURSE}} Practical Lab Session",
        desc_tmpl="Scheduled lab hours. Submission of lab report required by end of session.",
    ),
    InviteTemplate(
        id="INV_03",
        purpose="group_study",
        title_tmpl="Study Group: {{COURSE}} Exam Prep",
        desc_tmpl="Group revision and problem solving in Central Library Room B.",
    ),
    InviteTemplate(
        id="INV_04",
        purpose="club_meeting",
        title_tmpl="{{CLUB_NAME}} General Body Meeting",
        desc_tmpl="Discussion on upcoming college symposium and hackathon logistics.",
    ),
    InviteTemplate(
        id="INV_05",
        purpose="webinar",
        title_tmpl="Tech Talk: Industry Career Insights with {{COMPANY}}",
        desc_tmpl="Interactive session with engineering leads. Q&A on internships and campus placements.",
    ),
]

_REPLY_SENTENCES: list[str] = [
    "Thank you for the update. I have noted the details.",
    "Thanks for letting me know. I will submit the work on time.",
    "Got it, professor. I will review the guidelines and submit accordingly.",
    "Sounds good! Count me in for the study session.",
    "Thank you for the invitation. I will attend the session.",
    "Thanks, I have downloaded the materials and will go through them.",
    "I appreciate the information. Let me check my schedule and get back to you.",
    "Noted with thanks. See you in class tomorrow.",
    "Thanks for reaching out. Looking forward to the discussion.",
    "Understood. I will prepare the required slide deck before our meeting.",
]


class BodyPool:
    """Manages cached deterministic synthetic content templates."""

    def __init__(self, templates: list[MailTemplate] | None = None) -> None:
        self.mail_templates = templates or _MAIL_TEMPLATES
        self.invite_templates = _INVITE_TEMPLATES

    def get_mail_template(self, sender_role: str, intent: str, rng: random.Random) -> MailTemplate:
        """Find matching template or closest fallback."""
        matches = [
            t for t in self.mail_templates if t.sender_role == sender_role and t.intent == intent
        ]
        if not matches:
            matches = [t for t in self.mail_templates if t.sender_role == sender_role]
        if not matches:
            matches = self.mail_templates
        return rng.choice(matches)

    def get_invite_template(self, purpose: str, rng: random.Random) -> InviteTemplate:
        """Find matching invite template or random fallback."""
        matches = [t for t in self.invite_templates if t.purpose == purpose]
        if not matches:
            matches = self.invite_templates
        return rng.choice(matches)

    def render_mail(
        self,
        template: MailTemplate,
        persona: Persona,
        contact: Contact,
        date_str: str,
        deadline_str: str,
        rng: random.Random,
    ) -> tuple[str, str]:
        """Perform slot substitution to generate subject and body."""
        first_name = persona.name.split()[0]
        prof_name = contact.name.replace("Prof. ", "") if contact.role == "professor" else "Staff"
        course = contact.course or (persona.courses[0] if persona.courses else "CS301")
        company = contact.company_or_dept or "TechCorp"
        club = contact.company_or_dept or "Campus Coding Club"
        amount = str(rng.randint(2500, 15000))
        txn_id = f"TXN{rng.randint(100000, 999999)}"

        subs = {
            "{{NAME}}": persona.name,
            "{{FIRST_NAME}}": first_name,
            "{{PROFESSOR_NAME}}": prof_name,
            "{{FRIEND_NAME}}": contact.name.split()[0],
            "{{COURSE}}": course,
            "{{COMPANY}}": company,
            "{{CLUB_NAME}}": club,
            "{{COLLEGE}}": persona.college,
            "{{DATE}}": date_str,
            "{{DEADLINE}}": deadline_str,
            "{{AMOUNT}}": amount,
            "{{TXN_ID}}": txn_id,
        }

        subj = template.subject_tmpl
        body = template.body_tmpl
        for k, v in subs.items():
            subj = subj.replace(k, v)
            body = body.replace(k, v)

        return subj, body

    def render_invite(
        self,
        template: InviteTemplate,
        persona: Persona,
        contact: Contact,
        rng: random.Random,
    ) -> tuple[str, str]:
        """Render calendar invite title and description."""
        prof_name = contact.name.replace("Prof. ", "")
        course = contact.course or (persona.courses[0] if persona.courses else "CS301")
        company = contact.company_or_dept or "TechCorp"
        club = contact.company_or_dept or "Campus Coding Club"

        subs = {
            "{{NAME}}": persona.name,
            "{{PROFESSOR_NAME}}": prof_name,
            "{{COURSE}}": course,
            "{{COMPANY}}": company,
            "{{CLUB_NAME}}": club,
        }

        title = template.title_tmpl
        desc = template.desc_tmpl
        for k, v in subs.items():
            title = title.replace(k, v)
            desc = desc.replace(k, v)

        return title, desc

    def render_user_reply(
        self,
        persona: Persona,
        original_subject: str,
        recipient_contact: Contact,
        rng: random.Random,
    ) -> tuple[str, str]:
        """Generate persona reply email (no LLM, purely code templates)."""
        greeting = rng.choice(persona.writing_style.greetings)
        if recipient_contact.role == "professor":
            greeting = (
                "Dear Professor," if persona.writing_style.formality > 0.7 else "Hello Professor,"
            )
        elif recipient_contact.role == "friend":
            greeting = f"Hi {recipient_contact.name.split()[0]},"

        sentence = rng.choice(_REPLY_SENTENCES)
        signoff = rng.choice(persona.writing_style.signoffs)

        subject = original_subject
        if not (subject.startswith("Re: ") or subject.startswith("RE: ")):
            subject = f"Re: {subject}"

        body = f"{greeting}\n\n{sentence}\n\n{signoff}"
        return subject, body
