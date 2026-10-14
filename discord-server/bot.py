"""配達員コミュニティの見張り役 Bot。

- ✅認証：ボタン＋かんたんな計算問題で人間か確認し、「配達員」ロールを付与
  （作ったばかりのアカウントは認証できない＝使い捨てスパムBot対策）
- スパム対策：連投・同じ文の多チャンネル投稿・大量メンション・招待リンク・NGワード
- レイド対策：短時間に大量参加があったら認証を一時停止して運営に通知
- 会話のきっかけ：認証した人を雑談で歓迎、毎日お題を投稿
- 運営用コマンド：/lockdown /お題

使い方: DISCORD_TOKEN=xxx GUILD_ID=123 python bot.py
"""

import datetime as dt
import json
import os
import random
import sys
import time
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import tasks

from guard import RaidDetector, SpamDetector

HERE = Path(__file__).resolve().parent
JST = dt.timezone(dt.timedelta(hours=9))
CFG = json.loads((HERE / "config.json").read_text(encoding="utf-8"))


def norm(name):
    return name.lower().replace(" ", "-")


def find_channel(guild, name):
    return next((c for c in guild.channels if norm(c.name) == norm(name)), None)


def is_staff(member):
    return isinstance(member, discord.Member) and member.guild_permissions.manage_messages


class Guard(discord.Client):
    def __init__(self, guild_id):
        intents = discord.Intents.default()
        intents.members = True          # 参加検知（Developer Portal で ON が必要）
        intents.message_content = True  # 本文チェック（Developer Portal で ON が必要）
        super().__init__(intents=intents)
        self.guild_id = guild_id
        self.tree = app_commands.CommandTree(self)
        self.spam = SpamDetector(CFG)
        self.raid = RaidDetector(CFG["raid"]["joins"], CFG["raid"]["seconds"])
        self.lockdown_until = 0.0
        self.verify_fail = {}  # user_id -> (失敗回数, 最終失敗時刻)

    # ---------- 起動 ----------
    async def setup_hook(self):
        self.add_view(VerifyView())  # 再起動後もボタンが効くように
        guild = discord.Object(id=self.guild_id)
        self.tree.copy_global_to(guild=guild)
        await self.tree.sync(guild=guild)
        self.daily_topic.start()

    async def on_ready(self):
        guild = self.get_guild(self.guild_id)
        if guild is None:
            print("❌ GUILD_ID のサーバーに Bot が参加していません", file=sys.stderr)
            return
        print(f"✅ {self.user} として {guild.name} で起動しました")
        await self.ensure_verify_panel(guild)

    async def ensure_verify_panel(self, guild):
        ch = find_channel(guild, CFG["verify_channel"])
        if not isinstance(ch, discord.TextChannel):
            print(f"⚠️ 認証チャンネル「{CFG['verify_channel']}」が見つかりません")
            return
        async for m in ch.history(limit=20):
            if m.author == self.user and m.components:
                return  # 設置済み
        embed = discord.Embed(
            title="✅ 認証してサーバーに参加",
            description=(
                "📌ルール を読んで同意できたら、下のボタンを押してください。\n"
                "かんたんな計算問題に答えると、全チャンネルが見られるようになります。\n\n"
                "※スパム対策のため、作成から日が浅いアカウントは認証できません。"
            ),
            color=0x3498DB,
        )
        await ch.send(embed=embed, view=VerifyView())

    # ---------- ログ ----------
    async def log(self, guild, text):
        print(text)
        ch = find_channel(guild, CFG["log_channel"])
        if isinstance(ch, discord.TextChannel):
            await ch.send(text[:2000], allowed_mentions=discord.AllowedMentions.none())

    # ---------- 参加・レイド ----------
    def in_lockdown(self):
        return time.time() < self.lockdown_until

    async def set_lockdown(self, guild, minutes, reason):
        self.lockdown_until = time.time() + minutes * 60
        await self.log(guild, f"🚨 **ロックダウン開始**（{minutes}分）理由: {reason}\n認証を一時停止しています。解除は `/lockdown 0`")

    async def on_member_join(self, member):
        if member.guild.id != self.guild_id or member.bot:
            return
        age_days = (discord.utils.utcnow() - member.created_at).days
        note = f"（アカウント作成 {age_days}日前）"
        if age_days < CFG["min_account_age_days"]:
            note += " ⚠️新しいアカウント"
        await self.log(member.guild, f"📥 参加: {member.mention} `{member}` {note}")
        if self.raid.joined(time.time()) and not self.in_lockdown():
            await self.set_lockdown(
                member.guild, CFG["raid"]["lockdown_minutes"],
                f"{CFG['raid']['seconds']}秒間に{CFG['raid']['joins']}人以上が参加",
            )

    # ---------- メッセージ監視 ----------
    async def on_message(self, message):
        if (message.guild is None or message.guild.id != self.guild_id
                or message.author.bot or is_staff(message.author)):
            return
        member = message.author
        age_h = None
        if isinstance(member, discord.Member) and member.joined_at:
            age_h = (discord.utils.utcnow() - member.joined_at).total_seconds() / 3600
        text = message.content
        v = self.spam.check(
            member.id, message.channel.id, text, time.time(),
            mentions=len({u.id for u in message.mentions}),
            mentions_everyone="@everyone" in text or "@here" in text,
            member_age_hours=age_h,
        )
        if v is None:
            return

        try:
            await message.delete()
        except discord.HTTPException:
            pass
        action = "メッセージ削除"
        if v.timeout and isinstance(member, discord.Member):
            minutes = CFG["timeout_minutes"]
            try:
                await member.timeout(dt.timedelta(minutes=minutes), reason=f"自動: {v.reason}")
                action += f"＋{minutes}分タイムアウト"
            except discord.HTTPException:
                action += "（タイムアウト失敗：Bot の権限・ロール順を確認）"
            # 連投の残りも消しておく
            await self.purge_recent(message.guild, member)
            self.spam.forget(member.id)
        try:
            await member.send(
                f"「{message.guild.name}」でのあなたの投稿は自動で削除されました。\n"
                f"理由: {v.reason}\n間違いの場合は運営に連絡してください。"
            )
        except discord.HTTPException:
            pass
        await self.log(
            message.guild,
            f"🛡️ {action}: {member.mention} in {message.channel.mention}\n理由: {v.reason}\n"
            f"内容: ```{text[:500].replace('`', 'ˋ')}```",
        )

    async def purge_recent(self, guild, member):
        """直近2分の同じ人の投稿を各チャンネルから削除する。"""
        since = discord.utils.utcnow() - dt.timedelta(minutes=2)
        for ch in guild.text_channels:
            perms = ch.permissions_for(guild.me)
            if not (perms.read_message_history and perms.manage_messages):
                continue
            try:
                await ch.purge(limit=30, after=since, check=lambda m: m.author.id == member.id)
            except discord.HTTPException:
                pass

    # ---------- お題 ----------
    @tasks.loop(time=dt.time(hour=CFG["topic_hour_jst"], tzinfo=JST))
    async def daily_topic(self):
        guild = self.get_guild(self.guild_id)
        if guild:
            await self.post_topic(guild)

    async def post_topic(self, guild):
        ch = find_channel(guild, CFG["topic_channel"])
        if isinstance(ch, discord.TextChannel):
            await ch.send(f"💡 **今日のお題**\n{random.choice(CFG['topics'])}")


class VerifyModal(discord.ui.Modal):
    def __init__(self):
        self.a, self.b = random.randint(2, 9), random.randint(2, 9)
        super().__init__(title="認証")
        self.answer = discord.ui.TextInput(label=f"{self.a} + {self.b} = ?（半角数字で）", max_length=3)
        self.add_item(self.answer)

    async def on_submit(self, interaction):
        bot: Guard = interaction.client
        member = interaction.user
        if self.answer.value.strip() != str(self.a + self.b):
            n, _ = bot.verify_fail.get(member.id, (0, 0))
            bot.verify_fail[member.id] = (n + 1, time.time())
            await interaction.response.send_message("答えが違います。もう一度お試しください。", ephemeral=True)
            if n + 1 >= CFG["verify_max_failures"]:
                await bot.log(interaction.guild, f"⚠️ 認証に{n + 1}回失敗: {member.mention} `{member}`")
            return

        role = discord.utils.get(interaction.guild.roles, name=CFG["verified_role"])
        if role is None:
            await interaction.response.send_message("ロール設定エラーです。運営に連絡してください。", ephemeral=True)
            return
        try:
            await member.add_roles(role, reason="認証完了")
        except discord.HTTPException:
            await interaction.response.send_message("ロールを付けられませんでした。運営に連絡してください。", ephemeral=True)
            await bot.log(interaction.guild, "❌ ロール付与に失敗。Bot のロールを「配達員」より上に移動してください")
            return
        bot.verify_fail.pop(member.id, None)
        await interaction.response.send_message("✅ 認証できました！ようこそ！", ephemeral=True)
        await bot.log(interaction.guild, f"✅ 認証: {member.mention} `{member}`")

        welcome = find_channel(interaction.guild, CFG["welcome_channel"])
        intro = find_channel(interaction.guild, CFG["intro_channel"])
        if isinstance(welcome, discord.TextChannel):
            where = intro.mention if intro else "自己紹介チャンネル"
            await welcome.send(f"🛵 {member.mention} さんが参加しました！ようこそ！\n{where} でひとこと挨拶してもらえると嬉しいです🙌")


class VerifyView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="ルールに同意して認証", style=discord.ButtonStyle.success,
                       emoji="✅", custom_id="verify:start")
    async def start(self, interaction, button):
        bot: Guard = interaction.client
        member = interaction.user
        role = discord.utils.get(interaction.guild.roles, name=CFG["verified_role"])
        if role and role in getattr(member, "roles", []):
            await interaction.response.send_message("すでに認証済みです👍", ephemeral=True)
            return
        if bot.in_lockdown():
            await interaction.response.send_message(
                "現在、荒らし対策のため認証を一時停止しています。しばらくしてからお試しください。", ephemeral=True)
            return
        age_days = (discord.utils.utcnow() - member.created_at).days
        if age_days < CFG["min_account_age_days"]:
            await interaction.response.send_message(
                f"スパム対策のため、作成から{CFG['min_account_age_days']}日未満のアカウントは認証できません。\n"
                "日数がたってからもう一度お試しいただくか、運営にDMしてください。", ephemeral=True)
            await bot.log(interaction.guild, f"⛔ 新しいアカウントの認証を拒否: {member.mention} `{member}`（作成{age_days}日）")
            return
        n, last = bot.verify_fail.get(member.id, (0, 0))
        wait = CFG["verify_cooldown_minutes"] * 60 - (time.time() - last)
        if n >= CFG["verify_max_failures"] and wait > 0:
            await interaction.response.send_message(
                f"失敗が続いたため、あと{int(wait // 60) + 1}分ほど待ってからお試しください。", ephemeral=True)
            return
        if n >= CFG["verify_max_failures"]:
            bot.verify_fail.pop(member.id, None)
        await interaction.response.send_modal(VerifyModal())


# ---------- 運営用スラッシュコマンド ----------
def register_commands(bot: Guard):
    @bot.tree.command(name="lockdown", description="認証を一時停止（荒らし対策）。0で解除")
    @app_commands.describe(minutes="停止する分数（0で解除）")
    @app_commands.default_permissions(manage_messages=True)
    async def lockdown(interaction: discord.Interaction, minutes: app_commands.Range[int, 0, 1440]):
        if minutes == 0:
            bot.lockdown_until = 0
            await interaction.response.send_message("🔓 ロックダウンを解除しました", ephemeral=True)
            await bot.log(interaction.guild, f"🔓 ロックダウン解除（{interaction.user.mention}）")
        else:
            await interaction.response.send_message(f"🔒 {minutes}分間 認証を停止します", ephemeral=True)
            await bot.set_lockdown(interaction.guild, minutes, f"{interaction.user.mention} が手動で実行")

    @bot.tree.command(name="お題", description="雑談チャンネルに今日のお題を投稿")
    @app_commands.default_permissions(manage_messages=True)
    async def topic(interaction: discord.Interaction):
        await bot.post_topic(interaction.guild)
        await interaction.response.send_message("💡 お題を投稿しました", ephemeral=True)


def main():
    token = os.environ.get("DISCORD_TOKEN")
    guild_id = os.environ.get("GUILD_ID")
    if not token or not guild_id:
        sys.exit("環境変数 DISCORD_TOKEN と GUILD_ID を設定してください（README.md 参照）")
    bot = Guard(int(guild_id))
    register_commands(bot)
    bot.run(token)


if __name__ == "__main__":
    main()
