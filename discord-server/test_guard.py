"""guard.py のテスト。 実行: python -m unittest test_guard"""

import json
import unittest
from pathlib import Path

from guard import RaidDetector, SpamDetector

CFG = json.loads((Path(__file__).parent / "config.json").read_text(encoding="utf-8"))


class SpamTest(unittest.TestCase):
    def setUp(self):
        self.d = SpamDetector(CFG)

    def check(self, text, t=0.0, ch=1, user=1, **kw):
        kw.setdefault("member_age_hours", 100)
        return self.d.check(user, ch, text, t, **kw)

    def test_normal_conversation_passes(self):
        for i, text in enumerate(["おつかれさまです！", "今日は雨で稼げた", "闇バイトの勧誘に気をつけて",
                                  "https://www.uber.com/jp/ja/ の公式発表見た？"]):
            self.assertIsNone(self.check(text, t=i * 5))

    def test_ng_word_ignores_width_and_spacing(self):
        v = self.check("ＦＲＥＥ  ＮＩＴＲＯ 配布中")
        self.assertIn("NGワード", v.reason)
        self.assertFalse(v.timeout)

    def test_flood(self):
        results = [self.check(f"連投{i}", t=i * 0.5) for i in range(CFG["flood"]["count"])]
        self.assertTrue(all(r is None for r in results[:-1]))
        self.assertTrue(results[-1].timeout)

    def test_same_message_many_channels(self):
        msg = "お得な情報はこちらから見てね"
        r = [self.check(msg, t=i * 10, ch=i) for i in range(3)]
        self.assertIsNone(r[0])
        self.assertIn("チャンネル", r[2].reason)

    def test_mentions_and_everyone(self):
        self.assertTrue(self.check("hi", mentions=CFG["max_mentions"]).timeout)
        self.assertTrue(self.check("hi", mentions_everyone=True).timeout)

    def test_invite_and_new_member_links(self):
        self.assertIn("招待", self.check("discord.gg/abcdef 来てね").reason)
        self.assertIn("参加直後", self.check("https://example.com", member_age_hours=1).reason)

    def test_users_are_independent(self):
        for i in range(CFG["flood"]["count"] - 1):
            self.check(f"a{i}", t=i, user=1)
        self.assertIsNone(self.check("b", t=3, user=2))


class RaidTest(unittest.TestCase):
    def test_raid(self):
        r = RaidDetector(joins=3, seconds=10)
        self.assertFalse(r.joined(0))
        self.assertFalse(r.joined(1))
        self.assertTrue(r.joined(2))
        self.assertFalse(RaidDetector(3, 10).joined(100))


if __name__ == "__main__":
    unittest.main()
