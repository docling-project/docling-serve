import enum


class TaskStatus(str, enum.Enum):
    SUCCESS = "success"
    PENDING = "pending"
    STARTED = "started"
    FAILURE = "failure"


class AsyncEngine(str, enum.Enum):
    LOCAL = "local"
    KFP = "kfp"
