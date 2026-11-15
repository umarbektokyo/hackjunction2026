"""Port of outbox.ts (RoutePulse v21e): the pending-action queue and its sending order."""
from __future__ import annotations

from .js import co

ACTION_PRIORITY = {
    "quote": 0,
    "withdraw": 1,
    "release": 2,
    "post": 3,
    "reprice": 4,
    "offer": 5,
}


def wire(actions):
    """The actions as JSON sends them from JavaScript: whole floats become integers, Infinity never leaves.
    (Same as the old port's desk.wire; underscore keys are stripped.)"""
    def fix(v):
        if isinstance(v, float) and v.is_integer():
            return int(v)
        if isinstance(v, dict):
            return {k: fix(x) for k, x in v.items() if not k.startswith("_")}
        if isinstance(v, list):
            return [fix(x) for x in v]
        return v
    return [fix(a) for a in actions]


class ActionOutbox:
    def __init__(self):
        self.actions = []
        # WeakMap<PostAction, PendingPostMeta> -> dict keyed by id(action). The meta holds a reference to the
        # action ("action" key), so the id stays valid and unique; entries are never deleted (read_results
        # looks the meta up after the action has been drained and sent). Actions carry no extra keys.
        self.pending_post_meta = {}

    def length(self):  # getter `length` -> method
        return len(self.actions)

    def push(self, action):
        self.actions.append(action)

    def enqueue_post(self, stops, audience, schedule, meta):
        post_action = {"type": "post", "stops": stops, "audience": audience, "schedule": schedule}
        self.pending_post_meta[id(post_action)] = {"action": post_action, **meta}
        self.actions.append(post_action)
        return post_action

    def get_post_meta(self, action):
        return self.pending_post_meta.get(id(action))

    def has_pending_quote(self):
        return any(a["type"] == "quote" for a in self.actions)

    def has_pending_post_for_leg(self, order_id, leg):
        return any(
            a["type"] == "post"
            and any(s["kind"] == "pickup" and s["orderId"] == order_id and s["leg"] == leg for s in a["stops"])
            for a in self.actions
        )

    def has_stale_pending_release_post(self, order_id, leg, min_from_exclusive):
        def win_from(s):
            w = s.get("window")
            return co(w["from"] if w else None, 0)

        return any(
            a["type"] == "post"
            and any(
                s["orderId"] == order_id and s["leg"] == leg and s["kind"] == "pickup"
                and win_from(s) > min_from_exclusive
                for s in a["stops"]
            )
            for a in self.actions
        )

    def remove_posts_for_order(self, order_id):
        displaced_other_pickups = []
        for i in range(len(self.actions) - 1, -1, -1):
            act = self.actions[i]
            if act["type"] == "post" and any(s["orderId"] == order_id for s in act["stops"]):
                for s in act["stops"]:
                    if s["orderId"] != order_id and s["kind"] == "pickup":
                        displaced_other_pickups.append(s)
                del self.actions[i]
        return displaced_other_pickups

    def remove_withdraw_for_gig(self, gig_id):
        removed = False
        for i in range(len(self.actions) - 1, -1, -1):
            act = self.actions[i]
            if act["type"] == "withdraw" and act["gigId"] == gig_id:
                del self.actions[i]
                removed = True
        return removed

    def remove_posts_overlapping_orders(self, covered_orders):
        """Returns a Set<string> as a dict (insertion-ordered keys)."""
        orphaned_orders = {}
        for i in range(len(self.actions) - 1, -1, -1):
            act = self.actions[i]
            if act["type"] == "post" and any(s["orderId"] in covered_orders for s in act["stops"]):
                for s in act["stops"]:
                    if s["orderId"] not in covered_orders:
                        orphaned_orders[s["orderId"]] = True
                del self.actions[i]
        return orphaned_orders

    def remove_posts_overlapping_pickup_legs(self, covered_legs, covered_orders):
        """Returns a Set<string> as a dict (insertion-ordered keys)."""
        orphaned_partners = {}
        for i in range(len(self.actions) - 1, -1, -1):
            cand = self.actions[i]
            if cand["type"] == "post" and any(
                s["kind"] == "pickup" and f"{s['orderId']}:{s['leg']}" in covered_legs for s in cand["stops"]
            ):
                for s in cand["stops"]:
                    if s["kind"] == "pickup" and s["orderId"] not in covered_orders:
                        orphaned_partners[s["orderId"]] = True
                del self.actions[i]
        return orphaned_partners

    def drain_sorted(self):
        if len(self.actions) == 0:
            return []
        drained = self.actions[:]
        del self.actions[:]
        drained.sort(key=lambda a: ACTION_PRIORITY[a["type"]])
        return drained

    def extract_by_predicate(self, pred):
        extracted = []
        for i in range(len(self.actions) - 1, -1, -1):
            if pred(self.actions[i]):
                extracted.append(self.actions.pop(i))
        extracted.reverse()
        return extracted

    # `async` in TS; the Python kit client is synchronous. world.act takes the wire-serialised actions.
    def send_quotes_only(self, world, on_results):
        quotes = self.extract_by_predicate(lambda a: a["type"] == "quote")
        for i in range(0, len(quotes), 20):
            chunk = quotes[i:i + 20]
            res = world.act(wire(chunk))
            on_results(chunk, res)

    def send(self, world, is_final, on_results):
        if len(self.actions) == 0:
            return
        if not is_final:
            has_cancel = any(a["type"] == "withdraw" or a["type"] == "release" for a in self.actions)
            has_post = any(a["type"] == "post" for a in self.actions)
            if not has_cancel or not has_post:
                sorted_ = self.drain_sorted()
                if len(sorted_) > 0:
                    results = world.act(wire(sorted_))
                    on_results(sorted_, results)
                return

        self.send_quotes_only(world, on_results)

        cancels = self.extract_by_predicate(lambda a: a["type"] == "withdraw" or a["type"] == "release")
        if len(cancels) > 0:
            res = world.act(wire(cancels))
            on_results(cancels, res)

        rest = self.drain_sorted()
        if not is_final:
            if len(rest) > 0:
                res = world.act(wire(rest))
                on_results(rest, res)
        else:
            for i in range(0, len(rest), 15):
                if self.has_pending_quote():
                    self.send_quotes_only(world, on_results)
                chunk = rest[i:i + 15]
                res = world.act(wire(chunk))
                on_results(chunk, res)
