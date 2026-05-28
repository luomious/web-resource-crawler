"""
统一资源抓取 + 解析模块（向后兼容层）。

此模块保留向后兼容的公共 API，新代码应直接从子模块精确导入：
    from core.parser import Resource, parse_resources
    from core.fetcher import fetch_html, fetch_all_urls
    from core.asmr_one import is_asmr_one, parse_asmr_one

不再推荐 from core.scraper import *，未来版本可能移除重导出。
"""

# ── 向后兼容重导出（deprecated，新代码请直接导入子模块）────────
from core.constants import (                         # noqa: F401
    USER_AGENTS, TIMEOUT, CONNECT_TIMEOUT, MAX_RETRIES,
    IMG_EXTS, AUDIO_EXTS, VIDEO_EXTS, DOC_EXTS, CSS_EXTS, JS_EXTS,
    CHUNK_SIZE, MAX_FETCH_WORKERS, ASMR_API_WORK_INFO, ASMR_API_TRACKS,
)

from core.parser import (                            # noqa: F401
    Resource, classify,
    extract_name,
    extract_chapters,
    parse_resources,
)

from core.unpacker import (                         # noqa: F401
    unpack_js,
    extract_m3u8_from_html,
)

from core.fetcher import (                          # noqa: F401
    make_session,
    fetch_html,
    fetch_all_urls,
)

from core.asmr_one import (                        # noqa: F401
    is_asmr_one,
    parse_asmr_one,
)

from core.translator import (                       # noqa: F401
    translate_to_zh,
    translate_chapters,
)

import re as _re
ASMR_ONE_PATTERN = _re.compile(r'asmr\.one/work/(RJ\d+)', _re.I)
