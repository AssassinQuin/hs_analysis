# Standard Card Effect Analysis Report
Total cards: 984
Cards with matched effects: 914
Uncategorized cards: 70

## Group 1: Random Effects (Previously Defined)
### discover: 78 cards
  - 冬泉雏龙 (1mana MAGE) | 战吼：发现一张任意职业的法力值消耗为（1）的法术牌。
  - 指挥官迦顿 (7mana WARRIOR) | 战吼：你在每回合开始时的抽牌改为从你的牌库中发现一张牌，其法力值消耗减少（3）点，并摧毁未选
的牌。
  - 蔽影密探 (2mana NEUTRAL) | 战吼：发现一张你的职业的法术牌。（每回合切换职业！）
  - 冰川急冻 (6mana SHAMAN) | 发现一张法力值消耗为（8）的随从牌。召唤并冻结该随从。
  - 符文宝珠 (2mana MAGE) | 造成$2点伤害。发现一张法术牌。
  ... and 73 more

### dark_gift: 20 cards
  - 迅猛龙先锋 (3mana NEUTRAL) | 回溯。战吼：发现一张具有黑暗之赐的野兽牌。延系：其法力值消耗减少（1）点。
  - 狡诈拷问者 (4mana NEUTRAL) | 战吼：
发现一张具有黑暗之赐的传说随从牌。
  - 疯狂生物 (2mana NEUTRAL) | 战吼：发现一张具有黑暗之赐的法力值消耗为（3）的随从牌。
  - 黑暗的龙骑士 (1mana WARRIOR) | 战吼：如果你的手牌中有龙牌，发现一张具有黑暗之赐的龙牌。
  - 瓦洛，污邪古树 (7mana WARLOCK) | 当本牌在你的手牌或牌库中时，会获得你的随从获得的每项黑暗之赐的复制。
  ... and 15 more

### random_summon: 53 cards
  - 塔兰吉的奋战 (5mana DEATHKNIGHT) | 使你的随从获得
“亡语：随机召唤一个法力值消耗为（4）的随从。”
  - 助祭耗材 (2mana WARLOCK) | 当你使用或弃掉本牌时，随机召唤两个法力值消耗为（1）的随从。
  - 演武仪式 (4mana SHAMAN) | 随机召唤法力值消耗为（3），（2）和（1）的随从各一个。过载：（1）
  - 毁灭之焰 (5mana WARRIOR) | 在本随从受到伤害并存活下来后，召唤一个毁灭之焰。亡语：随机对一个敌人造成2点伤害。
  - 洛戈什的奋战 (5mana WARRIOR) | 使一个随从获得
“亡语：从你的手牌中随机召唤一个
随从。”
  ... and 48 more

### random_damage: 36 cards
  - 激寒急流 (1mana MAGE) | 造成$2点伤害。随机对一个敌方随从造成$1点伤害。
  - 拉法姆的奋战 (3mana WARLOCK) | 随机对两个敌方随从造成$2点伤害。（每回合都会升级！）
  - 喷发火山 (3mana WARRIOR) | 造成3点伤害，随机分配到所有敌人身上。如果你在本回合中使用过火焰法术牌，再造成3点。
  - 毁灭之焰 (5mana WARRIOR) | 在本随从受到伤害并存活下来后，召唤一个毁灭之焰。亡语：随机对一个敌人造成2点伤害。
  - 辛达苟萨的胜利 (5mana MAGE) | 对一个随从造成$8点伤害。使你手牌中一张随机牌的法力值消耗减少，减少的量等于超过目标生命值的伤害。
  ... and 31 more

### random_generate: 28 cards
  - 命令之爪 (2mana DEATHKNIGHT) | 在你的英雄攻击后，随机使一个友方随从获得+2攻击力。
  - 空中悍匪 (1mana WARRIOR) | 战吼：随机将一张海盗牌置入你的手牌。
  - 光明之翼 (2mana NEUTRAL) | 战吼：随机将一张传说随从牌置入你的
手牌。
  - 女巫的学徒 (0mana SHAMAN) | 嘲讽，战吼：随机将一张萨满祭司法术牌置入你的手牌。
  - 齿轮光锤 (3mana PALADIN) | 战吼：随机使一个友方随从获得圣盾和嘲讽。
  ... and 23 more

### random_buff: 22 cards
  - 艾萨拉的胜利 (1mana DRUID) | 随机将5张法力值消耗大于或等于（8）点的随从牌洗入你的牌库，其属性值翻倍。
  - 命令之爪 (2mana DEATHKNIGHT) | 在你的英雄攻击后，随机使一个友方随从获得+2攻击力。
  - 辛达苟萨的胜利 (5mana MAGE) | 对一个随从造成$8点伤害。使你手牌中一张随机牌的法力值消耗减少，减少的量等于超过目标生命值的伤害。
  - 暗影升腾者 (2mana PRIEST) | 在你的回合结束时，随机使另一个友方随从获得+1/+1。
  - 展馆茶杯 (3mana NEUTRAL) | 战吼：随机使三个不同类型的友方随从获得+1/+1。
  ... and 17 more

## Group 2: Player Choice Effects (NOT random, but variable value)
These cards have VARIABLE value depending on player choice - NOT modeled by random EV.

### choose_one: 23 cards
  - 活体根须 (1mana DRUID) | 抉择：造成$2点伤害；或者召唤两个1/1的树苗。
  - 愤怒 (2mana DRUID) | 抉择：
对一个随从造成$3点伤害；或者造成$1点伤害并抽一张牌。
  - 野性之力 (2mana DRUID) | 抉择：使你的所有随从获得+1/+1；或者召唤一只3/2的
猎豹。
  - 乌鸦神像 (1mana DRUID) | 抉择：
发现一张随从牌；或者发现一张法术牌。
  - 范达尔·鹿盔 (4mana DRUID) | 你的抉择牌和英雄技能可以同时拥有两种效果。
  - 野性之怒 (3mana DRUID) | 抉择：使你的英雄在本回合中获得+4攻击力；或者获得8点护甲值。
  - 暴烈枭兽 (5mana DRUID) | 抉择：为你的英雄恢复#8点生命值；或者造成4点伤害。
  - 划水好友 (5mana DRUID) | 抉择：召唤一只6/6并具有嘲讽的虎鲸；或者六只1/1并具有突袭的海獭。
  ... and 15 more

### adapt: 0 cards

## Group 3: Conditional Effects (value depends on game state)
These cards have value that CHANGES based on game conditions - need state-aware modeling.

### conditional_if: 104 cards
  - 晦鳞巢母 (3mana NEUTRAL) | 战吼：如果你的手牌中有龙牌，复原两个法力水晶。
  - 费伍德树人 (2mana DRUID) | 战吼：获得一个临时的法力水晶。如果你在本牌在你手中时消耗过4点法力值，该法力水晶变为永久获得。（还剩{0}点！）@战吼：获得一个临时的法力水晶。如果你在本牌在你手中时消耗过4点法力值，该法力水晶变为永久获得。（已经就绪！）@战吼：获得一个临
  - 护巢龙 (4mana DRUID) | 战吼：获取两张3/3并具有嘲讽的雏龙。如果你在本牌在你手中时消耗过8点法力值，召唤这两条雏龙。（还剩{0}点！）@战吼：获取两张3/3并具有嘲讽的雏龙。如果你在本牌在你手中时消耗过8点法力值，召唤这两条雏龙。（已经就绪！）@战吼：获取两张3
  - 梦境之龙麦琳瑟拉 (8mana DRUID) | 战吼：用随机的龙牌填满你的手牌。如果你在本牌在你手中时消耗过25点法力值，这些龙牌的法力值消耗为（1）点。（还剩{0}点！）@战吼：用随机的龙牌填满你的手牌。如果你在本牌在你手中时消耗过25点法力值，这些龙牌的法力值消耗为（1）点。（已经就
  - 威拉诺兹 (6mana NEUTRAL) | 战吼：如果你的套牌中随从牌的法力值消耗之和为100，使你牌库中的随从获得总计100点的属性值。
  - 净化吐息 (2mana PRIEST) | 对一个随从造成$5点伤害。如果该随从死亡，则为敌方英雄恢复#5点生命值。
  - 盛怒主母 (4mana PRIEST) | 在你的回合结束时，如果本随从具有所有生命值，获得+3
生命值。
  - 麦迪文的胜利 (5mana PRIEST) | 对所有随从造成$4点伤害。如果你控制着传说牌，本牌的法力值消耗为（1）点。
  ... and 96 more

### conditional_when: 50 cards
  - 炫晶小熊 (1mana DRUID) | 每当你消耗掉最后一个法力水晶，获得+1/+1。
  - 复活的奥妮克希亚 (9mana DEATHKNIGHT) | 巨型+2
当你的英雄在你的回合即将失去生命值时，改为获得等量的生命值上限。
  - 阿莱克丝塔萨，生命守护者 (7mana PRIEST) | 战吼：将你的英雄剩余生命值变为15。当你恢复所有生命值时，对敌方英雄造成15点伤害。
  - 多彩龙巢母 (4mana DEATHKNIGHT) | 突袭。每当本随从
攻击时，复原等同于本随从攻击力的法力水晶。
  - 助祭耗材 (2mana WARLOCK) | 当你使用或弃掉本牌时，随机召唤两个法力值消耗为（1）的随从。
  - 熔喉 (7mana HUNTER) | 巨型+99
当场上有空位时，召唤剩余的肢节。99巨型+99
当场上有空位时，召唤剩余的肢节。（还剩{0}个！）
  - 石爪打击者 (3mana HUNTER) | 嘲讽。（当本牌在你手中时，使用一张龙牌即可将本牌变为6/6的龙！）
  - 乌鳞斥候 (6mana HUNTER) | 战吼：造成等同于本随从攻击力的伤害。（当本牌在你手中时，使用一张龙牌即可将本牌变为8/8的龙！）
  ... and 42 more

### conditional_per: 10 cards
  - 布洛克斯加的奋战 (2mana DEMONHUNTER) | 对所有随从造成$1点伤害。每有一个随从死亡，抽一
张牌。
  - 屠灭 (6mana WARRIOR) | 对所有随从造成$1点伤害（战场上每有一个随从都会提高）。
  - 吞噬 (4mana DEATHKNIGHT) | 随机对两个敌方随从造成$3点伤害。每有一个随从死亡，抽一张牌。
  - 暮光幼龙 (4mana NEUTRAL) | 战吼：
你每有一张手牌，便获得+1生命值。
  - 女巫森林灰熊 (5mana NEUTRAL) | 嘲讽。战吼：
你的对手每有一张手牌，本随从便失去1点生命值。
  - 星涌术 (3mana MAGE) | 对一个随从造成$1点伤害。（每有一个在本局对战中死亡的友方随从都会提升。）
  - 愤怒残魂 (7mana ) | 在本回合中每有一个随从死亡，本牌的法力值消耗便减少（1）点。战吼：抽两张牌。
  - 破碎现实 (4mana DRUID) | 召唤两个2/2的树人。在本局对战中，每有一个友方树人死亡，使这两个树人获得+1/+1。0（已
死亡0个）
  ... and 2 more

### conditional_mana: 209 cards
  - 炫晶小熊 (1mana DRUID) | 每当你消耗掉最后一个法力水晶，获得+1/+1。
  - 费伍德树人 (2mana DRUID) | 战吼：获得一个临时的法力水晶。如果你在本牌在你手中时消耗过4点法力值，该法力水晶变为永久获得。（还剩{0}点！）@战吼：获得一个临时的法力水晶。如果你在本牌在你手中时消耗过4点法力值，该法力水晶变为永久获得。（已经就绪！）@战吼：获得一个临
  - 护巢龙 (4mana DRUID) | 战吼：获取两张3/3并具有嘲讽的雏龙。如果你在本牌在你手中时消耗过8点法力值，召唤这两条雏龙。（还剩{0}点！）@战吼：获取两张3/3并具有嘲讽的雏龙。如果你在本牌在你手中时消耗过8点法力值，召唤这两条雏龙。（已经就绪！）@战吼：获取两张3
  - 苔缚术 (2mana DRUID) | 召唤两个1/2的魔像。消耗你的所有法力值，每消耗一点法力值，使其获得+1/+1。
  - 艾萨拉的胜利 (1mana DRUID) | 随机将5张法力值消耗大于或等于（8）点的随从牌洗入你的牌库，其属性值翻倍。
  - 梦境之龙麦琳瑟拉 (8mana DRUID) | 战吼：用随机的龙牌填满你的手牌。如果你在本牌在你手中时消耗过25点法力值，这些龙牌的法力值消耗为（1）点。（还剩{0}点！）@战吼：用随机的龙牌填满你的手牌。如果你在本牌在你手中时消耗过25点法力值，这些龙牌的法力值消耗为（1）点。（已经就
  - 奥拉基尔，风暴之主 (8mana SHAMAN) | 巨型+2
突袭。风怒。战吼：获取2张法力值消耗等同于本随从攻击力的随从牌，这两张牌的法力值消耗为（1）点。
  - 速逝鱼人 (2mana NEUTRAL) | 战吼：你的下一张法力值消耗小于或等于（3）点的鱼人牌会消耗生命值，而非法力值。
  ... and 201 more

## Group 4: Cumulative/Progressive Effects (build up over turns)
These cards have escalating value - need time-discounted EV modeling.

### quest: 14 cards
  - 征战时光之末 (1mana ) | 任务：填满你的手牌，然后清空。奖励：提克和托克。
  - 群山之灵 (1mana SHAMAN) | 任务：使用6个不同类型的随从牌。奖励：阿沙隆。
  - 治愈荒野 (1mana DRUID) | 任务：填满你的面板，总计3回合。奖励：永茂之花。
  - 潜入葛拉卡 (1mana PALADIN) | 可重复任务：召唤6个鱼人。奖励：你召唤的鱼人获得+1/+1。
  - 恐怖再起 (1mana DEATHKNIGHT) | 任务：消耗15份残骸。奖励：泰拉克斯，魔骸暴龙。
  - 逃离邪能地窟 (1mana WARLOCK) | 任务：使用6张临时牌。奖励：邪能地窟裂隙。
  - 禁忌序列 (1mana MAGE) | 任务：发现7张牌。奖励：源生之石。
  - 暗中设伏 (1mana ROGUE) | 任务：将卡牌洗入你的牌库，总计5次。奖励：暮影
大师。
  ... and 6 more

## Group 5: Transform/Morph Effects (become something else)
These cards change identity - the 'target' card is unknown until it transforms.

### transform: 12 cards
  - 无面复制者 (3mana NEUTRAL) | 扰魔。亡语：将消灭本随从的随从变形成为无面复制者。
  - 古神的眼线 (1mana ROGUE) | 战吼：选择你手牌中的一张牌，将其变形成为幸运币。
  - 升腾 (4mana SHAMAN) | 将所有友方随从变形成为法力值消耗增加（1）点的随从。当这些随从死亡时，召唤原随从。
  - 吉恩，咒厄国王 (4mana NEUTRAL) | 当本牌在你手牌中时，如果你其他手牌的法力值消耗均为偶数或奇数，变形成为6/5的狼人国王。
  - 妖术 (3mana SHAMAN) | 使一个随从变形成为一只0/1并具有嘲讽的青蛙。
  - 殒命暗影 (0mana ROGUE) | 每当你施放一个法术，变形成为该法术的复制。
  - 祭礼之舞 (5mana MAGE) | 选择一个随从，将其变形成为你另选的一个不同的随从。
  - 阿莱纳希 (5mana DEMONHUNTER) | 战吼：随机使你手牌中的所有随从牌变形成为恶魔牌。（保留其原始属性值和法力值消耗。）
  ... and 4 more

### corrupt: 1 cards
  - 莎拉达希尔 (8mana NEUTRAL) | 获取全部5张梦境牌。如果你在本牌在你手中时使用过法力值消耗更高的牌，腐蚀这些梦境牌！

## Group 6: Positional/Aura Effects (board-position dependent)
These cards have value that depends on board state - need board-aware modeling.

### adjacent: 7 cards
  - 黏弹爆破手 (4mana NEUTRAL) | 战吼：使你的对手获得一张法力值消耗为（2）的黏弹。黏弹相邻的卡牌法力值消耗增加（1）点。
  - 雷加尔·大地之怒 (5mana SHAMAN) | 在本随从或相邻的随从攻击后，获取一张闪电箭。
  - 日怒保卫者 (2mana NEUTRAL) | 战吼：使相邻的随从获得嘲讽。
  - 恐狼前锋 (2mana NEUTRAL) | 相邻的随从拥有+1攻击力。
  - 止水湖蛇颈龙 (5mana NEUTRAL) | 同时对其攻击目标相邻的随从造成伤害。
  - 灵敏的厨师 (3mana DEMONHUNTER) | 战吼：
使相邻手牌的法力值消耗减少（1）点。
  - 苦涩结局 (5mana ) | 冻结一个随从及其相邻随从，并消灭其中受伤的随从。

### aura: 21 cards
  - 苔缚术 (2mana DRUID) | 召唤两个1/2的魔像。消耗你的所有法力值，每消耗一点法力值，使其获得+1/+1。
  - 盛怒主母 (4mana PRIEST) | 在你的回合结束时，如果本随从具有所有生命值，获得+3
生命值。
  - 大法师卡雷 (4mana MAGE) | 战吼：使你手牌和牌库中所有法术牌获得法术伤害+1。
  - 灼热裂隙 (2mana WARRIOR) | 对所有随从造成$1点伤害。在本回合中，使你的英雄获得+3攻击力。
  - 格尔宾的胜利 (1mana PALADIN) | 随机获取一张圣骑士光环牌，其持续时间增加一回合。
  - 污手街供货商 (2mana PALADIN) | 战吼：使你手牌中的所有随从牌获得+1/+1。
  - 野性之力 (2mana DRUID) | 抉择：使你的所有随从获得+1/+1；或者召唤一只3/2的
猎豹。
  - 活力分流 (2mana DEATHKNIGHT) | 使你手牌中的所有随从牌获得+1/+1。消耗2份残骸，再获得+1/+1。
  ... and 13 more

## Group 7: Turn Timing Effects (trigger at specific times)

### start_of_turn: 17 cards
  - 暮光龙卵 (1mana NEUTRAL) | 亡语：召唤一条2/2的雏龙。（在你的回合开始时获得+1/+1！）
  - 海洋咒符 (1mana DEMONHUNTER) | 在你的下个回合开始时，召唤一个3/3并具有嘲讽的纳迦。
  - 托维尔雕琢师 (3mana HUNTER) | 战吼：选择你手牌中的一张牌，在你的回合开始时，其法力值消耗减少（1）点。
  - 指挥官迦顿 (7mana WARRIOR) | 战吼：你在每回合开始时的抽牌改为从你的牌库中发现一张牌，其法力值消耗减少（3）点，并摧毁未选
的牌。
  - 微型战斗机甲 (2mana NEUTRAL) | 在每个回合开始时，获得+1攻击力。
  ... and 12 more

### end_of_turn: 53 cards
  - 彩翼灵龙 (5mana DRUID) | 扰魔。在你的回合结束时，使你的其他随从获得+1/+1。
  - 拉格纳罗斯，绝世烈火 (8mana WARRIOR) | 巨型+2
在你的回合结束时，触发你的随从的
亡语。
  - 盛怒主母 (4mana PRIEST) | 在你的回合结束时，如果本随从具有所有生命值，获得+3
生命值。
  - 灵感之槌 (2mana PALADIN) | 亡语：随机触发一个友方随从的回合结束效果。
  - 诺兹多姆，青铜守护巨龙 (5mana PALADIN) | 在你的回合结束时，使你的随从获得圣盾，已有圣盾的随从改为获得+3/+3。
  ... and 48 more

### end_of_your_turn: 45 cards
  - 彩翼灵龙 (5mana DRUID) | 扰魔。在你的回合结束时，使你的其他随从获得+1/+1。
  - 拉格纳罗斯，绝世烈火 (8mana WARRIOR) | 巨型+2
在你的回合结束时，触发你的随从的
亡语。
  - 盛怒主母 (4mana PRIEST) | 在你的回合结束时，如果本随从具有所有生命值，获得+3
生命值。
  - 诺兹多姆，青铜守护巨龙 (5mana PALADIN) | 在你的回合结束时，使你的随从获得圣盾，已有圣盾的随从改为获得+3/+3。
  - 矛心哨卫 (4mana PALADIN) | 在你的回合结束时，随机获取一张神圣法术牌，其法力值消耗减少（3）点。
  ... and 40 more

## Group 8: Special Mechanics (unique card types)

### location: 14 cards
  - 红玉圣殿 (1mana PRIEST) | 在本回合中，你的下一次治疗效果转而造成等量的伤害。
  - 守护巨龙之厅 (2mana PALADIN) | 选择你手牌中的一张随从牌，使其获得+2/+2。
  - 暮光神坛 (4mana WARLOCK) | 兆示{0}。抽一张牌。
  - 奈瑟匹拉，蒙难古灵 (3mana DEMONHUNTER) | 造成1点伤害。在你施放一个邪能法术后，重新开启。亡语：召唤奈瑟匹拉，脱困古灵。
  - 喷发火山 (3mana WARRIOR) | 造成3点伤害，随机分配到所有敌人身上。如果你在本回合中使用过火焰法术牌，再造成3点。
  - 赤红深渊 (1mana WARRIOR) | 对一个随从造成1点伤害，并使其获得+2攻击力。
  - 腐蚀之巢 (2mana WARRIOR) | 选择一条友方的龙。召唤一枚0/2的可以孵化成所选龙的复制的龙蛋。
  - 禁忌神龛 (1mana MAGE) | 消耗你所有的法力值，随机施放一个法力值消耗相同的法术。
  ... and 6 more

### colossal: 11 cards
  - 柳牙 (6mana DRUID) | 巨型+4
在柳牙的腿获得属性值后，本随从也会
获得。
  - 拉格纳罗斯，绝世烈火 (8mana WARRIOR) | 巨型+2
在你的回合结束时，触发你的随从的
亡语。
  - 艾萨拉，海洋之主 (8mana DEMONHUNTER) | 巨型+2
你的英雄拥有风怒。
  - 奥拉基尔，风暴之主 (8mana SHAMAN) | 巨型+2
突袭。风怒。战吼：获取2张法力值消耗等同于本随从攻击力的随从牌，这两张牌的法力值消耗为（1）点。
  - 希奈丝特拉 (6mana ROGUE) | 巨型+2
你的其他职业的法术会施放两次。
  - 复活的奥妮克希亚 (9mana DEATHKNIGHT) | 巨型+2
当你的英雄在你的回合即将失去生命值时，改为获得等量的生命值上限。
  - 黑血 (7mana PRIEST) | 巨型+3
在你为一个角色恢复生命值后，随机攻击一个敌方随从。
  - 克洛玛图斯 (8mana PALADIN) | 巨型+4
嘲讽。吸血。扰魔
圣盾
  ... and 3 more

### secret: 11 cards
  - 绿洲盟军 (3mana MAGE) | 奥秘：
当一个友方随从受到攻击时，召唤一个3/6的水元素。
  - 法术反制 (3mana MAGE) | 奥秘：当你的对手施放一个法术时，反制该法术。
  - 寒冰护体 (3mana MAGE) | 奥秘：当你的英雄受到攻击时，获得8点护甲值。
  - 爆炸陷阱 (2mana HUNTER) | 奥秘：当你的英雄受到攻击，对所有敌人造成$2点伤害。
  - 冰冻陷阱 (2mana HUNTER) | 奥秘：当一个敌方随从攻击时，将其移回拥有者的手牌，并且法力值消耗增加（2）点。
  - 捕鼠陷阱 (2mana HUNTER) | 奥秘：当你的对手在一回合中使用三张牌后，召唤一只6/6的老鼠。
  - 爆炸符文 (3mana MAGE) | 奥秘：在你的对手使用一张随从牌后，对该随从造成$6点伤害，超过其生命值的伤害将由对方英雄
承受。
  - 压感陷阱 (2mana HUNTER) | 奥秘：在你的对手施放一个法术后，随机消灭一个敌方
随从。
  ... and 3 more

## Group 9: Keyword Mechanics (trigger-based)

### battlecry: 322 cards
  - 晦鳞巢母 (3mana NEUTRAL) | 战吼：如果你的手牌中有龙牌，复原两个法力水晶。
  - 费伍德树人 (2mana DRUID) | 战吼：获得一个临时的法力水晶。如果你在本牌在你手中时消耗过4点法力值，该法力水晶变为永久获得。（还剩{0}点！）@战吼：获得一个临时的法力水晶。如果你在本牌在你手中时消耗过4点法力值，该法力水晶变为永久获得。（已经就绪！）@战吼：获得一个临
  - 护巢龙 (4mana DRUID) | 战吼：获取两张3/3并具有嘲讽的雏龙。如果你在本牌在你手中时消耗过8点法力值，召唤这两条雏龙。（还剩{0}点！）@战吼：获取两张3/3并具有嘲讽的雏龙。如果你在本牌在你手中时消耗过8点法力值，召唤这两条雏龙。（已经就绪！）@战吼：获取两张3
  ... and 319 more

### deathrattle: 134 cards
  - 荒林怪圈 (4mana DRUID) | 裂变
召唤两个2/2的树人。使你的随从获得“亡语：召唤一个2/2的树人。”122972召唤两个2/2的树人。使你的随从获得“亡语：召唤一个2/2的树人。”
  - 拉格纳罗斯，绝世烈火 (8mana WARRIOR) | 巨型+2
在你的回合结束时，触发你的随从的
亡语。
  - 癫狂的追随者 (3mana ROGUE) | 潜行。亡语：兆示{0}。
  ... and 131 more

### combo: 14 cards
  - 暮光祭礼 (2mana ROGUE) | 兆示{0}。连击：造成$3点伤害。
  - 疯狂的药剂师 (5mana ROGUE) | 连击：使一个友方随从获得+4攻击力。
  - 狐人老千 (2mana ROGUE) | 战吼：
在本回合中，你的下一张连击牌法力值消耗减少（2）点。
  ... and 11 more

### outcast: 8 cards
  - 涣漫洪流 (5mana DEMONHUNTER) | 对你的对手最左边和最右边的随从造成$5点伤害。流放：重复一次。
  - 火色魔印奔行者 (1mana DEMONHUNTER) | 流放：抽一张牌。
  - 幽灵视觉 (2mana DEMONHUNTER) | 抽一张牌。流放：再抽一张。
  ... and 5 more

## Group 10: Deck/Hand Manipulation

### draw: 102 cards
  - 愈合 (1mana PRIEST) | 为一个随从恢复所有生命值。抽一张牌。
  - 暮光神坛 (4mana WARLOCK) | 兆示{0}。抽一张牌。
  - 布洛克斯加的奋战 (2mana DEMONHUNTER) | 对所有随从造成$1点伤害。每有一个随从死亡，抽一
张牌。
  ... and 99 more

### discard: 18 cards
  - 魔眼秘术师 (3mana WARLOCK) | 嘲讽。战吼：选择你手牌中的一张牌
并弃掉。
  - 地狱公爵 (4mana WARLOCK) | 突袭。在本局对战中，你每弃掉一张牌，便拥有+2/+2。
  - 马洛拉克 (7mana WARLOCK) | 在你弃掉一张随从牌后，召唤一个该随从的复制。
  ... and 15 more

### shuffle: 17 cards
  - 艾萨拉的胜利 (1mana DRUID) | 随机将5张法力值消耗大于或等于（8）点的随从牌洗入你的牌库，其属性值翻倍。
  - 避难的幸存者 (2mana NEUTRAL) | 战吼：选择一张你的手牌洗入你的牌库。抽一张牌。
  - 活泼的松鼠 (1mana DRUID) | 亡语：将四张橡果洗入你的牌库。当抽到橡果时，召唤一只2/1的松鼠。
  ... and 14 more

### tradeable_kw: 8 cards
  - 迦罗娜的奋战 (2mana ROGUE) | 可交易
消灭一个传说
随从。
  - 黑骑士 (4mana NEUTRAL) | 可交易
战吼：消灭一个具有嘲讽的敌方随从。
  - 王牌猎人 (4mana NEUTRAL) | 可交易
战吼：消灭一个攻击力大于或等于7的随从。
  ... and 5 more

## Uncategorized Cards (no matched patterns)
Total: 70
  - 试验演示 (6mana SPELL DEATHKNIGHT) | 兆示{0}。对所有敌方随从造成$4点伤害。
  - 能量窃取 (3mana SPELL ROGUE) | 随机获取一张另一职业的已拼合的裂变牌。
  - 眩晕 (3mana SPELL ROGUE) | 将一个敌方随从移回其拥有者的手牌，并使其无法在下回合中使用。
  - 祈雨元素 (2mana MINION MAGE) | 每回合中，你第一次用法术造成伤害时，获得+2攻击力。
  - 奥术涌流 (4mana SPELL MAGE) | 裂变
造成$4点伤害。对所有敌人造成$2点伤害。123743造成$4点伤害。对所有敌人造成$2点伤害。
  - 怪异触手 (6mana SPELL WARLOCK) | 对所有随从造成$3点伤害。重复
此效果，每次伤害减少1点。
  - 进击的募援官 (1mana MINION HUNTER) | 扰魔
  - 图腾魔像 (2mana MINION SHAMAN) | 过载：（1）
  - 灵魂炸弹 (1mana SPELL WARLOCK) | 对一个随从和你的英雄各造成$4点伤害。
  - 战斗邪犬 (1mana MINION DEMONHUNTER) | 在你的英雄攻击后，获得+1攻击力。
  - 诺格弗格市长 (9mana MINION NEUTRAL) | 所有角色都会随机选择目标。
  - 神圣惩击 (1mana SPELL PRIEST) | 对一个随从造成$3点伤害。
  - 火球术 (4mana SPELL MAGE) | 造成$6点伤害。
  - 烈焰风暴 (7mana SPELL MAGE) | 对所有敌方随从造成$5点伤害。
  - 地狱烈焰 (3mana SPELL WARLOCK) | 对所有角色造成$3点伤害。
  - 背刺 (0mana SPELL ROGUE) | 对一个未受伤的随从造成$2点
伤害。
  - 刺杀 (4mana SPELL ROGUE) | 消灭一个敌方随从。
  - 奉献 (3mana SPELL PALADIN) | 对所有敌人造成$2点伤害。
  - 斩杀 (1mana SPELL WARRIOR) | 消灭一个受伤的敌方随从。
  - 团队领袖 (3mana MINION NEUTRAL) | 你的其他随从拥有+1攻击力。
  ... and 50 more

## Summary Statistics

- battlecry: 322 cards
- conditional_mana: 209 cards
- deathrattle: 134 cards
- taunt: 114 cards
- conditional_if: 104 cards
- draw: 102 cards
- discover: 78 cards
- rush: 60 cards
- end_of_turn: 53 cards
- random_summon: 53 cards
- conditional_when: 50 cards
- end_of_your_turn: 45 cards
- copy: 44 cards
- random_damage: 36 cards
- lifesteal: 35 cards
- divine_shield: 29 cards
- random_generate: 28 cards
- heal: 27 cards
- armor: 27 cards
- choose_one: 23 cards
- random_buff: 22 cards
- aura: 21 cards
- dark_gift: 20 cards
- stealth: 19 cards
- discard: 18 cards
- shuffle: 17 cards
- start_of_turn: 17 cards
- steal: 15 cards
- location: 14 cards
- combo: 14 cards
- weapon: 14 cards
- quest: 14 cards
- reward: 13 cards
- transform: 12 cards
- colossal: 11 cards
- reborn: 11 cards
- freeze: 11 cards
- secret: 11 cards
- secret_gen: 11 cards
- spell_damage: 10 cards
- conditional_per: 10 cards
- windfury: 9 cards
- tradeable_kw: 8 cards
- tradeable: 8 cards
- outcast: 8 cards
- adjacent: 7 cards
- immune: 7 cards
- poisonous: 7 cards
- cant_attack: 6 cards
- charge: 5 cards
- silence: 3 cards
- corrupt: 1 cards

## EV Modeling Difficulty Assessment

### Easy (direct calculation): 112 card-effects
  - random_damage: 36
  - random_buff: 22
  - heal: 27
  - armor: 27
### Medium (pool-based EV): 281 card-effects
  - discover: 78
  - random_summon: 53
  - random_generate: 28
  - dark_gift: 20
  - draw: 102
  - dredge: 0
### Hard (state-conditional): 201 card-effects
  - conditional_if: 104
  - conditional_when: 50
  - conditional_per: 10
  - choose_one: 23
  - quest: 14
  - excavate: 0
### Very Hard (complex systems): 65 card-effects
  - location: 14
  - titan: 0
  - colossal: 11
  - dormant: 0
  - starship: 0
  - transform: 12
  - aura: 21
  - adjacent: 7
  - imbue: 0

## Multi-Effect Cards (cards with 3+ variable effects)

- 灰叶树精: 5 effects → battlecry, conditional_if, conditional_mana, divine_shield, lifesteal
- 圣者麦迪文: 5 effects → battlecry, conditional_if, conditional_mana, silence, steal
- 奥拉基尔，风暴之主: 5 effects → battlecry, colossal, conditional_mana, rush, windfury
- 指挥官迦顿: 5 effects → battlecry, conditional_mana, discover, draw, start_of_turn
- 希亚玛特: 5 effects → battlecry, divine_shield, rush, taunt, windfury
- 烟雾弹: 5 effects → battlecry, combo, dark_gift, discover, stealth
- 尼斐塞特武器匠: 5 effects → battlecry, combo, random_buff, random_generate, weapon
- 泰兰·弗丁: 5 effects → conditional_mana, deathrattle, divine_shield, draw, taunt
- 大地庇护: 5 effects → armor, conditional_mana, random_generate, random_summon, taunt
- 护巢龙: 4 effects → battlecry, conditional_if, conditional_mana, taunt
- 盛怒主母: 4 effects → aura, conditional_if, end_of_turn, end_of_your_turn
- 不稳定的施法者: 4 effects → battlecry, conditional_if, copy, spell_damage
- 莫卓克: 4 effects → battlecry, conditional_if, conditional_mana, draw
- 吉恩，咒厄国王: 4 effects → conditional_if, conditional_mana, conditional_when, transform
- 安瑟祭司: 4 effects → battlecry, conditional_if, heal, taunt
- A3型机械金刚: 4 effects → battlecry, conditional_if, discover, steal
- 水晶商人: 4 effects → conditional_if, draw, end_of_turn, end_of_your_turn
- 梦境卫士: 4 effects → battlecry, conditional_if, draw, taunt
- 黑暗的龙骑士: 4 effects → battlecry, conditional_if, dark_gift, discover
- 神秘符文熊: 4 effects → battlecry, conditional_if, copy, taunt
- 护路者玛洛恩: 4 effects → battlecry, conditional_if, conditional_mana, discover
- 邪恶荒裔怪: 4 effects → conditional_if, deathrattle, reborn, weapon
- 永时困苦: 4 effects → conditional_if, conditional_mana, draw, random_summon
- 永时火焰箭: 4 effects → conditional_if, end_of_turn, end_of_your_turn, lifesteal
- 卡多雷精魂: 4 effects → battlecry, conditional_if, lifesteal, taunt
- 霜灼巢母: 4 effects → battlecry, conditional_if, dark_gift, taunt
- 龙龟: 4 effects → armor, battlecry, conditional_if, dark_gift
- 时间流具象: 4 effects → aura, battlecry, conditional_if, steal
- 史书守护者: 4 effects → battlecry, conditional_if, divine_shield, taunt
- 永时坚垒: 4 effects → conditional_if, conditional_mana, discover, location
- 濒危的渡渡鸟: 4 effects → battlecry, conditional_if, copy, taunt
- 出土神器: 4 effects → conditional_if, conditional_mana, discover, random_summon
- 宝石囤积者: 4 effects → battlecry, conditional_mana, deathrattle, discard
- 迅猛龙先锋: 4 effects → battlecry, conditional_mana, dark_gift, discover
- 黑骑士: 4 effects → battlecry, taunt, tradeable, tradeable_kw
- 齿轮光锤: 4 effects → battlecry, divine_shield, random_generate, taunt
- 象牙骑士: 4 effects → battlecry, conditional_mana, discover, heal
- 地底虫王: 4 effects → armor, battlecry, deathrattle, rush
- 王室图书管理员: 4 effects → battlecry, silence, tradeable, tradeable_kw
- 锈烂蝰蛇: 4 effects → battlecry, tradeable, tradeable_kw, weapon
- 棱晶獠牙: 4 effects → battlecry, deathrattle, draw, shuffle
- 迅猛龙巢护工: 4 effects → battlecry, conditional_mana, deathrattle, random_generate
- 疯狂生物: 4 effects → battlecry, conditional_mana, dark_gift, discover
- 阿莱纳希: 4 effects → battlecry, conditional_mana, random_buff, transform
- 疯长的恐魔: 4 effects → battlecry, conditional_mana, dark_gift, taunt
- 愤怒残魂: 4 effects → battlecry, conditional_mana, conditional_per, draw
- 戮屠末日巨口: 4 effects → battlecry, conditional_mana, dark_gift, discover
- 影焰猎豹: 4 effects → battlecry, copy, dark_gift, discover
- 萨萨里安: 4 effects → battlecry, deathrattle, random_damage, reborn
- 传送门卫士: 4 effects → battlecry, draw, random_buff, random_generate
- 现场播报员: 4 effects → battlecry, random_buff, random_generate, weapon
- 昼夜节律术师: 4 effects → battlecry, conditional_mana, random_generate, start_of_turn
- 恐惧迅猛龙: 4 effects → battlecry, conditional_mana, deathrattle, draw
- 潜踪大师奥普: 4 effects → battlecry, combo, deathrattle, stealth
- 栉龙: 4 effects → battlecry, deathrattle, discard, draw
- 卡纳莎的故事: 4 effects → battlecry, conditional_mana, draw, shuffle
- 助祭耗材: 4 effects → conditional_mana, conditional_when, discard, random_summon
- 寒冰护体: 4 effects → armor, conditional_when, secret, secret_gen
- 冰冻陷阱: 4 effects → conditional_mana, conditional_when, secret, secret_gen
- 钥匙专家阿拉巴斯特: 4 effects → conditional_mana, conditional_when, copy, draw
- 活泼的松鼠: 4 effects → conditional_when, deathrattle, draw, shuffle
- 甲龙: 4 effects → conditional_mana, deathrattle, random_summon, taunt
- 擎天雷龙: 4 effects → conditional_mana, deathrattle, random_summon, taunt
- 圣光护盾: 4 effects → conditional_mana, random_generate, random_summon, taunt
- 跳脸惊吓: 4 effects → conditional_mana, dark_gift, discover, shuffle
- 阿梅达希尔: 4 effects → armor, conditional_mana, draw, location
- 闪回: 4 effects → combo, conditional_mana, random_buff, random_summon
- 低语之石: 4 effects → conditional_mana, deathrattle, random_buff, taunt
- 墓晨虚空芽: 4 effects → conditional_mana, random_generate, random_summon, taunt
- 克洛玛图斯: 4 effects → colossal, divine_shield, lifesteal, taunt
- 绝息剑龙: 4 effects → end_of_turn, end_of_your_turn, random_damage, taunt
- 圣光抚愈者: 4 effects → choose_one, divine_shield, lifesteal, taunt
- 幻影绿翼龙: 4 effects → deathrattle, draw, shuffle, taunt
- 侏儒嚼嚼怪: 4 effects → end_of_turn, end_of_your_turn, lifesteal, taunt
- 拉格纳罗斯，绝世烈火: 4 effects → colossal, deathrattle, end_of_turn, end_of_your_turn
- 暗影升腾者: 4 effects → end_of_turn, end_of_your_turn, random_buff, random_generate
- 恶毒恐魔: 4 effects → copy, end_of_turn, end_of_your_turn, reborn
- 棘嗣幼龙: 4 effects → end_of_turn, end_of_your_turn, random_buff, random_damage
- 鲜花商贩: 4 effects → end_of_turn, end_of_your_turn, random_buff, random_generate
- 喜悦的枭兽: 4 effects → armor, end_of_turn, end_of_your_turn, steal
- 昔时古树: 4 effects → armor, draw, end_of_turn, end_of_your_turn
- 沙漏侍者: 4 effects → aura, divine_shield, end_of_turn, end_of_your_turn
- 着魔的动物术师: 4 effects → deathrattle, lifesteal, random_generate, random_summon
- 飞翼畸变体: 4 effects → combo, immune, rush, windfury
- 梦魇供能: 4 effects → combo, copy, dark_gift, discover
- 费伍德树人: 3 effects → battlecry, conditional_if, conditional_mana
- 梦境之龙麦琳瑟拉: 3 effects → battlecry, conditional_if, conditional_mana
- 威拉诺兹: 3 effects → battlecry, conditional_if, conditional_mana
- 麦迪文的胜利: 3 effects → conditional_if, conditional_mana, steal
- 维克多·奈法里奥斯: 3 effects → battlecry, conditional_if, conditional_mana
- 喷发火山: 3 effects → conditional_if, location, random_damage
- 生存专家: 3 effects → conditional_if, immune, steal
- 冰喉: 3 effects → conditional_if, deathrattle, taunt
- 死亡金属骑士: 3 effects → conditional_if, conditional_mana, taunt
- 虚空幽龙史学家: 3 effects → battlecry, conditional_if, discover
- 死灵殡葬师: 3 effects → battlecry, conditional_if, discover
- 猎头者之斧: 3 effects → battlecry, conditional_if, steal
- 雾帆劫掠者: 3 effects → battlecry, conditional_if, weapon
- 茏葱梦刃豹: 3 effects → battlecry, conditional_if, conditional_mana
- 艾森娜: 3 effects → battlecry, conditional_if, random_damage
- 轮回编织者: 3 effects → battlecry, conditional_if, conditional_mana
- 影蔽袭击者: 3 effects → battlecry, conditional_if, shuffle
- 胆大的魔荚人: 3 effects → conditional_if, conditional_mana, transform
- 莎拉达希尔: 3 effects → conditional_if, conditional_mana, corrupt
- 明耀织梦者: 3 effects → battlecry, conditional_if, lifesteal
- 协作火花: 3 effects → conditional_if, random_buff, random_generate
- 末世幸存者: 3 effects → battlecry, conditional_if, taunt
- 火炭变色龙: 3 effects → battlecry, conditional_if, rush
- 花木护侍: 3 effects → battlecry, conditional_if, draw
- 燃薪之剑: 3 effects → battlecry, conditional_if, dark_gift
- 扎卡利驭焰者: 3 effects → battlecry, conditional_if, conditional_mana
- 累世巨蛇: 3 effects → conditional_if, conditional_mana, rush
- 始源监督者: 3 effects → battlecry, conditional_if, draw
- 命源: 3 effects → conditional_if, conditional_mana, discover
- 墓地尊主塔兰吉: 3 effects → battlecry, conditional_if, draw
- 先行打击: 3 effects → conditional_if, conditional_mana, draw
- 碧蓝女王辛达苟萨: 3 effects → conditional_if, conditional_mana, steal
- 导航员伊莉斯: 3 effects → battlecry, conditional_if, conditional_mana
- 班纳布斯的故事: 3 effects → armor, conditional_if, draw
- 乱翻库存: 3 effects → conditional_if, conditional_mana, discover
- 拉特维亚护甲师: 3 effects → armor, battlecry, conditional_if
- 林歌海妖: 3 effects → conditional_if, conditional_mana, lifesteal
- 任务助理: 3 effects → battlecry, conditional_if, quest
- 黏弹爆破手: 3 effects → adjacent, battlecry, conditional_mana
- 阿莱克丝塔萨，生命守护者: 3 effects → battlecry, conditional_when, heal
- 大法师卡雷: 3 effects → aura, battlecry, spell_damage
- 冬泉雏龙: 3 effects → battlecry, conditional_mana, discover
- 魔眼秘术师: 3 effects → battlecry, discard, taunt
- 艾比西安: 3 effects → battlecry, conditional_when, rush
- 雷鸣流云: 3 effects → battlecry, conditional_mana, deathrattle
- 飞行助翼: 3 effects → battlecry, cant_attack, windfury
- 托维尔雕琢师: 3 effects → battlecry, conditional_mana, start_of_turn
- 恐怖海兽: 3 effects → battlecry, steal, taunt
- 避难的幸存者: 3 effects → battlecry, draw, shuffle
- 暗誓信徒: 3 effects → battlecry, deathrattle, heal
- 毁焚火凤: 3 effects → battlecry, copy, discard
- 星术师: 3 effects → battlecry, conditional_mana, random_summon
- 提克迪奥斯: 3 effects → battlecry, conditional_mana, immune
- 奥尔法: 3 effects → battlecry, conditional_mana, deathrattle
- 卑劣的脏鼠: 3 effects → battlecry, random_summon, taunt
- 奖品商贩: 3 effects → battlecry, deathrattle, draw
- 狐人老千: 3 effects → battlecry, combo, conditional_mana
- 王牌猎人: 3 effects → battlecry, tradeable, tradeable_kw
- 日怒保卫者: 3 effects → adjacent, battlecry, taunt
- 末日守卫: 3 effects → battlecry, charge, discard
- 女巫的学徒: 3 effects → battlecry, random_generate, taunt
- 女巫森林灰熊: 3 effects → battlecry, conditional_per, taunt
- 炽焰祈咒: 3 effects → battlecry, conditional_mana, discover
- 馆长: 3 effects → battlecry, draw, taunt
- 拆迁修理工: 3 effects → battlecry, tradeable, tradeable_kw
- 迷宫向导: 3 effects → battlecry, conditional_mana, random_summon
- 蛛魔护群守卫: 3 effects → battlecry, copy, taunt
- 亚历山德罗斯·莫格莱尼: 3 effects → battlecry, end_of_turn, end_of_your_turn
- 石丘防御者: 3 effects → battlecry, discover, taunt
- 黑市摊贩: 3 effects → battlecry, conditional_mana, discover
- 展馆茶杯: 3 effects → battlecry, random_buff, random_generate
- 灵敏的厨师: 3 effects → adjacent, battlecry, conditional_mana
- 冰脊剑龙: 3 effects → battlecry, freeze, random_damage
- 装扮商贩: 3 effects → battlecry, combo, conditional_mana
- 兽语者塔卡: 3 effects → battlecry, deathrattle, discover
- 狡诈拷问者: 3 effects → battlecry, dark_gift, discover
- 乌索尔: 3 effects → aura, battlecry, conditional_mana
- 狡猾的萨特: 3 effects → battlecry, conditional_mana, copy
- 阿莎曼: 3 effects → battlecry, conditional_mana, copy
- 振翅守卫: 3 effects → battlecry, divine_shield, taunt
- 恐魂腐蚀者: 3 effects → battlecry, deathrattle, random_summon
- 梦缚信徒: 3 effects → battlecry, conditional_mana, deathrattle
- 梦魇之王萨维斯: 3 effects → battlecry, dark_gift, discover
- 艾维娜，艾露恩钦选者: 3 effects → battlecry, conditional_mana, conditional_when
- 锐目侦察兵: 3 effects → battlecry, conditional_mana, draw
- 无穷之手: 3 effects → battlecry, cant_attack, weapon
- 无穷助祭: 3 effects → battlecry, conditional_mana, deathrattle
- 次元武器匠: 3 effects → aura, battlecry, weapon
- 末世的姆诺兹多: 3 effects → battlecry, heal, random_buff
- 烬鳞雏龙: 3 effects → battlecry, conditional_mana, discover
- 沃尔科罗斯: 3 effects → battlecry, rush, taunt
- 灼热掠夺者: 3 effects → battlecry, conditional_mana, discover
- 火光之龙菲莱克: 3 effects → battlecry, conditional_mana, immune
- 龙裔护育师: 3 effects → battlecry, conditional_mana, copy
- 堕寒男爵: 3 effects → battlecry, deathrattle, draw
- 强光护卫: 3 effects → battlecry, divine_shield, heal
- 暮光时空跃迁者: 3 effects → battlecry, draw, shuffle
- 灾毁迅疾幼龙: 3 effects → battlecry, copy, rush
- 克洛诺戈尔: 3 effects → battlecry, conditional_mana, draw
- 王室线人: 3 effects → battlecry, conditional_mana, copy
- 时空领主戴欧斯: 3 effects → battlecry, deathrattle, end_of_turn
- 高山之王穆拉丁: 3 effects → battlecry, deathrattle, rush
- 琥珀女祭司: 3 effects → battlecry, heal, taunt
- 纪元追猎者: 3 effects → battlecry, copy, rush
- 上层精灵教师: 3 effects → battlecry, conditional_mana, discover
- 纪元守护者克洛纳: 3 effects → battlecry, conditional_mana, taunt
- 超时空鳍侠: 3 effects → battlecry, end_of_turn, end_of_your_turn
- 神秘无面者: 3 effects → battlecry, secret, secret_gen
- 后世之嗣: 3 effects → battlecry, conditional_per, taunt
- 不败冠军: 3 effects → battlecry, conditional_mana, rush
- 火山长尾蜥: 3 effects → battlecry, draw, spell_damage
- 远古剑龙: 3 effects → battlecry, poisonous, taunt
- 远古迅猛龙: 3 effects → battlecry, deathrattle, divine_shield
- 远古翼手龙: 3 effects → battlecry, stealth, windfury
- 水晶养护工: 3 effects → battlecry, tradeable, tradeable_kw
- 温泉踏浪鱼人: 3 effects → battlecry, conditional_mana, divine_shield
- 拾荒清道夫: 3 effects → battlecry, conditional_mana, discover
- 传奇商贩: 3 effects → battlecry, discover, shuffle
- 乘风浮龙: 3 effects → armor, battlecry, conditional_mana
- 观察者娜博亚: 3 effects → battlecry, copy, rush
- 升腾: 3 effects → conditional_mana, conditional_when, transform
- 绿洲盟军: 3 effects → conditional_when, secret, secret_gen
- 法术反制: 3 effects → conditional_when, secret, secret_gen
- 爆炸陷阱: 3 effects → conditional_when, secret, secret_gen
- 捕鼠陷阱: 3 effects → conditional_when, secret, secret_gen
- 殒命暗影: 3 effects → conditional_when, copy, transform
- 艾瑞达欺诈者: 3 effects → conditional_when, draw, rush
- 伦萨克大王: 3 effects → aura, conditional_when, rush
- 瓦洛，污邪古树: 3 effects → conditional_when, copy, dark_gift
- 凋零先驱: 3 effects → conditional_mana, conditional_when, random_summon
- 雷鸫: 3 effects → conditional_mana, conditional_when, random_summon
- 失时往生: 3 effects → conditional_when, secret, secret_gen
- 蛇颈龙群的伊度: 3 effects → conditional_mana, conditional_when, divine_shield
- 格里什异种虫: 3 effects → conditional_mana, conditional_when, rush
- 艾萨拉的胜利: 3 effects → conditional_mana, random_buff, shuffle
- 塔兰吉的奋战: 3 effects → conditional_mana, deathrattle, random_summon
- 矛心哨卫: 3 effects → conditional_mana, end_of_turn, end_of_your_turn
- 龙脉混血兽: 3 effects → conditional_mana, deathrattle, random_summon
- 辛达苟萨的胜利: 3 effects → conditional_mana, random_buff, random_damage
- 冰川急冻: 3 effects → conditional_mana, discover, freeze
- 眼棱: 3 effects → conditional_mana, lifesteal, outcast
- 恐怖海盗: 3 effects → conditional_mana, taunt, weapon
- 铁炉堡传送门: 3 effects → armor, conditional_mana, random_summon
- 伊利达雷研习: 3 effects → conditional_mana, discover, outcast
- 安布拉的故事: 3 effects → conditional_mana, deathrattle, discover
- 生命仪式: 3 effects → conditional_mana, copy, discover
- 守卫执勤: 3 effects → conditional_mana, random_summon, taunt
- 暮光侵扰: 3 effects → choose_one, conditional_mana, random_summon
- 腐心树妖: 3 effects → conditional_mana, deathrattle, draw
- 法夜欺诈者: 3 effects → conditional_mana, deathrattle, draw
- 受难的恐翼巨龙: 3 effects → conditional_mana, deathrattle, draw
- 贪婪的地狱猎犬: 3 effects → conditional_mana, copy, deathrattle
- 残暴的魔蝠: 3 effects → conditional_mana, copy, deathrattle
- 踏青驼鹿: 3 effects → conditional_mana, deathrattle, taunt
- 旧时回响: 3 effects → conditional_mana, outcast, random_summon
- 火化: 3 effects → conditional_mana, dark_gift, discover
- 永燃火凤: 3 effects → conditional_mana, deathrattle, end_of_turn
- 修补时间线: 3 effects → conditional_mana, heal, random_buff
- 危险的异变体: 3 effects → conditional_mana, start_of_turn, transform
- 渺小的振翅蝶: 3 effects → conditional_mana, deathrattle, random_summon
- 过去的时光流汇: 3 effects → conditional_mana, location, random_summon
- 诛灭暴君: 3 effects → combo, conditional_mana, random_summon
- 为了荣耀！: 3 effects → conditional_mana, draw, steal
- 异化: 3 effects → conditional_mana, random_buff, random_summon
- 欢迎回家: 3 effects → conditional_mana, deathrattle, random_summon
- 血瓣群系: 3 effects → conditional_mana, discover, location
- 蛇颈龙骑手的祝福: 3 effects → conditional_mana, deathrattle, random_summon
- 灌林追踪者: 3 effects → conditional_mana, rush, shuffle
- 恐龙保育师: 3 effects → conditional_mana, end_of_turn, end_of_your_turn
- 围攻城门: 3 effects → conditional_mana, quest, reward
- 光沐元素: 3 effects → deathrattle, heal, taunt
- 提里奥·弗丁: 3 effects → deathrattle, divine_shield, taunt
- 黑曜石雕像: 3 effects → deathrattle, lifesteal, taunt
- 莫尔葛熔魔: 3 effects → armor, deathrattle, taunt
- 紧壳商品: 3 effects → taunt, tradeable, tradeable_kw
- 划水好友: 3 effects → choose_one, rush, taunt
- 震地雷龙: 3 effects → aura, deathrattle, taunt
- 森林之灵: 3 effects → choose_one, taunt, windfury
- 伊森德雷: 3 effects → deathrattle, random_summon, taunt
- 麻痹睡眠: 3 effects → cant_attack, choose_one, taunt
- 尼珊德拉: 3 effects → deathrattle, start_of_turn, taunt
- 战场通灵师: 3 effects → end_of_turn, end_of_your_turn, taunt
- 琥珀守卫: 3 effects → deathrattle, random_summon, taunt
- 不情愿的饲养员: 3 effects → deathrattle, reborn, taunt
- 黏团焦油: 3 effects → deathrattle, poisonous, taunt
- 死烂巨口: 3 effects → deathrattle, random_summon, taunt
- 诺兹多姆，青铜守护巨龙: 3 effects → divine_shield, end_of_turn, end_of_your_turn
- 青铜护卫者: 3 effects → divine_shield, end_of_turn, end_of_your_turn
- 沃坎诺斯: 3 effects → colossal, end_of_turn, end_of_your_turn
- 诅咒之链: 3 effects → cant_attack, end_of_turn, steal
- 愤怒的女祭司: 3 effects → end_of_turn, end_of_your_turn, random_damage
- 神秘恐魔: 3 effects → end_of_turn, end_of_your_turn, lifesteal
- 窜逃的黑翼龙: 3 effects → end_of_turn, end_of_your_turn, random_damage
- 安魂仪典: 3 effects → end_of_turn, end_of_your_turn, rush
- 饥饿古树: 3 effects → deathrattle, end_of_turn, end_of_your_turn
- 小动物看护者: 3 effects → end_of_turn, end_of_your_turn, heal
- 无穷烈焰: 3 effects → end_of_turn, secret, secret_gen
- 拉卡利的故事: 3 effects → discard, end_of_turn, end_of_your_turn
- 无面复制者: 3 effects → copy, deathrattle, transform
- 毁灭之焰: 3 effects → deathrattle, random_damage, random_summon
- 血法师萨尔诺斯: 3 effects → deathrattle, draw, spell_damage
- 邪魔仆从: 3 effects → deathrattle, random_buff, random_generate
- 孢子尖牙怪: 3 effects → deathrattle, poisonous, random_damage
- 年兽: 3 effects → deathrattle, rush, windfury
- 前卫园艺: 3 effects → dark_gift, deathrattle, discover
- 扭曲的树人: 3 effects → deathrattle, random_buff, random_generate
- 倒刺荆棘: 3 effects → choose_one, deathrattle, poisonous
- 克罗米: 3 effects → copy, deathrattle, draw
- 血斗士洛戈什: 3 effects → deathrattle, random_summon, rush
- 咒术图书管理员: 3 effects → copy, deathrattle, draw
- 填鳃暴龙: 3 effects → deathrattle, random_summon, rush
- 过热: 3 effects → discard, random_buff, random_generate
- 暗中设伏: 3 effects → quest, reward, shuffle
- 审讯: 3 effects → draw, shuffle, stealth
- 黑血: 3 effects → colossal, heal, reborn
- 涡流风暴幼龙: 3 effects → immune, rush, windfury
- 盛宴之角: 3 effects → immune, outcast, rush
- 暴徒双人组: 3 effects → combo, copy, stealth
- 烧灼映像: 3 effects → copy, divine_shield, draw
- 吞噬: 3 effects → conditional_per, draw, random_damage
- 禁忌序列: 3 effects → discover, quest, reward