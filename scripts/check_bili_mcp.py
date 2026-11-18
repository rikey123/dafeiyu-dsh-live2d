"""Offline-only protocol probe of the installed upstream Bili MCP server.

Initialize/list_tools never logs in or fetches Bilibili. The child lives on E,
advertises only three read tools, and is closed by the native MCP stdio client.
"""
import asyncio
import json
import os
from pathlib import Path
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def main():
    home = Path('E:/Dafeiyu/dsh-community/data/bili-duty')
    tools = ['bili_search', 'bili_comments', 'bili_subtitle']
    env = {**os.environ, 'PYTHONUTF8': '1', 'PYTHONIOENCODING': 'utf-8',
        'BILI_MCP_TOOLS': ','.join(tools), 'TEMP': 'E:/Dafeiyu/tmp', 'TMP': 'E:/Dafeiyu/tmp'}
    params = StdioServerParameters(command=sys.executable, args=[str(home / 'mcp_server.py')], cwd=home, env=env)
    async with asyncio.timeout(20):
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                names = [tool.name for tool in (await session.list_tools()).tools]
                assert names and set(names) <= set(tools), names
                print(json.dumps({'mcp_initialize': True, 'read_only_tools': names,
                    'login': False, 'network_tools_called': 0}))


if __name__ == '__main__':
    asyncio.run(main())
