#!/usr/bin/env python3
"""一次性迁移:老版 dat/*.dat + Perl 源内文案 → v2/seeds/*.json

用法: python3 tools/migrate_dat.py [--check]
  --check 只输出对照报告(条目数),不写文件。

文案来源(逐字转录,保留原版标点/换行,含原版翻译中的「?」伪标点):
  - 22 地点描述   br.cgi @arinfo
  - 尸体描述 7×8 battle.cgi DEATHGET
  - 事件文案     lib/event.cgi
  - 3 结局       lib/ending.cgi
  - 开场剧情     regist.cgi INFO
  - 注册校验文案 regist.cgi REGIST
  - 通用消息     battle.cgi / lib2.cgi
[补充投放] 原版 dat 中不存在合成素材/毒药/扩音器(相关功能不可达),
此处按主题补投,详见 EXTRA_PLACEMENTS。
"""
import json
import os
import re
import sys
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # /home/zqin/BR-CN
DAT = os.path.join(ROOT, "dat")
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "seeds")
os.makedirs(OUT, exist_ok=True)


def parse_uses(s):
    s = s.strip()
    if s in ("∞", "", "inf"):
        return None
    return int(s)


def read_lines(path):
    with open(path, encoding="utf-8") as f:
        return [ln.strip() for ln in f if ln.strip()]


def migrate_weapons():
    """dat/wepfile.dat: 名称<>码,攻击力,耐久,"""
    weapons = []
    for ln in read_lines(os.path.join(DAT, "wepfile.dat")):
        item, att, uses = ln.split(",")[:3]
        name, code = item.split("<>")
        weapons.append(dict(name=name, code=code, att=int(att), uses=parse_uses(uses)))
    return weapons


def migrate_personal():
    out = []
    for ln in read_lines(os.path.join(DAT, "stitemfile.dat")):
        item, eff, uses = ln.split(",")[:3]
        name, code = item.split("<>")
        out.append(dict(name=name, code=code, eff=int(eff), uses=parse_uses(uses)))
    return out


# [补充投放] 原版投放表中缺失、导致合成/投毒/扩音器/黑客/EX 不可达的物品。
# place: 99=随机撒放;数量按同类稀有物平衡。
EXTRA_PLACEMENTS = [
    # 合成素材
    (5,  "轻油<>Y", 1, 2), (20, "轻油<>Y", 1, 2),          # 消防署/灯塔(发电机油)
    (5,  "汽油<>Y", 1, 3), (14, "汽油<>Y", 1, 1),          # 消防署/废弃学校
    (11, "导火索<>Y", 1, 3), (10, "导火索<>Y", 1, 2),       # 隧道/山岳地带
    (2,  "喷雾罐<>Y", 1, 2), (12, "喷雾罐<>Y", 1, 2), (18, "喷雾罐<>Y", 1, 2),
    (2,  "打火机<>Y", 1, 3), (12, "打火机<>Y", 1, 3), (18, "打火机<>Y", 1, 3), (9, "打火机<>Y", 1, 2),
    (14, "苹果电脑<>Y", 1, 2), (4, "苹果电脑<>Y", 1, 1),    # 废弃学校/邮局
    (11, "雷管<>Y", 1, 2), (10, "雷管<>Y", 1, 2),            # 隧道/山岳地带
    (11, "火药<>Y", 1, 2), (10, "火药<>Y", 1, 1),            # 隧道/山岳地带(工程炸药)
    (4, "手机<>Y", 1, 2), (2, "手机<>Y", 1, 1), (18, "手机<>Y", 1, 1),  # 邮局/住宅街
    # 毒药/扩音器(原版功能存在但投放缺失)
    (19, "毒药<>Y", 20, 2), (14, "毒药<>Y", 20, 1),         # 诊疗所/废弃学校
    (3,  "携带式扩音器<>Y", 1, 2), (4, "携带式扩音器<>Y", 1, 1),  # 公所/邮局
    (99, "毒药<>Y", 20, 2), (99, "携带式扩音器<>Y", 1, 1),
]


def migrate_items():
    """dat/itemfile.dat: 区域号,名称<>码,效果,数量, → {place: [...]};并叠加补充投放。"""
    table = defaultdict(list)
    for ln in read_lines(os.path.join(DAT, "itemfile.dat")):
        place, item, eff, uses = ln.split(",")[:4]
        name, code = item.split("<>")
        table[int(place)].append(dict(name=name, code=code, eff=int(eff), uses=parse_uses(uses)))
    for place, item, eff, qty in EXTRA_PLACEMENTS:
        name, code = item.split("<>")
        for _ in range(int(qty)):
            table[int(place)].append(dict(name=name, code=code, eff=int(eff), uses=None))
    return {str(k): v for k, v in sorted(table.items())}


def migrate_npcs():
    """dat/base.dat: 姓,名,性别,班级,学号,武器3列,身体3列,头3,足3,腕3,icon,物品6×3,com,msg,dmes"""
    out = []
    for ln in read_lines(os.path.join(DAT, "base.dat")):
        c = ln.split(",")
        npc = dict(
            f_name=c[0], l_name=c[1], sex=c[2], class_name=c[3], class_no=int(c[4]),
        )
        wep = c[5].split("<>")
        npc["weapon"] = dict(name=wep[0], code=wep[1], att=int(c[6]), uses=parse_uses(c[7]))
        bou = c[8].split("<>")
        npc["body_armor"] = dict(name=bou[0], code=bou[1], deff=int(c[9]), uses=parse_uses(c[10]))
        def part(a):
            nc = c[a].split("<>")
            if nc[0] in ("空", ""):
                return None
            return dict(name=nc[0], code=nc[1], deff=int(c[a + 1]), uses=parse_uses(c[a + 2]))
        npc["head_armor"] = part(11)
        npc["foot_armor"] = part(14)
        npc["arm_armor"] = part(17)
        # c[20] = icon(不迁移);物品 6 格自 c[21] 起,每格 3 列
        items = []
        for i in range(6):
            base = 21 + i * 3
            nc = c[base].split("<>")
            if nc[0] not in ("空", ""):
                items.append(dict(name=nc[0], code=nc[1], eff=int(c[base + 1]), uses=parse_uses(c[base + 2])))
            else:
                items.append(None)
        npc["items"] = items
        out.append(npc)
    return out


# ============================================================#
# 文案(逐字转录自 Perl 源;{var} 为渲染占位符)
# ============================================================#

ARINFO = [
    "分校。现在是禁止地区。<BR>赶快离开、不然颈环就要爆炸了。",
    "海上依稀看见船的影子,想逃走的学生仔细辨认,却不能确定是不是政府派来监视的船只。",
    "这里原来也曾经像有人住过的样子，如今却只留下一片废墟了。",
    "这里就是村庄的中心了，不知道现在这里还有没有人。",
    "看上去是个邮局的样子，但是却因为没有人办公而显得诡异无比。",
    "说起来是消防局，但是也没见有消防车停着啊。",
    "大大小小的佛像被供在神龛上，在夜色中却让人感到不大自然。",
    "满满地装着清澄的池水。",
    "这里供奉着的好像是智慧之神的样子。。",
    "这样的地方傍晚不知道会不会有幽灵出没，虽说幽灵是不存在的，但是……。",
    "这是一个对整个岛屿一览无余的制高点，当然，同时给别人发现的机会也大大增加了…………。",
    "这里真黑啊，如果长时间呆在这里很容易被人夹击的……。",
    "这里也和这个岛上的其它居民区相同，成为了一片废墟……。",
    "一片荒芜的地方…………。",
    "这里白天还像学校的样子，晚上却像一座恐怖故事里的城堡。",
    "鸟儿在自己树上的窝前肆无忌惮地冲着人张望……。",
    "浓密的树林和杂草丛生的，地方，真不知道会忽然窜出什么……。",
    "这个地方是污浊的河流和沼泽，散发着一股难闻的味道……。",
    "这里相比其它的住宅街而言，这里有很多的商店，但是都门户禁闭……。",
    "这里很安静，进去看看不知道能不能找到需要的药物………。",
    "作为岛上的要塞，在海边高高耸立着，可怖的是里面的床和墙上都是斑斑血迹，怎么会这样？",
    "运送士兵的船只，不知道胜利者是不是也乘这个船走，看上去岛上的士兵可不少……。",
]

# 尸体描述(battle.cgi DEATHGET):死因关键词 → 7 变体
CORPSE_DESC = {
    "斩杀": [
        "头部只靠脖子上的一层皮连着???。看来是被斩首了。",
        "腹部像被锋利的刃器撕开似的裂着，内脏溢了出来???。",
        "从肩口到胸口是一道斜劈。被漂亮地斩裂了???。",
        "头?躯干?双臂?双腿都被截断了。这种事是精神正常的人做得出来的吗???。",
        "脸被集中地乱刀切碎。完全看不出生前的模样???。",
        "腹部被切开，但仔细一看手腕上也有许多切割伤???。<br>是被对方砍伤之后才想自杀的吗？",
        "从头到胸被凄惨地斩裂着???。",
    ],
    "射杀": [
        "一支箭深深地插在额头上???。",
        "背上插着好几支箭。似乎是想逃跑的时候，被从背后射中的。",
        "一支箭分毫不差地刺在心脏的位置。应该是相当厉害的射手吧???。",
        "腿和头上插着箭。似乎是先射中腿让对方无法逃跑，再射要害的???。",
        "像被箭钉在墙上一样???姿势宛如在各各他山被处刑的圣者??。",
        "插着无数支箭，像刺猬一样???。",
        "脖子上刺着好几支箭???。一支从下巴底下贯穿了???。",
    ],
    "枪杀": [
        "胸口有???3发、额头有1发弹痕???。额头上那一发似乎成了致命伤???。",
        "腹部有好几发弹痕，鲜血正流出来。不过，那些血也已经干涸了。",
        "脑袋被轰得面目全非???。勉强从头名牌上认出了名字。",
        "胸口好几发。而且脑浆都被轰飞了。大概是杀了之后又把枪塞进嘴里开的枪。真是干了番混账事???。",
        "腹部开了一个大洞，对面都看得见。这样肯定活不成了???。",
        "脸上有好几发弹痕???。难道是有什么仇怨吗。",
        "右头部严重破损，脑浆流了出来????。",
    ],
    "绞杀": [
        "是被什么东西勒住了脖子吗???。嘴里喷出了大量呕吐物。",
        "是被绞死的???一副怨恨的样子朝这边瞪着。",
        "是被什么勒住脖子了吧。吐着舌头、翻着白眼，样子凄惨???。",
        "像是被谁勒死的样子。失禁了???。",
        "被勒住脖子时激烈反抗过吗。指甲里嵌着肉一样的东西??。",
        "是吊死的尸体???只能认为是被杀之后才吊起来的???。",
        "脖颈上有被什么东西勒过的紫色淤痕???。",
    ],
    "爆杀": [
        "四处散落着身体的碎块。看来被炸得很惨???。",
        "双腿被炸飞了。是只想用双臂爬着逃跑吗???。",
        "大概是被炸弹袭击了吧，只剩下头和右臂???。",
        "是被炸弹炸飞的吗，脑袋缺了一半，里面的东西隐约可见???。",
        "被爆风吹飞的一条手臂，滚落在5米开外???。",
        "与其说是尸体，不如说是一堆肉块???。",
        "脖子和手都不见了???。是被爆风吹飞了吗???。",
    ],
    "殴杀": [
        "按着腹部蜷缩着???看来就这样断气了???。",
        "看来被揍得很惨???。脸肿得发紫???。",
        "颈骨被打断，骨头从脖子里突出来???。",
        "脸埋在地面上，脸上流着大量的血??。看来是倒下时后脑遭到了殴打。",
        "是被从背后用钝器之类的东西殴打的吗？就那样抱着头倒着???。",
        "额头裂开，流淌着血和脑浆。看来是被正面狠狠殴打的??。",
        "脖子彻底歪向了一边。怎么看都是颈骨断了???。",
    ],
    "刺杀": [
        "全身上下有大量被锋利刃器刺出的伤口???。尸体周围是一片血海???。",
        "有被骑在身上、一次又一次被刺杀的痕迹???。",
        "心脏被一刀刺穿。伤口至今还涌着血???。被杀似乎就在刚才。",
        "喉咙被刺穿了??。眼睛翻着白眼???。",
        "被从背后刺中腹部倒下。是遭了偷袭吗??？",
        "左腹部严重受损。有刺入后再搅挖般的伤口???。",
        "双眼被什么东西刺穿了???。像是在流着血泪???。",
    ],
    "毒": [
        "是吃了毒物吗??？也有呕吐过的痕迹???。",
        "嘴角流着一道血。乍一看只会觉得是在睡觉???。",
        "把脸凑近尸体，有一股特有的杏仁味。是被毒杀的吗???。",
        "是被毒杀的吗。嘴里吐着大量带血的泡沫???。",
        "是喝毒药痛苦过吗。喉咙被自己用指甲狠狠抓烂了???。",
        "是被谁下了毒药吗？皮肤严重变色了???。",
        "皮肤变成紫黑色，嘴里吐着大量的血???。",
    ],
}
CORPSE_DESC_DEFAULT = "凄惨地仰面倒着???。"
CORPSE_DESC_TAIL = "要不要搜一搜背包里的东西呢???。<br>"

# 事件文案(lib/event.cgi):dice∈{2,3,4}(dice<2 无事)
EVENTS = {
    "crow": {   # 住宅街(2/12/18)乌鸦
        "intro": "无意间抬头看天，是一群乌鸦！<BR>",
        "injury": "被乌鸦袭击，头部受伤了！<BR>",
        "damage": "被乌鸦袭击，受到了<span class=\"red\"><b>{damage}点损害</b></span>！<BR>",
        "repel": "呼，总算击退了???。<BR>",
        "part": "头",
    },
    "rock": {   # 山岳地带(10) 落石
        "intro": "糟糕，是山体滑坡！<BR>",
        "injury": "好不容易躲开了，却被落石砸伤了足部！<BR>",
        "damage": "被落石砸中，受到了<span class=\"red\"><b>{damage}点损害</b></span>！<BR>",
        "repel": "呼，总算躲开了???。<BR>",
        "part": "足",
    },
    "dog": {    # 森林地带(16) 野狗
        "intro": "突然，野狗扑了过来！<BR>",
        "injury": "被咬住了手腕，腕部受伤了！<BR>",
        "damage": "被野狗袭击，受到了<span class=\"red\"><b>{damage}点损害</b></span>！<BR>",
        "repel": "呼，总算击退了???。<BR>",
        "part": "腕",
    },
    "pond": {   # 源二郎池(17) 滑落:dice<=3 掉池耐力-(dice2+10)
        "intro": "糟糕，脚底一滑！<BR>",
        "damage": "掉进了池子里，不过总算爬上来了！<BR>消耗了 <span class=\"red\"><b>{damage}点</b></span> 精力！<BR>",
        "repel": "呼，总算没掉下去???。<BR>",
    },
}
# 地点 → 事件
PLACE_EVENTS = {2: "crow", 12: "crow", 18: "crow", 10: "rock", 16: "dog", 17: "pond"}

EVENT_DAMAGE_DICE = "5_9"     # int(rand(5)+5) → 5~9 伤害
POND_STA_DICE = "15_19"       # dice2(5~9)+10 → 15~19 耐力

# 注册开场剧情(regist.cgi INFO)
INTRO = """慢慢睁开眼睛、好象身处一个教室一样的地方。说出来是修学旅行，可是···。<br>
「恍恍惚惚好象记得，自己是在修学旅行路上的大巴士上忽然感到一种难以抵抗的睡意···」<br>
环视周围、其它的同学似乎也刚刚醒来 。每个人脖子上有一个银色的颈环，闪着冷漠的光泽，显得分外刺眼和不协调 <br>
下意识地摸摸自己的脖子、冷冷的金属触感传递到指间。<br>
都一样、那个银色的颈环同样戴在自己的脖子上。<br>
<br>
突然、教室的门打开了，一个中年男人走了进来···。<br><br>
<br>
『好了、该告诉大家真相了。看起来大家都不明白自己为什么在这里和干些什么。<br>
如今，这个国家已经彻底完了，为了振兴这个国家，司法部门推出了这个法案。<br>
<br>
不要试图逃出这个岛，因为你们脖子里面戴着的颈环里面的装置会通知我们，然后结果可以自己去猜测。<br>
<br>
同学们，是的，今年你们被荣幸地选为执行BR法的对象了，这是经过严格抽选的结果。<br>
<br>
游戏的规则很简单，就是要你们互相杀戮，直到杀剩下最后一个人为止。<br>
这是唯一的胜出方式。<br><br>
啊、老师忘了说了，你们的行动范围就是在这个岛上。<br>
<br>
你们所在，是我们学校在这个岛的分校。<br>
在游戏的进行中，老师会一直守侯在这里，关注着你们。<br>
<br>
下面还有一个情况要说明。<br>
每天零点，岛上将放送广播。一日一次。<br>
<br>
按照地址上标识的坐标,将随机决定若干个流动的禁止区域、<br>
这些区域老师会定时宣布。<br>
一定要仔细查看地图,确定自己的方位,一旦被宣布是禁止区域、<br>
马上要用最快的速度离开那里。<br>
<br>
不然的话,颈环就会因为感应而爆炸。<br>
<br>
最后，忘记说最重要的一点。<br>
游戏有一定的限定时间,如果到了限定的时间仍然没有决出最后的胜利者<br>
所有残存人员的颈环都将爆炸，没有胜利者!既然参加了游戏就要全力以赴,老师可不想看到这样的情况出现哦！<br>
<br>
你们每个人将被发到一个包,里面有食物和水,指南针,以及一件武器。下面开始,按照学号,拿好你们的东西，一个个离开这里!<br>"""

# 首页世界观引言(index.htm)
HOME_INTRO = """西历20XX年,大东亚共和国。<br>
<br>
「新世纪恐怖主义对策特别法」——通称「BR法」。<br>
每年从全国的中学校3年级中随机选出一个班级,<br>
并将他们送到无人岛等地,让他们自相残杀,直到剩下最后一人为止——<br>
这就是这个国家最疯狂的「游戏」。<br>
<br>
现在,新的参加者们已被送到岛上。<br>
你能活到最后吗?"""

# 结局文案(ending.cgi;{sex}{no}{f_name}{l_name} 为优胜者信息占位符)
ENDING_WIN = """突然警报响起，随后奏响了大东亚共和国的国歌。<br>
接着，传来一个熟悉的声音。<br>
<br>
「恭喜啦——。你就是优胜者——。老师真的很为你高兴。<br>
我现在就去接你，乖乖等着哦——」<br>
<br>
刚才，在眼前咽下最后一口气的那个人，就是最后一人了吗？<br>
我呆呆地听着新班主任的广播。<br>
真的是这样吗？<br>
会不会还有别的幸存者，刚才的广播只是新班主任的诡计？<br>
记得这个程序，好像还是政府要员们打赌的对象。<br>
可是，听完这段广播，紧绷的神经啪的一声断了。<br>
意识渐渐模糊起来。。。<br>
想起来了，这几天完全没合过眼啊。。。<br>
?<br>
?<br>
?<br>
眼前，是只剩一颗头颅的好友。<br>
「你果然是想干的吧，你就是想杀人吧？」<br>
身后，站着半边身体残缺不全的同学。<br>
「说好了要互相信任、大家一起活下去的，不就是你吗！」<br>
右手的黑暗中传来一个声音。<br>
「叛徒！」<br>
<br>
我坐立难安，终于喊出了声。<br>
「我不想杀人，大家都是朋友！可是，可是???我想活下去」<br>
?<br>
?<br>
?<br>
感到身体的摇晃，我醒了过来。<br>
看向右手边，站着一个专制军的士兵。我似乎在一辆押送车里。<br>
膝盖上放着一块题字板。<br>
上面用蚯蚓般扭曲的字迹写着『恭喜获胜！来自共和国总统』。<br>
<br>
突然，一阵强光刺得我一瞬间什么也看不见。<br>
新闻记者围着押送车不停按着快门。<br>
有人朝押送车跑了过来，手里拿着话筒。<br>
「??的第??届?程??、由????同学??。接下来想?采访一下?。<br>
首先，请?谈谈获?优胜的感想？」<br>
<br>
听不太清说的什么，不过好像是在采访我。<br>
对了，我是这场游戏的优胜者。今晚的新闻大概就会播出来吧。<br>
下一次闪光灯亮起的瞬间，不知为何，我竖起了大拇指。<br>
然后，补充了一句。<br><br>
「{sex}{no}号 {f_name}{l_name}」<br><br>
一边念着名字、一边竖着大拇指，心里这样想着的自己。<br>
『我要连大家的份一起活下去。绝对???绝对???』<br>
而且还???带着笑容。<br>
因为我觉得，这是自己能为同学们做到的回报。<br>
不知为什么。<br>
虽然在旁人看来，那也许只是抽搐僵硬的笑容。<br>
<br>
然后，在念完最后一位同学的名字之后，<br>
一把扯下了左耳上GROM HEARTS的耳钉。<br>
「好痛」<br>
不由得叫出了声。<br>
鲜血从左耳流了下来。<br>
<br>
　「我要和大家一起，留在这里」<br>
<br>
在心中这样低语的下一瞬间，<br>
一道血痕、<br>
一滴泪水、<br>
和耳钉一起在空中飞舞。<br>
?<br>
?<br>
?<br>
?<br>
?<br>
那天傍晚，新宿Alta前的广场上像往常一样聚集着人群。<br>
无所事事、闲得发慌的人们。<br>
对着手机拼命说话的人们。<br>
实际上，抬头看着大屏幕Alta Vision的人并不多。<br>
<br>
「日前进行的程序，其优胜者已经决出！<br>
下面请看来自现场的连线报道」<br>
连线画面里，映出了优胜者的身影。<br>
<br>
「这次的优胜者就是这个家伙啊。居然还在笑。哼！杀人犯。」<br>
一个正埋头用手机拼命发短信的年轻人抬起头说道。<br>
随着他抬起头，左耳的银色耳钉晃了晃。<br>
他看不见优胜者那带血的泪水。<br>
当然，也听不见那微微哼念着的同学们的名字。<br>
<br>
不过，他的注意力马上转到了别的地方。<br>
「哦！发现一个美女！」<br>
瘫坐在地上的他拖着沉重的身子站了起来，<br>
朝一个女子跑了过去。<br>
<br>
<br>
　一枚GROM HEARTS的耳钉映着霓虹的灯光，<br>
　另一枚GROM HEARTS的耳钉则???<br>
<br>
<br>
<br>
Now，‘‘1 student remaining’’．<br>
Surely 1 is lonly．<br>
But there is hope there．"""

ENDING_ESCAPE_OTHERS = """冷不防，警报声贯穿了耳膜。<br>
优胜者决出来了吗…？不，明明应该还有幸存的同学才对…。<br>
正想着，一个十分熟悉的同学的声音在四周回荡开来。<br>
「程序已经结束了！不用再战斗了！！」<br>
<br>
简直不敢相信。<br>
竟然从这个恶魔的程序中逃了出来。可是，我们接下来该怎么办？<br>
和同学们一起对抗政府？<br>
还是四散逃走，各自积蓄力量？<br>
或者干脆什么都不想，先回家？<br>
已经没有时间犹豫了。禁区的解除到今晚０：００就会恢复原状。<br>
而且，再磨磨蹭蹭的话，程序执行总部的士兵们就会来处决我们了。<br>
「………」<br>
首先，摘下了把我们拴在这里的项圈。<br>
收起武器，深深地吸了一口气……<br>
<br>
总之先从这里逃出去吧。<br>
今后的事，之后再想也不迟。<br>
我们就是『希望』。对抗这个恶魔的游戏、这个世纪恶法的『希望』。<br>
也许是诞生自绝望之中的希望…但也要走到能走的最远处！<br>
要一直跑下去，直到倒下为止……！！<br>
<br>
<br>
「程序紧急停止后，从会场逃出的少年们目前仍然……」<br>
……一个少年望着街头大屏幕上播放的临时新闻。<br>
咬紧嘴唇，握紧拳头，神情凝重。<br>
「跑吧…！走到能走的最远处！」<br>
无视下一条新闻，少年逆着人流、像游泳一样奔跑起来。"""

ENDING_ESCAPE_KEYUSER = """　<br>
「呼…呼……」<br>
眼前躺着的，是把我们送进这个程序的男人的尸体……坂持金发。<br>
就是这家伙……就是因为他，我们才被推进了这个程序。<br>
其中没有我们的意愿，只有强加于人的、蛮横无理的暴力。<br>
摸索他的衣服，手触到了一个像电子钥匙一样的东西。<br>
用它的话……自己，还有幸存的大家，都能从这个游戏中解放出来…。<br>
「………」<br>
可是，我犹豫了。<br>
这样真的可以吗？真的能从政府手里逃掉吗？<br>
不……那种事之后再考虑也行。<br>
只要能从和同学自相残杀的荒唐境地里解脱出来…。<br>
<br>
刷过钥匙，游戏结束的电子音响起，项圈「咔啷」一声高响着掉落在地上。<br>
然后，拿起那支想必曾宣报过无数同学死讯的话筒，深吸一口气。<br>
「程序已经结束了！不用再战斗了！！」<br>
<br>
能做的都已经做了。<br>
剩下的，就该由幸存的大家各自去考虑了。<br>
没有时间在这种地方磨蹭了。<br>
因为比程序更加严酷的现实，正在前方等着我们…。<br>
今后的事，只能由自己来决定…。<br>
<br>
「涉嫌紧急停止程序的学生目前仍然……」<br>
……一个少年望着街头大屏幕上播放的临时新闻。<br>
嘴角浮着笑意，双手插在口袋里，一脸无所畏惧的表情。<br>
「加油吧……反正没有人会来救你们的……」<br>
无视下一条新闻，少年撞开人群、像逃跑一样离去了。"""

# 注册校验错误文案(regist.cgi REGIST/MAIN)
REGISTER_ERRORS = {
    "closed": "新游戏的注册已经终止了。<br><br>　请耐心等待下一次游戏的开始。",
    "dead_reentry": "游戏者死亡之后、２小时内不能再次登陆。<br><br>　下次可注册时间：{time}",
    "full": "非常抱歉，参加人数（{max}人）已满。",
    "multi_id": "本游戏禁止一人使用多个ID。如有问题请与管理员联系。",
    "f_name_empty": "姓的一栏里没有输入字符。",
    "f_name_len": "姓的一栏里输入错误（请使用不超过4位的汉字）",
    "f_name_half": "名的一栏里不能使用半角字符（请使用不超过4位的汉字）",
    "l_name_empty": "名的一栏里没有输入字符。",
    "l_name_len": "名的一栏里输入错误（请使用不超过4位的汉字）",
    "l_name_half": "名的一栏里不能使用半角字符（请使用不超过4位的汉字）",
    "no_sex": "没有选择性别。",
    "id_len": "ID输入错误。（ID请使用8位以内的英文字符和数字。）",
    "id_empty": "ID没有输入。",
    "id_half": "ID请使用半角字符。（8位以内的英文字符和数字）",
    "id_forbidden": "ＩＤ使用了禁止的字符。",
    "pw_empty": "没有输入密码。",
    "pw_len": "密码填写错误。（8位以内的英文字符和数字）",
    "pw_half": "password填写请使用半角字符。（8位以内的英文字符和数字）",
    "pw_forbidden": "密码填写使用了禁止的字符。",
    "id_eq_pw": "ID和密码使用了相同的字符。",
    "msg_len": "口癖填写错误。（请使用32位以内的汉字）",
    "dmes_len": "遺言填写错误。（请使用32位以内的汉字）",
    "com_len": "座右铭填写错误。（请使用32位以内的汉字）",
    "male_full": "男学生名额以满。",
    "female_full": "女学生名额以满。",
    "dup": "错误：有相同ID或者姓名的人存在。",
}

# 通用消息(battle.cgi / lib2.cgi / item.cgi 等;实现各阶段时继续补充)
MESSAGES = {
    "now_what": "现在怎么办呢？<br>",
    "where_go": "现在去哪里呢？<br><br>",
    "move_arrive_next_forbidden": "{place}移动到达。这里是下次禁止的地区。<br>{arinfo}<br>",
    "move_arrive": "{place}移动到达。<br>{arinfo}<br>",
    "move_forbidden": "{place}现在是禁止地区。赶快离开……。<br>",
    "search_start": "{name}、在四周进行探索。<br>",
    "search_nothing": "但是、什么都没有发现。<br>",
    "sense_people": "感觉到有什么人潜伏着的气息???。是错觉吗？<br>",
    "sleep_effect": "睡眠的效果，耐力恢复了{up}。<br>",
    "heal_effect": "治疗的效果，体力恢复了{up}。<br>",
    "start_sleep": "稍微睡一会儿。<br>",
    "start_heal": "来治疗伤口吧。<br>",
    "drain": "{name}的耐力耗尽。最大HP减少。<br>",
    "dead_line": "<span class=\"red\"><b>{f_name} {l_name}（{cl} {sex}{no}号）已经死亡。</b></span><br>",
    "first_aid_done": "应急治疗完成。<br>",
    "corpse_found": "发现了{f_name} {l_name}的尸体。<br>",
    "corpse_tail": CORPSE_DESC_TAIL,
    "no_carry": "没办法再携带更多物品了。<br>",
    "self_pick": "试着抢夺了自己的物品。<br>真是空虚???。<br>",
    "pick_give_up": "放弃了拾取。<br>",
    "pick_want": "强烈地念叨着想要{f_name}的那件物品。<br>真是空虚???。<br>",
    "got_item": "{name} 得到了{item}。<br>",
    "msg_changed": "口癖变更完成。<br>",
    "already_dead": "你已经死亡了。<br><br>死因：{death}<br><br><span class=\"lime\"><b>{msg}</b></span><br>",
    "wrong_pass": "密码不正确。",
    "no_id": "ＩＤ不见了。",
    "bad_access": "不正确的存取。",
    "gunshot_near": "<span class=\"yellow\"><b>{place} 的方向传来一声枪响。</b></span><br>",
    "scream_near": "<span class=\"yellow\"><b>旁边传来绝望的悲鸣？是谁被杀了？</b></span><br>",
    "announce_near": "<span class=\"yellow\"><b>{place} 的方向传来{name}的声音?</b></span><br><span class=\"lime\"><b>『{speech}』</b></span><br>",
}


def build_texts():
    return dict(
        arinfo=ARINFO,
        corpse=CORPSE_DESC,
        corpse_default=CORPSE_DESC_DEFAULT,
        corpse_tail=CORPSE_DESC_TAIL,
        events=EVENTS,
        place_events=PLACE_EVENTS,
        intro=INTRO,
        home_intro=HOME_INTRO,
        ending_win=ENDING_WIN,
        ending_escape_others=ENDING_ESCAPE_OTHERS,
        ending_escape_keyuser=ENDING_ESCAPE_KEYUSER,
        register_errors=REGISTER_ERRORS,
        messages=MESSAGES,
    )


def main():
    check_only = "--check" in sys.argv
    weapons = migrate_weapons()
    personal = migrate_personal()
    items = migrate_items()
    npcs = migrate_npcs()
    texts = build_texts()

    report = {
        "weapons": len(weapons),
        "personal_items": len(personal),
        "npcs": len(npcs),
        "item_places": {k: len(v) for k, v in items.items()},
        "extra_placements": len(EXTRA_PLACEMENTS),
        "corpse_variants": {k: len(v) for k, v in CORPSE_DESC.items()},
        "arinfo": len(ARINFO),
    }
    print(json.dumps(report, ensure_ascii=False, indent=1))

    # 对等校验
    assert len(weapons) == 44, f"武器应为 44 条,实际 {len(weapons)}"
    assert len(personal) == 19, f"私人物品应为 19 条,实际 {len(personal)}"
    assert len(npcs) == 4, f"NPC 应为 4 条,实际 {len(npcs)}"
    assert len(ARINFO) == 22, "地点描述应为 22 条"
    assert all(len(v) == 7 for v in CORPSE_DESC.values()), "尸体描述每类应为 7 变体"
    key_npc = [n for n in npcs if any(i and i["name"] == "程序解除钥匙" for i in n["items"])]
    assert len(key_npc) == 1 and key_npc[0]["class_name"] == "班主任", "班主任应携带程序解除钥匙"
    # 合成素材齐备性:配方两种素材均可获得(地点投放 ∪ 私人物品 ∪ 配发武器)
    all_names = {it["name"] for lst in items.values() for it in lst}
    all_names |= {w["name"] for w in personal} | {w["name"] for w in weapons}
    recipes = [("轻油", "肥料"), ("汽油", "空瓶"), ("雷管", "火药"),
               ("火药", "导火索"), ("喷雾罐", "打火机"), ("手机", "苹果电脑")]
    for a, b in recipes:
        assert a in all_names, f"合成素材 {a} 未投放"
        assert b in all_names, f"合成素材 {b} 未投放"
    assert "毒药" in all_names and "携带式扩音器" in all_names, "毒药/扩音器应投放"

    if check_only:
        print("check OK")
        return

    for fname, data in [("weapons.json", weapons), ("personal_items.json", personal),
                        ("items.json", items), ("npcs.json", npcs), ("texts.json", texts)]:
        with open(os.path.join(OUT, fname), "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
        print("wrote", fname)


if __name__ == "__main__":
    main()
