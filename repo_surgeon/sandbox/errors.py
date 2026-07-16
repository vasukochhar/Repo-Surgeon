class SandboxError(RuntimeError):
    """Base error for safe workspace operations."""


class InvalidRepositoryError(SandboxError):
    pass


class CloneError(SandboxError):
    pass


class DockerUnavailableError(SandboxError):
    pass
