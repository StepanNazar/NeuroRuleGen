"""Register every ORM table before Alembic reads metadata."""

from neurorulegen.authentication_authorization import models  # noqa
from neurorulegen.ai_configuration import models  # noqa
from neurorulegen.analysis_management import models  # noqa
from neurorulegen.project_management import models  # noqa
from neurorulegen.rule_management import models  # noqa
