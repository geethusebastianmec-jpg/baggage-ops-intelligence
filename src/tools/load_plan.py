"""Aircraft load plan (weight & balance) mock tool."""
from src.models import LoadPlan
from src.tools import store
from src.tools.base import BaseTool


class LoadPlanTool(BaseTool):
    name = "load_plan"

    def get_load_plan(self, flight_id: str) -> LoadPlan | None:
        self._latency()
        return store.LOAD_PLANS.get(flight_id)

    def add_pending_bags(self, flight_id: str, bag_tags: list[str]) -> LoadPlan | None:
        """Flag bags as pending on the load plan (waiting to be loaded)."""
        self._latency()
        if self._should_fail():
            raise RuntimeError("Load plan service unavailable")
        lp = store.LOAD_PLANS.get(flight_id)
        if not lp:
            return None
        updated_pending = list(set(lp.pending_bags + bag_tags))
        store.LOAD_PLANS[flight_id] = lp.model_copy(update={"pending_bags": updated_pending})
        store.ACTION_LOG.append({
            "tool": self.name,
            "action": "add_pending_bags",
            "flight_id": flight_id,
            "bag_tags": bag_tags,
        })
        return store.LOAD_PLANS[flight_id]

    def remove_bags(self, flight_id: str, bag_tags: list[str], weight_kg_per_bag: float = 20.0) -> LoadPlan | None:
        """Remove bags from load plan (off-load scenario)."""
        self._latency()
        lp = store.LOAD_PLANS.get(flight_id)
        if not lp:
            return None
        new_weight = lp.current_weight_kg - (len(bag_tags) * weight_kg_per_bag)
        new_count = lp.bag_count - len(bag_tags)
        updated_pending = [t for t in lp.pending_bags if t not in bag_tags]
        store.LOAD_PLANS[flight_id] = lp.model_copy(update={
            "current_weight_kg": max(0.0, new_weight),
            "bag_count": max(0, new_count),
            "pending_bags": updated_pending,
        })
        store.ACTION_LOG.append({
            "tool": self.name,
            "action": "remove_bags",
            "flight_id": flight_id,
            "bag_tags": bag_tags,
        })
        return store.LOAD_PLANS[flight_id]

    def confirm_bags_loaded(self, flight_id: str, bag_tags: list[str], weight_kg_per_bag: float = 20.0) -> bool:
        """Confirm bags physically loaded, update count and weight."""
        self._latency()
        lp = store.LOAD_PLANS.get(flight_id)
        if not lp:
            return False
        new_weight = lp.current_weight_kg + (len(bag_tags) * weight_kg_per_bag)
        new_count = lp.bag_count + len(bag_tags)
        remaining_pending = [t for t in lp.pending_bags if t not in bag_tags]
        store.LOAD_PLANS[flight_id] = lp.model_copy(update={
            "current_weight_kg": new_weight,
            "bag_count": new_count,
            "pending_bags": remaining_pending,
        })
        store.ACTION_LOG.append({
            "tool": self.name,
            "action": "confirm_bags_loaded",
            "flight_id": flight_id,
            "bag_tags": bag_tags,
        })
        return True
