"""The single ORM model registry (CONVENTIONS.md §10, T147).

**Why this file exists, stated once so nobody deletes it as boilerplate:**
``Base.metadata`` must know every mapper before any ``ForeignKey`` string is
resolved and before Alembic autogenerates. A model that is only reachable
through a router import raises ``NoReferencedTableError`` at runtime, in
whichever unrelated module happens to resolve the foreign key first — which
means in production, on one code path, not in tests.

Every process entry point (``main.py``, ``worker.py``, ``seed.py``, the Alembic
``env.py``) imports this module and nothing else for its models.

BonviZvonki carries the same requirement as folklore. Here it is a test:
``tests/test_model_registry.py::test_model_registry_complete`` walks
``src/modules/*/models.py`` on disk and asserts every ``Base`` subclass is
reachable from here. A missing import fails CI instead of production.
"""

from __future__ import annotations

from src.core.database import Base
from src.modules.agents.models import AgentModel  # noqa: F401
from src.modules.alerts.models import AlertModel  # noqa: F401
from src.modules.analysis.models import (  # noqa: F401
    AiProviderCooldownModel,
    CallAnalysisStateModel,
    CallScoreModel,
    CallTranscriptModel,
)
from src.modules.audio.models import (  # noqa: F401
    AudioUploadSessionModel,
    CallAudioModel,
    StorageUsageDailyModel,
)
from src.modules.audit.models import AuditLogModel  # noqa: F401
from src.modules.auth.models import (  # noqa: F401
    RefreshTokenModel,
    ServiceTokenModel,
)
from src.modules.calls.models import CallModel  # noqa: F401
from src.modules.catalog.models import (  # noqa: F401
    AppVersionModel,
    LineDirectoryEntryModel,
    ModelCaptureStatModel,
    SupportedModelModel,
)
from src.modules.commands.models import CommandModel  # noqa: F401
from src.modules.devices.models import (  # noqa: F401
    CallLogDeltaModel,
    CapabilityStateModel,
    CapabilityTransitionModel,
    DataUsageDailyModel,
    DeviceHealthModel,
    DeviceModel,
)
from src.modules.enrolment.models import (  # noqa: F401
    CallbackEventModel,
    CallbackReceiverModel,
    EnrolmentAttemptModel,
    EnrolmentCodeModel,
    NumberVerificationModel,
)
from src.modules.installations.models import InstallationModel  # noqa: F401
from src.modules.numbers.models import (  # noqa: F401
    NumberAssignmentModel,
    RegisteredNumberModel,
)
from src.modules.settings.models import AppSettingModel  # noqa: F401
from src.modules.users.models import UserModel  # noqa: F401

#: The metadata every migration and every test builds the schema from.
metadata = Base.metadata

__all__ = ["Base", "metadata"]
