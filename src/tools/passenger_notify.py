"""Passenger notification mock tool (SMS / app push)."""
from src.tools import store
from src.tools.base import BaseTool


_SENT_NOTIFICATIONS: list[dict] = []


class PassengerNotifyTool(BaseTool):
    name = "passenger_notify"

    def notify_bag_at_risk(self, passenger_id: str, bag_tag: str, outbound_flight: str) -> bool:
        self._latency()
        msg = (
            f"Your bag {bag_tag} is at risk of missing your connection on {outbound_flight}. "
            "Our team is working to transfer it. We'll update you shortly."
        )
        return self._send(passenger_id, bag_tag, "AT_RISK", msg)

    def notify_bag_missed(self, passenger_id: str, bag_tag: str, delivery_eta: str = "next available flight") -> bool:
        self._latency()
        msg = (
            f"We're sorry — your bag {bag_tag} missed your connection. "
            f"It will be delivered to your destination via {delivery_eta}. "
            "Claim reference will follow by SMS."
        )
        return self._send(passenger_id, bag_tag, "MISSED", msg)

    def notify_bag_recovered(self, passenger_id: str, bag_tag: str) -> bool:
        self._latency()
        msg = f"Great news! Your bag {bag_tag} has been successfully transferred to your connecting flight."
        return self._send(passenger_id, bag_tag, "RECOVERED", msg)

    def _send(self, passenger_id: str, bag_tag: str, notification_type: str, message: str) -> bool:
        if self._should_fail():
            return False
        record = {
            "tool": self.name,
            "action": "send_notification",
            "passenger_id": passenger_id,
            "bag_tag": bag_tag,
            "type": notification_type,
            "message": message,
        }
        _SENT_NOTIFICATIONS.append(record)
        store.ACTION_LOG.append(record)
        return True

    @staticmethod
    def get_sent() -> list[dict]:
        return list(_SENT_NOTIFICATIONS)

    @staticmethod
    def clear() -> None:
        _SENT_NOTIFICATIONS.clear()
