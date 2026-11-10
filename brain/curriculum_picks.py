"""Glue between the curriculum and the Parent Board: the child's grade, and the parent's boost / skip choices.

A parent's choice is a NORMAL Parent Board item (so it is encrypted, shown under "What the toys know", expires never and is
deletable like any other):
    boost -> kind "goal"     text "teach more: <title>"   detail "curriculum:<topic id>"
    skip  -> kind "boundary" text "not yet: <title>"      detail "curriculum:<topic id>"
The grade is the child's 'profile' item ("in 2nd grade"). Parent.notes_block ignores items whose detail starts with
PICK_PREFIX (the [GRADE TOPICS] block consumes them instead), so a pick is not also repeated in the private notes.
"""
from __future__ import annotations

from . import curriculum as C

PICK_PREFIX = "curriculum:"


def is_pick(item: dict) -> bool:
    return str(item.get("detail") or "").startswith(PICK_PREFIX)


def _grade_of_items(items: list[dict]) -> int | None:
    for i in items:
        if i.get("kind") == "profile":
            g = C.grade_from_text(i.get("text", ""))
            if g is not None:
                return g
    return None


def _picks_of_items(items: list[dict]) -> tuple[set, set]:
    boost, skip = set(), set()
    for i in items:
        if not is_pick(i):
            continue
        tid = i["detail"][len(PICK_PREFIX):]
        if i["kind"] == "goal":
            boost.add(tid)
        elif i["kind"] == "boundary":
            skip.add(tid)
    return boost, skip - boost


def context_for_bound_child(parent) -> tuple[int | None, set, set]:
    """(grade or None, boost ids, skip ids) for the child marked 'Playing now'. Nobody bound, locked or notes paused -> (None, {}, {}),
    which means the default grade and no preferences: the toys still have grade-level topics, nothing private is used."""
    if parent is None:
        return None, set(), set()
    with parent._lock:
        if parent._dek is None or not parent.index["settings"].get("notes_on", True):
            return None, set(), set()
        child = parent.bound_child()
        if not child:
            return None, set(), set()
        items = parent.items.get(child["id"], [])
        return (_grade_of_items(items), *_picks_of_items(items))


def overview(parent, cid: str) -> dict:
    """What the board shows for a child: grade, whether it is the default, and every topic of that grade with its state."""
    with parent._lock:
        parent._require()
        parent._child(cid)
        items = parent.items.get(cid, [])
        grade = _grade_of_items(items)
        boost, skip = _picks_of_items(items)
    g = C.DEFAULT_GRADE if grade is None else grade
    subjects = []
    for s in C.SUBJECTS:
        topics = [dict(C.public(it), state="boost" if it["id"] in boost else "skip" if it["id"] in skip else "")
                  for it in C.query(grade=g, subject=s)]
        if topics:
            subjects.append({"id": s, "label": C.SUBJECT_LABELS[s], "topics": topics})
    return {"grade": g, "grade_label": C.grade_label(g), "grade_known": grade is not None, "subjects": subjects}


def set_pick(parent, cid: str, topic_id: str, mode: str) -> None:
    """mode: 'boost', 'skip' or 'clear'. Replaces any earlier pick for that topic."""
    it = C.get(topic_id)
    if it is None:
        raise ValueError("Unknown topic.")
    if mode not in ("boost", "skip", "clear"):
        raise ValueError("Unknown choice.")
    tag = PICK_PREFIX + topic_id
    with parent._lock:
        parent._require()
        parent._child(cid)
        for old in [i for i in parent.items.get(cid, []) if i.get("detail") == tag]:
            parent.delete_item(cid, old["id"])
        if mode == "boost":
            parent.add_items(cid, [{"kind": "goal", "text": "teach more: " + it["title"][:44], "detail": tag}])
        elif mode == "skip":
            parent.add_items(cid, [{"kind": "boundary", "text": "not yet: " + it["title"][:48], "detail": tag}])
