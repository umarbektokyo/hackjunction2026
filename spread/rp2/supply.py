"""Driver supply model. Python port of supply.ts (RoutePulse v21e)."""
from __future__ import annotations


def is_experienced_driver(driver) -> bool:
    return driver["rating"] >= 4.8 and driver["completedGigs"] >= 50


def empty_town_counts() -> dict:
    return {"all": 0, "exp": 0, "man": 0, "expMan": 0}


def add_town_counts(dst: dict, src: dict) -> None:
    dst["all"] += src["all"]
    dst["exp"] += src["exp"]
    dst["man"] += src["man"]
    dst["expMan"] += src["expMan"]


def select_pool_count(counts, experienced: bool, manual: bool):
    if counts is None:
        return 0
    if experienced and manual:
        return counts["expMan"]
    if experienced:
        return counts["exp"]
    if manual:
        return counts["man"]
    return counts["all"]


class RosterSupplyModel:
    def __init__(self, m, roster=None):
        self.map = m
        self.drivers: list = []
        self.by_id: dict = {}
        self.home_counts: dict = {}
        self.pool30_counts: dict = {}
        self.pool65_counts: dict = {}
        self.update_roster([] if roster is None else roster)

    def update_roster(self, roster) -> None:
        self.drivers = roster
        self.by_id.clear()
        self.home_counts.clear()
        self.pool30_counts.clear()
        self.pool65_counts.clear()

        for place_id in self.map.places_by_id:
            self.home_counts[place_id] = empty_town_counts()
            self.pool30_counts[place_id] = empty_town_counts()
            self.pool65_counts[place_id] = empty_town_counts()

        for d in roster:
            self.by_id[d["id"]] = d
            is_exp = is_experienced_driver(d)
            is_man = d["licence"] == "manual"
            h = self.home_counts.get(d["homePlaceId"])
            if h is not None:
                h["all"] += 1
                if is_exp:
                    h["exp"] += 1
                if is_man:
                    h["man"] += 1
                if is_exp and is_man:
                    h["expMan"] += 1

        for place_id, n30 in self.map.within30km.items():
            c30 = self.pool30_counts[place_id]
            for q in n30:
                h = self.home_counts.get(q)
                if h is not None:
                    add_town_counts(c30, h)

        for place_id, n65 in self.map.within65km.items():
            c65 = self.pool65_counts[place_id]
            for q in n65:
                h = self.home_counts.get(q)
                if h is not None:
                    add_town_counts(c65, h)

    @property
    def total_drivers(self):
        # TS getter `get totalDrivers()` -> plain method
        return len(self.drivers) or 782

    def home_drivers(self, place_id):
        c = self.home_counts.get(place_id)
        return c["all"] if c is not None else 0

    def pool30(self, place_id, experienced=False, manual=False):
        return select_pool_count(self.pool30_counts.get(place_id), experienced, manual)

    def pool65(self, place_id, experienced=False, manual=False):
        return select_pool_count(self.pool65_counts.get(place_id), experienced, manual)
