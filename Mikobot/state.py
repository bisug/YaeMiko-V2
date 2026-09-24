from aiohttp import ClientSession
from httpx import AsyncClient, Timeout

session = ClientSession()
state = AsyncClient(
    http2=True,
    verify=False,
    headers={
        "Accept-Language": "en-US,en;q=0.9,id-ID;q=0.8,id;q=0.7",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/107.0.0.0 Safari/537.36",
    },
    timeout=Timeout(20),
)
