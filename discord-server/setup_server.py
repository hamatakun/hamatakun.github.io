"""配達員コミュニティ用 Discord サーバーを server.json の内容で一括構築するスクリプト。

使い方:
    python setup_server.py --dry-run          # 作成内容を表示するだけ（トークン不要）
    DISCORD_TOKEN=xxx GUILD_ID=123 python setup_server.py

何度実行しても、同じ名前のロール・チャンネルは作り直さずに再利用します。
"""

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
MAX_MESSAGE = 2000  # Discord の1メッセージ上限


def load_blueprint(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def split_message(text):
    """2000文字を超える場合は段落の切れ目で分割する。"""
    chunks, cur = [], ""
    for para in text.strip().split("\n\n"):
        add = para if not cur else cur + "\n\n" + para
        if len(add) <= MAX_MESSAGE:
            cur = add
        else:
            if cur:
                chunks.append(cur)
            cur = para[:MAX_MESSAGE]
    if cur:
        chunks.append(cur)
    return chunks


def print_plan(bp):
    print("■ ロール")
    for r in bp["roles"]:
        tag = "（運営）" if r.get("staff") else ""
        print(f"  - {r['name']} {r.get('color', '')}{tag}")
    print("■ チャンネル")
    for cat in bp["categories"]:
        tag = ("（運営のみ閲覧可）" if cat.get("staff_only")
               else f"（{bp.get('members_role')}ロールのみ閲覧可）" if cat.get("members_only") else "")
        print(f"  [{cat['name']}]{tag}")
        for ch in cat["channels"]:
            kind = ch.get("type", "text")
            flags = []
            if ch.get("readonly"):
                flags.append("書き込みは運営のみ")
            if ch.get("post"):
                flags.append(f"{ch['post']} を投稿")
            extra = f" ({', '.join(flags)})" if flags else ""
            print(f"    - {ch['name']} [{kind}]{extra}")


async def build(bp, token, guild_id):
    import discord

    def norm(name):
        return name.lower().replace(" ", "-")

    client = discord.Client(intents=discord.Intents.default())

    @client.event
    async def on_ready():
        try:
            guild = client.get_guild(guild_id) or await client.fetch_guild(guild_id)
            await setup(guild)
            print("✅ 完了しました")
        except Exception as e:
            print(f"❌ エラー: {e!r}", file=sys.stderr)
        finally:
            await client.close()

    async def setup(guild):
        everyone = guild.default_role

        # --- ロール ---
        roles, staff_roles = {}, []
        for r in bp["roles"]:
            role = discord.utils.get(guild.roles, name=r["name"])
            if role is None:
                if r.get("admin"):
                    perms = discord.Permissions(administrator=True)
                elif r.get("staff"):
                    perms = discord.Permissions(
                        manage_messages=True, manage_threads=True, kick_members=True,
                        ban_members=True, moderate_members=True, mute_members=True,
                        move_members=True, view_audit_log=True,
                    )
                else:
                    perms = discord.Permissions.none()
                role = await guild.create_role(
                    name=r["name"],
                    colour=discord.Colour.from_str(r.get("color", "#99aab5")),
                    hoist=r.get("hoist", False),
                    mentionable=not r.get("staff", False),
                    permissions=perms,
                    reason="配達員サーバー初期構築",
                )
                print(f"  + ロール作成: {r['name']}")
            roles[r["name"]] = role
            if r.get("staff"):
                staff_roles.append(role)

        members_role = roles.get(bp.get("members_role", ""))

        # --- カテゴリとチャンネル ---
        for cat in bp["categories"]:
            hidden = cat.get("staff_only") or cat.get("members_only")
            cat_over = {}
            if hidden:
                cat_over[everyone] = discord.PermissionOverwrite(view_channel=False)
                for sr in staff_roles:
                    cat_over[sr] = discord.PermissionOverwrite(view_channel=True)
                if cat.get("members_only") and members_role:
                    cat_over[members_role] = discord.PermissionOverwrite(view_channel=True)
            category = discord.utils.get(guild.categories, name=cat["name"])
            if category is None:
                category = await guild.create_category(cat["name"], overwrites=cat_over)
                print(f"  + カテゴリ作成: {cat['name']}")

            for ch in cat["channels"]:
                kind = ch.get("type", "text")
                over = dict(cat_over)
                if ch.get("readonly"):
                    over[everyone] = discord.PermissionOverwrite(
                        send_messages=False, create_public_threads=False,
                        add_reactions=True,
                        **({"view_channel": False} if hidden else {}),
                    )
                    if cat.get("members_only") and members_role:
                        over[members_role] = discord.PermissionOverwrite(view_channel=True, send_messages=False)
                    for sr in staff_roles:
                        over[sr] = discord.PermissionOverwrite(view_channel=True, send_messages=True)

                existing = next((c for c in category.channels if norm(c.name) == norm(ch["name"])), None)
                if existing is not None:
                    channel = existing
                elif kind == "voice":
                    channel = await category.create_voice_channel(ch["name"], overwrites=over)
                elif kind == "forum":
                    try:
                        channel = await category.create_forum(ch["name"], topic=ch.get("topic"), overwrites=over)
                    except discord.HTTPException:
                        # フォーラムが使えないサーバーでは通常のテキストチャンネルで代用
                        channel = await category.create_text_channel(ch["name"], topic=ch.get("topic"), overwrites=over)
                else:
                    channel = await category.create_text_channel(
                        ch["name"], topic=ch.get("topic"),
                        slowmode_delay=ch.get("slowmode", 0), overwrites=over,
                    )
                if existing is None:
                    print(f"    + チャンネル作成: {ch['name']}")

                if ch.get("post") and isinstance(channel, discord.TextChannel):
                    already = [m async for m in channel.history(limit=1)]
                    if not already:
                        text = (HERE / ch["post"]).read_text(encoding="utf-8")
                        for chunk in split_message(text):
                            await channel.send(chunk)
                        print(f"    ✉ {ch['post']} を投稿: {ch['name']}")

    await client.start(token)


def main():
    ap = argparse.ArgumentParser(description="配達員コミュニティ用 Discord サーバー構築")
    ap.add_argument("--config", default=str(HERE / "server.json"))
    ap.add_argument("--dry-run", action="store_true", help="作成内容を表示するだけ")
    args = ap.parse_args()

    bp = load_blueprint(args.config)
    print_plan(bp)
    if args.dry_run:
        return

    token = os.environ.get("DISCORD_TOKEN")
    guild_id = os.environ.get("GUILD_ID")
    if not token or not guild_id:
        sys.exit("環境変数 DISCORD_TOKEN と GUILD_ID を設定してください（README.md 参照）")
    print("\n▶ 構築を開始します…")
    asyncio.run(build(bp, token, int(guild_id)))


if __name__ == "__main__":
    main()
