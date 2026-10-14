"""スパム・荒らし判定ロジック（Discord に依存しない部分）。

bot.py から使う。単体でテストできるよう、時刻は引数で受け取る。
"""

import re
import unicodedata
from collections import defaultdict, deque, namedtuple

INVITE_RE = re.compile(r"(discord\.gg|discord(app)?\.com/invite)/\S+", re.I)
URL_RE = re.compile(r"https?://\S+", re.I)

# reason: 理由 / timeout: True ならタイムアウトまで行う（False は削除と注意のみ）
Violation = namedtuple("Violation", "reason timeout")


def normalize(text):
    """全角/半角・大文字小文字・空白の違いを吸収して比較しやすくする。"""
    text = unicodedata.normalize("NFKC", text).lower()
    return re.sub(r"\s+", "", text)


class SpamDetector:
    """1ユーザーごとの直近の投稿を覚えておき、スパムっぽい動きを判定する。"""

    def __init__(self, cfg):
        self.cfg = cfg
        self.ng_words = [normalize(w) for w in cfg.get("ng_words", [])]
        self.recent = defaultdict(deque)  # user_id -> deque[(time, channel_id, content)]

    def check(self, user_id, channel_id, content, now, *, mentions=0,
              mentions_everyone=False, member_age_hours=None):
        """違反があれば Violation、なければ None を返す。"""
        cfg = self.cfg
        norm = normalize(content)

        # 直近の投稿履歴を更新
        keep = max(cfg["flood"]["seconds"], cfg["duplicate"]["seconds"])
        q = self.recent[user_id]
        q.append((now, channel_id, norm))
        while q and now - q[0][0] > keep:
            q.popleft()

        for w in self.ng_words:
            if w and w in norm:
                # 「闇バイトに注意」のような注意喚起もあり得るので、削除と注意だけにする
                return Violation(f"NGワード「{w}」", False)

        if mentions_everyone:
            return Violation("@everyone / @here の使用", True)
        if mentions >= cfg["max_mentions"]:
            return Violation(f"大量メンション（{mentions}人）", True)

        if cfg.get("block_invites") and INVITE_RE.search(content):
            return Violation("他サーバーの招待リンク", False)

        if (member_age_hours is not None
                and member_age_hours < cfg["new_member_link_block_hours"]
                and URL_RE.search(content)):
            return Violation("参加直後のリンク投稿", False)

        fl = cfg["flood"]
        if sum(1 for t, _, _ in q if now - t <= fl["seconds"]) >= fl["count"]:
            return Violation(f"連投（{fl['seconds']}秒に{fl['count']}回以上）", True)

        dup = cfg["duplicate"]
        if len(norm) >= 5:
            chans = {c for t, c, m in q if m == norm and now - t <= dup["seconds"]}
            if len(chans) >= dup["channels"]:
                return Violation(f"同じ内容を{len(chans)}チャンネルに投稿", True)

        return None

    def forget(self, user_id):
        self.recent.pop(user_id, None)


class RaidDetector:
    """短時間に大量の参加があったら True を返す。"""

    def __init__(self, joins, seconds):
        self.joins, self.seconds = joins, seconds
        self.times = deque()

    def joined(self, now):
        self.times.append(now)
        while self.times and now - self.times[0] > self.seconds:
            self.times.popleft()
        return len(self.times) >= self.joins
