"""Deterministic synthetic timeline event generator and ground truth engine.

Authority: docs/EVALUATION_PLAN.md section 2 and docs/PACKS_SPEC.md sections 0.5, 6.
Engine code must NEVER read truth.json (invariant enforced by static check T-SYNTH).
"""

import json
import random
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from probation.core.hashing import det_id
from probation.synth.body_pool import BodyPool
from probation.synth.habits_dsl import PersonaHabits, build_habits_for_persona, evaluate_habit
from probation.synth.personas import Persona, get_persona
from probation.synth.render import render_files, render_ics, render_mbox
from probation.synth.world import SimWorld

SIMULATION_START = datetime(2026, 1, 1, 8, 0, 0, tzinfo=UTC)
SIMULATION_DAYS = 180
CENSOR_WINDOW_DAYS = 14


class SyntheticGenerator:
    """Generates 180 days of timeline items and hidden ground truth."""

    def __init__(
        self,
        persona: Persona,
        seed: int = 7,
        size: str = "tiny",
    ) -> None:
        self.persona = persona
        self.seed = seed
        self.size = size
        self.rng = random.Random(seed)
        self.habits: PersonaHabits = build_habits_for_persona(persona, seed)
        self.body_pool = BodyPool()

    def generate(self, out_dir: str | Path) -> dict[str, Any]:
        """Generate entire synthetic world and ground truth answer key."""
        out_path = Path(out_dir)
        out_path.mkdir(parents=True, exist_ok=True)

        if self.size == "tiny":
            n_mails = 120
            n_invites = 30
            n_files = 50
        else:
            n_mails = 2000
            n_invites = 300
            n_files = 600

        all_messages: list[dict[str, Any]] = []
        all_events: list[dict[str, Any]] = []
        all_files: list[dict[str, Any]] = []
        truth_records: dict[str, dict[str, Any]] = {}

        # 1. Generate Email Activity
        professors = self.persona.get_contacts_by_role("professor")
        friends = self.persona.get_contacts_by_role("friend")
        clubs = self.persona.get_contacts_by_role("club")
        recruiters = self.persona.get_contacts_by_role("recruiter")
        services = self.persona.get_contacts_by_role("service")

        for i in range(n_mails):
            day_idx = int((i / n_mails) * (SIMULATION_DAYS - 1))
            day_offset = timedelta(
                days=day_idx,
                hours=self.rng.randint(8, 20),
                minutes=self.rng.randint(0, 59),
                seconds=self.rng.randint(0, 59),
            )
            event_dt = SIMULATION_START + day_offset
            occurred_at = event_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
            date_str = event_dt.strftime("%d %b %Y")
            deadline_dt = event_dt + timedelta(days=self.rng.randint(2, 7))
            deadline_str = deadline_dt.strftime("%d %b %Y, 11:59 PM")

            # Determine sender category
            p_cat = self.rng.random()
            if p_cat < 0.25 and professors:
                contact = self.rng.choice(professors)
                intent = "request" if self.rng.random() < 0.7 else "notification"
                is_automated = False
            elif p_cat < 0.45 and friends:
                contact = self.rng.choice(friends)
                intent = "chat"
                is_automated = False
            elif p_cat < 0.55 and recruiters:
                contact = self.rng.choice(recruiters)
                intent = "opportunity"
                is_automated = False
            elif p_cat < 0.65 and clubs:
                contact = self.rng.choice(clubs)
                intent = "notification"
                is_automated = False
            else:
                contact = self.rng.choice(services)
                is_automated = True
                p_sub = self.rng.random()
                if p_sub < 0.40:
                    intent = "newsletter"
                elif p_sub < 0.70:
                    intent = "notification"
                elif p_sub < 0.90:
                    intent = "receipt"
                else:
                    intent = "sales"

            tmpl = self.body_pool.get_mail_template(contact.role, intent, self.rng)
            subject, body = self.body_pool.render_mail(
                tmpl, self.persona, contact, date_str, deadline_str, self.rng
            )

            msg_ref = f"<msg-{self.persona.id}-{i:05d}@{contact.email.split('@')[-1]}>"
            thread_id = f"thread-{self.persona.id}-{i:05d}"

            # Evaluate ground truth habit
            situation_attrs = {
                "sender_role": contact.role,
                "intent": intent,
                "has_deadline": tmpl.has_deadline,
                "money_involved": tmpl.money_involved,
                "urgency": tmpl.urgency,
                "is_automated": is_automated,
            }

            eval_res = evaluate_habit(
                self.habits, "email_action", situation_attrs, day_idx, self.rng
            )

            is_censored = day_idx >= (SIMULATION_DAYS - CENSOR_WINDOW_DAYS)

            # Determine labels in world.db based on true action
            initial_labels = ["INBOX"]
            if eval_res.final_action == "TRASH":
                initial_labels = ["TRASH"]
            elif eval_res.final_action == "ARCHIVE":
                initial_labels = ["ARCHIVED"]

            msg_record = {
                "id": det_id("mail_msg", self.persona.email, msg_ref),
                "message_id": msg_ref,
                "thread_id": thread_id,
                "from_addr": f"{contact.name} <{contact.email}>",
                "to_addr": f"{self.persona.name} <{self.persona.email}>",
                "subject": subject,
                "body": body,
                "labels": initial_labels,
                "occurred_at": occurred_at,
                "in_reply_to": None,
                "is_automated": is_automated,
                "has_attachment": tmpl.has_deadline and self.rng.random() < 0.5,
            }
            all_messages.append(msg_record)

            sit_id = det_id("mail", msg_ref, occurred_at, "email_action", "")
            truth_records[sit_id] = {
                "situation_id": sit_id,
                "pack": "mail",
                "family": "email_action",
                "day_idx": day_idx,
                "occurred_at": occurred_at,
                "attributes": situation_attrs,
                "candidate_action": eval_res.candidate_action,
                "true_action": eval_res.final_action,
                "rule_id": eval_res.rule_id,
                "is_drifted": eval_res.is_drifted,
                "noise_applied": eval_res.noise_applied,
                "is_censored": is_censored,
            }

            # If true action is REPLY, generate matching sent message in world
            if eval_res.final_action == "REPLY" and not is_censored:
                reply_subj, reply_body = self.body_pool.render_user_reply(
                    self.persona, subject, contact, self.rng
                )
                reply_dt = event_dt + timedelta(
                    hours=self.rng.randint(1, 18), minutes=self.rng.randint(0, 59)
                )
                reply_ref = f"<reply-{self.persona.id}-{i:05d}@{self.persona.email.split('@')[-1]}>"
                all_messages.append(
                    {
                        "id": det_id("mail_msg", self.persona.email, reply_ref),
                        "message_id": reply_ref,
                        "thread_id": thread_id,
                        "from_addr": f"{self.persona.name} <{self.persona.email}>",
                        "to_addr": f"{contact.name} <{contact.email}>",
                        "subject": reply_subj,
                        "body": reply_body,
                        "labels": ["SENT"],
                        "occurred_at": reply_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
                        "in_reply_to": msg_ref,
                        "is_automated": False,
                        "has_attachment": False,
                    }
                )

                # Check chain rule: trigger BLOCK_TIME on deadline if professor
                if contact.role == "professor" and tmpl.has_deadline:
                    chain_eval = self.rng.random()
                    if chain_eval < 0.85:  # Chain follow probability
                        block_start = deadline_dt - timedelta(hours=2)
                        block_end = deadline_dt
                        block_uid = f"chain-block-{self.persona.id}-{i:05d}@probation.sim"
                        all_events.append(
                            {
                                "id": det_id("event", block_uid),
                                "uid": block_uid,
                                "title": f"Study Block: {subject}",
                                "description": f"Dedicated prep time for deadline: {subject}",
                                "start_time": block_start.strftime("%Y-%m-%dT%H:%M:%SZ"),
                                "end_time": block_end.strftime("%Y-%m-%dT%H:%M:%SZ"),
                                "organizer": self.persona.email,
                                "attendees": [self.persona.email],
                                "attendee_status": "ACCEPTED",
                                "status": "CONFIRMED",
                                "created_at": reply_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
                            }
                        )

        # 2. Generate Calendar Invites
        for j in range(n_invites):
            day_idx = int((j / n_invites) * (SIMULATION_DAYS - 1))
            start_hour = self.rng.choice([7, 8, 10, 14, 16, 18])  # 7 and 8 are 'early'
            day_offset = timedelta(days=day_idx, hours=start_hour)
            ev_dt = SIMULATION_START + day_offset
            occurred_at = ev_dt.strftime("%Y-%m-%dT%H:%M:%SZ")

            is_early = start_hour < 9
            is_weekend = ev_dt.weekday() >= 5
            hour_bucket = "early" if is_early else ("weekend" if is_weekend else "normal")

            if self.rng.random() < 0.6 and professors:
                organizer = self.rng.choice(professors)
                purpose = "office_hours" if self.rng.random() < 0.6 else "lab_session"
            elif self.rng.random() < 0.8 and clubs:
                organizer = self.rng.choice(clubs)
                purpose = "club_meeting"
            else:
                organizer = self.rng.choice(friends)
                purpose = "group_study"

            tmpl_inv = self.body_pool.get_invite_template(purpose, self.rng)
            title, desc = self.body_pool.render_invite(tmpl_inv, self.persona, organizer, self.rng)

            invite_attrs = {
                "start_hour_bucket": hour_bucket,
                "organizer_role": organizer.role,
                "purpose": purpose,
            }
            eval_res = evaluate_habit(self.habits, "invite_rsvp", invite_attrs, day_idx, self.rng)

            is_censored = day_idx >= (SIMULATION_DAYS - CENSOR_WINDOW_DAYS)
            ev_uid = f"inv-{self.persona.id}-{j:05d}@{organizer.email.split('@')[-1]}"

            my_status = "NEEDS_ACTION"
            if not is_censored:
                if eval_res.final_action == "ACCEPT":
                    my_status = "ACCEPTED"
                elif eval_res.final_action == "DECLINE":
                    my_status = "DECLINED"
                elif eval_res.final_action == "TENTATIVE":
                    my_status = "TENTATIVE"

            ev_record = {
                "id": det_id("event", ev_uid),
                "uid": ev_uid,
                "title": title,
                "description": desc,
                "start_time": occurred_at,
                "end_time": (ev_dt + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "organizer": organizer.email,
                "attendees": [self.persona.email, organizer.email],
                "attendee_status": my_status,
                "status": "CONFIRMED",
                "created_at": occurred_at,
            }
            all_events.append(ev_record)

            sit_id = det_id("calendar", ev_uid, occurred_at, "invite_rsvp", "")
            truth_records[sit_id] = {
                "situation_id": sit_id,
                "pack": "calendar",
                "family": "invite_rsvp",
                "day_idx": day_idx,
                "occurred_at": occurred_at,
                "attributes": invite_attrs,
                "candidate_action": eval_res.candidate_action,
                "true_action": eval_res.final_action,
                "rule_id": eval_res.rule_id,
                "is_drifted": eval_res.is_drifted,
                "noise_applied": eval_res.noise_applied,
                "is_censored": is_censored,
            }

        # 3. Generate Files
        for k in range(n_files):
            day_idx = int((k / n_files) * (SIMULATION_DAYS - 1))
            day_offset = timedelta(
                days=day_idx,
                hours=self.rng.randint(9, 21),
                minutes=self.rng.randint(0, 59),
            )
            file_dt = SIMULATION_START + day_offset
            occurred_at = file_dt.strftime("%Y-%m-%dT%H:%M:%SZ")

            origin_site = self.rng.choice(self.persona.origin_sites)
            ext = self.rng.choice(["pdf", "docx", "py", "zip"])
            course_code = self.persona.courses[0].split()[0]
            filename = f"{course_code}_Lab{k + 1:02d}_Report.{ext}"
            rel_path = f"Downloads/{filename}"

            file_attrs = {
                "origin_site": origin_site,
                "ext": ext,
                "filename": filename,
            }
            eval_res = evaluate_habit(
                self.habits, "file_destination", file_attrs, day_idx, self.rng
            )

            is_censored = day_idx >= (SIMULATION_DAYS - CENSOR_WINDOW_DAYS)

            file_record = {
                "id": det_id("file", rel_path, occurred_at),
                "rel_path": rel_path,
                "filename": filename,
                "ext": ext,
                "origin_url": f"https://{origin_site}/downloads/{filename}",
                "downloaded_at": occurred_at,
            }
            all_files.append(file_record)

            sit_id = det_id("files", rel_path, occurred_at, "file_destination", "")
            truth_records[sit_id] = {
                "situation_id": sit_id,
                "pack": "files",
                "family": "file_destination",
                "day_idx": day_idx,
                "occurred_at": occurred_at,
                "attributes": file_attrs,
                "candidate_action": eval_res.candidate_action,
                "true_action": eval_res.final_action,
                "rule_id": eval_res.rule_id,
                "is_drifted": eval_res.is_drifted,
                "noise_applied": eval_res.noise_applied,
                "is_censored": is_censored,
            }

        # 4. Render All Outputs
        # Sort chronologically
        all_messages.sort(key=lambda m: m["occurred_at"])
        all_events.sort(key=lambda e: e["start_time"])
        all_files.sort(key=lambda f: f["downloaded_at"])

        # Render mbox
        mbox_path = out_path / "mailbox.mbox"
        render_mbox(all_messages, mbox_path)

        # Render ics
        ics_path = out_path / "calendar.ics"
        render_ics(all_events, ics_path)

        # Render files tree and manifest
        manifest_meta = render_files(
            all_files, out_path, SIMULATION_START.strftime("%Y-%m-%dT%H:%M:%SZ")
        )

        # Render world.db
        world_db_path = out_path / "world.db"
        if world_db_path.exists():
            world_db_path.unlink()
        with SimWorld(world_db_path) as world:
            for msg in all_messages:
                world.add_message(
                    msg_id=msg["id"],
                    message_id=msg["message_id"],
                    thread_id=msg["thread_id"],
                    from_addr=msg["from_addr"],
                    to_addr=msg["to_addr"],
                    subject=msg["subject"],
                    body=msg["body"],
                    labels=msg["labels"],
                    received_at=msg["occurred_at"],
                    in_reply_to=msg.get("in_reply_to"),
                    has_attachment=msg.get("has_attachment", False),
                )
            for ev in all_events:
                world.add_event(
                    event_id=ev["id"],
                    uid=ev["uid"],
                    title=ev["title"],
                    description=ev["description"],
                    start_time=ev["start_time"],
                    end_time=ev["end_time"],
                    organizer=ev["organizer"],
                    attendees=ev["attendees"],
                    status=ev["status"],
                    my_status=ev["attendee_status"],
                )
            for fl in manifest_meta["files"]:
                world.add_file(
                    file_id=det_id("world_file", fl["rel_path"]),
                    path=fl["rel_path"],
                    filename=fl["filename"],
                    ext=fl["ext"],
                    size_bytes=fl["size_bytes"],
                    origin_url=fl.get("origin_url", ""),
                    downloaded_at=fl["mtime"],
                    sha256=fl["sha256"],
                )

        # Write truth.json (HIDDEN ground truth)
        truth_file = out_path / "truth.json"
        with open(truth_file, "w", encoding="utf-8") as f:
            json.dump(truth_records, f, indent=2, sort_keys=True)

        # Write persona metadata and habits spec
        with open(out_path / "persona.json", "w", encoding="utf-8") as f:
            json.dump(self.persona.to_dict(), f, indent=2)

        with open(out_path / "habits.json", "w", encoding="utf-8") as f:
            json.dump(self.habits.to_dict(), f, indent=2)

        summary = {
            "persona_id": self.persona.id,
            "seed": self.seed,
            "size": self.size,
            "situations_total": len(truth_records),
            "messages_total": len(all_messages),
            "events_total": len(all_events),
            "files_total": len(all_files),
            "out_dir": str(out_path),
        }
        return summary


def generate_synthetic_world(
    persona_id: int = 0,
    seed: int = 7,
    size: str = "tiny",
    out_dir: str | Path = "data/synth/0",
) -> dict[str, Any]:
    """Convenience helper to generate synthetic persona universe."""
    persona = get_persona(persona_id)
    generator = SyntheticGenerator(persona=persona, seed=seed, size=size)
    return generator.generate(out_dir=out_dir)
