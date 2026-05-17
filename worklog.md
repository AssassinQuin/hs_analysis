---
Task ID: 1
Agent: main
Task: 克隆仓库并识别补丁式修复

Work Log:
- 克隆了 https://github.com/AssassinQuin/hs_analysis.git 到 /home/z/my-project/hs_analysis
- 分析了 git diff HEAD~15 HEAD，识别出 7 大补丁式修复 + 3 额外问题

Stage Summary:
- 识别出7个补丁式修复模式和3个额外问题
- 按优先级排列了重构方案

---
Task ID: 2-9
Agent: main
Task: 执行 7+3 项重构

Work Log:
- Patch #1: 提取 EntityFields dataclass + _extract_entity_fields() 统一函数，消除3处重复字段解析代码
- Patch #3: 用 hs_enums 的 ZONE_NAME_MAP/CARDTYPE_NAME_MAP 替代硬编码 _ZONE_MAP/_CARD_TYPE_MAP，消除魔法数字
- Patch #7: 合并 _get_card_db(strict=False) 和 _ensure_card_db()，后者委托给前者(strict=True)
- Patch #2: 合并 _try_enrich_player_info 和 _enrich_player_info 为 _enrich_player_info_core(re_bridge, re_emit)
  - 提取 _refresh_opp_counts(opp_player) 消除4处重复计数代码
  - 提取 _refresh_opp_counts_from_exporter() 消除3处重复 exporter 获取代码
  - 提取 _emit_game_started() 消除3处重复信号构建代码
  - 提取 _handle_controller_correction() 消除2处重复 controller 修正代码
  - 保留 _enrich_player_info() 作为兼容别名
- Patch #4: 提取 _bridge_single_entity() 统一桥接逻辑，_bridge_entities_to_global_tracker 和 _bridge_new_entities 都委托给它
- Patch #5: 用 GameLifecycle 枚举(IDLE/STARTING/READY/ENDED) 替代 _game_started_emitted + _game_started_with_classes 标志对
- Patch #6: 将 _ROW_H 全局变量改为 _ROW_H_DEFAULT 常量 + OverlayWindow._row_height 实例属性
- 额外: class_to_cn 导入统一到模块顶部，get_opp_hand_count() 委托给 count_opp_hand()
- 提取 _safe_int() 统一安全整数转换

Stage Summary:
- 修改文件: tracker/log_monitor.py, analysis/watcher/global_tracker.py, tracker/overlay_ui.py
- 语法检查通过: 所有3个文件
- 删除约427行重复代码，新增约511行(含新增结构化方法)
- 核心改善: 消除了重复逻辑、硬编码魔法数字、全局变量修改、标志位对
