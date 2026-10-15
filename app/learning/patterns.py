"""Learned patterns (docs/SPEC-v4.md 4.2): what admins teach with teaching cards.

  nickname       text -> product         ("ysl edp" -> Y Eau de Parfum)
  intent_phrase  text -> intent          ("လေးထည့်ထားပေး" -> buy)
  not_stocked    text -> we don't sell it ("liquid brun")

pending: the parser uses it to UNDERSTAND (one-tap suggestion "📘 learned"), never automatic.
approved: exactly like a seed alias / keyword (auto allowed). It becomes approved when the
owner approves it, or after `auto_approve_after` one-tap accepts with no corrections.
rejected: ignored. A nickname never overrides an alias of a DIFFERENT product: such a
conflict is not saved, the owner decides ("Needs you" / Learning page).
"""
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import exists, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models import AppSetting, AuditLog, LearnedPattern, Product, ProductAlias, User
from app.parser.normalize import normalize
from app.parser.rules import Alias, Phrase, find_intent, greeting_only

SETTING = "learning"
DEFAULTS = {"auto_approve_after": 3, "greeting": True, "auto_not_stocked": True}
MAX_AUTO_APPROVE = 20
LIVE = ("pending", "approved")
LEARNABLE_INTENTS = ("buy", "ask_price", "ask_stock", "remove", "cancel_order", "ask_delivery", "greeting")


# ---------- settings ----------

def settings(session: Session) -> dict:
    row = session.get(AppSetting, SETTING)
    return {**DEFAULTS, **(row.value if row else {})}


def set_settings(session: Session, values: dict, user: User | None) -> None:
    n = values["auto_approve_after"]
    if not isinstance(n, int) or not 0 <= n <= MAX_AUTO_APPROVE:
        raise ValueError(f"Auto-approve after: 0-{MAX_AUTO_APPROVE} uses (0 = only the owner approves).")
    value = {"auto_approve_after": n, "greeting": bool(values["greeting"]),
             "auto_not_stocked": bool(values["auto_not_stocked"])}
    stmt = insert(AppSetting).values(key=SETTING, value=value, updated_by=user.id if user else None)
    session.execute(stmt.on_conflict_do_update(index_elements=["key"], set_={
        "value": stmt.excluded.value, "updated_by": stmt.excluded.updated_by, "updated_at": func.now()}))


# ---------- what the parser uses ----------

def nickname_aliases(session: Session) -> list[Alias]:
    rows = session.execute(select(LearnedPattern).join(Product, Product.id == LearnedPattern.product_id).where(
        LearnedPattern.kind == "nickname", LearnedPattern.status.in_(LIVE), Product.active)
        .order_by(LearnedPattern.id)).scalars()
    return [Alias(p.product_id, p.normalized_text, p.id, p.status == "pending") for p in rows]


def intent_phrases(session: Session) -> list[Phrase]:
    rows = session.scalars(select(LearnedPattern).where(
        LearnedPattern.kind == "intent_phrase", LearnedPattern.status.in_(LIVE)).order_by(LearnedPattern.id))
    return [Phrase(p.id, p.normalized_text, p.intent, p.status == "pending") for p in rows]


def fingerprint(session: Session) -> frozenset:
    """Changes when anything the parser uses changes (the worker then re-parses)."""
    return frozenset(session.execute(select(
        LearnedPattern.id, LearnedPattern.kind, LearnedPattern.normalized_text, LearnedPattern.product_id,
        LearnedPattern.intent, LearnedPattern.status).where(LearnedPattern.kind != "not_stocked")).all())


def _words_in(pattern: str, text: str) -> bool:
    """pattern found in text as whole words ("liquid brun" in "liquid brun edp")."""
    return f" {pattern} " in f" {text} "


def not_stocked_hits(session: Session, texts: list[str]) -> dict[str, LearnedPattern]:
    """Unknown item texts (normalized) that a live not_stocked pattern answers."""
    if not texts:
        return {}
    patterns = list(session.scalars(select(LearnedPattern).where(
        LearnedPattern.kind == "not_stocked", LearnedPattern.status.in_(LIVE))))
    hits = {}
    for t in texts:
        best = max((p for p in patterns if _words_in(p.normalized_text, t)),
                   key=lambda p: len(p.normalized_text), default=None)
        if best is not None:
            hits[t] = best
    return hits


def not_certain(session: Session, ids: list[int]) -> list[LearnedPattern]:
    """The patterns among ids that may NOT act by themselves: pending ones, and approved
    not_stocked ones while "auto not stocked" is off."""
    if not ids:
        return []
    auto_not_stocked = settings(session)["auto_not_stocked"]
    return [p for p in session.scalars(select(LearnedPattern).where(LearnedPattern.id.in_(ids)))
            if p.status != "approved" or (p.kind == "not_stocked" and not auto_not_stocked)]


# ---------- teaching ----------

@dataclass
class Taught:
    status: str  # saved | known | conflict | invalid
    pattern: LearnedPattern | None = None
    note: str = ""


def _record_conflict(session: Session, kind: str, text: str, user: User | None, message_id: int | None,
                     existing: str, product_id: int | None = None, intent: str | None = None,
                     existing_pattern_id: int | None = None, existing_alias_id: int | None = None) -> Taught:
    session.add(AuditLog(user_id=user.id if user else None, action="learning.conflict", details={
        "kind": kind, "text": text, "product_id": product_id, "intent": intent, "message_id": message_id,
        "existing": existing, "existing_pattern_id": existing_pattern_id, "existing_alias_id": existing_alias_id}))
    return Taught("conflict", note=f"“{text}” is already {existing}: not saved, the owner will decide.")


def _product_name(session: Session, product_id: int) -> str:
    product = session.get(Product, product_id)
    return product.name if product else "?"


def teach(session: Session, kind: str, text: str, user: User | None, *, product_id: int | None = None,
          intent: str | None = None, message_id: int | None = None, approved: bool = False) -> Taught:
    """Save a new pattern (pending, or approved when the owner decides directly), unless it is
    already known or conflicts with something else (then the owner is asked)."""
    text = " ".join(text.split())[:255]
    norm = normalize(text)
    if len(norm.replace(" ", "")) < 2 or norm.isdigit():
        return Taught("invalid", note="Too short to learn.")
    live = session.scalars(select(LearnedPattern).where(
        LearnedPattern.normalized_text == norm, LearnedPattern.status.in_(LIVE))).all()
    if kind in ("nickname", "not_stocked"):
        aliases = session.execute(select(ProductAlias.id, ProductAlias.product_id).join(
            Product, Product.id == ProductAlias.product_id).where(
            ProductAlias.normalized_alias == norm, Product.active)).all()
        if kind == "nickname" and any(pid == product_id for _, pid in aliases):
            return Taught("known")
        if kind == "nickname" and any(p.kind == "nickname" and p.product_id == product_id for p in live):
            return Taught("known")
        if kind == "not_stocked" and any(p.kind == "not_stocked" for p in live):
            return Taught("known")
        for alias_id, pid in aliases:
            return _record_conflict(session, kind, text, user, message_id, f"a nickname of {_product_name(session, pid)}",
                                    product_id, existing_alias_id=alias_id)
        for p in live:
            if p.kind == "nickname":
                return _record_conflict(session, kind, text, user, message_id,
                                        f"a learned nickname of {_product_name(session, p.product_id)}", product_id,
                                        existing_pattern_id=p.id)
            if p.kind == "not_stocked":
                return _record_conflict(session, kind, text, user, message_id, "marked “we don't sell it”",
                                        product_id, existing_pattern_id=p.id)
    elif kind == "intent_phrase":
        if intent not in LEARNABLE_INTENTS:
            return Taught("invalid", note="This answer is not learned.")
        if find_intent(norm) == intent or (intent == "greeting" and greeting_only(norm)[0]):
            return Taught("known")
        for p in live:
            if p.kind == "intent_phrase":
                if p.intent == intent:
                    return Taught("known")
                return _record_conflict(session, kind, text, user, message_id,
                                        f"taught as “{p.intent.replace('_', ' ')}”", intent=intent,
                                        existing_pattern_id=p.id)
    else:
        raise ValueError(kind)
    now = datetime.now(UTC)
    pattern = LearnedPattern(kind=kind, text=text, normalized_text=norm, product_id=product_id, intent=intent,
                             status="approved" if approved else "pending", taught_by=user.id if user else None,
                             source_message_id=message_id,
                             approved_by=user.id if approved and user else None, approved_at=now if approved else None)
    session.add(pattern)
    session.flush()
    session.add(AuditLog(user_id=user.id if user else None, action="learning.taught", details={
        "pattern_id": pattern.id, "kind": kind, "text": text, "product_id": product_id, "intent": intent,
        "message_id": message_id, "status": pattern.status}))
    return Taught("saved", pattern)


def remove_taught(session: Session, ids: list[int]) -> None:
    """Undo of a teaching card: the patterns it created disappear."""
    for p in session.scalars(select(LearnedPattern).where(LearnedPattern.id.in_(ids))):
        session.delete(p)


# ---------- uses, corrections, approval ----------

def confirm_uses(session: Session, ids: list[int], user: User | None) -> list[int]:
    """An admin accepted a 📘 suggestion unchanged: +1 use for each pending pattern; those
    reaching `auto_approve_after` uses with no corrections become approved. Returns them."""
    n = settings(session)["auto_approve_after"]
    approved = []
    for p in session.scalars(select(LearnedPattern).where(LearnedPattern.id.in_(ids),
                                                          LearnedPattern.status == "pending")):
        p.confirmed_uses += 1
        if n > 0 and p.confirmed_uses >= n and p.corrections == 0:
            p.status, p.approved_at, p.approved_by = "approved", datetime.now(UTC), None
            approved.append(p.id)
            session.add(AuditLog(user_id=user.id if user else None, action="learning.auto_approved",
                                 details={"pattern_id": p.id, "uses": p.confirmed_uses}))
    return approved


def unconfirm_uses(session: Session, ids: list[int], approved: list[int]) -> None:
    """Undo of an accepted suggestion."""
    for p in session.scalars(select(LearnedPattern).where(LearnedPattern.id.in_(ids))):
        p.confirmed_uses = max(p.confirmed_uses - 1, 0)
        if p.id in approved and p.status == "approved" and p.approved_by is None:
            p.status, p.approved_at = "pending", None


def add_corrections(session: Session, ids: list[int], user: User | None, message_id: int) -> None:
    for p in session.scalars(select(LearnedPattern).where(LearnedPattern.id.in_(ids),
                                                          LearnedPattern.status == "pending")):
        p.corrections += 1
        session.add(AuditLog(user_id=user.id if user else None, action="learning.corrected",
                             details={"pattern_id": p.id, "message_id": message_id}))


def decide(session: Session, pattern: LearnedPattern, status: str, user: User) -> None:
    """Owner: approve / reject (reject also = remove an approved one)."""
    if status not in ("approved", "rejected"):
        raise ValueError(status)
    pattern.status = status
    pattern.approved_by, pattern.approved_at = (user.id, datetime.now(UTC)) if status == "approved" else (None, None)
    session.add(AuditLog(user_id=user.id, action=f"learning.{'approve' if status == 'approved' else 'reject'}",
                         details={"pattern_id": pattern.id, "kind": pattern.kind, "text": pattern.text}))


def edit(session: Session, pattern: LearnedPattern, text: str, user: User, product_id: int | None = None,
         intent: str | None = None) -> None:
    """Owner: change the words or the answer. ValueError if too short or taken."""
    text = " ".join(text.split())[:255]
    norm = normalize(text)
    if len(norm.replace(" ", "")) < 2:
        raise ValueError("Too short.")
    taken = session.scalar(select(exists().where(
        LearnedPattern.kind == pattern.kind, LearnedPattern.normalized_text == norm,
        LearnedPattern.status.in_(LIVE), LearnedPattern.id != pattern.id)))
    if taken:
        raise ValueError(f"“{text}” is already learned.")
    if pattern.kind == "nickname" and product_id:
        clash = session.scalar(select(ProductAlias.product_id).where(
            ProductAlias.normalized_alias == norm, ProductAlias.product_id != product_id).limit(1))
        if clash:
            raise ValueError(f"“{text}” is a nickname of {_product_name(session, clash)}.")
        pattern.product_id = product_id
    if pattern.kind == "intent_phrase" and intent:
        if intent not in LEARNABLE_INTENTS:
            raise ValueError("Unknown answer.")
        pattern.intent = intent
    before = pattern.text
    pattern.text, pattern.normalized_text = text, norm
    session.add(AuditLog(user_id=user.id, action="learning.edit",
                         details={"pattern_id": pattern.id, "from": before, "to": text}))


# ---------- conflicts (the owner decides) ----------

def conflicts(session: Session) -> list[AuditLog]:
    """Taught answers that clashed with an existing one and that the owner has not decided yet."""
    closed = {d.details.get("conflict_id") for d in session.scalars(
        select(AuditLog).where(AuditLog.action == "learning.conflict_done"))}
    rows = session.scalars(select(AuditLog).where(AuditLog.action == "learning.conflict").order_by(AuditLog.id.desc()))
    return [r for r in rows if r.id not in closed]


def resolve_conflict(session: Session, conflict: AuditLog, use_new: bool, user: User) -> str:
    """use_new: the newly taught answer replaces the old one (approved, the owner decided)."""
    d = conflict.details
    note = "Kept as it was."
    if use_new:
        if d.get("existing_pattern_id"):
            old = session.get(LearnedPattern, d["existing_pattern_id"])
            if old is not None and old.status in LIVE:
                old.status = "rejected"
        if d.get("existing_alias_id"):
            alias = session.get(ProductAlias, d["existing_alias_id"])
            if alias is not None:
                session.delete(alias)
        session.flush()
        taught = teach(session, d["kind"], d["text"], user, product_id=d.get("product_id"), intent=d.get("intent"),
                       message_id=d.get("message_id"), approved=True)
        note = f"“{d['text']}” now means the new answer." if taught.status in ("saved", "known") else taught.note
    session.add(AuditLog(user_id=user.id, action="learning.conflict_done",
                         details={"conflict_id": conflict.id, "use_new": use_new}))
    return note


def pending_count(session: Session) -> int:
    return session.scalar(select(func.count()).select_from(LearnedPattern).where(LearnedPattern.status == "pending"))

