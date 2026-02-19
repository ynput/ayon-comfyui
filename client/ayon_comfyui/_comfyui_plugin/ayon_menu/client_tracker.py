"""Singleton class to help track clients and maybe metadata"""

from dataclasses import dataclass, field
from datetime import datetime
from uuid import uuid4


class MetaSingleton(type):
    _instances = {}

    def __call__(cls, *args, **kwargs):
        if cls not in cls._instances:
            cls._instances[cls] = super(MetaSingleton, cls).__call__(*args, **kwargs)
        return cls._instances[cls]


@dataclass
class ClientID:
    """Structured way to access a client"""

    hash: int
    hostname: str
    ip: str
    _last_update: datetime = field(default=datetime.now())

    @property
    def minutes_since_last_update(self) -> float:
        """Compares current time and last update time to see whether client is still connected"""
        now = datetime.now()
        delta = now - self._last_update
        return delta.total_seconds() / 60

    def update(self):
        """Update client time"""
        self._last_update = datetime.now()


class ClientTracker(metaclass=MetaSingleton):
    """Store data internally"""

    def __init__(self, expiry_mins: int = 10):
        self._data: dict[int, ClientID] = {}
        self._expiration_mins = expiry_mins

    @classmethod
    def construct_hash(cls, hostname, ip):
        # NOTE: This sucks. do something better. Very easy to spoof.
        # Hash is based on time & uuid. I don't know how safe this is but
        # The hash should be constructed RIGHT now and then passed to the client on first ping
        # Including the time should also help with differentiating different sessions
        return hash(f"{hostname}{ip}{datetime.now().isoformat()}{uuid4()}")

    def register(self, hostname, ip) -> int | None:
        _hash = self.construct_hash(hostname, ip)
        if _hash not in self._data:
            self._data[_hash] = ClientID(_hash, hostname, ip)

            return _hash

    def update_client(self, hash_nr: int):
        client = self._data.get(hash_nr, None)
        if client:
            client.update()

    def expire_clients(self):
        self._data = {
            k: v
            for k, v in self._data.items()
            if v.minutes_since_last_update < self._expiration_mins
        }


TRACKER = ClientTracker()
