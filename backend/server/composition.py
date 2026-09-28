"""知伴应用对 Yuxi 平台端口的唯一装配入口。"""

from counseling.integrations.identity import CounselingIdentityReader
from counseling.integrations.capabilities import CounselingBusinessCapabilityMapper
from yuxi.identity import configure_identity_reader
from yuxi.business_capabilities import configure_business_capability_mapper


def configure_platform_ports() -> None:
    """注册业务实现，避免 Yuxi 反向导入 counseling。"""
    configure_identity_reader(CounselingIdentityReader())
    configure_business_capability_mapper(CounselingBusinessCapabilityMapper())
