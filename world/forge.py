"""Deterministic character forge.

`forge_cast` builds a cast from a seed, a size, an era (`jianghu` or `town`) and optional archetype
limits and field locks. The same arguments always produce the same bytes. Randomness comes only from
`world.rng.rng`. A lock keeps that field and leaves every other roll where it was.

Charm is the same number as looks, unless both were locked to different values.
A person whose age was locked under 18 is marked out of the romance line and is attracted to nobody,
unless `attracted_to` itself was locked.

When `size >= 6` the cast has at least one nemesis pair, one secret, one one-way crush (both adults,
the admirer's orientation includes the other's gender) and one underestimated person. Two of the
archetypes are reserved for that when they are in the pool: 被看輕的天才 and 藏著秘密的人.

Given names are split into a male pool and a female pool, for both eras. The two pools do not overlap,
and a cast does not reuse a given name. Each archetype carries at least three inner-text sets per era.
While one of those sets is still unused, another person of the same archetype in the cast will not draw it.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass

from contracts.base import from_dict
from contracts.character import VALUE_KEYS, CharacterProfile, CharacterRoster, check_roster
from contracts.persona import TEMPERAMENT_KEYS
from world.personas import PersonaError, lift
from world.rng import rng

# The same ban list as tests/test_drama_content.py. Generated names are rejected against it.
FAMOUS = (
    "令狐沖", "楊過", "蕭峰", "郭靖", "黃蓉", "小龍女", "張無忌", "韋小寶", "段譽", "虛竹", "喬峰", "任盈盈",
    "東方不敗", "岳不群", "李尋歡", "楚留香", "陸小鳳", "花滿樓", "西門吹雪", "傅紅雪", "燕南天", "蕭十一郎",
    "沈浪", "王憐花", "朱七七", "林仙兒", "葉孤城", "司空摘星", "丁鵬", "謝曉峰", "小李飛刀",
)

SURNAMES = (
    "沈", "秦", "柳", "顧", "江", "謝", "宋", "魏", "薛", "周", "韓", "陸", "蘇", "白", "穆", "裴",
    "崔", "羅", "潘", "方", "袁", "唐", "曹", "鄧", "馮", "許", "何", "趙", "錢", "孫", "程", "丁",
)
# One-character and two-character given names. Male and female pools do not share a name.
GIVEN_MALE_ONE = (
    "遠", "川", "昭", "衡", "朗", "澈", "晏", "珩", "舟", "淵", "岐", "岑",
    "鶴", "硯", "鋒", "剛", "毅", "博", "澤", "謙", "桓", "晟", "修", "凱",
)
GIVEN_FEMALE_ONE = (
    "寧", "禾", "吟", "霜", "嵐", "岫", "珂", "瑜", "珀", "棠",
    "婉", "妍", "芷", "薇", "瑤", "琪", "嫣", "淑", "蘭", "菲",
)
GIVEN_MALE_TWO = (
    "懷瑾", "照夜", "知秋", "問舟", "聽瀾", "拾燈", "歸雁", "長歌", "未央", "如晦", "景行",
    "子寧", "明遠", "思齊", "清越", "凌川", "寄雲", "臨風", "書白", "嘉樹", "敬之", "承志",
)
GIVEN_FEMALE_TWO = (
    "清禾", "晚吟", "疏影", "微涼", "南枝", "若溪", "漱玉", "聽雪", "靜姝", "望舒",
    "清婉", "晚晴", "如霜", "念慈", "采薇", "懷瑜", "聽雨", "依雲", "若蘭", "靜宜",
)
GIVEN_MALE = GIVEN_MALE_ONE + GIVEN_MALE_TWO
GIVEN_FEMALE = GIVEN_FEMALE_ONE + GIVEN_FEMALE_TWO
GIVEN_ONE = GIVEN_MALE_ONE + GIVEN_FEMALE_ONE
GIVEN_TWO = GIVEN_MALE_TWO + GIVEN_FEMALE_TWO
TOWN_SURNAMES = (
    "陳", "林", "黃", "張", "李", "王", "吳", "劉", "蔡", "楊", "許", "鄭", "洪", "郭", "邱", "曾", "徐", "周", "蘇", "高",
)
TOWN_GIVEN_MALE = (
    "承恩", "柏宇", "家豪", "品睿", "冠宇", "柏翰", "宇軒", "承翰", "子豪", "宥廷", "宸安",
    "柏睿", "家維", "品辰", "冠廷", "宇恩", "承宇", "子謙", "宥豪", "宸宇", "柏安", "家廷",
)
TOWN_GIVEN_FEMALE = (
    "雅婷", "欣怡", "宜臻", "心柔", "詩涵", "依婷", "佳穎", "欣妍", "品妍", "予恩", "可恩",
    "詠恩", "子涵", "雅筑", "心怡", "宜庭", "詩婷", "依琳", "佳恩", "品萱", "宥萱", "詠晴", "可馨",
)
TOWN_GIVEN = TOWN_GIVEN_MALE + TOWN_GIVEN_FEMALE

JIANGHU_TOPICS = {
    "swordplay": "劍法", "manuals": "劍譜典籍", "duels": "比武論劍", "tea": "茶", "wine": "酒",
    "chess": "下棋", "horses": "馬匹", "escort": "鏢局的事", "legends": "江湖傳說", "herbs": "藥草",
    "rumours": "江湖傳聞", "poetry": "詩詞", "fishing": "垂釣", "cooking": "下廚做菜", "roaming": "浪跡天涯",
    "cats": "野貓", "zither": "琴曲", "silver": "銀兩", "attire": "衣裳", "ink": "丹青",
    "sect_rules": "門規", "rival_sect": "對頭門派", "elders": "長老訓話", "overtraining": "加練",
    "noise": "喧嘩吵鬧", "lying": "說謊", "borrowing": "借銀兩", "showing_off": "炫耀武藝",
    "being_ordered": "被呼來喝去", "prying": "被打聽私事",
}
TOWN_TOPICS = {
    "fishing": "釣魚", "movies": "電影", "basketball": "籃球", "cooking": "做菜", "coffee": "咖啡",
    "travel": "旅行", "cats": "貓", "music": "音樂", "gossip": "八卦", "money": "理財", "games": "電玩",
    "reading": "閱讀", "plants": "盆栽", "fashion": "穿搭", "drawing": "畫畫", "the_boss": "主管",
    "overtime": "加班", "noise": "吵鬧", "lying": "說謊", "borrowing": "借錢", "showing_off": "炫耀",
    "being_ordered": "被使喚", "prying": "被打聽私事", "commute": "捷運",
}
TOPICS = {"jianghu": JIANGHU_TOPICS, "town": TOWN_TOPICS}

JIANGHU_JOB_WORDS = {
    "work": "練功", "superior": "掌門", "overtime": "加練", "praise": "得到掌門的誇獎",
    "quit": "離開師門", "look": "打聽別的門派", "offer": "收到別派相邀",
    "accept": "答應了別派", "decline": "婉拒了別派", "lapse": "別派的邀約過期了",
}
TOWN_JOB_WORDS = {
    "work": "上班", "superior": "主管", "overtime": "加班", "praise": "得到主管的誇獎",
    "quit": "辭職", "look": "看看別的工作", "offer": "收到別的邀約",
    "accept": "答應了", "decline": "婉拒了", "lapse": "邀約過期了",
}
JOB_WORDS = {"jianghu": JIANGHU_JOB_WORDS, "town": TOWN_JOB_WORDS}
DUTY = {"jianghu": "train", "town": "work"}

BIRTHPLACES = {
    "jianghu": (
        "朔北黑石堡", "江南水鄉", "南嶺山村", "清河鎮", "東海漁港", "京城外城",
        "巴蜀山城", "隴西小鎮", "雲夢澤邊", "閩南漁村", "關中的村子", "塞外驛站",
    ),
    "town": (
        "台中", "高雄", "台北", "這座城市", "南部小鎮", "外縣市", "基隆港邊", "花蓮的小鎮",
    ),
}

# (role, place id, superior). The superior is an offstage name, as in the hand-written rosters.
# want, fear, wound, false belief, need, life question, life goal, season goal, blurb.

def _core(want, fear, wound, belief, need, question, life, season, blurb):
    return {
        "want": want, "fear": fear, "wound": wound, "false_belief": belief, "need": need,
        "life_question": question, "life_goal": life, "season_goal": season, "blurb": blurb,
    }


def _look(face, hair, build, mark, presence, costume_f, costume_m):
    return {
        "face": face, "hair": hair, "build": build, "mark": mark, "presence": presence,
        "costume": {"female": costume_f, "male": costume_m},
    }


def _voice(timbre, pace, *phrases):
    return {"timbre": timbre, "pace": pace, "catchphrases": list(phrases)}


_CORE_KEYS = ("want", "fear", "wound", "false_belief", "need", "life_question", "life_goal", "season_goal", "blurb")
_LOCK_FIELDS = set(_CORE_KEYS) | set(VALUE_KEYS) | set(TEMPERAMENT_KEYS) | {
    "name", "age", "gender", "archetype", "blurb", "looks", "warmth", "talkativeness", "charm",
    "attracted_to", "attachment", "conflict", "temperament", "values",
}

ARCHETYPES = {
    "被看輕的天才": {
        "p_female": 0.45,
        "age": (18, 28),
        "job_p": 0.92,
        "temperament": {
            "honesty": (0.55, 0.85), "temper": (0.35, 0.65), "gossip": (0.05, 0.25),
            "generosity": (0.35, 0.60), "absent_minded": (0.25, 0.55), "curiosity": (0.78, 0.96),
        },
        "values": {
            "truth": (0.70, 0.90), "loyalty": (0.40, 0.65), "security": (0.30, 0.55),
            "belonging": (0.25, 0.50), "ambition": (0.45, 0.70), "freedom": (0.40, 0.65),
            "family": (0.35, 0.60), "fairness": (0.68, 0.92), "revenge": (0.20, 0.45),
        },
        "looks": (0.40, 0.62), "warmth": (0.28, 0.48), "talkativeness": (0.18, 0.40),
        "attachment": ("avoidant", "anxious"),
        "conflict": ("bottle_up", "confront"),
        "social": {"strangers": ("客氣", "話少"), "friends": ("沉默", "愛逞強"), "intimate": ("嘴硬", "不願多說")},
        "affinity": {
            "jianghu": {
                "interests": ("manuals", "swordplay", "chess", "fishing", "poetry"),
                "dislikes": ("showing_off", "elders", "being_ordered", "rumours"),
            },
            "town": {
                "interests": ("reading", "games", "fishing", "drawing", "cooking"),
                "dislikes": ("showing_off", "the_boss", "being_ordered", "gossip"),
            },
        },
        "roles": {
            "jianghu": (("外門弟子", "sect", "掌門"), ("守閣人", "library", "掌門")),
            "town": (("職員", "office", "主管"), ("研究助理", "office", "主管")),
        },
        "family": {
            "jianghu": (
                "父親是退隱的老鏢師，從不稱讚{ta}",
                "師父把{ta}的悟性當成胡思亂想",
            ),
            "town": (
                "父親從不稱讚{ta}，家裡只問成績",
                "主管當眾把{ta}的點子帶過去",
            ),
        },
        "education": {
            "jianghu": ("外門弟子出身，高深的招沒人肯教", "在藏書閣自己摸過幾年劍譜"),
            "town": ("大學讀的是冷門科系，沒人當回事", "專科畢業，提案常被笑著放下"),
        },
        "habits": {
            "jianghu": (
                ("after_work", "practise_quiet", "收功後自己又練到天黑"),
                ("alone", "read_manual", "獨處時把劍譜翻到舊頁"),
                ("angry", "go_quiet", "生氣時反而不說話"),
                ("stressed", "polish_sword", "心煩就一遍遍擦劍"),
            ),
            "town": (
                ("after_work", "keep_working", "下班後自己又把稿子改一輪"),
                ("alone", "read_notes", "一個人時翻自己的筆記"),
                ("angry", "go_quiet", "生氣時反而不說話"),
                ("stressed", "tidy_desk", "壓力大就一直整理桌面"),
            ),
        },
        "cores": {
            "jianghu": (
                _core(
                    "讓師門看見自己真正的劍法", "一輩子被當成不成器的弟子",
                    "入門試劍時被師兄當眾譏笑，掌門也沒有出聲", "只有一鳴驚人，才會有人正眼看我",
                    "承認自己已經夠好，不必等別人點頭", "我是要被看見，還是自己看見自己？",
                    "練成一門配得上自己的劍", "在門派比試裡拿出不敢藏的那一劍",
                    "劍法遠在眾人之上，師門卻只當{ta}是個不起眼的弟子",
                ),
                _core(
                    "證明當年沒收的那個徒弟，其實是對的", "才華爛在沒人問的角落",
                    "師父從不讓{ta}練高深的招", "不被認可的本事，就不算本事",
                    "為自己練，而不是為了堵住別人的嘴", "沒有人鼓掌的時候，我還練不練？",
                    "讓自己的劍自己說話", "找一個肯看完{ta}整套劍的人",
                    "悟性極高，卻被當成愛空想的普通弟子",
                ),
                _core(
                    "在沒有人看的場子裡，也把劍練完", "哪天連自己都相信了那些輕視",
                    "一次閉門試煉，{ta}破了關，紀錄上卻寫著別人的名字", "名字沒被記下的勝，就不算勝",
                    "把紀錄訂正過來，也把心思從別人的筆上挪開", "沒有名字的那一劍，還算我的嗎？",
                    "留下一套署名是自己的劍法", "在下一次閉門試煉裡自己報上名",
                    "破關的紀錄寫著別人的名字，劍卻是{ta}練的",
                ),
            ),
            "town": (
                _core(
                    "讓公司看見自己真正的本事", "一輩子被當成多餘的人",
                    "提案被主管當眾笑掉，同事也沒有人幫腔", "只有一鳴驚人，才會有人正眼看我",
                    "承認自己已經夠好，不必等別人點頭", "我是要被看見，還是自己看見自己？",
                    "做出一件配得上自己的作品", "在這季的提案裡拿出不敢藏的那一版",
                    "本事遠在同事之上，辦公室裡卻只當{ta}是個不起眼的人",
                ),
                _core(
                    "證明當初沒被錄取的那份履歷，其實是對的", "點子爛在沒人打開的檔案裡",
                    "主管說{ta}想太多，從不讓{ta}獨立做", "不被採用的本事，就不算本事",
                    "為自己做，而不是為了堵住別人的嘴", "沒有人鼓掌的時候，我還做不做？",
                    "讓作品自己說話", "找一個肯看完{ta}整份稿的人",
                    "想得比周圍的人深，會議上卻常常被跳過",
                ),
                _core(
                    "在沒有人看的時候，也把事情做完", "哪天連自己都相信了那些輕視",
                    "一次內部評比，{ta}寫的稿得了前頭，署名卻換成別人", "名字沒被記下的成果，就不算成果",
                    "把署名要回來，也把心思從別人的筆上挪開", "沒有名字的那一版，還算我的嗎？",
                    "留下一件署名是自己的作品", "在下一次評比裡自己掛上名",
                    "得前頭的那份稿署名是別人，字卻是{ta}寫的",
                ),
            ),
        },
        "looks_pool": {
            "jianghu": (
                _look("眉眼清淡，不笑的時候像在想別的事", "頭髮隨便束著，常有一綹落下來", "瘦", "手指有磨出來的薄繭",
                      "站在人後頭，劍出鞘才有人回頭", "洗得發舊的灰布長衫", "洗得發舊的灰布長衫"),
                _look("窄臉，眼神專注得有點兇", "低髻，用一根舊木簪別住", "中等偏瘦", "袖口永遠磨得發白",
                      "不起眼，直到{ta}把一套劍練完", "素色短褐", "素色短褐"),
            ),
            "town": (
                _look("眉眼清淡，不笑的時候像在想別的事", "頭髮隨便紮著", "瘦", "指側有寫字磨出來的痕",
                      "坐在角落，把東西做出來才有人看", "洗得發白的襯衫", "洗得發白的襯衫"),
                _look("窄臉，眼神專注", "短髮，有點亂", "中等偏瘦", "背包帶舊了",
                      "不起眼，直到{ta}把一件事做完", "深色外套", "深色外套"),
            ),
        },
        "voices": (
            _voice("偏輕", "慢，想清楚才說", "這一套我練過", "你看完再說"),
            _voice("平", "不多，一句是一句", "我可以再做一版", "不是那樣"),
        ),
    },
    "野心家": {
        "p_female": 0.40,
        "age": (24, 40),
        "job_p": 0.96,
        "temperament": {
            "honesty": (0.25, 0.55), "temper": (0.48, 0.78), "gossip": (0.30, 0.55),
            "generosity": (0.10, 0.32), "absent_minded": (0.05, 0.22), "curiosity": (0.40, 0.65),
        },
        "values": {
            "truth": (0.25, 0.50), "loyalty": (0.15, 0.38), "security": (0.35, 0.60),
            "belonging": (0.18, 0.42), "ambition": (0.86, 0.98), "freedom": (0.42, 0.70),
            "family": (0.20, 0.45), "fairness": (0.18, 0.42), "revenge": (0.42, 0.72),
        },
        "looks": (0.52, 0.74), "warmth": (0.12, 0.34), "talkativeness": (0.46, 0.72),
        "attachment": ("avoidant",),
        "conflict": ("confront", "sulk"),
        "social": {"strangers": ("客氣", "會看人下菜"), "friends": ("愛逞強", "算計"), "intimate": ("不把話說明", "要人先讓")},
        "affinity": {
            "jianghu": {
                "interests": ("duels", "rival_sect", "escort", "silver", "sect_rules"),
                "dislikes": ("being_ordered", "elders", "lying", "noise"),
            },
            "town": {
                "interests": ("money", "gossip", "basketball", "coffee", "travel"),
                "dislikes": ("being_ordered", "the_boss", "lying", "noise"),
            },
        },
        "roles": {
            "jianghu": (("首席候補", "sect", "掌門"), ("鏢師", "escort", "鏢頭")),
            "town": (("業務", "office", "主管"), ("店長候補", "shop", "主管")),
        },
        "family": {
            "jianghu": ("家道中落過，有人當面踩過{ta}", "從小看人臉色吃飯，發誓要翻過來"),
            "town": ("家裡做過生意，垮的時候沒有人伸手", "親戚裡有人當面說過{ta}沒出息"),
        },
        "education": {
            "jianghu": ("小門派出身，早就想往上走", "跟過一位狠角色，學會了把功勞留在自己名下"),
            "town": ("大學讀商，實習時就在搶案子", "專科畢業，第一份工作就盯著升遷"),
        },
        "habits": {
            "jianghu": (
                ("morning", "arrive_first", "天不亮就到練功場，占中間的位子"),
                ("stressed", "count_allies", "焦慮時在心裡數誰站在自己這邊"),
                ("happy", "talk_big", "高興時話裡全是下一步"),
                ("evening", "review_day", "夜裡把白天誰說了什麼再想一遍"),
            ),
            "town": (
                ("morning", "arrive_first", "最早到辦公室，占靠窗的位子"),
                ("stressed", "check_mail", "焦慮時一直看信箱裡有沒有回覆"),
                ("happy", "talk_big", "開心時話裡全是下一步"),
                ("after_work", "network", "下班還約人喝咖啡談事情"),
            ),
        },
        "cores": {
            "jianghu": (
                _core(
                    "坐上這片地盤最高的位子", "一輩子寄人籬下",
                    "少年時看著家道中落，有人當面踩過{ta}", "只有壓過所有人，才不會再被踩",
                    "明白位子保不住{ta}真正怕失去的東西", "爬到頂的時候，我還剩什麼？",
                    "自立門戶，不再看人臉色", "把掌門面前的功勞留在自己名下",
                    "步步算計，眼睛盯著那個還空著的位子",
                ),
                _core(
                    "讓當初瞧不起{ta}的人低頭", "被人看穿自己其實怕輸",
                    "一次比武被判輸，{ta}覺得是有人做了手腳", "不狠，就會被更狠的人吃掉",
                    "學會贏不必踩著別人", "我要的是位子，還是別人的畏懼？",
                    "成為這一代說了算的人", "拉攏兩個能替{ta}說話的人",
                    "笑的時候也在盤算，誰能幫{ta}往上走",
                ),
                _core(
                    "把對頭門派的人挖到自己這邊", "跟班忽然倒向別人",
                    "有一次{ta}把功勞分出去，對方轉頭就拿去領賞", "分出去的東西，就會變成別人的梯子",
                    "明白分一點也不會少掉自己要的位子", "我防的是對手，還是所有人？",
                    "建一個只聽自己號令的班底", "把一個動搖的人重新拉回來",
                    "功勞從不外流，連盟友也只信一半",
                ),
            ),
            "town": (
                _core(
                    "坐上這間公司說了算的位子", "一輩子看主管的臉色",
                    "家裡的店垮的那年，有人當面踩過{ta}", "只有壓過所有人，才不會再被踩",
                    "明白頭銜保不住{ta}真正怕失去的東西", "爬到頂的時候，我還剩什麼？",
                    "自己當家，不再看人臉色", "把這季的業績留在自己名下",
                    "步步算計，眼睛盯著那個還空著的位子",
                ),
                _core(
                    "讓當初瞧不起{ta}的人低頭", "被人看穿自己其實怕輸",
                    "一次評比被刷掉，{ta}覺得是有人做了手腳", "不狠，就會被更狠的人吃掉",
                    "學會贏不必踩著別人", "我要的是位子，還是別人的畏懼？",
                    "成為這裡說了算的人", "拉攏兩個能替{ta}說話的同事",
                    "笑的時候也在盤算，誰能幫{ta}升上去",
                ),
                _core(
                    "把對頭部門的人挖到自己這邊", "跟班忽然倒向別人",
                    "有一次{ta}把功勞分出去，對方轉頭就拿去跟主管請賞", "分出去的東西，就會變成別人的梯子",
                    "明白分一點也不會少掉自己要的位子", "我防的是對手，還是所有人？",
                    "建一個只聽自己號令的班底", "把一個動搖的同事重新拉回來",
                    "業績從不外流，連盟友也只信一半",
                ),
            ),
        },
        "looks_pool": {
            "jianghu": (
                _look("笑起來很快，眼睛卻在看人", "頭髮梳得一絲不亂", "中等偏高", "腰間的牌子擦得很亮",
                      "進門就往中間站", "裁得合身的深色長衫", "裁得合身的深色長衫"),
                _look("眉目銳，笑不達眼底", "高髻，整整齊齊", "精瘦", "袖裡常多一封沒寄出的信",
                      "讓人覺得{ta}下一句就要談條件", "玄色箭袖", "玄色箭袖"),
            ),
            "town": (
                _look("笑起來很快，眼睛卻在看人", "頭髮梳得一絲不亂", "中等偏高", "工牌掛得很正",
                      "進門就往中間坐", "合身的深色西裝外套", "合身的深色西裝外套"),
                _look("眉目銳，笑不達眼底", "短髮，整整齊齊", "精瘦", "手機殼磨舊了還不肯換",
                      "讓人覺得{ta}下一句就要談條件", "熨過的襯衫", "熨過的襯衫"),
            ),
        },
        "voices": (
            _voice("亮", "快，愛把話接過去", "這件事我來", "你考慮一下"),
            _voice("清晰", "有條理，帶一點壓", "按這個走", "功勞要算清楚"),
        ),
    },
    "老好人": {
        "p_female": 0.50,
        "age": (28, 48),
        "job_p": 0.84,
        "temperament": {
            "honesty": (0.62, 0.90), "temper": (0.05, 0.24), "gossip": (0.20, 0.45),
            "generosity": (0.78, 0.96), "absent_minded": (0.20, 0.45), "curiosity": (0.35, 0.58),
        },
        "values": {
            "truth": (0.48, 0.70), "loyalty": (0.72, 0.92), "security": (0.40, 0.62),
            "belonging": (0.82, 0.96), "ambition": (0.12, 0.36), "freedom": (0.22, 0.48),
            "family": (0.62, 0.86), "fairness": (0.55, 0.80), "revenge": (0.02, 0.14),
        },
        "looks": (0.40, 0.64), "warmth": (0.74, 0.93), "talkativeness": (0.50, 0.74),
        "attachment": ("anxious", "secure"),
        "conflict": ("appease", "avoid"),
        "social": {"strangers": ("親切", "笑臉"), "friends": ("照顧人", "不好意思拒絕"), "intimate": ("委屈自己", "怕讓人失望")},
        "affinity": {
            "jianghu": {
                "interests": ("cooking", "tea", "herbs", "legends", "cats"),
                "dislikes": ("lying", "noise", "showing_off", "borrowing"),
            },
            "town": {
                "interests": ("cooking", "plants", "cats", "coffee", "gossip"),
                "dislikes": ("lying", "noise", "showing_off", "borrowing"),
            },
        },
        "roles": {
            "jianghu": (("藥鋪夥計", "herb_shop", "掌櫃"), ("客棧夥計", "inn", "掌櫃")),
            "town": (("行政", "office", "主管"), ("鄰居裡辦事的人", "shop", "店長")),
        },
        "family": {
            "jianghu": ("家裡誰有事都找{ta}，拒絕一次就被說沒良心", "有個舊友疏遠了，{ta}一直覺得是自己沒幫上"),
            "town": ("家裡誰的忙都找{ta}，拒絕一次就被說沒良心", "有個老朋友疏遠了，{ta}一直覺得是自己沒幫上"),
        },
        "education": {
            "jianghu": ("鎮上長大，藥鋪裡打過雜", "沒正式拜過師，什麼雜事都會一點"),
            "town": ("大學讀一半去打工，後來沒再回去", "高職畢業，第一份工作就是幫人善後"),
        },
        "habits": {
            "jianghu": (
                ("at_meal", "share_food", "吃飯總多盛一碗，怕有人沒吃"),
                ("lonely", "seek_company", "寂寞時主動去找人說話"),
                ("hurt", "tend_herbs", "難過時去侍弄藥草"),
                ("evening", "check_on_people", "夜裡還去問一聲別人都好不好"),
            ),
            "town": (
                ("at_meal", "share_food", "吃飯總多買一份，怕有人沒吃"),
                ("lonely", "send_message", "寂寞時主動傳訊息問人"),
                ("hurt", "water_plants", "難過時去澆花"),
                ("after_work", "stay_late_help", "下班還留下來幫人收尾"),
            ),
        },
        "cores": {
            "jianghu": (
                _core(
                    "讓身邊的人都好好的", "有人因為自己的拒絕而受苦",
                    "有一次沒幫上忙，那人後來再也不來找{ta}", "拒絕別人，就是我的錯",
                    "學會有些忙可以不幫", "我幫了所有人，誰來問我想要什麼？",
                    "做一個讓人放心的人", "把欠人的人情還清，也不再隨便答應",
                    "誰開口都不好意思拒絕，自己的事總排在最後",
                ),
                _core(
                    "守住這群人，不讓他們散", "被說成薄情",
                    "家裡的人只在用得上{ta}的時候才想起{ta}", "我有用，別人才會留",
                    "知道自己不幫忙也值得被留下", "不做老好人的那天，還有人在嗎？",
                    "有幾個不必討好也在的朋友", "這回先把自己的事理清",
                    "熱心到虧待自己，還覺得是應該的",
                ),
                _core(
                    "有一天能說一次不行，而不跟著道歉", "說了不，就被整個院子孤立",
                    "{ta}替人頂了一回罪，那人事後只當沒這回事", "我吃虧，別人才會覺得我好",
                    "被虧待的時候也把自己算進去", "老好人做到底，還剩不剩自己？",
                    "學會把忙留一點給自己", "這回有一件事明確地拒絕",
                    "替人頂過罪，對方卻裝著不知道",
                ),
            ),
            "town": (
                _core(
                    "讓身邊的人都好好的", "有人因為自己的拒絕而受苦",
                    "有一次沒幫上忙，那人後來已讀不回", "拒絕別人，就是我的錯",
                    "學會有些忙可以不幫", "我幫了所有人，誰來問我想要什麼？",
                    "做一個讓人放心的人", "把欠人的人情還清，也不再隨便答應",
                    "誰開口都不好意思拒絕，自己的事總排在最後",
                ),
                _core(
                    "守住這群同事和鄰居，不讓他們散", "被說成薄情",
                    "家裡的人只在用得上{ta}的時候才打電話", "我有用，別人才會留",
                    "知道自己不幫忙也值得被留下", "不做老好人的那天，還有人在嗎？",
                    "有幾個不必討好也在的朋友", "這回先把自己的假請完",
                    "熱心到虧待自己，還覺得是應該的",
                ),
                _core(
                    "有一天能說一次不行，而不跟著道歉", "說了不，就被整個圈子孤立",
                    "{ta}替人背了一回黑鍋，那人事後只當沒這回事", "我吃虧，別人才會覺得我好",
                    "被虧待的時候也把自己算進去", "老好人做到底，還剩不剩自己？",
                    "學會把忙留一點給自己", "這回有一件事明確地拒絕",
                    "替人背過黑鍋，對方卻裝著不知道",
                ),
            ),
        },
        "looks_pool": {
            "jianghu": (
                _look("圓臉，笑起來眼角有紋", "頭髮用布巾束住，常有些亂", "中等", "手上總帶著一包點心",
                      "讓人覺得可以把麻煩交給{ta}", "米色的舊袍", "米色的舊袍"),
                _look("和氣的眼睛，容易先道歉", "中長髮，鬆鬆挽著", "微壯", "袖口常沾著藥草屑",
                      "人還沒開口，{ta}已經想幫忙", "藥鋪的青布圍裙", "短褐，腰間一條舊布帶"),
            ),
            "town": (
                _look("圓臉，笑起來眼角有紋", "頭髮用夾子隨便夾住", "中等", "包裡總有多的零食",
                      "讓人覺得可以把麻煩交給{ta}", "米色針織衫", "淺色休閒外套"),
                _look("和氣的眼睛，容易先道歉", "短髮，有點塌", "微壯", "袖口常沾著咖啡漬",
                      "人還沒開口，{ta}已經想幫忙", "店裡的圍裙", "皺一點的襯衫"),
            ),
        },
        "voices": (
            _voice("軟", "快，忙著圓場", "我來就好", "你們別這樣"),
            _voice("溫", "碎，一句裡塞很多關心", "吃了嗎", "沒關係，我可以"),
        ),
    },
    "藏著秘密的人": {
        "p_female": 0.55,
        "age": (22, 38),
        "job_p": 0.70,
        "temperament": {
            "honesty": (0.12, 0.38), "temper": (0.20, 0.45), "gossip": (0.04, 0.20),
            "generosity": (0.30, 0.55), "absent_minded": (0.32, 0.60), "curiosity": (0.34, 0.58),
        },
        "values": {
            "truth": (0.15, 0.38), "loyalty": (0.35, 0.60), "security": (0.78, 0.96),
            "belonging": (0.30, 0.55), "ambition": (0.22, 0.48), "freedom": (0.25, 0.50),
            "family": (0.58, 0.86), "fairness": (0.30, 0.55), "revenge": (0.12, 0.36),
        },
        "looks": (0.42, 0.68), "warmth": (0.20, 0.42), "talkativeness": (0.10, 0.30),
        "attachment": ("avoidant",),
        "conflict": ("avoid", "bottle_up"),
        "social": {"strangers": ("防備", "客氣而遠"), "friends": ("安靜", "話到一半就停"), "intimate": ("藏得很深", "不敢靠近")},
        "affinity": {
            "jianghu": {
                "interests": ("cats", "zither", "herbs", "ink", "roaming"),
                "dislikes": ("prying", "rumours", "noise", "showing_off"),
            },
            "town": {
                "interests": ("cats", "music", "drawing", "reading", "plants"),
                "dislikes": ("prying", "gossip", "noise", "showing_off"),
            },
        },
        "roles": {
            "jianghu": (("客棧後廚", "inn", "掌櫃"), ("藥鋪學徒", "herb_shop", "掌櫃")),
            "town": (("會計助理", "office", "主管"), ("夜班店員", "shop", "店長")),
        },
        "family": {
            "jianghu": ("母親臥病，湯藥錢是一筆重擔", "家裡只剩{ta}能撐，所以有些事不能說"),
            "town": ("母親生病，醫藥費壓著", "家裡只剩{ta}能撐，所以有些事不能說"),
        },
        "education": {
            "jianghu": ("山村出身，識得幾味草藥", "客棧後廚做過事，識字不多"),
            "town": ("高職畢業就去工作", "沒讀完大學，因為家裡突然需要錢"),
        },
        "habits": {
            "jianghu": (
                ("anxious", "touch_finger", "緊張時反覆摩挲自己的手指"),
                ("alone", "feed_cat", "獨處時去餵後院的野貓"),
                ("stressed", "check_bundle", "心慌就去摸行囊裡那件不能見人的東西"),
                ("evening", "stay_in", "天一黑就回自己的屋子"),
            ),
            "town": (
                ("anxious", "check_phone", "不安時一直看手機，又不敢點開"),
                ("alone", "feed_cat", "一個人時去餵流浪貓"),
                ("stressed", "lock_drawer", "心慌就去確認抽屜有沒有鎖"),
                ("evening", "stay_in", "下班就回家，不太赴約"),
            ),
        },
        "cores": {
            "jianghu": (
                _core(
                    "把秘密留到沒有人再追問", "事情被揭開，現在的日子就沒了",
                    "為了家裡的湯藥錢，做過一件見不得人的事", "說出來就什麼都沒了",
                    "承認，才能不再天天害怕", "我還算是個好人嗎？",
                    "讓在乎的人平安，秘密最好永遠沉著", "不讓任何人碰到那件舊事",
                    "笑得很淺，有一件事死也不肯說",
                ),
                _core(
                    "保住別人對自己的信任", "被最在乎的人當面拆穿",
                    "年少時辜負過一個信任{ta}的人，對方到現在不知道", "隱瞞是為了保護對方",
                    "把選擇權還給被瞞的人", "瞞著，算保護還是算背叛？",
                    "有一天能親口說完", "先把證據藏好",
                    "對誰都客氣，就是不讓人走近那一段過去",
                ),
                _core(
                    "把那封不該留下的信燒掉", "有人從字跡認出{ta}",
                    "一封求救的信被{ta}壓了下來，人沒有等到", "燒掉證據，事情就沒有發生過",
                    "面對那個人已經不在的事實", "我藏的是秘密，還是藏的是愧疚？",
                    "不再靠隱瞞過日子", "把那封信從夾層裡拿出來，自己看完",
                    "夾層裡壓著一封不敢燒的信",
                ),
            ),
            "town": (
                _core(
                    "把秘密留到沒有人再追問", "事情被揭開，現在的工作就沒了",
                    "為了家裡的醫藥費，做過一件見不得人的事", "說出來就什麼都沒了",
                    "承認，才能不再天天害怕", "我還算是個好人嗎？",
                    "讓在乎的人平安，秘密最好永遠沉著", "不讓任何人翻到那筆舊帳",
                    "笑得很淺，有一件事死也不肯說",
                ),
                _core(
                    "保住別人對自己的信任", "被最在乎的人當面拆穿",
                    "年少時辜負過一個信任{ta}的人，對方到現在不知道", "隱瞞是為了保護對方",
                    "把選擇權還給被瞞的人", "瞞著，算保護還是算背叛？",
                    "有一天能親口說完", "先把證據藏好",
                    "對誰都客氣，就是不讓人走近那一段過去",
                ),
                _core(
                    "把那段不該留下的話刪掉", "有人從用詞認出{ta}",
                    "一封求救的訊息被{ta}壓了下來，人沒有等到", "刪掉紀錄，事情就沒有發生過",
                    "面對那個人已經不在的事實", "我藏的是秘密，還是藏的是愧疚？",
                    "不再靠隱瞞過日子", "把那段對話從手機裡打開，自己看完",
                    "手機裡留著一段不敢刪的對話",
                ),
            ),
        },
        "looks_pool": {
            "jianghu": (
                _look("小臉，眼神常往旁邊避", "髮用深色布巾半掩", "嬌小", "總把一只舊布包抱在身前",
                      "安靜，問深了就變冷", "深色斗篷，帽沿壓低", "深色短褐，帽子壓低"),
                _look("膚色淡，笑一下就收回去", "低馬尾，很整齊", "瘦", "指節常常絞在一起",
                      "讓人覺得{ta}有一句話停在嘴邊", "素色布衣", "洗舊的青衫"),
            ),
            "town": (
                _look("小臉，眼神常往旁邊避", "帽子壓得很低", "嬌小", "總把一只舊帆布袋抱在身前",
                      "安靜，問深了就變冷", "深色連帽外套", "深色連帽外套"),
                _look("膚色淡，笑一下就收回去", "頭髮紮得很緊", "瘦", "指節常常絞在一起",
                      "讓人覺得{ta}有一句話停在嘴邊", "素色上衣", "灰色帽T"),
            ),
        },
        "voices": (
            _voice("輕", "慢，被問到會更短", "沒什麼", "你想多了"),
            _voice("乾", "停頓多", "以後再說", "別問了"),
        ),
    },
    "毒舌": {
        "p_female": 0.50,
        "age": (20, 40),
        "job_p": 0.80,
        "temperament": {
            "honesty": (0.68, 0.92), "temper": (0.62, 0.88), "gossip": (0.48, 0.76),
            "generosity": (0.15, 0.38), "absent_minded": (0.05, 0.22), "curiosity": (0.42, 0.70),
        },
        "values": {
            "truth": (0.72, 0.94), "loyalty": (0.20, 0.45), "security": (0.20, 0.45),
            "belonging": (0.14, 0.38), "ambition": (0.35, 0.60), "freedom": (0.48, 0.75),
            "family": (0.25, 0.50), "fairness": (0.42, 0.70), "revenge": (0.36, 0.64),
        },
        "looks": (0.44, 0.70), "warmth": (0.10, 0.30), "talkativeness": (0.70, 0.93),
        "attachment": ("avoidant", "secure"),
        "conflict": ("confront",),
        "social": {"strangers": ("帶刺", "不客氣"), "friends": ("嘴巴壞", "愛拆台"), "intimate": ("嘴硬", "怕被看穿在乎")},
        "affinity": {
            "jianghu": {
                "interests": ("rumours", "duels", "wine", "poetry", "legends"),
                "dislikes": ("lying", "showing_off", "elders", "sect_rules"),
            },
            "town": {
                "interests": ("gossip", "movies", "coffee", "music", "fashion"),
                "dislikes": ("lying", "showing_off", "the_boss", "overtime"),
            },
        },
        "roles": {
            "jianghu": (("弟子", "sect", "掌門"), ("茶館裡說書的幫手", "inn", "掌櫃")),
            "town": (("客服", "office", "主管"), ("咖啡店裡嘴最快的那個", "cafe", "店長")),
        },
        "family": {
            "jianghu": ("家裡說話就靠壓過對方，{ta}是這樣學的", "有一次被一句笑話傷到，席上沒有人站出來"),
            "town": ("家裡吃飯就靠互損，{ta}是這樣學的", "有一次在班上被當眾笑，沒有人站出來"),
        },
        "education": {
            "jianghu": ("書院讀過幾年，後來覺得盡是空話", "鏢局裡聽過太多謊，學會先拆穿"),
            "town": ("大學讀文學，論文比人還尖", "社團裡當過主筆，標題向來不留情"),
        },
        "habits": {
            "jianghu": (
                ("bored", "pick_a_flaw", "無聊就挑一件事說穿"),
                ("angry", "say_it", "生氣時把最難聽的那句直接說出來"),
                ("evening", "drink_wine", "夜裡獨飲，嘴還是不饒人"),
                ("happy", "tease", "高興時也用損人的方式親近"),
            ),
            "town": (
                ("bored", "scroll_and_comment", "無聊就在群組裡回一句刺的"),
                ("angry", "say_it", "生氣時把最難聽的那句直接說出來"),
                ("after_work", "drink_coffee", "下班喝咖啡，嘴還是不饒人"),
                ("happy", "tease", "開心時也用損人的方式親近"),
            ),
        },
        "cores": {
            "jianghu": (
                _core(
                    "把看不慣的事說穿", "哪天自己也被人這樣當眾揭開",
                    "曾被一句笑話傷到，沒人站出來", "先刺出去，就沒有人傷得到我",
                    "學會有些真話可以晚一點說", "我是在說真話，還是在報仇？",
                    "做一個不被糊弄的人", "少傷一個其實沒有惡意的人",
                    "嘴快又準，常常一句話把場面說僵",
                ),
                _core(
                    "讓虛偽的人下不了台", "被人當成只會挑刺的討厭鬼",
                    "真心被當成麻煩，從此改用刺人的方式說話", "溫柔沒有用，只有刻薄被人記住",
                    "把在乎說出來，而不只是把假的拆掉", "我不傷人的時候，還有人聽我說話嗎？",
                    "留下幾個挨過{ta}的嘴還願意留下的人", "這回對一個人把好話也說完",
                    "專門拆台，其實很怕沒人再理{ta}",
                ),
                _core(
                    "有人聽完刺耳的話還留下來", "哪天說得太準，連最後一個聽的人也走了",
                    "{ta}說中過一件醜事，那人當夜就離開了鎮", "說得準的人，註定是一個人",
                    "把準頭用在該幫的地方，而不是只用來傷人", "我不說話的時候，還認識我是誰嗎？",
                    "練成也能把好話講清楚的嘴", "這回先聽完別人說，再開口",
                    "說得太準，有人聽完就走，再也沒回來",
                ),
            ),
            "town": (
                _core(
                    "把看不慣的事說穿", "哪天自己也被人這樣當眾揭開",
                    "曾在群組裡被一句笑話傷到，沒人站出來", "先刺出去，就沒有人傷得到我",
                    "學會有些真話可以晚一點說", "我是在說真話，還是在報仇？",
                    "做一個不被糊弄的人", "少傷一個其實沒有惡意的同事",
                    "嘴快又準，常常一句話把會議室說僵",
                ),
                _core(
                    "讓裝好人的人下不了台", "被人當成只會挑刺的討厭鬼",
                    "真心被當成麻煩，從此改用刺人的方式說話", "溫柔沒有用，只有刻薄被人記住",
                    "把在乎說出來，而不只是把假的拆掉", "我不傷人的時候，還有人聽我說話嗎？",
                    "留下幾個挨過{ta}的嘴還願意留下的人", "這回對一個人把好話也說完",
                    "專門拆台，其實很怕群組裡沒人再理{ta}",
                ),
                _core(
                    "有人聽完刺耳的話還留下來", "哪天說得太準，連最後一個聽的人也走了",
                    "{ta}說中過一件醜事，那人當夜就不再回覆", "說得準的人，註定是一個人",
                    "把準頭用在該幫的地方，而不是只用來傷人", "我不說話的時候，還認識我是誰嗎？",
                    "練成也能把好話講清楚的嘴", "這回先聽完別人說，再回訊息",
                    "說得太準，有人看完就已讀不回",
                ),
            ),
        },
        "looks_pool": {
            "jianghu": (
                _look("薄唇，眉毛挑得高", "短髻，露出耳朵", "瘦而利", "說話時下巴微抬",
                      "人還沒靠近，話已經先到了", "顏色乾淨的短襖", "顏色乾淨的短褐"),
                _look("眼睛亮，看人像在挑錯", "髮束得很高", "中等", "手上常轉著一枚舊錢",
                      "一開口場面就緊一下", "酒樓常見的青衫", "酒樓常見的青衫"),
            ),
            "town": (
                _look("薄唇，眉毛挑得高", "短髮，露出耳朵", "瘦而利", "說話時下巴微抬",
                      "人還沒靠近，話已經先到了", "黑上衣", "黑上衣"),
                _look("眼睛亮，看人像在挑錯", "髮夾別得很高", "中等", "手上常轉著原子筆",
                      "一開口會議就緊一下", "鮮色的外套", "鮮色的帽T"),
            ),
        },
        "voices": (
            _voice("尖亮", "快，不給人接", "你自己信嗎", "說重點"),
            _voice("乾脆", "短，一句收尾", "然後呢", "這也叫理由"),
        ),
    },
    "高冷美人": {
        "p_female": 0.92,
        "age": (20, 32),
        "job_p": 0.42,
        "temperament": {
            "honesty": (0.42, 0.70), "temper": (0.12, 0.36), "gossip": (0.02, 0.16),
            "generosity": (0.18, 0.42), "absent_minded": (0.08, 0.28), "curiosity": (0.34, 0.58),
        },
        "values": {
            "truth": (0.46, 0.70), "loyalty": (0.22, 0.48), "security": (0.30, 0.55),
            "belonging": (0.06, 0.26), "ambition": (0.24, 0.48), "freedom": (0.78, 0.96),
            "family": (0.20, 0.44), "fairness": (0.35, 0.60), "revenge": (0.08, 0.30),
        },
        "looks": (0.82, 0.95), "warmth": (0.06, 0.24), "talkativeness": (0.05, 0.20),
        "attachment": ("avoidant",),
        "conflict": ("avoid", "bottle_up"),
        "social": {"strangers": ("冷淡", "客氣而疏"), "friends": ("少言", "直接"), "intimate": ("若即若離", "不願牽絆")},
        "affinity": {
            "jianghu": {
                "interests": ("zither", "poetry", "tea", "ink", "roaming"),
                "dislikes": ("noise", "rumours", "prying", "showing_off"),
            },
            "town": {
                "interests": ("music", "drawing", "coffee", "travel", "reading"),
                "dislikes": ("noise", "gossip", "prying", "showing_off"),
            },
        },
        "roles": {
            "jianghu": (("外來的琴師", "inn", "掌櫃"), ("暫住的客人", "inn", "掌櫃")),
            "town": (("自由接案", "cafe", "沒有主管"), ("設計", "office", "主管")),
        },
        "family": {
            "jianghu": ("因為長得好看，家裡只安排{ta}的去處，不問{ta}想不想", "母親盼{ta}留在故鄉，{ta}只想走"),
            "town": ("因為長得好看，家裡只安排{ta}的路，不問{ta}想不想", "母親盼{ta}留在這座城市，{ta}只想走"),
        },
        "education": {
            "jianghu": ("名門教過禮，琴與劍都學過，卻不願被人留下", "隨一位雲遊的先生學過幾年丹青"),
            "town": ("設計學校畢業，作品比人紅", "大學讀藝術，不太參加系上的聚會"),
        },
        "habits": {
            "jianghu": (
                ("alone", "stand_by_window", "獨處時在窗邊站很久"),
                ("anxious", "touch_pin", "不安時摸一摸髮間的簪"),
                ("evening", "play_zither", "夜裡獨自彈一曲，不讓人進來"),
                ("bored", "pack_bag", "無聊就開始收拾行囊"),
            ),
            "town": (
                ("alone", "headphones", "一個人時戴上耳機，不看人"),
                ("anxious", "check_ticket", "不安時反覆看手機裡的機票"),
                ("evening", "sketch", "夜裡畫幾筆，不傳給任何人"),
                ("bored", "walk_alone", "無聊就自己出去走，不約人"),
            ),
        },
        "cores": {
            "jianghu": (
                _core(
                    "按自己的意思過，不被人安排", "被困在別人的眼光裡",
                    "因為長得好看，從來沒有人問{ta}想留下還是離開", "走近誰，就會被誰留下",
                    "允許一個人真正靠近", "我是在保護自己，還是在懲罰別人？",
                    "有一處不必裝的地方", "拒絕一門不想要的安排",
                    "好看，也冷，話少到讓人不敢靠近",
                ),
                _core(
                    "被人記得的是本事，不是臉", "一旦親近，就被看成可以佔有的人",
                    "有人曾把{ta}的好意說成應允，{ta}從此把話收短", "冷著，才安全",
                    "分辨靠近與侵佔", "我能不能既好看、又被當成一個人？",
                    "走自己選的路", "把不想答的問題都拒乾淨",
                    "眉眼極好，神情卻像隨時會走",
                ),
                _core(
                    "有人問{ta}冷不冷，而不是問{ta}從哪裡來", "一旦答話，就被當成可以留下的人",
                    "有一回{ta}多看了一眼，對方就四處說{ta}心動了", "多一句話，就多一條把我留下的繩子",
                    "相信靠近不一定等於被抓住", "我沉默，是因為不想說，還是不敢說？",
                    "能在一個地方住過一季而不逃", "對一個人把一句完整的話講完",
                    "多看一眼都會被說成心動，所以{ta}連眼也不抬",
                ),
            ),
            "town": (
                _core(
                    "按自己的意思過，不被人安排", "被困在別人的眼光裡",
                    "因為長得好看，從來沒有人問{ta}想留下還是離開", "走近誰，就會被誰留下",
                    "允許一個人真正靠近", "我是在保護自己，還是在懲罰別人？",
                    "有一處不必裝的地方", "拒絕一個不想要的工作安排",
                    "好看，也冷，話少到讓人不敢靠近",
                ),
                _core(
                    "被人記得的是作品，不是臉", "一旦親近，就被看成可以佔有的人",
                    "有人曾把{ta}的好意說成答應，{ta}從此把話收短", "冷著，才安全",
                    "分辨靠近與侵佔", "我能不能既好看、又被當成一個人？",
                    "走自己選的城市", "把不想回的訊息都放著",
                    "眉眼極好，神情卻像隨時會走",
                ),
                _core(
                    "有人問{ta}冷不冷，而不是問{ta}從哪裡來", "一旦回覆，就被當成可以留下的人",
                    "有一回{ta}多看了一眼，對方就傳話說{ta}心動了", "多一則訊息，就多一條把我留下的繩子",
                    "相信靠近不一定等於被抓住", "我沉默，是因為不想說，還是不敢說？",
                    "能在一座城市住過一季而不逃", "對一個人把一句完整的話講完",
                    "多看一眼都會被說成心動，所以{ta}連訊息也不回",
                ),
            ),
        },
        "looks_pool": {
            "jianghu": (
                _look("鵝蛋臉，眼神冷，很少笑", "及肩長髮，用一根木簪鬆鬆綰住", "高瘦", "總背著一個舊行囊",
                      "不說話的時候最吸引人，像隨時會離開", "素色布衣配舊披風", "素色長衫，領口扣得整齊"),
                _look("眉眼清淡，嘴角不輕易動", "長髮，一絲不亂", "修長", "腕上什麼都不戴",
                      "站著就讓人讓路，卻不讓人走近", "月白的長衣", "月白的長衫"),
            ),
            "town": (
                _look("鵝蛋臉，眼神冷，很少笑", "及肩長髮，隨便別住", "高瘦", "總背著一個舊背包",
                      "不說話的時候最吸引人，像隨時會離開", "黑大衣", "剪裁乾淨的黑上衣"),
                _look("眉眼清淡，嘴角不輕易動", "長髮，一絲不亂", "修長", "耳朵上沒有飾品",
                      "走進咖啡廳就讓人讓路，卻不讓人搭話", "素色洋裝", "素色襯衫"),
            ),
        },
        "voices": (
            _voice("清冷", "慢，句子很短", "再說吧", "我不一定會留"),
            _voice("輕而遠", "少，不解釋", "不必", "你看錯了"),
        ),
    },
    "親切的鄰家": {
        "p_female": 0.55,
        "age": (22, 36),
        "job_p": 0.88,
        "temperament": {
            "honesty": (0.60, 0.86), "temper": (0.08, 0.26), "gossip": (0.36, 0.60),
            "generosity": (0.72, 0.93), "absent_minded": (0.15, 0.38), "curiosity": (0.46, 0.70),
        },
        "values": {
            "truth": (0.50, 0.72), "loyalty": (0.66, 0.88), "security": (0.45, 0.68),
            "belonging": (0.82, 0.96), "ambition": (0.18, 0.40), "freedom": (0.30, 0.55),
            "family": (0.60, 0.85), "fairness": (0.55, 0.78), "revenge": (0.02, 0.16),
        },
        "looks": (0.48, 0.70), "warmth": (0.78, 0.95), "talkativeness": (0.58, 0.84),
        "attachment": ("secure",),
        "conflict": ("appease",),
        "social": {"strangers": ("熱情", "自來熟"), "friends": ("話多", "八面玲瓏"), "intimate": ("大方", "照顧人")},
        "affinity": {
            "jianghu": {
                "interests": ("cooking", "tea", "legends", "cats", "rumours"),
                "dislikes": ("lying", "noise", "being_ordered", "borrowing"),
            },
            "town": {
                "interests": ("cooking", "coffee", "gossip", "cats", "plants"),
                "dislikes": ("lying", "noise", "being_ordered", "borrowing"),
            },
        },
        "roles": {
            "jianghu": (("茶館夥計", "inn", "掌櫃"), ("巷口雜貨的幫手", "market", "掌櫃")),
            "town": (("咖啡店店員", "cafe", "店長"), ("社區裡辦事的人", "shop", "店長")),
        },
        "family": {
            "jianghu": ("巷口長大，認得每一戶，自己的屋子也總有人進進出出", "家裡散過一次，{ta}從此見不得人走"),
            "town": ("社區裡長大，認得每一戶，自己的客廳也總有人", "家裡搬散過一次，{ta}從此見不得群組安靜"),
        },
        "education": {
            "jianghu": ("私塾念過兩年，後來去茶館幫忙", "沒有正式的師承，人情卻比劍譜熟"),
            "town": ("大學就讀在本地，暑假都在店裡打工", "社區大學上過課，同學現在都是鄰居"),
        },
        "habits": {
            "jianghu": (
                ("morning", "greet_street", "清晨就把巷子裡的人招呼一輪"),
                ("happy", "cook_extra", "高興時多煮一個人的飯"),
                ("bored", "visit", "無聊就串門子"),
                ("at_meal", "save_a_seat", "吃飯總留一個空位"),
            ),
            "town": (
                ("morning", "greet_street", "早上去咖啡店就把熟客招呼一輪"),
                ("happy", "cook_extra", "開心時多煮一個人的飯"),
                ("bored", "group_chat", "無聊就在群組裡找人說話"),
                ("after_work", "drop_by", "下班順路去鄰居家坐一下"),
            ),
        },
        "cores": {
            "jianghu": (
                _core(
                    "讓鎮上的人互相照應", "哪一戶出事時自己不在",
                    "初到這個鎮的那年沒人理，{ta}知道被晾在外面的滋味", "我先對人好，人家就一定會留下",
                    "接受有人就是不想親近", "熱絡是真的情分，還是我怕冷清？",
                    "成為別人願意順路來坐的人", "把新來的旅人介紹給鎮上的人",
                    "見人就打招呼，記得每個人愛喝濃茶還是淡茶",
                ),
                _core(
                    "有一張永遠坐得下人的桌子", "家裡再度只剩自己",
                    "家裡散過一次，{ta}從此見不得人走", "把人都留住，就不會再失去",
                    "讓人走的時候也能好好道別", "我留的是人，還是留的是害怕？",
                    "經營一個有人氣的小院子", "這個月請每個人來坐一次",
                    "院子的門總是開著，灶上常常多煮一個人的飯",
                ),
                _core(
                    "有一個人是來找{ta}，不是來找這扇開著的門", "門一關上，院子就再沒有人聲",
                    "有一回{ta}病了，來串門的人站了一站就走，沒有人問{ta}怎麼了", "我得一直張羅，別人才會記得有我",
                    "被人照顧一次，而不是只照顧人", "他們來，是因為我，還是因為這裡有熱茶？",
                    "讓自己也成為可以被招呼的那一個", "累一回，看看誰會留下",
                    "門總是開著，病的那天卻沒有人問{ta}一聲",
                ),
            ),
            "town": (
                _core(
                    "讓這條街上的人互相照應", "哪一家出事時自己不在",
                    "搬來的第一年沒人理，{ta}知道被晾在群組外面的滋味", "我先對人好，人家就一定會留下",
                    "接受有人就是不想親近", "熱絡是真的情分，還是我怕冷清？",
                    "成為別人願意順路來坐的人", "把新來的鄰居拉進社區群組",
                    "見人就打招呼，記得每個人咖啡要不要糖",
                ),
                _core(
                    "有一張永遠坐得下人的桌子", "家裡再度只剩自己",
                    "家裡搬散過一次，{ta}從此見不得人走", "把人都留住，就不會再失去",
                    "讓人走的時候也能好好道別", "我留的是人，還是留的是害怕？",
                    "經營一個有人氣的客廳", "這個月請每個人來坐一次",
                    "家門總是開著，冰箱裡常常多一個人的菜",
                ),
                _core(
                    "有一個人是來找{ta}，不是來找這扇開著的門", "屋子一靜，家裡就再沒有人聲",
                    "有一回{ta}病了，來串門的人站了一站就走，沒有人問{ta}怎麼了", "我得一直張羅，別人才會記得有我",
                    "被人照顧一次，而不是只照顧人", "他們來，是因為我，還是因為這裡有咖啡？",
                    "讓自己也成為可以被招呼的那一個", "請一次假，看看誰會傳訊息來",
                    "人最勤快，病的那天卻沒有人問{ta}一聲",
                ),
            ),
        },
        "looks_pool": {
            "jianghu": (
                _look("笑臉，有淺酒窩", "髮髻鬆，額前有碎髮", "中等", "袖口常捲著，手上有熱茶的溫度",
                      "走進來就像把燈點亮", "淺色短襖", "淺色短褐，袖口捲起"),
                _look("眼睛圓，看人的時候很專心", "中長髮，用紅繩束住", "嬌小", "總帶著一包要分人的點心",
                      "讓場面自然變得和氣", "碎花布衣", "乾淨的青布衣"),
            ),
            "town": (
                _look("笑臉，有淺酒窩", "髮髻鬆，額前有碎髮", "中等", "袖口常捲著",
                      "走進來就像把燈點亮", "印著咖啡店標誌的圍裙", "印著店名的外套"),
                _look("眼睛圓，看人的時候很專心", "短髮，用紅色髮圈束住", "嬌小", "總帶著一包要分人的點心",
                      "讓場面自然變得和氣", "碎花襯衫", "乾淨的T恤"),
            ),
        },
        "voices": (
            _voice("明亮", "輕快，愛打招呼", "吃過了嗎", "來坐啊"),
            _voice("暖", "碎，記得別人的小事", "我幫你留了一份", "你們認識一下"),
        ),
    },
    "其貌不揚的熱心人": {
        "p_female": 0.45,
        "age": (24, 45),
        "job_p": 0.90,
        "temperament": {
            "honesty": (0.66, 0.92), "temper": (0.08, 0.30), "gossip": (0.12, 0.36),
            "generosity": (0.80, 0.97), "absent_minded": (0.18, 0.42), "curiosity": (0.38, 0.62),
        },
        "values": {
            "truth": (0.55, 0.78), "loyalty": (0.68, 0.90), "security": (0.40, 0.62),
            "belonging": (0.60, 0.82), "ambition": (0.12, 0.36), "freedom": (0.28, 0.52),
            "family": (0.55, 0.80), "fairness": (0.72, 0.92), "revenge": (0.02, 0.14),
        },
        "looks": (0.16, 0.38), "warmth": (0.78, 0.96), "talkativeness": (0.42, 0.66),
        "attachment": ("secure", "anxious"),
        "conflict": ("appease", "confront"),
        "social": {"strangers": ("親切", "樸實"), "friends": ("熱心", "講話不拐彎"), "intimate": ("照顧人", "不會說漂亮話")},
        "affinity": {
            "jianghu": {
                "interests": ("cooking", "herbs", "horses", "fishing", "escort"),
                "dislikes": ("showing_off", "lying", "prying", "rumours"),
            },
            "town": {
                "interests": ("cooking", "basketball", "fishing", "plants", "cats"),
                "dislikes": ("showing_off", "lying", "prying", "gossip"),
            },
        },
        "roles": {
            "jianghu": (("鐵匠鋪下手", "market", "師父"), ("鏢局雜役", "escort", "鏢頭")),
            "town": (("倉管", "shop", "店長"), ("維修", "office", "主管")),
        },
        "family": {
            "jianghu": ("獵戶家的孩子，出力比說話早", "家裡不富裕，{ta}習慣先顧別人的缺口"),
            "town": ("工地家庭長大，出力比說話早", "家裡不富裕，{ta}習慣先顧別人的缺口"),
        },
        "education": {
            "jianghu": ("沒讀過幾年書，活是一學就會", "鐵匠鋪裡打過下手"),
            "town": ("高職學的是技藝，沒有人記得{ta}的臉", "沒考上大學，很早去工作"),
        },
        "habits": {
            "jianghu": (
                ("morning", "do_the_heavy", "天一亮就把重活先做完"),
                ("stressed", "fix_something", "心煩就去修一件壞掉的東西"),
                ("happy", "feed_people", "高興時把吃的分出去"),
                ("after_work", "help_next", "收功後還去問誰需要搭把手"),
            ),
            "town": (
                ("morning", "do_the_heavy", "一早就把重的東西搬完"),
                ("stressed", "fix_something", "心煩就去修一件壞掉的東西"),
                ("happy", "feed_people", "開心時把吃的分出去"),
                ("after_work", "help_next", "下班後還去問誰需要搭把手"),
            ),
        },
        "cores": {
            "jianghu": (
                _core(
                    "幫得上的忙都幫", "被人覺得多餘",
                    "長得不起眼，從小被忽略，只有出力時才被想起", "我不好看，就得更有用才行",
                    "知道不出力也值得被當朋友", "他們靠近的是我，還是我的幫忙？",
                    "有一個人不是因為被幫才留下", "這回幫人之前先問自己想不想",
                    "長相普通，卻是出事時第一個到的人",
                ),
                _core(
                    "讓弱的那一方有人站在旁邊", "自己的好意被當成討好",
                    "有一次拼了命幫忙，對方只說了句「你這樣的人也想出頭」", "長得不好，心意就不值錢",
                    "把幫忙和討好分開", "我不做什麼的時候，還有人看見我嗎？",
                    "被一個人好好看過一次", "把一件別人沒注意的事做完",
                    "不起眼，熱心得讓人不好意思拒絕",
                ),
                _core(
                    "有人記得{ta}的名字，而不只記得{ta}修過什麼", "手停下來的那天，就沒有人再叫{ta}",
                    "宴席上座位不夠，有人說{ta}站著也一樣，反正是來幫忙的", "我這種長相，坐下來就是佔位子",
                    "坐下的時候也不覺得虧欠", "我不做事的時候，還有沒有一個位子是我的？",
                    "被請去坐席，而不是被叫去搬席", "這回吃飯，自己也坐下",
                    "席面上沒有{ta}的位子，灶房裡卻總有{ta}的手",
                ),
            ),
            "town": (
                _core(
                    "幫得上的忙都幫", "被人覺得多餘",
                    "長得不起眼，從小被忽略，只有出力時才被想起", "我不好看，就得更有用才行",
                    "知道不出力也值得被當朋友", "他們靠近的是我，還是我的幫忙？",
                    "有一個人不是因為被幫才留下", "這回幫人之前先問自己想不想",
                    "長相普通，卻是出事時第一個到的人",
                ),
                _core(
                    "讓弱的那一方有人站在旁邊", "自己的好意被當成討好",
                    "有一次拼了命幫忙，對方只說了句「你這樣的人也想出頭」", "長得不好，心意就不值錢",
                    "把幫忙和討好分開", "我不做什麼的時候，還有人看見我嗎？",
                    "被一個人好好看過一次", "把一件別人沒注意的事做完",
                    "不起眼，熱心得讓人不好意思只說謝謝",
                ),
                _core(
                    "有人記得{ta}的名字，而不只記得{ta}修過什麼", "手停下來的那天，就沒有人再叫{ta}",
                    "聚餐座位不夠，有人說{ta}站著也一樣，反正是來幫忙的", "我這種長相，坐下來就是佔位子",
                    "坐下的時候也不覺得虧欠", "我不做事的時候，還有沒有一個位子是我的？",
                    "被請去吃飯，而不是被叫去搬東西", "這回聚餐，自己也坐下",
                    "餐桌上沒有{ta}的位子，後頭忙的卻總是{ta}",
                ),
            ),
        },
        "looks_pool": {
            "jianghu": (
                _look("寬臉，皮膚粗，五官平", "頭髮剪得很短，不服貼", "結實", "掌心有一層厚繭",
                      "樸實，笑起來讓人放心", "舊得發白的短褐", "舊得發白的短褐"),
                _look("眉毛淡，鼻子有點塌", "用布巾胡亂紮住", "矮壯", "衣襟的盤扣常常扣錯",
                      "不起眼，忙起來卻最醒目", "粗布衣", "粗布短打"),
            ),
            "town": (
                _look("寬臉，皮膚粗，五官平", "平頭，不服貼", "結實", "掌心有一層厚繭",
                      "樸實，笑起來讓人放心", "洗舊的工作服", "洗舊的工作服"),
                _look("眉毛淡，鼻子有點塌", "頭髮隨便紮", "矮壯", "上衣的扣子常常扣錯",
                      "不起眼，忙起來卻最醒目", "寬大的毛衣", "寬大的帽T"),
            ),
        },
        "voices": (
            _voice("粗", "直，不修飾", "我來吧", "別客氣"),
            _voice("沙", "慢，好話也說得笨", "這個我能修", "你先歇著"),
        ),
    },
}


NEMESIS_WHY = {
    "jianghu": (
        "{a}與{b}在比武場上結了怨，一個當眾下了狠手",
        "{a}與{b}爭過同一個位子，話已經說死了",
        "{a}揭過{b}的短，從此見面就冷",
    ),
    "town": (
        "{a}與{b}搶過同一個升遷的位子，從此不說話",
        "{a}當眾損過{b}，{b}記到現在",
        "{a}與{b}在同一件案子上撕破了臉",
    ),
}
SECRET_MATCHED = {
    "jianghu": (
        "{h}為了家裡的湯藥錢，拿走了{o}的一件舊物，至今沒對{o}說",
        "{h}年少時辜負過{o}的信任，{o}到現在還不知道",
    ),
    "town": (
        "{h}為了家裡的醫藥費，拿走了{o}的一件東西，至今沒對{o}說",
        "{h}曾經辜負過{o}的信任，{o}到現在還不知道",
    ),
}
SECRET_GENERIC = {
    "jianghu": (
        "{h}知道一件關於{o}的事，選擇瞞著{o}",
        "{h}背著{o}做過一件不能當面說的事",
    ),
    "town": (
        "{h}知道一件關於{o}的事，選擇瞞著{o}",
        "{h}背著{o}做過一件不能當面說的事",
    ),
}


def _audit() -> None:
    if len(ARCHETYPES) < 8:
        raise RuntimeError("forge needs at least 8 archetypes")
    for era, topics in TOPICS.items():
        for name, spec in ARCHETYPES.items():
            aff = spec["affinity"][era]
            if len(aff["interests"]) < 3 or len(aff["dislikes"]) < 2:
                raise RuntimeError(f"{name} {era} affinity is short")
            if set(aff["interests"]) & set(aff["dislikes"]):
                raise RuntimeError(f"{name} {era} likes and dislikes overlap")
            missing = [t for t in aff["interests"] + aff["dislikes"] if t not in topics]
            if missing:
                raise RuntimeError(f"{name} {era} unknown topics {missing}")
            for key in ("cores", "habits", "looks_pool", "family", "education", "roles"):
                if era not in spec[key] or len(spec[key][era]) < 1:
                    raise RuntimeError(f"{name} missing {era} {key}")
            cores = spec["cores"][era]
            if len(cores) < 3:
                raise RuntimeError(f"{name} {era} needs at least 3 inner-text sets")
            blurbs = [core["blurb"] for core in cores]
            if len(set(blurbs)) != len(blurbs):
                raise RuntimeError(f"{name} {era} one-line descriptions repeat")
            for core in cores:
                for field in _CORE_KEYS:
                    if not str(core.get(field, "")).strip():
                        raise RuntimeError(f"{name} {era} core missing {field}")
            for key, bounds in {**spec["temperament"], **spec["values"]}.items():
                lo, hi = bounds
                if not 0.0 <= lo <= hi <= 1.0:
                    raise RuntimeError(f"{name} {key} range {bounds}")
            for key in ("looks", "warmth", "talkativeness"):
                lo, hi = spec[key]
                if not 0.0 <= lo <= hi <= 1.0:
                    raise RuntimeError(f"{name} {key} range")
            if spec["age"][0] < 18:
                raise RuntimeError(f"{name} age range goes under 18")
    _audit_names()


def _audit_names() -> None:
    """Surnames are one character. Male and female given-name pools do not overlap."""
    for label, pool in (("jianghu surname", SURNAMES), ("town surname", TOWN_SURNAMES)):
        if any(len(item) != 1 for item in pool) or len(pool) != len(set(pool)):
            raise RuntimeError(f"{label} pool is not a set of one-character surnames")
    gendered = (
        ("jianghu given", GIVEN_MALE, GIVEN_FEMALE),
        ("town given", TOWN_GIVEN_MALE, TOWN_GIVEN_FEMALE),
    )
    for label, male, female in gendered:
        if len(male) < 12 or len(female) < 12:
            raise RuntimeError(f"{label} pool is shorter than a cast of 12")
        if len(male) != len(set(male)) or len(female) != len(set(female)):
            raise RuntimeError(f"{label} pool repeats a name")
        overlap = set(male) & set(female)
        if overlap:
            raise RuntimeError(f"{label} pools overlap: {sorted(overlap)}")
    for label, pool in (("male one", GIVEN_MALE_ONE), ("female one", GIVEN_FEMALE_ONE)):
        if any(len(item) != 1 for item in pool):
            raise RuntimeError(f"{label} given names must be one character")
    for label, pool in (
        ("male two", GIVEN_MALE_TWO), ("female two", GIVEN_FEMALE_TWO),
        ("town male", TOWN_GIVEN_MALE), ("town female", TOWN_GIVEN_FEMALE),
    ):
        if any(len(item) != 2 for item in pool):
            raise RuntimeError(f"{label} given names must be two characters")


_audit()


def _pick(roll: float, options):
    options = tuple(options)
    return options[min(int(roll * len(options)), len(options) - 1)]


def _unit(roll: float, bounds: tuple[float, float]) -> float:
    lo, hi = bounds
    return round(min(1.0, max(0.0, lo + (hi - lo) * roll)), 2)


def _fill(text: str, gender: str) -> str:
    ta = "她" if gender == "female" else "他"
    return text.replace("{ta}", ta)


def _dumps(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=2) + "\n"


def _shuffle(items: list, stream) -> None:
    for n in range(len(items) - 1, 0, -1):
        k = min(int(stream.random() * (n + 1)), n)
        items[n], items[k] = items[k], items[n]


class _Rolls:
    """A fixed run of rolls for one person. Locks never skip a draw, so later fields stay put."""

    def __init__(self, seed: int, index: int, n: int = 80):
        stream = rng(seed, 0, str(index), "forge")
        self._v = [stream.random() for _ in range(n)]
        self._i = 0

    def next(self) -> float:
        if self._i >= len(self._v):
            raise RuntimeError("forge roll budget exceeded")
        value = self._v[self._i]
        self._i += 1
        return value


def _pool(archetypes) -> tuple[str, ...]:
    if not archetypes:
        return tuple(ARCHETYPES)
    if isinstance(archetypes, str):
        archetypes = [part.strip() for part in archetypes.replace("，", ",").split(",") if part.strip()]
    out = []
    for name in archetypes:
        if name not in ARCHETYPES:
            known = "、".join(ARCHETYPES)
            raise ValueError(f"unknown archetype {name!r}; known: {known}")
        if name not in out:
            out.append(name)
    if not out:
        raise ValueError("archetypes is empty")
    return tuple(out)


def _normalize_locks(locks, size: int) -> dict[int, dict]:
    if not locks:
        return {}
    out = {}
    for key, spec in locks.items():
        try:
            index = int(key)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"lock key {key!r} is not a person index") from exc
        if not 0 <= index < size:
            raise ValueError(f"lock index {index} is outside 0..{size - 1}")
        if not isinstance(spec, dict):
            raise ValueError(f"lock {index} must be a dict of fields")
        unknown = sorted(set(spec) - _LOCK_FIELDS)
        if unknown:
            raise ValueError(f"lock {index}: unknown field {unknown}")
        out[index] = dict(spec)
    return out


def _preassign(seed: int, size: int, pool: tuple[str, ...], locks: dict[int, dict]) -> dict[int, str]:
    """Reserve an underestimated genius and a secret-keeper when size asks for balance and the pool has them."""
    assigned = {}
    for index, spec in locks.items():
        if "archetype" in spec:
            assigned[index] = spec["archetype"]
    if size < 6:
        return assigned
    stream = rng(seed, 0, "cast", "forge")
    for role in ("被看輕的天才", "藏著秘密的人"):
        roll = stream.random()
        if role not in pool or any(value == role for value in assigned.values()):
            continue
        free = [i for i in range(size) if i not in assigned]
        if not free:
            continue
        assigned[free[min(int(roll * len(free)), len(free) - 1)]] = role
    return assigned


def _orientation(gender: str, roll: float) -> list[str]:
    if gender == "female":
        opposite, same = "male", "female"
    elif gender == "male":
        opposite, same = "female", "male"
    else:
        return ["female", "male"]
    if roll < 0.72:
        return [opposite]
    if roll < 0.88:
        return [opposite, same]
    return [same]


def _given_parts(era: str, gender: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """(short, long) given-name pools for this gender. Town names are all two characters, so both halves match."""
    female = gender == "female"
    if era == "jianghu":
        if female:
            return GIVEN_FEMALE_ONE, GIVEN_FEMALE_TWO
        return GIVEN_MALE_ONE, GIVEN_MALE_TWO
    pool = TOWN_GIVEN_FEMALE if female else TOWN_GIVEN_MALE
    mid = len(pool) // 2
    return pool[:mid], pool[mid:]


def _candidate_name(era: str, gender: str, surname_roll: float, style_roll: float, given_roll: float) -> str:
    surnames = SURNAMES if era == "jianghu" else TOWN_SURNAMES
    short, long = _given_parts(era, gender)
    surname = _pick(surname_roll, surnames)
    given = _pick(given_roll, short if style_roll < 0.35 else long)
    return surname + given


def _valid_generated_name(era: str, gender: str, name: str) -> bool:
    surnames = SURNAMES if era == "jianghu" else TOWN_SURNAMES
    if name[:1] not in surnames:
        return False
    rest = name[1:]
    short, long = _given_parts(era, gender)
    if era == "jianghu" and not (2 <= len(name) <= 3):
        return False
    return rest in short or rest in long


def _given_of(era: str, name: str) -> str:
    surnames = SURNAMES if era == "jianghu" else TOWN_SURNAMES
    if len(name) > 1 and name[:1] in surnames:
        return name[1:]
    return name


def _repair_name(seed: int, index: int, era: str, gender: str, used_full: set[str], used_given: set[str]) -> str:
    stream = rng(seed, 0, str(index), "forge-name")
    for _ in range(96):
        name = _candidate_name(era, gender, stream.random(), stream.random(), stream.random())
        given = _given_of(era, name)
        if (name not in used_full and given not in used_given and name not in FAMOUS
                and _valid_generated_name(era, gender, name)):
            return name
    raise RuntimeError(f"could not find a free name for person {index}")


def _core_index(archetype: str, era: str, roll: float, used: dict[str, set[int]]) -> int:
    """Pick a set. The same archetype in one cast does not reuse a set while an unused set remains."""
    n = len(ARCHETYPES[archetype]["cores"][era])
    want = min(int(roll * n), n - 1)
    taken = used.setdefault(archetype, set())
    chosen = want
    if len(taken) < n and want in taken:
        for offset in range(1, n):
            cand = (want + offset) % n
            if cand not in taken:
                chosen = cand
                break
    taken.add(chosen)
    return chosen


def _draft(seed: int, index: int, era: str, pool: tuple[str, ...], pre: str | None, lock: dict,
           used_cores: dict[str, set[int]]) -> dict:
    rolls = _Rolls(seed, index)
    drawn = _pick(rolls.next(), pool)
    archetype = pre or drawn
    if "archetype" in lock:
        archetype = lock["archetype"]
    spec = ARCHETYPES[archetype]

    gender = "female" if rolls.next() < spec["p_female"] else "male"
    lo, hi = spec["age"]
    age_roll = rolls.next()
    age = lo + min(int(age_roll * (hi - lo + 1)), hi - lo)
    orient_roll = rolls.next()
    looks = _unit(rolls.next(), spec["looks"])
    warmth = _unit(rolls.next(), spec["warmth"])
    talk = _unit(rolls.next(), spec["talkativeness"])
    temperament = {key: _unit(rolls.next(), spec["temperament"][key]) for key in TEMPERAMENT_KEYS}
    values = {key: _unit(rolls.next(), spec["values"][key]) for key in VALUE_KEYS}
    attachment = _pick(rolls.next(), spec["attachment"])
    conflict = _pick(rolls.next(), spec["conflict"])
    strangers = _pick(rolls.next(), spec["social"]["strangers"])
    friends = _pick(rolls.next(), spec["social"]["friends"])
    intimate = _pick(rolls.next(), spec["social"]["intimate"])
    core_i = _core_index(archetype, era, rolls.next(), used_cores)
    look_i = min(int(rolls.next() * len(spec["looks_pool"][era])), len(spec["looks_pool"][era]) - 1)
    voice = _pick(rolls.next(), spec["voices"])
    n_habits = 2 if rolls.next() < 0.55 else 3
    habit_pool = list(spec["habits"][era])
    habits = []
    for nth in range(3):
        choice = _pick(rolls.next(), habit_pool)
        habit_pool.remove(choice)
        if nth < n_habits:
            habits.append({"when": choice[0], "do": choice[1], "label": choice[2]})
    interest_pool = list(spec["affinity"][era]["interests"])
    interests = {}
    for _ in range(3):
        topic = _pick(rolls.next(), interest_pool)
        interest_pool.remove(topic)
        interests[topic] = _unit(rolls.next(), (0.40, 0.90))
    dislike_pool = list(spec["affinity"][era]["dislikes"])
    dislikes = {}
    for _ in range(2):
        topic = _pick(rolls.next(), dislike_pool)
        dislike_pool.remove(topic)
        dislikes[topic] = _unit(rolls.next(), (0.40, 0.90))
    birthplace = _pick(rolls.next(), BIRTHPLACES[era])
    family = _pick(rolls.next(), spec["family"][era])
    education = _pick(rolls.next(), spec["education"][era])
    look = spec["looks_pool"][era][look_i]
    has_job = rolls.next() < spec["job_p"]
    role = _pick(rolls.next(), spec["roles"][era])
    surname_roll, style_roll, given_roll = rolls.next(), rolls.next(), rolls.next()

    person = {
        "index": index, "id": f"p{index}", "archetype": archetype, "gender": gender, "age": age,
        "name": "", "name_locked": False, "looks": looks, "warmth": warmth, "talkativeness": talk,
        "charm": looks, "orient_roll": orient_roll, "attracted_locked": False,
        "attachment": attachment, "conflict": conflict,
        "strangers": strangers, "friends": friends, "intimate": intimate,
        "temperament": temperament, "values": values, "interests": interests, "dislikes": dislikes,
        "habits": habits, "birthplace": birthplace, "family": family, "education": education,
        "look": look, "voice": voice, "has_job": has_job, "role": role, "core_i": core_i,
        "core": dict(spec["cores"][era][core_i]),
    }
    _apply_lock(person, lock)
    if not person["name_locked"]:
        person["name"] = _candidate_name(era, person["gender"], surname_roll, style_roll, given_roll)
    _finish_person(person, era)
    return person


def _apply_lock(person: dict, lock: dict) -> None:
    if "name" in lock:
        person["name"] = str(lock["name"])
        person["name_locked"] = True
    if "age" in lock:
        person["age"] = int(lock["age"])
    if "gender" in lock:
        person["gender"] = str(lock["gender"])
    if "archetype" in lock:
        person["archetype"] = str(lock["archetype"])
    for key in ("looks", "warmth", "talkativeness", "charm"):
        if key in lock:
            person[key] = float(lock[key])
    if "attachment" in lock:
        person["attachment"] = str(lock["attachment"])
    if "conflict" in lock:
        person["conflict"] = str(lock["conflict"])
    if "temperament" in lock:
        for key, value in lock["temperament"].items():
            if key not in TEMPERAMENT_KEYS:
                raise ValueError(f"unknown temperament {key!r}")
            person["temperament"][key] = float(value)
    for key in TEMPERAMENT_KEYS:
        if key in lock:
            person["temperament"][key] = float(lock[key])
    if "values" in lock:
        for key, value in lock["values"].items():
            if key not in VALUE_KEYS:
                raise ValueError(f"unknown value {key!r}")
            person["values"][key] = float(value)
    for key in VALUE_KEYS:
        if key in lock:
            person["values"][key] = float(lock[key])
    if "attracted_to" in lock:
        raw = lock["attracted_to"]
        if isinstance(raw, str):
            raw = [raw]
        person["attracted_to"] = [str(item) for item in raw]
        person["attracted_locked"] = True
    for key in _CORE_KEYS:
        if key in lock:
            person["core"][key] = str(lock[key])
    if "looks" in lock and "charm" not in lock:
        person["charm"] = person["looks"]
    elif "charm" in lock and "looks" not in lock:
        person["looks"] = person["charm"]
    elif "looks" not in lock and "charm" not in lock:
        person["charm"] = person["looks"]


def _finish_person(person: dict, era: str) -> None:
    gender = person["gender"]
    if "attracted_to" not in person:
        if person["age"] < 18:
            person["attracted_to"] = []
        else:
            person["attracted_to"] = _orientation(gender, person["orient_roll"])
    elif person["age"] < 18 and not person["attracted_locked"]:
        person["attracted_to"] = []
    person["romance_eligible"] = person["age"] >= 18
    for key in _CORE_KEYS:
        person["core"][key] = _fill(person["core"][key], gender)
    person["family"] = _fill(person["family"], gender)
    person["education"] = _fill(person["education"], gender)
    for habit in person["habits"]:
        habit["label"] = _fill(habit["label"], gender)
    look = dict(person["look"])
    for key in ("face", "hair", "build", "mark", "presence"):
        look[key] = _fill(look[key], gender)
    costumes = look["costume"]
    look["costume_worn"] = costumes.get(gender) or costumes.get("female") or next(iter(costumes.values()))
    person["look"] = look
    if not person["has_job"]:
        person["occupation"] = None
    else:
        role, place, superior = person["role"]
        person["occupation"] = {
            "domain": "work", "role": role, "place": place, "superior": superior,
            "duty": DUTY[era], "words": dict(JOB_WORDS[era]),
        }


def _resolve_names(seed: int, era: str, people: list[dict]) -> None:
    used_full: set[str] = set()
    used_given: set[str] = set()
    for person in people:
        if not person["name_locked"]:
            continue
        given = _given_of(era, person["name"])
        if person["name"] in used_full:
            raise ValueError(f"locked name {person['name']!r} is duplicated")
        if given in used_given:
            raise ValueError(f"locked given name {given!r} is duplicated")
        used_full.add(person["name"])
        used_given.add(given)
    for person in people:
        if person["name_locked"]:
            continue
        name = person["name"]
        given = _given_of(era, name)
        if (name in used_full or given in used_given or name in FAMOUS
                or not _valid_generated_name(era, person["gender"], name)):
            name = _repair_name(seed, person["index"], era, person["gender"], used_full, used_given)
            given = _given_of(era, name)
        person["name"] = name
        used_full.add(name)
        used_given.add(given)


def _compatible(admirer: dict, other: dict) -> bool:
    return other["gender"] in admirer["attracted_to"]


def _reciprocated(admirer: dict, other: dict) -> bool:
    return admirer["gender"] in other["attracted_to"]


def _place_crush(people: list[dict], stream) -> dict | None:
    eligible = [p for p in people if p["romance_eligible"]]
    if len(eligible) < 2:
        return None
    order = list(eligible)
    _shuffle(order, stream)

    def scan(allow_mutual: bool):
        for admirer in order:
            for other in order:
                if admirer["id"] == other["id"] or not _compatible(admirer, other):
                    continue
                if _reciprocated(admirer, other) and not allow_mutual:
                    continue
                return admirer, other
        return None

    pair = scan(False) or scan(True)
    if pair is None:
        for admirer in order:
            if admirer["attracted_locked"]:
                continue
            for other in order:
                if admirer["id"] == other["id"]:
                    continue
                genders = list(admirer["attracted_to"])
                if other["gender"] not in genders:
                    genders.append(other["gender"])
                admirer["attracted_to"] = genders
                if (not other["attracted_locked"] and admirer["gender"] in other["attracted_to"]
                        and len(other["attracted_to"]) > 1):
                    other["attracted_to"] = [g for g in other["attracted_to"] if g != admirer["gender"]]
                pair = (admirer, other)
                break
            if pair is not None:
                break
    if pair is None:
        return None
    admirer, other = pair
    return {
        "from": admirer["id"], "to": other["id"], "one_way": True,
        "note": f"{admirer['name']}心裡有{other['name']}，{other['name']}只把{admirer['name']}當熟人",
    }


def _relations(seed: int, era: str, people: list[dict]) -> dict:
    stream = rng(seed, 0, "cast", "balance")
    nemeses = []
    secrets = []
    crushes = []
    underestimated = []
    if len(people) >= 2:
        order = list(people)
        _shuffle(order, stream)
        a, b = order[0], order[1]
        why = _pick(stream.random(), NEMESIS_WHY[era]).format(a=a["name"], b=b["name"])
        nemeses.append({"a": a["id"], "b": b["id"], "why": why})
        holders = [p for p in people if p["archetype"] == "藏著秘密的人"] or list(people)
        holder = holders[min(int(stream.random() * len(holders)), len(holders) - 1)]
        others = [p for p in people if p["id"] != holder["id"]]
        other = others[min(int(stream.random() * len(others)), len(others) - 1)]
        if holder["archetype"] == "藏著秘密的人":
            line = SECRET_MATCHED[era][holder["core_i"] % len(SECRET_MATCHED[era])]
        else:
            line = _pick(stream.random(), SECRET_GENERIC[era])
        secrets.append({
            "holder": holder["id"], "kept_from": other["id"],
            "secret": line.format(h=holder["name"], o=other["name"]),
        })
        crush = _place_crush(people, stream)
        if crush is not None:
            crushes.append(crush)
    if people:
        geniuses = [p for p in people if p["archetype"] == "被看輕的天才"]
        if geniuses:
            chosen = geniuses[min(int(stream.random() * len(geniuses)), len(geniuses) - 1)]
            ta = "她" if chosen["gender"] == "female" else "他"
            place = "弟子" if era == "jianghu" else "職員"
            why = f"{chosen['name']}的本事在眾人之上，周圍的人卻只當{ta}是個普通{place}"
        else:
            chosen = people[min(int(stream.random() * len(people)), len(people) - 1)]
            why = f"{chosen['name']}做出來的東西比別人以為的更好，卻很少有人認真看"
        underestimated.append({"id": chosen["id"], "why": why})
    if len(people) >= 6:
        missing = []
        if not nemeses:
            missing.append("nemeses")
        if not secrets:
            missing.append("secrets")
        if not underestimated:
            missing.append("underestimated")
        eligible = [p for p in people if p["romance_eligible"]]
        if len(eligible) >= 2 and not crushes and any(not p["attracted_locked"] for p in eligible):
            missing.append("crushes")
        if missing:
            raise RuntimeError("forge balance missing " + ", ".join(missing))
    return {
        "people": [
            {
                "id": p["id"], "name": p["name"], "archetype": p["archetype"],
                "romance_eligible": p["romance_eligible"],
                # Temperament is not a profile field and lift rejects it as a genome extra, so the cast file keeps it here.
                "temperament": {key: p["temperament"][key] for key in TEMPERAMENT_KEYS},
            }
            for p in people
        ],
        "nemeses": nemeses,
        "secrets": secrets,
        "crushes": crushes,
        "underestimated": underestimated,
        "not_romance": [p["id"] for p in people if not p["romance_eligible"]],
    }


def _profile_dict(person: dict) -> dict:
    core = person["core"]
    profile = {
        "id": person["id"],
        "name": person["name"],
        "age": person["age"],
        "gender": person["gender"],
        "costume": person["look"]["costume_worn"],
        "background": {
            "birthplace": person["birthplace"],
            "family": person["family"],
            "education": person["education"],
        },
        "interests": person["interests"],
        "dislikes": person["dislikes"],
        "values": {key: person["values"][key] for key in VALUE_KEYS},
        "habits": person["habits"],
        "social": {
            "strangers": person["strangers"],
            "friends": person["friends"],
            "intimate": person["intimate"],
            "conflict": person["conflict"],
        },
        "core": {key: core[key] for key in ("want", "fear", "wound", "false_belief", "need", "life_question")},
        "life_goal": core["life_goal"],
        "season_goal": core["season_goal"],
    }
    if person["occupation"] is not None:
        # The hand-written rosters put the job after the background.
        ordered = {}
        for key, value in profile.items():
            ordered[key] = value
            if key == "background":
                ordered["occupation"] = person["occupation"]
        profile = ordered
    return profile


def _extras(person: dict) -> dict:
    look = person["look"]
    return {
        "appearance": {
            "face": look["face"], "hair": look["hair"], "build": look["build"],
            "marks": [look["mark"]], "presence": look["presence"],
        },
        "voice": {
            "timbre": person["voice"]["timbre"], "pace": person["voice"]["pace"],
            "catchphrases": list(person["voice"]["catchphrases"]),
        },
        "charm": person["charm"],
        "attracted_to": list(person["attracted_to"]),
        "attachment": person["attachment"],
        "looks": person["looks"],
        "warmth": person["warmth"],
        "talkativeness": person["talkativeness"],
    }


def _summary(seed: int, era: str, people: list[dict], relations: dict) -> str:
    title = "江湖" if era == "jianghu" else "現代小鎮"
    names = {p["id"]: p["name"] for p in people}
    lines = [
        f"# {title}角色表",
        "",
        f"種子 {seed}，共 {len(people)} 人。",
        "",
        "| 名字 | 原型 | 一句話 | 外貌 | 親和 | 話量 |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for person in people:
        lines.append(
            f"| {person['name']} | {person['archetype']} | {person['core']['blurb']} | "
            f"{person['looks']:.2f} | {person['warmth']:.2f} | {person['talkativeness']:.2f} |"
        )
    lines += ["", "## 初始關係", ""]
    for pair in relations["nemeses"]:
        lines.append(f"- 宿敵：{names[pair['a']]}與{names[pair['b']]}。{pair['why']}")
    for secret in relations["secrets"]:
        lines.append(f"- 秘密：{names[secret['holder']]}背著{names[secret['kept_from']]}。{secret['secret']}")
    for crush in relations["crushes"]:
        lines.append(f"- 單向暗戀：{names[crush['from']]}對{names[crush['to']]}。{crush['note']}")
    for item in relations["underestimated"]:
        lines.append(f"- 被低估：{names[item['id']]}。{item['why']}")
    if relations["not_romance"]:
        skipped = "、".join(names[pid] for pid in relations["not_romance"])
        lines.append(f"- 不進感情線：{skipped}")
    lines.append("")
    return "\n".join(lines) + "\n"


def _validate(roster: dict, people: list[dict]) -> list[str]:
    bad = list(check_roster(from_dict(CharacterRoster, roster)))
    for person in people:
        try:
            lift(from_dict(CharacterProfile, person["profile"]), person["temperament"], person["core"]["blurb"],
                 person["extras"])
        except (PersonaError, TypeError, ValueError) as exc:
            bad.append(f"{person['id']}: {exc}")
    return bad


@dataclass(frozen=True)
class ForgedPerson:
    index: int
    id: str
    name: str
    age: int
    gender: str
    archetype: str
    blurb: str
    looks: float
    warmth: float
    talkativeness: float
    charm: float
    attracted_to: tuple[str, ...]
    attachment: str
    temperament: dict
    values: dict
    romance_eligible: bool
    conflict: str


@dataclass(frozen=True)
class ForgedCast:
    seed: int
    size: int
    era: str
    people: tuple[ForgedPerson, ...]
    relations: dict
    roster: dict
    genomes: dict
    profiles_json: str
    genomes_json: str
    relations_json: str
    summary: str


def forge_cast(seed: int, size: int, era: str, archetypes=None, locks=None) -> ForgedCast:
    """One cast. `locks` maps a person's index (0 .. size-1) to field values that must be kept."""
    seed_i = int(seed)
    if size < 1:
        raise ValueError("size must be >= 1")
    if era not in TOPICS:
        raise ValueError("era must be 'jianghu' or 'town'")
    pool = _pool(archetypes)
    lock_map = _normalize_locks(locks, size)
    pre = _preassign(seed_i, size, pool, lock_map)
    used_cores: dict[str, set[int]] = {}
    people = [
        _draft(seed_i, i, era, pool, pre.get(i), lock_map.get(i, {}), used_cores) for i in range(size)
    ]
    _resolve_names(seed_i, era, people)
    relations = _relations(seed_i, era, people)
    roster = {"content": f"forge_{era}", "topics": dict(TOPICS[era]), "people": [_profile_dict(p) for p in people]}
    genomes = {"people": {}}
    for person, profile in zip(people, roster["people"]):
        person["profile"] = profile
        person["extras"] = _extras(person)
        genomes["people"][person["id"]] = person["extras"]
    bad = _validate(roster, people)
    if bad:
        raise ValueError("forged cast does not validate: " + "; ".join(bad))
    forged = tuple(
        ForgedPerson(
            index=p["index"], id=p["id"], name=p["name"], age=p["age"], gender=p["gender"],
            archetype=p["archetype"], blurb=p["core"]["blurb"], looks=p["looks"], warmth=p["warmth"],
            talkativeness=p["talkativeness"], charm=p["charm"], attracted_to=tuple(p["attracted_to"]),
            attachment=p["attachment"], temperament=dict(p["temperament"]), values=dict(p["values"]),
            romance_eligible=p["romance_eligible"], conflict=p["conflict"],
        )
        for p in people
    )
    return ForgedCast(
        seed=seed_i, size=size, era=era, people=forged, relations=relations, roster=roster, genomes=genomes,
        profiles_json=_dumps(roster), genomes_json=_dumps(genomes), relations_json=_dumps(relations),
        summary=_summary(seed_i, era, people, relations),
    )


def find_modern(text: str, words) -> list[str]:
    """Modern words in prose. Latin entries such as ``app`` match a whole token, so ``appearance`` does not count."""
    hits = []
    for word in words:
        if not word:
            continue
        if word.isascii():
            if re.search(rf"(?i)(?<![A-Za-z0-9]){re.escape(word)}(?![A-Za-z0-9])", text):
                hits.append(word)
        elif word in text:
            hits.append(word)
    return hits


def cast_text(cast: ForgedCast) -> str:
    return cast.profiles_json + cast.genomes_json + cast.relations_json + cast.summary
