"""Constants for the Playwright Web Search integration."""

DOMAIN = "playwright_websearch"

# Config entry data (connection endpoints)
CONF_SEARXNG_URL = "searxng_url"
CONF_PLAYWRIGHT_WS_URL = "playwright_ws_url"

# Options (tunable defaults)
CONF_NUM_RESULTS = "num_results"
CONF_RENDER_TIMEOUT = "render_timeout"  # seconds
CONF_PER_RESULT_CAP = "per_result_cap"  # chars
CONF_TOTAL_CEILING = "total_ceiling"  # chars
CONF_FULL_PAGE_CAP = "full_page_cap"  # chars
CONF_CONCURRENCY = "concurrency"  # semaphore size
CONF_CONTENT_FLOOR = "content_floor"  # min word_count to keep a partial render

DEFAULT_NUM_RESULTS = 5
DEFAULT_RENDER_TIMEOUT = 20
DEFAULT_PER_RESULT_CAP = 2000
DEFAULT_TOTAL_CEILING = 8000
DEFAULT_FULL_PAGE_CAP = 20000
DEFAULT_CONCURRENCY = 3
DEFAULT_CONTENT_FLOOR = 50
CONF_SNIPPET_CEILING = "snippet_ceiling"  # chars for stub tier
DEFAULT_SNIPPET_CEILING = 500
