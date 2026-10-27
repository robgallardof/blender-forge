"""The server speaks MCP over stdio to a real client process."""
import asyncio
import json
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


def test_stdio_lists_tools_skills_and_reports_offline_bridge(tmp_path):
    cfg = tmp_path / "bridge.json"
    cfg.write_text(json.dumps({"port": 1, "token": "q" * 64}), encoding="utf-8")
    params = StdioServerParameters(command=sys.executable, args=["-m", "blender_forge.server"],
                                   env={"BLENDER_FORGE_CONFIG": str(cfg), "PATH": "", "SYSTEMROOT": "C:\\Windows"})

    async def session():
        async with stdio_client(params) as (read, write), ClientSession(read, write) as client:
            await client.initialize()
            tools = {t.name: t for t in (await client.list_tools()).tools}
            resources = [str(r.uri) for r in (await client.list_resources()).resources]
            prompts = [p.name for p in (await client.list_prompts()).prompts]
            status = await client.call_tool("forge_status", {})
            return tools, resources, prompts, json.loads(status.content[0].text)

    tools, resources, prompts, status = asyncio.run(session())
    assert {"build_scene", "look", "render_still", "export_file", "create_mesh"} <= set(tools)
    assert tools["scene_info"].annotations.readOnlyHint is True
    assert tools["delete"].annotations.destructiveHint is True
    assert "skill://blender-forge" in resources and "3d-artist" in prompts
    assert status["error"]["code"] == "BRIDGE_OFFLINE" and status["error"]["hint"]
