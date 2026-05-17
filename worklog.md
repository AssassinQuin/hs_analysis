# Work Log

---
Task ID: 1
Agent: main
Task: 修复对手打出手牌后卡组概率不更新 + 新增卡组不同步 + 衍生牌误入卡组

Work Log:
- 分析用户反馈：对手出牌后卡组概率/卡组列表不更新，后续新增卡组也不同步
- 诊断根因1：`_check_deck_codes_update` 只更新 DeckProvider，不重建贝叶斯模型
- 诊断根因2：`_predict_multi_deck` 的 `played_count` 统计所有打出牌，衍生牌误减 remaining
- 修复1：连接 DeckHotReloader 到 `_check_deck_codes_update`，热更新时重建 DB + 刷新贝叶斯模型
- 修复2：`played_count` 只统计 `source=='deck'` 的牌，跳过 `source=='generated'`
- 修复自检：发现 `generated_set` card_id 级排除会误伤同 card_id 牌库来源记录，改用 source 字段判断
- 新增 7 个回归测试
- 829 测试全通过
- commit: c8308b8

Stage Summary:
- tracker/app.py: `_check_deck_codes_update` 重写，连接 DeckHotReloader
- tracker/hand_predictor.py: `_predict_multi_deck` 衍生牌排除逻辑
- tests/watcher/test_watcher.py: 新增 TestGeneratedCardDeckExclusion 测试类（7个测试）
